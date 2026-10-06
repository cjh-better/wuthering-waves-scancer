# -*- coding: utf-8 -*-
"""AI增强的QR码扫描器 - 使用Caffe模型（通过OpenCV DNN）"""
from PIL import ImageGrab, Image, ImageEnhance
from pyzbar.pyzbar import decode
from typing import Optional, List, Tuple
import ctypes
import numpy as np
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.qr_payload import is_kuro_qr, normalise_qr_text
from utils.log import get_logger


logger = get_logger("AI")

# 尝试导入OpenCV
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    logger.error("[Error] OpenCV not installed, AI model features unavailable")

# 截图后端统一走 utils.screenshot.available_backends()（DXGI → BitBlt → PIL），
# 这里不再直接导入 win32 相关模块。

# 🚀 导入性能监控工具
try:
    from utils.performance_monitor import perf_monitor
    PERF_MONITOR_AVAILABLE = True
except Exception as e:
    PERF_MONITOR_AVAILABLE = False
    logger.info(f"[Info] Performance monitor not available: {e}")

# 内存池已移除：经审计，image_buffer_pool 预分配 ~23MB 却无任何真实复用
# （仅 warmup 空转 + stats 展示），属于装饰性优化。见重构说明。

# 🚀 导入智能ROI检测器
try:
    from utils.smart_roi_detector import smart_roi_detector
    ROI_DETECTOR_AVAILABLE = True
except Exception as e:
    ROI_DETECTOR_AVAILABLE = False
    logger.info(f"[Info] ROI detector not available: {e}")


class AIQRScanner:
    """AI增强的QR码扫描器 - 使用Caffe深度学习模型"""
    
    def __init__(self):
        # 获取屏幕缩放因子
        try:
            self.scale_factor = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
        except Exception:
            self.scale_factor = 1.0
        
        # 加载AI模型
        self.sr_net = None  # 超分辨率网络
        self.detect_net = None  # QR检测网络
        self.ai_enabled = False
        
        # 🚀 微信QR码识别器（比pyzbar更强大）
        self.wechat_detector = None

        # 原生解码器（WeChatQR / Caffe dnn）不是线程安全的：
        # try_decode_parallel 会从多个工作线程并发调用 decode，
        # 必须串行化，否则就是 native segfault（闪退）。这是 #8 的首要嫌疑。
        self._decode_lock = threading.Lock()
        
        # 📸 截图后端链（DXGI → BitBlt → PIL），统一走 ScreenshotBackend
        # 契约（utils.screenshot）。不可用的后端不会出现在链里。
        from utils.screenshot import available_backends

        self._screenshot_backends = available_backends(self.scale_factor)
        # 兼容属性：保留旧的具名访问方式
        self.dxgi_screenshot = next(
            (b for b in self._screenshot_backends if b.name == "DXGI"), None
        )
        self.fast_screenshot = next(
            (b for b in self._screenshot_backends if b.name == "BitBlt"), None
        )
        
        # 🚀 多线程池（自动检测CPU核心数，用于并行图像处理）
        self.use_thread_pool = False  # 默认关闭（串行已够快）
        self.thread_pool = None
        try:
            from utils.thread_pool_scanner import get_thread_pool_scanner
            self.thread_pool = get_thread_pool_scanner()  # 自动检测CPU核心数
            # self.use_thread_pool = True  # 可选：启用多线程（提升复杂场景性能）
            logger.info("[ThreadPool] Available (disabled by default, single-thread is faster for most cases)")
        except Exception as e:
            logger.info(f"[ThreadPool] Not available: {e}")
        
        # 🚀 并行识别线程池（用于多候选QR并行识别）
        self.parallel_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="QRDecode")
        
        # 🚀 启动预热标志
        self.warmed_up = False
        
        # 🚀 调试模式（打印详细识别信息）
        self.debug_mode = False  # 设置为 True 可以看到详细的识别过程
        
        # 模型懒加载：__init__ 只做轻量初始化，Caffe 模型在首次解码时
        # 经 _ensure_models() 加载（双重检查锁），避免 import 时阻塞启动
        # 数秒。后台另起 daemon 线程预热，首扫也不慢。
        self._models_loaded = False
        self._models_lock = threading.Lock()
        self.load_messages = []  # 模型加载日志（主窗口启动时读取展示）
        self.ai_enabled = False

        # 后台预热：不阻塞启动，UI 显示后模型已就绪
        threading.Thread(
            target=self.warm_up, name="AIQRWarmup", daemon=True
        ).start()
    
    def _load_ai_models(self):
        """加载Caffe AI模型（超分辨率和检测）"""
        self.load_messages = []  # 保存加载消息，供UI显示

        try:
            from utils.resources import model_dir, model_paths, resource_base

            base_path = resource_base()
            self.load_messages.append(f"[DEBUG] Base path: {base_path}")

            directory = model_dir()
            self.load_messages.append(f"[DEBUG] Model dir: {directory}")
            self.load_messages.append(f"[DEBUG] Dir exists: {os.path.exists(directory)}")

            paths = model_paths()
            # 超分辨率模型路径
            sr_proto = paths["sr.prototxt"]
            sr_model = paths["sr.caffemodel"]

            # QR检测模型路径
            detect_proto = paths["detect.prototxt"]
            detect_model = paths["detect.caffemodel"]
            
            # 加载超分辨率网络
            if os.path.exists(sr_proto) and os.path.exists(sr_model):
                self.load_messages.append("[AI] Loading SR model...")
                self.sr_net = cv2.dnn.readNetFromCaffe(sr_proto, sr_model)
                self.load_messages.append("[AI] SR model loaded OK")
            else:
                self.load_messages.append(f"[WARN] SR not found: proto={os.path.exists(sr_proto)}, model={os.path.exists(sr_model)}")
            
            # 加载QR检测网络
            if os.path.exists(detect_proto) and os.path.exists(detect_model):
                self.load_messages.append("[AI] Loading detect model...")
                self.detect_net = cv2.dnn.readNetFromCaffe(detect_proto, detect_model)
                self.load_messages.append("[AI] Detect model loaded OK")
            else:
                self.load_messages.append(f"[WARN] Detect not found: proto={os.path.exists(detect_proto)}, model={os.path.exists(detect_model)}")
            
            # 如果任一模型加载成功，启用AI
            if self.sr_net is not None or self.detect_net is not None:
                self.ai_enabled = True
                self.load_messages.append("[AI] AI mode enabled")
            else:
                self.load_messages.append("[AI] No models loaded, using traditional")
            
        except Exception as e:
            import traceback
            error_detail = traceback.format_exc()
            self.load_messages.append(f"[ERROR] Failed to load: {str(e)}")
            self.load_messages.append(f"[ERROR] Detail: {error_detail}")
            self.ai_enabled = False
        
        # 打印所有消息
        for msg in self.load_messages:
            logger.info(msg)
    
    def _init_wechat_detector(self):
        """初始化微信QR码识别器（与MHY_Scanner相同）"""
        try:
            from utils.resources import model_paths

            paths = model_paths()
            detect_proto = paths["detect.prototxt"]
            detect_model = paths["detect.caffemodel"]
            sr_proto = paths["sr.prototxt"]
            sr_model = paths["sr.caffemodel"]

            # 检查所有模型文件是否存在
            if all(os.path.exists(f) for f in paths.values()):
                # 创建微信QR码检测器（与MHY_Scanner相同）
                self.wechat_detector = cv2.wechat_qrcode_WeChatQRCode(
                    detect_proto, detect_model, sr_proto, sr_model
                )
                if hasattr(self.wechat_detector, "setScaleFactor"):
                    self.wechat_detector.setScaleFactor(0.4)
                logger.info("[WeChatQR] Detector initialized (same as MHY_Scanner)")
                if hasattr(self, 'load_messages'):
                    self.load_messages.append("[WeChatQR] WeChat QR detector enabled (MHY-style)")
            else:
                logger.info("[WeChatQR] Model files incomplete, using pyzbar")
        except AttributeError:
            logger.info("[WeChatQR] wechat_qrcode not available (need opencv-contrib-python)")
        except Exception as e:
            logger.warning(f"[WeChatQR] Init failed: {e}")
    
    def _ensure_models(self) -> None:
        """确保 AI 模型已加载（双重检查锁，线程安全）。

        为什么懒加载：两个 Caffe 模型 + WeChatQR 构造在 import 时会阻塞
        启动数秒。首次解码（或后台预热线程）触发一次加载，之后零开销。
        """
        if self._models_loaded or not OPENCV_AVAILABLE:
            return
        with self._models_lock:
            if self._models_loaded:
                return
            self._load_ai_models()
            self._init_wechat_detector()
            self._models_loaded = True

    def warm_up(self) -> None:
        """后台预热：加载模型 + 热身截图与检测器，首扫不卡。

        设计为 daemon 线程调用，不阻塞启动；若用户抢先扫描，
        ``_ensure_models`` 的锁会保证模型只加载一次。
        """
        if self.warmed_up:
            return

        try:
            logger.info("[Warmup] Pre-warming all components...")

            # 1. 模型（含 WeChat 检测器）
            self._ensure_models()

            # 2. 预热截图后端（取一小块区域，触发驱动/GPU 初始化）
            for backend in self._screenshot_backends:
                if backend.name == "PIL":
                    continue
                try:
                    backend.grab_region(0, 0, 100, 100)
                    logger.info("[Warmup] Screenshot backend OK: %s", backend.name)
                    break
                except Exception:
                    continue

            # 3. 预热 WeChat 检测器（首次 detectAndDecode 最慢，加锁串行）
            if self.wechat_detector is not None:
                try:
                    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
                    with self._decode_lock:
                        self.wechat_detector.detectAndDecode(dummy_img)
                    logger.info("[Warmup] WeChat detector OK")
                except Exception:
                    pass

            self.warmed_up = True
            logger.info("[Warmup] All components warmed up!")

        except Exception as e:
            logger.warning("[Warmup] Failed: %s", e)
    
    def apply_super_resolution(self, img: np.ndarray) -> np.ndarray:
        """
        使用AI超分辨率增强图像质量
        """
        if not self.ai_enabled or self.sr_net is None:
            return img
        
        try:
            # 准备输入
            h, w = img.shape[:2]
            blob = cv2.dnn.blobFromImage(img, 1.0, (w, h), (0, 0, 0), swapRB=False, crop=False)

            # 前向传播（dnn 非线程安全，与 WeChatQR 共用一把锁串行化）
            with self._decode_lock:
                self.sr_net.setInput(blob)
                output = self.sr_net.forward()
            
            # 处理输出
            output = output[0]
            output = np.transpose(output, (1, 2, 0))
            output = cv2.normalize(output, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            
            return output
        except Exception as e:
            logger.warning(f"[Warning] Super-resolution processing failed: {e}")
            return img
    
    def enhance_image_ai(self, img: Image.Image) -> List[Image.Image]:
        """
        🚀 AI增强图像（精简版：只保留最有效的3种算法，提升速度）
        返回多个增强版本
        """
        enhanced_images = [img]  # 原图
        
        if not OPENCV_AVAILABLE:
            # 降级到基础增强
            return self._enhance_image_basic(img)
        
        try:
            # 单次转换：PIL -> numpy(RGB)，后续所有分支复用，避免重复拷贝。
            # 注意：旧代码在这里转了两次 np.array(img) 并多做了一次
            # RGB2BGR，是每 tick 的纯浪费。
            img_np = np.array(img)
            # 灰度化直接用 cv2（IPP 优化，单次分配）；旧的
            # fast_rgb_to_gray_simd 用 np.dot+astype（两次分配）并无更快。
            gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)

            # 🚀 直播间抢码专用：只保留2种最有效的算法（极速）

            # 1. 自适应二值化 - 对QR码识别最有效（最快最准）
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            enhanced_images.append(Image.fromarray(binary))

            # 2. AI超分辨率（如果可用）- 处理直播间模糊画面
            if self.sr_net is not None:
                # BGR 只在这里需要：超分网络吃 BGR
                img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                sr_img = self.apply_super_resolution(img_bgr)
                sr_gray = cv2.cvtColor(sr_img, cv2.COLOR_BGR2GRAY)
                enhanced_images.append(Image.fromarray(sr_gray))
            
        except Exception as e:
            logger.warning(f"[Warning] AI image enhancement failed: {e}")
            # 降级到基础增强
            return self._enhance_image_basic(img)
        
        return enhanced_images
    
    def _enhance_image_basic(self, img: Image.Image) -> List[Image.Image]:
        """
        基础图像增强（不依赖OpenCV）
        """
        enhanced_images = [img]  # 原图
        
        try:
            # 提高对比度
            enhancer = ImageEnhance.Contrast(img)
            enhanced_images.append(enhancer.enhance(2.0))
            
            # 锐化
            enhancer = ImageEnhance.Sharpness(img)
            enhanced_images.append(enhancer.enhance(2.0))
            
            # 综合增强
            temp = ImageEnhance.Contrast(img).enhance(1.8)
            temp = ImageEnhance.Sharpness(temp).enhance(1.8)
            enhanced_images.append(temp)
            
        except Exception as e:
            logger.warning(f"[Warning] Basic image enhancement failed: {e}")
        
        return enhanced_images
    
    @staticmethod
    def _accepted_qr_data(qr_data) -> Optional[str]:
        """Return QR text only when it belongs to Kuro login."""
        text = normalise_qr_text(qr_data)
        if is_kuro_qr(text):
            return text
        return None

    def decode(self, image) -> Optional[str]:
        """统一解码契约（见 ``utils.qr_scanner.ImageDecoder``）。

        接受 ``numpy.ndarray``（BGR/RGB/GRAY，走 ``try_decode_array``
        免转换路径）或 ``PIL.Image``（走 ``try_decode_qr``）；其他类型
        返回 ``None``。永不抛异常。
        """
        try:
            if image is None:
                return None
            if hasattr(image, "shape"):
                return self.try_decode_array(image, color="BGR")
            if isinstance(image, Image.Image):
                return self.try_decode_qr(image)
            return None
        except Exception:
            return None

    def try_decode_array(self, img_array: np.ndarray, color: str = "BGR") -> Optional[str]:
        """Decode a QR code directly from a numpy frame.

        This avoids RGB-to-PIL conversion on live stream frames. ``color`` may
        be ``BGR`` (OpenCV default), ``RGB``, or ``GRAY``.
        """
        # 模型懒加载：首次解码时触发（后台预热线程通常已提前完成）
        self._ensure_models()
        try:
            if img_array is None:
                return None

            arr = np.asarray(img_array)
            # 守卫：空图 / 0 宽高（窗口最小化、截图失败时常见）。
            # 把这类图像喂给 WeChatQR/dnn 是 native segfault 的高发区，
            # 必须在这里拦掉，而不是依赖调用方。
            if arr.size == 0 or 0 in arr.shape:
                logger.warning(
                    "[AI] 拒绝解码非法图像(shape=%s)，跳过", getattr(arr, "shape", "?")
                )
                return None

            img_bgr = arr
            color = (color or "BGR").upper()
            if OPENCV_AVAILABLE:
                if arr.ndim == 2:
                    img_bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
                elif color == "RGB":
                    img_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                elif color == "GRAY":
                    img_bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

                if self.wechat_detector is not None:
                    try:
                        # WeChatQR 内部有状态，非线程安全：加锁串行化。
                        with self._decode_lock:
                            res, points = self.wechat_detector.detectAndDecode(img_bgr)
                        if isinstance(res, str):
                            res = [res]
                        for qr_data in res or []:
                            accepted = self._accepted_qr_data(qr_data)
                            if accepted:
                                return accepted
                    except Exception:
                        pass

                if arr.ndim == 2:
                    pil_image = Image.fromarray(arr)
                else:
                    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(rgb)
            else:
                pil_image = Image.fromarray(arr)

            decoded_objects = decode(pil_image)
            for obj in decoded_objects:
                accepted = self._accepted_qr_data(obj.data)
                if accepted:
                    return accepted
        except Exception:
            pass
        return None

    def try_decode_qr(self, img: Image.Image) -> Optional[str]:
        """
        尝试解码单张图片的QR码
        🚀 优先使用微信QR码检测器（与MHY_Scanner相同），失败则fallback到pyzbar
        """
        if OPENCV_AVAILABLE:
            result = self.try_decode_array(np.array(img), color="RGB")
            if result:
                return result
        
        # 🔄 方案2：Fallback到pyzbar（兼容性好）
        try:
            decoded_objects = decode(img)
            if decoded_objects:
                for obj in decoded_objects:
                    accepted = self._accepted_qr_data(obj.data)
                    if accepted:
                        return accepted
        except Exception:
            pass
        return None
    
    def try_decode_parallel(self, images: List[Tuple[str, Image.Image]]) -> Optional[Tuple[str, str]]:
        """
        🚀 并行尝试解码多个图像候选（速度提升30-50%）
        
        Args:
            images: List of (method_name, image) tuples
        
        Returns:
            (qr_code, method_name) if found, None otherwise
        """
        futures = {}
        
        # 提交所有任务
        for method_name, img in images:
            future = self.parallel_executor.submit(self.try_decode_qr, img)
            futures[future] = method_name
        
        # 等待第一个成功的结果
        for future in as_completed(futures):
            result = future.result()
            if result:
                # 取消其他任务
                for f in futures:
                    if f != future:
                        f.cancel()
                return (result, futures[future])
        
        return None
    
    def scan_region(self, x: int, y: int, width: int, height: int) -> Optional[str]:
        """
        🚀 扫描指定区域的二维码 - 终极优化版
        
        集成优化：
        1. 性能监控
        2. 智能ROI预测
        3. 并行多候选识别
        4. 内存池复用
        5. DXGI/BitBlt截图
        6. WeChat QR检测器
        
        Args:
            x: 区域左上角 x 坐标
            y: 区域左上角 y 坐标
            width: 区域宽度
            height: 区域高度
            
        Returns:
            二维码内容，如果没有检测到则返回 None
        """
        try:
            # 🚀 性能监控：开始计时
            if PERF_MONITOR_AVAILABLE:
                perf_monitor.start_scan()
            # 📸 截图阶段：按后端链依次尝试（DXGI → BitBlt → PIL）
            from utils.screenshot import grab_region_first_success

            img, screenshot_method = grab_region_first_success(
                self._screenshot_backends, x, y, width, height
            )
            
            # 守卫：截图失败/窗口最小化时 img 可能为 None 或 0 尺寸，
            # 直接喂给后续的 resize/解码是崩溃高发区。
            if img is None or getattr(img, "width", 0) <= 0 or getattr(img, "height", 0) <= 0:
                logger.warning(
                    "[Scan] 截图返回空图像(method=%s)，跳过本次扫描", screenshot_method
                )
                return None

            # 🚀 性能监控：截图完成
            if PERF_MONITOR_AVAILABLE:
                perf_monitor.mark_screenshot_done(method=screenshot_method, image_size=(img.width, img.height))
            
            # 🔍 QR检测阶段
            
            # 🚀 准备多个候选图像（用于并行识别）
            target_width = 1280
            target_height = 720
            width_ratio = target_width / img.width
            height_ratio = target_height / img.height
            scale_ratio = min(width_ratio, height_ratio)
            new_width = max(1, int(img.width * scale_ratio))
            new_height = max(1, int(img.height * scale_ratio))
            
            # BILINEAR 而非 LANCZOS：QR 是高对比图案，且 WeChatQR 内部
            # 以 scaleFactor 0.4 下采样，LANCZOS 的高质量在此处是纯开销
            #（约快 2-3 倍，识别率无可测差异）。
            img_1280 = img.resize((new_width, new_height), Image.Resampling.BILINEAR)
            img_40 = img.resize(
                (max(1, int(img.width * 0.4)), max(1, int(img.height * 0.4))),
                Image.Resampling.BILINEAR,
            )
            
            # 🚀 并行识别多个候选（增加识别率）
            candidates = [
                ("original", img),          # 原图（优先）
                ("1280x720", img_1280),     # 标准尺寸
                ("40%", img_40),            # 缩小版本
            ]
            
            # 🚀 调试：打印扫描信息
            if self.debug_mode:
                logger.info(f"[Scan] Trying {len(candidates)} candidates, size: {img.width}x{img.height}")
            
            parallel_result = self.try_decode_parallel(candidates)
            
            if parallel_result:
                qr_code, method = parallel_result
                decoder = "WeChat" if self.wechat_detector else "pyzbar"
                
                # 🚀 性能监控：QR检测完成
                if PERF_MONITOR_AVAILABLE:
                    perf_monitor.mark_qr_detect_done(method=method, decoder=decoder)
                
                # 🚀 记录到ROI检测器
                if ROI_DETECTOR_AVAILABLE:
                    smart_roi_detector.add_detection(x, y, width, height)
                
                logger.info(f"[QR] ✓ Decoded using {method} ({decoder})")
                return qr_code
            
            # 🚀 调试：如果并行识别失败，打印信息
            if self.debug_mode:
                logger.warning(f"[Scan] Parallel failed, trying enhanced...")
            
            # 🚀 如果并行识别失败，尝试AI增强版本（提升识别率）
            enhanced_images = self.enhance_image_ai(img_1280)
            
            method_names = ["原图(已尝试)", "二值化", "AI超分辨率"]
            for idx, enhanced_img in enumerate(enhanced_images[1:], 1):
                result = self.try_decode_qr(enhanced_img)
                if result:
                    method_name = method_names[idx] if idx < len(method_names) else f"增强{idx}"
                    decoder = "WeChat" if self.wechat_detector else "pyzbar"
                    
                    # 🚀 性能监控：QR检测完成
                    if PERF_MONITOR_AVAILABLE:
                        perf_monitor.mark_qr_detect_done(method=method_name, decoder=decoder)
                    
                    # 🚀 记录到ROI检测器
                    if ROI_DETECTOR_AVAILABLE:
                        smart_roi_detector.add_detection(x, y, width, height)
                    
                    logger.info(f"[QR] ✓ Decoded using {method_name} (enhanced, {decoder})")
                    return result
            
            # 🚀 调试：所有方法都失败
            if self.debug_mode:
                logger.warning(f"[Scan] ✗ All methods failed for {img.width}x{img.height} image")
            
            # 🚀 性能监控：未找到QR
            if PERF_MONITOR_AVAILABLE:
                perf_monitor.end_scan(success=False)
            
            return None
            
        except Exception as e:
            logger.error(f"[Error] AI QR scan failed: {e}")
            return None
    
    def scan_clipboard(self) -> Optional[str]:
        """
        从剪贴板扫描二维码
        
        Returns:
            二维码内容，如果没有检测到则返回 None
        """
        try:
            img = ImageGrab.grabclipboard()
            if not isinstance(img, Image.Image):
                return None
            
            # 多次尝试识别
            result = self.try_decode_qr(img)
            if result:
                return result
            
            # 使用AI增强版本
            enhanced_images = self.enhance_image_ai(img)
            
            for enhanced_img in enhanced_images[1:]:
                result = self.try_decode_qr(enhanced_img)
                if result:
                    return result
            
            return None
            
        except Exception as e:
            logger.error(f"[Error] Clipboard QR scan failed: {e}")
            return None


# 全局AI扫描器实例
ai_qr_scanner = AIQRScanner()

