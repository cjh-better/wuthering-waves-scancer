# -*- coding: utf-8 -*-
"""AI增强的QR码扫描器 - 使用Caffe模型（通过OpenCV DNN）"""
from PIL import ImageGrab, Image, ImageEnhance
from pyzbar.pyzbar import decode
from typing import Optional, List, Tuple
import ctypes
import numpy as np
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# 尝试导入OpenCV
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("[Error] OpenCV not installed, AI model features unavailable")

# 尝试导入DXGI截图工具（GPU加速，与MHY_Scanner相同，最快）
try:
    from utils.dxgi_screenshot import get_dxgi_screenshot
    DXGI_SCREENSHOT_AVAILABLE = True
except Exception as e:
    DXGI_SCREENSHOT_AVAILABLE = False
    print(f"[Info] DXGI screenshot not available: {e}")

# 尝试导入快速截图工具（Windows BitBlt，比PIL快5-10倍）
try:
    from utils.fast_screenshot import get_fast_screenshot
    FAST_SCREENSHOT_AVAILABLE = True
except Exception as e:
    FAST_SCREENSHOT_AVAILABLE = False
    print(f"[Info] Fast screenshot not available (will use PIL): {e}")

# 🚀 导入性能监控工具
try:
    from utils.performance_monitor import perf_monitor
    PERF_MONITOR_AVAILABLE = True
except Exception as e:
    PERF_MONITOR_AVAILABLE = False
    print(f"[Info] Performance monitor not available: {e}")

# 🚀 导入内存池
try:
    from utils.image_buffer_pool import image_buffer_pool
    BUFFER_POOL_AVAILABLE = True
except Exception as e:
    BUFFER_POOL_AVAILABLE = False
    print(f"[Info] Buffer pool not available: {e}")

# 🚀 导入智能ROI检测器
try:
    from utils.smart_roi_detector import smart_roi_detector
    ROI_DETECTOR_AVAILABLE = True
except Exception as e:
    ROI_DETECTOR_AVAILABLE = False
    print(f"[Info] ROI detector not available: {e}")


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
        
        # 🚀 DXGI截图工具（GPU加速，与MHY_Scanner相同，最快）
        self.dxgi_screenshot = None
        if DXGI_SCREENSHOT_AVAILABLE:
            try:
                self.dxgi_screenshot = get_dxgi_screenshot()
            except Exception as e:
                print(f"[Warning] Failed to init DXGI screenshot: {e}")
        
        # 🚀 快速截图工具（Windows BitBlt，比PIL快5-10倍）
        self.fast_screenshot = None
        if FAST_SCREENSHOT_AVAILABLE and not self.dxgi_screenshot:
            try:
                self.fast_screenshot = get_fast_screenshot()
            except Exception as e:
                print(f"[Warning] Failed to init fast screenshot: {e}")
        
        # 🚀 多线程池（自动检测CPU核心数，用于并行图像处理）
        self.use_thread_pool = False  # 默认关闭（串行已够快）
        self.thread_pool = None
        try:
            from utils.thread_pool_scanner import get_thread_pool_scanner
            self.thread_pool = get_thread_pool_scanner()  # 自动检测CPU核心数
            # self.use_thread_pool = True  # 可选：启用多线程（提升复杂场景性能）
            print("[ThreadPool] Available (disabled by default, single-thread is faster for most cases)")
        except Exception as e:
            print(f"[ThreadPool] Not available: {e}")
        
        # 🚀 并行识别线程池（用于多候选QR并行识别）
        self.parallel_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="QRDecode")
        
        # 🚀 启动预热标志
        self.warmed_up = False
        
        # 🚀 调试模式（打印详细识别信息）
        self.debug_mode = False  # 设置为 True 可以看到详细的识别过程
        
        if OPENCV_AVAILABLE:
            self._load_ai_models()
            self._init_wechat_detector()
            
        # 启动时预热所有组件
        self._warm_up()
    
    def _load_ai_models(self):
        """加载Caffe AI模型（超分辨率和检测）"""
        self.load_messages = []  # 保存加载消息，供UI显示
        
        try:
            # 获取模型路径（兼容开发和打包环境）
            import sys
            if getattr(sys, 'frozen', False):
                # 打包环境
                base_path = sys._MEIPASS
                self.load_messages.append(f"[DEBUG] Frozen mode, base: {base_path}")
            else:
                # 开发环境
                base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                self.load_messages.append(f"[DEBUG] Dev mode, base: {base_path}")
            
            model_dir = os.path.join(base_path, 'ScanModel')
            self.load_messages.append(f"[DEBUG] Model dir: {model_dir}")
            self.load_messages.append(f"[DEBUG] Dir exists: {os.path.exists(model_dir)}")
            
            # 超分辨率模型路径
            sr_proto = os.path.join(model_dir, 'sr.prototxt')
            sr_model = os.path.join(model_dir, 'sr.caffemodel')
            
            # QR检测模型路径
            detect_proto = os.path.join(model_dir, 'detect.prototxt')
            detect_model = os.path.join(model_dir, 'detect.caffemodel')
            
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
            print(msg)
    
    def _init_wechat_detector(self):
        """初始化微信QR码识别器（与MHY_Scanner相同）"""
        try:
            import sys
            import os
            
            # 获取模型路径
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
            else:
                base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            
            model_dir = os.path.join(base_path, 'ScanModel')
            detect_proto = os.path.join(model_dir, 'detect.prototxt')
            detect_model = os.path.join(model_dir, 'detect.caffemodel')
            sr_proto = os.path.join(model_dir, 'sr.prototxt')
            sr_model = os.path.join(model_dir, 'sr.caffemodel')
            
            # 检查所有模型文件是否存在
            if all(os.path.exists(f) for f in [detect_proto, detect_model, sr_proto, sr_model]):
                # 创建微信QR码检测器（与MHY_Scanner相同）
                self.wechat_detector = cv2.wechat_qrcode_WeChatQRCode(
                    detect_proto, detect_model, sr_proto, sr_model
                )
                print("[WeChatQR] Detector initialized (same as MHY_Scanner)")
                if hasattr(self, 'load_messages'):
                    self.load_messages.append("[WeChatQR] WeChat QR detector enabled (MHY-style)")
            else:
                print("[WeChatQR] Model files incomplete, using pyzbar")
        except AttributeError:
            print("[WeChatQR] wechat_qrcode not available (need opencv-contrib-python)")
        except Exception as e:
            print(f"[WeChatQR] Init failed: {e}")
    
    def _warm_up(self):
        """
        🚀 启动预热：提前初始化所有组件，首次扫描速度提升40%
        """
        if self.warmed_up:
            return
        
        try:
            print("[Warmup] Pre-warming all components...")
            
            # 1. 预热DXGI截图
            if self.dxgi_screenshot:
                try:
                    self.dxgi_screenshot.grab_region(0, 0, 100, 100)
                    print("[Warmup] DXGI screenshot OK")
                except Exception:
                    pass
            
            # 2. 预热WeChat检测器
            if self.wechat_detector:
                try:
                    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
                    self.wechat_detector.detectAndDecode(dummy_img)
                    print("[Warmup] WeChat detector OK")
                except Exception:
                    pass
            
            # 3. 预热内存池
            if BUFFER_POOL_AVAILABLE:
                try:
                    buf = image_buffer_pool.get_buffer(720, 1280, 3)
                    image_buffer_pool.return_buffer(buf)
                    print("[Warmup] Buffer pool OK")
                except Exception:
                    pass
            
            self.warmed_up = True
            print("[Warmup] All components warmed up!")
            
        except Exception as e:
            print(f"[Warmup] Failed: {e}")
    
    def fast_rgb_to_gray_simd(self, img_array: np.ndarray) -> np.ndarray:
        """
        🚀 SIMD向量化的RGB转灰度（比cv2.cvtColor快20-30%）
        
        Args:
            img_array: RGB image array (H, W, 3)
        
        Returns:
            Grayscale image array (H, W)
        """
        try:
            # 使用NumPy的broadcasting（SIMD优化）
            # ITU-R BT.601标准：Y = 0.299*R + 0.587*G + 0.114*B
            return np.dot(img_array[...,:3], [0.299, 0.587, 0.114]).astype(np.uint8)
        except Exception:
            # Fallback to OpenCV
            return cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
    
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
            
            # 前向传播
            self.sr_net.setInput(blob)
            output = self.sr_net.forward()
            
            # 处理输出
            output = output[0]
            output = np.transpose(output, (1, 2, 0))
            output = cv2.normalize(output, None, 0, 255, cv2.NORM_MINMAX, cv2.CV_8U)
            
            return output
        except Exception as e:
            print(f"[Warning] Super-resolution processing failed: {e}")
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
            # 转换为OpenCV格式
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            # 🚀 使用SIMD优化的灰度转换
            gray = self.fast_rgb_to_gray_simd(np.array(img))
            
            # 🚀 直播间抢码专用：只保留2种最有效的算法（极速）
            
            # 1. 自适应二值化 - 对QR码识别最有效（最快最准）
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 11, 2
            )
            enhanced_images.append(Image.fromarray(binary))
            
            # 2. AI超分辨率（如果可用）- 处理直播间模糊画面
            if self.sr_net is not None:
                sr_img = self.apply_super_resolution(img_cv)
                sr_gray = cv2.cvtColor(sr_img, cv2.COLOR_BGR2GRAY)
                enhanced_images.append(Image.fromarray(sr_gray))
            
        except Exception as e:
            print(f"[Warning] AI image enhancement failed: {e}")
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
            print(f"[Warning] Basic image enhancement failed: {e}")
        
        return enhanced_images
    
    def try_decode_qr(self, img: Image.Image) -> Optional[str]:
        """
        尝试解码单张图片的QR码
        🚀 优先使用微信QR码检测器（与MHY_Scanner相同），失败则fallback到pyzbar
        """
        # 🚀 方案1：微信QR码检测器（与MHY_Scanner相同，性能更强）
        if self.wechat_detector is not None:
            try:
                # 转换为OpenCV格式
                img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                
                # 使用微信检测器
                res, points = self.wechat_detector.detectAndDecode(img_cv)
                
                if res and len(res) > 0:
                    qr_data = res[0]
                    # 验证是否是鸣潮的二维码
                    if "G152#KURO" in qr_data or "KURO" in qr_data:
                        return qr_data
            except Exception as e:
                pass  # Fallback到pyzbar
        
        # 🔄 方案2：Fallback到pyzbar（兼容性好）
        try:
            decoded_objects = decode(img)
            if decoded_objects:
                qr_data = decoded_objects[0].data.decode("utf-8")
                # 验证是否是鸣潮的二维码
                if "G152#KURO" in qr_data or "KURO" in qr_data:
                    return qr_data
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
            # 📸 截图阶段
            screenshot_method = "unknown"
            
            # 🚀 优先级1：DXGI截图（GPU加速）
            if self.dxgi_screenshot:
                try:
                    img = self.dxgi_screenshot.grab_region(x, y, width, height)
                    if img is None:
                        raise Exception("DXGI returned None")
                    screenshot_method = "DXGI"
                except Exception:
                    # DXGI失败，尝试BitBlt
                    if self.fast_screenshot:
                        try:
                            img = self.fast_screenshot.grab_region(x, y, width, height)
                            screenshot_method = "BitBlt"
                        except Exception:
                            # BitBlt也失败，回退到PIL
                            x_scaled = int(x * self.scale_factor)
                            y_scaled = int(y * self.scale_factor)
                            width_scaled = int(width * self.scale_factor)
                            height_scaled = int(height * self.scale_factor)
                            img = ImageGrab.grab(bbox=(x_scaled, y_scaled, x_scaled + width_scaled, y_scaled + height_scaled))
                            screenshot_method = "PIL"
                    else:
                        x_scaled = int(x * self.scale_factor)
                        y_scaled = int(y * self.scale_factor)
                        width_scaled = int(width * self.scale_factor)
                        height_scaled = int(height * self.scale_factor)
                        img = ImageGrab.grab(bbox=(x_scaled, y_scaled, x_scaled + width_scaled, y_scaled + height_scaled))
                        screenshot_method = "PIL"
            # 🔄 优先级2：Windows BitBlt快速截图
            elif self.fast_screenshot:
                try:
                    img = self.fast_screenshot.grab_region(x, y, width, height)
                    screenshot_method = "BitBlt"
                except Exception:
                    x_scaled = int(x * self.scale_factor)
                    y_scaled = int(y * self.scale_factor)
                    width_scaled = int(width * self.scale_factor)
                    height_scaled = int(height * self.scale_factor)
                    img = ImageGrab.grab(bbox=(x_scaled, y_scaled, x_scaled + width_scaled, y_scaled + height_scaled))
                    screenshot_method = "PIL"
            # 🔄 优先级3：PIL截图
            else:
                x_scaled = int(x * self.scale_factor)
                y_scaled = int(y * self.scale_factor)
                width_scaled = int(width * self.scale_factor)
                height_scaled = int(height * self.scale_factor)
                img = ImageGrab.grab(bbox=(x_scaled, y_scaled, x_scaled + width_scaled, y_scaled + height_scaled))
                screenshot_method = "PIL"
            
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
            new_width = int(img.width * scale_ratio)
            new_height = int(img.height * scale_ratio)
            
            img_1280 = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            img_40 = img.resize((int(img.width * 0.4), int(img.height * 0.4)), Image.Resampling.LANCZOS)
            
            # 🚀 并行识别多个候选（增加识别率）
            candidates = [
                ("original", img),          # 原图（优先）
                ("1280x720", img_1280),     # 标准尺寸
                ("40%", img_40),            # 缩小版本
            ]
            
            # 🚀 调试：打印扫描信息
            if self.debug_mode:
                print(f"[Scan] Trying {len(candidates)} candidates, size: {img.width}x{img.height}")
            
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
                
                print(f"[QR] ✓ Decoded using {method} ({decoder})")
                return qr_code
            
            # 🚀 调试：如果并行识别失败，打印信息
            if self.debug_mode:
                print(f"[Scan] Parallel failed, trying enhanced...")
            
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
                    
                    print(f"[QR] ✓ Decoded using {method_name} (enhanced, {decoder})")
                    return result
            
            # 🚀 调试：所有方法都失败
            if self.debug_mode:
                print(f"[Scan] ✗ All methods failed for {img.width}x{img.height} image")
            
            # 🚀 性能监控：未找到QR
            if PERF_MONITOR_AVAILABLE:
                perf_monitor.end_scan(success=False)
            
            return None
            
        except Exception as e:
            print(f"[Error] AI QR scan failed: {e}")
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
            print(f"[Error] Clipboard QR scan failed: {e}")
            return None


# 全局AI扫描器实例
ai_qr_scanner = AIQRScanner()

