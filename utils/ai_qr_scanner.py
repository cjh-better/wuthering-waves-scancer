# -*- coding: utf-8 -*-
"""AI增强的QR码扫描器 - 使用Caffe模型（通过OpenCV DNN）"""
from PIL import ImageGrab, Image, ImageEnhance
try:
    from pyzbar.pyzbar import decode as _pyzbar_decode
    PYZBAR_AVAILABLE = True
except Exception:
    _pyzbar_decode = None
    PYZBAR_AVAILABLE = False

def decode(*args, **kwargs):
    """pyzbar 兜底（可选依赖，缺失时返回空列表）"""
    if _pyzbar_decode is None:
        return []
    return _pyzbar_decode(*args, **kwargs)
from typing import Optional, List, Tuple
import ctypes
import numpy as np
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

from utils.qr_payload import is_kuro_qr, normalise_qr_text
from utils.log import get_logger


logger = get_logger("AI")

#: 并行解码等待上限（秒）。正常 3 候选约 10-60ms（含 SR 约 1s）；
#: 超过即视为 worker 在 native 层 hang 住，按"本次未检出"返回，
#: 不能让扫描线程永久卡死。
_PARALLEL_DECODE_TIMEOUT_S = 10.0

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

        # thread_local 检测器（仿 C++ KuRo_Scanner）：每个线程独立 detector，
        # 无需全局锁串行化。WeChatQR 非线程安全，但 thread_local 让各线程
        # 用自己的实例，天然隔离。模型按需加载，用到的线程才占内存。
        self._thread_detectors = threading.local()
        self._detector_count = 0
        self._detector_count_lock = threading.Lock()
        # 保留 _decode_lock 作兼容（旧代码引用），新路径不再使用
        self._decode_lock = threading.Lock()
        # sr_net 与 wechat_detector 是不同的 dnn 对象，并发 forward 安全，
        # 没必要跟 WeChatQR 抢同一把锁（SR 在 CPU 上要几百 ms，会队头阻塞解码）
        self._sr_lock = threading.Lock()
        
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
        
        # 🚀 并行识别线程池（用于多候选QR并行识别）
        self.parallel_executor = ThreadPoolExecutor(
            # 优化4：按 CPU 核心数自适应（IO+计算混合，2-4 个为宜）
            max_workers=min(4, max(2, (os.cpu_count() or 4) // 2)),
            thread_name_prefix="QRDecode",
        )
        # 优化81/82/84：解码统计（p99 延迟、成功率，采样日志）
        self._decode_count = 0
        self._decode_hit = 0
        self._decode_times: list = []  # 最近 100 次耗时（ms）
        self._decode_lock = threading.Lock()
        
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
    
    def _create_wechat_detector(self):
        """创建新的 WeChatQR 检测器实例（每个线程一个）。"""
        try:
            from utils.resources import model_paths

            paths = model_paths()
            detect_proto = paths["detect.prototxt"]
            detect_model = paths["detect.caffemodel"]
            sr_proto = paths["sr.prototxt"]
            sr_model = paths["sr.caffemodel"]

            if all(os.path.exists(f) for f in paths.values()):
                detector = cv2.wechat_qrcode_WeChatQRCode(
                    detect_proto, detect_model, sr_proto, sr_model
                )
                if hasattr(detector, "setScaleFactor"):
                    detector.setScaleFactor(0.4)
                return detector
            return None
        except Exception:
            return None

    def _try_decode_isolated(self, img_array, color: str = "BGR") -> Optional[str]:
        """子进程隔离解码（config decode_subprocess_isolation=true 时）。

        img_array 转 BGR 后送 worker；worker 死了自动重启并返回 None。
        """
        try:
            from utils.decode_worker import IsolatedDecoder
            import numpy as _np
            import cv2 as _cv2
        except Exception:
            return None
        # 懒创建 worker（进程启动 ~1-2s，只一次）
        dec = getattr(self, "_isolated_decoder", None)
        if dec is None:
            dec = IsolatedDecoder(model_dir="ScanModel")
            self._isolated_decoder = dec
        try:
            arr = _np.ascontiguousarray(img_array)
            if color == "RGB" and arr.ndim == 3:
                arr = _cv2.cvtColor(arr, _cv2.COLOR_RGB2BGR)
            elif color == "GRAY" and arr.ndim == 2:
                arr = _cv2.cvtColor(arr, _cv2.COLOR_GRAY2BGR)
            return dec.decode(arr)
        except Exception:
            return None

    def _get_thread_detector(self):
        """获取当前线程的 WeChatQR 检测器（thread_local，懒加载）。

        仿 C++ KuRo_Scanner 的 thread_local QRScanner：各线程独立实例，
        无需锁。首次调用时加载模型（慢），之后复用。
        """
        # 模型不可用（或被测试 mock 掉）时直接返回 None，不尝试创建
        if not getattr(self, "_wechat_models_ok", True):
            return None
        if self.wechat_detector is None:
            # 兼容测试 mock：wechat_detector 被置 None 视为不可用
            return None
        det = getattr(self._thread_detectors, "detector", None)
        if det is None:
            det = self._create_wechat_detector()
            self._thread_detectors.detector = det
            if det is not None:
                # 诊断计数：正常应 ≤3（主线程+直播解码+并行worker），
                # 若持续增长说明有线程泄漏
                with self._detector_count_lock:
                    self._detector_count += 1
                    n = self._detector_count
                logger.info(f"[WeChatQR] Thread-local detector initialized (total={n})")
                if n > 4:
                    logger.warning(
                        f"[WeChatQR] {n} thread-local detectors alive, "
                        "possible thread leak"
                    )
        return det

    def _init_wechat_detector(self):
        """初始化微信QR码识别器（与MHY_Scanner相同）"""
        # 主线程的 detector（兼容旧代码），工作线程用 _get_thread_detector()
        self.wechat_detector = self._create_wechat_detector()
        # 可用性标志：模型缺失时 thread_local 也不尝试创建（省 IO，且让
        # 测试 mock wechat_detector=None 时行为一致）
        self._wechat_models_ok = self.wechat_detector is not None
        if self.wechat_detector is not None:
            logger.info("[WeChatQR] Detector initialized (same as MHY_Scanner)")
            if hasattr(self, 'load_messages'):
                self.load_messages.append("[WeChatQR] WeChat QR detector enabled (MHY-style)")
        else:
            logger.info("[WeChatQR] Model files incomplete or wechat_qrcode unavailable, using pyzbar")
    
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
            # 完整性校验：损坏的模型是 native segfault 高发区，先拦掉
            try:
                from utils.model_integrity import verify_or_warn
                if not verify_or_warn():
                    logger.warning(
                        "[AIQR] 模型文件校验未通过，WeChatQR 可能不可用，"
                        "将依赖 pyzbar 兜底"
                    )
            except Exception:
                pass
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

            # 3. 预热 WeChat 检测器（首次 detectAndDecode 最慢）
            # 主线程的 detector 在此预热；工作线程的 thread_local detector
            # 在首次使用时懒加载（会有一次慢调用，可接受）
            detector = self._get_thread_detector()
            if detector is not None:
                try:
                    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
                    detector.detectAndDecode(dummy_img)
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

            # 前向传播（sr_net 独立锁：与 WeChatQR 不同的 dnn 对象，
            # 并发 forward 安全，不必串行等待）
            with self._sr_lock:
                self.sr_net.setInput(blob)
                output = self.sr_net.forward()
            
            # 处理输出
            output = output[0]
            output = np.transpose(output, (1, 2, 0))
            # 显式 dst：mypy 的 cv2.normalize overload 不接受 dst=None + Any src
            _dst = np.empty_like(np.asarray(output))
            output = cv2.normalize(output, _dst, 0, 255, cv2.NORM_MINMAX)
            
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
            enhanced_images.append(ImageEnhance.Contrast(img).enhance(2.0))

            # 锐化
            enhanced_images.append(ImageEnhance.Sharpness(img).enhance(2.0))
            
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

    def decode(self, image, allow_slow_fallback: bool = True) -> Optional[str]:
        """统一解码契约（见 ``utils.qr_scanner.ImageDecoder``）。

        接受 ``numpy.ndarray``（BGR/RGB/GRAY，走 ``try_decode_array``
        免转换路径）或 ``PIL.Image``（走 ``try_decode_qr``）；其他类型
        返回 ``None``。永不抛异常。

        ``allow_slow_fallback`` 会透传给下层，见 ``try_decode_array``。
        """
        try:
            if image is None:
                return None
            if hasattr(image, "shape"):
                return self.try_decode_array(
                    image, color="BGR", allow_slow_fallback=allow_slow_fallback
                )
            if isinstance(image, Image.Image):
                return self.try_decode_qr(image, allow_slow_fallback=allow_slow_fallback)
            return None
        except Exception:
            return None

    def try_decode_array(
        self,
        img_array: np.ndarray,
        color: str = "BGR",
        allow_slow_fallback: bool = True,
    ) -> Optional[str]:
        # 优化81：p99 延迟统计（包装内层逻辑）
        import time as _t
        _start = _t.time()
        try:
            result = self._try_decode_array_inner(img_array, color, allow_slow_fallback)
            # 优化84：命中计数
            if result:
                try:
                    with self._decode_lock:
                        self._decode_hit += 1
                except Exception:
                    pass
            return result
        finally:
            _elapsed_ms = (_t.time() - _start) * 1000
            try:
                with self._decode_lock:
                    self._decode_count += 1
                    self._decode_times.append(_elapsed_ms)
                    if len(self._decode_times) > 100:
                        self._decode_times.pop(0)
                    # 优化82：每 100 次采样一次统计（避免刷屏）
                    if self._decode_count % 100 == 0:
                        import numpy as _np
                        arr = _np.array(self._decode_times)
                        p99 = float(_np.percentile(arr, 99))
                        hit_rate = self._decode_hit / max(1, self._decode_count)
                        logger.info(
                            "[Decode] 100次统计: p99=%.0fms 命中率=%.1f%%",
                            p99, hit_rate * 100,
                        )
            except Exception:
                pass

    def _try_decode_array_inner(
        self,
        img_array: np.ndarray,
        color: str = "BGR",
        allow_slow_fallback: bool = True,
    ) -> Optional[str]:
        """Decode a QR code directly from a numpy frame.

        This avoids RGB-to-PIL conversion on live stream frames. ``color`` may
        be ``BGR`` (OpenCV default), ``RGB``, or ``GRAY``.

        ``allow_slow_fallback``: when False, skip the pyzbar fallback
        (~200ms) after WeChatQR misses. Use it on hot paths where a slow
        fallback would head-of-line block fresher frames; WeChatQR alone
        catches all tested QR sizes 3/3 (see benchmarks/decode_bench.py).
        """
        # 模型懒加载：首次解码时触发（后台预热线程通常已提前完成）
        self._ensure_models()
        # 子进程隔离（可选）：native segfault 只死 worker，主进程不受影响。
        # 默认关闭（thread-local 已解决已知并发 crash），极端 robustness 需求时开启。
        try:
            from utils.config_manager import config_manager as _cm_iso
            if _cm_iso.get("decode_subprocess_isolation", False):
                return self._try_decode_isolated(img_array, color)
        except Exception:
            pass
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
            # 前置校验（issue #8 纵深防护）：dtype/通道/尺寸/内存连续性。
            # native 代码对这些假设很脆弱，Python 侧拦掉比闪退好。
            if arr.dtype != np.uint8:
                logger.warning("[AI] 拒绝非 uint8 图像(dtype=%s)，跳过", arr.dtype)
                return None
            if arr.ndim not in (2, 3):
                logger.warning("[AI] 拒绝非法维度(ndim=%s)，跳过", arr.ndim)
                return None
            if arr.ndim == 3 and arr.shape[2] not in (1, 3, 4):
                logger.warning("[AI] 拒绝非法通道数(%s)，跳过", arr.shape[2])
                return None
            h, w = arr.shape[0], arr.shape[1]
            if h < 21 or w < 21:  # QR 最小 21x21 模块
                return None  # 太小不可能有码，静默跳过（高频，不打日志）
            if h > 8192 or w > 8192:  # 异常大，可能是损坏的 buffer
                logger.warning("[AI] 拒绝超大图像(%dx%d)，跳过", w, h)
                return None
            if not arr.flags["C_CONTIGUOUS"]:
                arr = np.ascontiguousarray(arr)
            # 优化2：纯色图快速拒绝——全黑/全白/纯色不可能有二维码，
            # 用降采样后的标准差 O(1) 判断，省一次 WeChatQR 调用（~50ms）。
            # 降采样到 64x64 再算， overhead < 0.1ms。
            try:
                small = arr[::max(1, h // 64), ::max(1, w // 64)]
                if float(small.std()) < 5.0:
                    return None
            except Exception:
                pass

            img_bgr = arr
            color = (color or "BGR").upper()
            wechat_attempted = False
            if OPENCV_AVAILABLE:
                if arr.ndim == 2:
                    img_bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
                elif color == "BGR":
                    # 已是 BGR（DXGI 零拷贝路径），无需转换
                    img_bgr = arr
                elif color == "RGB":
                    img_bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
                elif color == "GRAY":
                    img_bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

                # thread_local detector：各线程独立实例，无需锁
                detector = self._get_thread_detector()
                if detector is not None:
                    wechat_attempted = True
                    try:
                        res, points = detector.detectAndDecode(img_bgr)
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

            # pyzbar 兜底（~200ms）：只在允许时跑。热路径上 WeChatQR 已尝试
            # 未命中即返回，避免慢兜底阻塞更新鲜的帧；WeChatQR 不可用时
            # pyzbar 是唯一希望，必须跑。
            # 注意：曾有"小图跳过 pyzbar"优化，但它与以下契约冲突：
            # 1) allow_slow_fallback=True 时调用方明确要求跑慢兜底
            # 2) WeChatQR 不可用时 pyzbar 是唯一解码器
            # 故移除该优化，保证契约优先。
            if not allow_slow_fallback and wechat_attempted:
                return None
            decoded_objects = decode(pil_image)
            for obj in decoded_objects:
                accepted = self._accepted_qr_data(obj.data)
                if accepted:
                    return accepted
        except Exception:
            pass
        return None

    def try_decode_qr(
        self, img: Image.Image, allow_slow_fallback: bool = True
    ) -> Optional[str]:
        """
        尝试解码单张图片的QR码
        🚀 优先使用微信QR码检测器（与MHY_Scanner相同），失败则fallback到pyzbar
        """
        if OPENCV_AVAILABLE:
            result = self.try_decode_array(
                np.array(img), color="RGB", allow_slow_fallback=allow_slow_fallback
            )
            if result:
                return result
        
        # 🔄 方案2：Fallback到pyzbar（兼容性好，~200ms）。
        # 热路径可通过 allow_slow_fallback=False 跳过，但 WeChatQR 不可用
        # 时 pyzbar 是唯一解码器，必须跑。
        # thread_local：检查当前线程能否拿到 detector
        wechat_available = OPENCV_AVAILABLE and self._get_thread_detector() is not None
        if not allow_slow_fallback and wechat_available:
            return None
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
    
    def try_decode_parallel(
        self,
        images: List[Tuple[str, object]],
        allow_slow_fallback: bool = True,
        array_color: str = "RGB",
    ) -> Optional[Tuple[str, str]]:
        """
        🚀 并行尝试解码多个图像候选（速度提升30-50%）
        
        Args:
            images: List of (method_name, image) tuples；image 可为 PIL.Image
                （走 try_decode_qr）或 np.ndarray（走 try_decode_array，
                免 PIL→numpy 重复转换）
            allow_slow_fallback: 透传给各候选的解码（见 try_decode_array）
            array_color: np.ndarray 候选的颜色顺序（"RGB"/"BGR"/"GRAY"）
        
        Returns:
            (qr_code, method_name) if found, None otherwise
        """
        # 注意：单候选也走 executor，不做直调 fast-path——
        # as_completed 的 timeout 是 native hang 的唯一保护，直调会丢掉它。
        # 0.5ms 的提交开销不值得冒 hang 死风险。
        futures = {}
        
        # 提交所有任务
        for method_name, img in images:
            if hasattr(img, "shape"):
                # np.ndarray：直接走数组路径，免 PIL→numpy 重复转换
                future = self.parallel_executor.submit(
                    self.try_decode_array, img, array_color, allow_slow_fallback
                )
            else:
                future = self.parallel_executor.submit(
                    self.try_decode_qr, img, allow_slow_fallback
                )
            futures[future] = method_name
        
        # 等待第一个成功的结果。
        # 有界等待 + 单任务异常隔离：某个 worker 在 native 层 hang 住
        # 或抛异常时，不能把调用线程（扫描线程）一起拖死。
        # 优化3：超时按图像尺寸自适应——1080p 基准 10s，4K 给 15s，
        # 小图 5s。避免大图超时误杀、小图空等。
        try:
            max_pixels = 0
            for _, img in images:
                if hasattr(img, "shape") and len(img.shape) >= 2:
                    max_pixels = max(max_pixels, img.shape[0] * img.shape[1])
            # 1080p=2M像素→10s，线性缩放，夹在 5s~15s
            timeout_s = min(15.0, max(5.0, 10.0 * max_pixels / 2073600)) if max_pixels else _PARALLEL_DECODE_TIMEOUT_S
        except Exception:
            timeout_s = _PARALLEL_DECODE_TIMEOUT_S
        try:
            completed = as_completed(futures, timeout=timeout_s)
        except FuturesTimeoutError:
            completed = iter(())
        try:
            for future in completed:
                try:
                    result = future.result()
                except Exception:
                    continue  # 单个候选失败不影响其他
                if result:
                    # 取消其他任务
                    for f in futures:
                        if f != future:
                            f.cancel()
                    return (result, futures[future])
        except FuturesTimeoutError:
            pass
        finally:
            # 超时/异常路径：取消还没跑完的任务，避免白烧 CPU
            for f in futures:
                f.cancel()

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

            # 零拷贝路径：DXGI 后端直接返回 BGR numpy，跳过 PIL 中转
            # （省一次 6MB 拷贝 + BGR→RGB→BGR 来回转换）
            img_np_direct = None
            img_color = "RGB"
            screenshot_method = "unknown"
            for _backend in self._screenshot_backends:
                _grab_np = getattr(_backend, "grab_region_numpy", None)
                if _grab_np is None:
                    continue
                try:
                    _res = _grab_np(x, y, width, height)
                except Exception:
                    continue
                if _res is not None:
                    img_np_direct, img_color = _res
                    screenshot_method = getattr(_backend, "name", "unknown") + "+numpy"
                    break

            if img_np_direct is not None:
                img = None  # PIL 路径跳过
            else:
                img, screenshot_method = grab_region_first_success(
                    self._screenshot_backends, x, y, width, height
                )
            
            # 守卫：截图失败/窗口最小化时 img 可能为 None 或 0 尺寸，
            # 直接喂给后续的 resize/解码是崩溃高发区。
            if img_np_direct is not None:
                if img_np_direct.size == 0 or img_np_direct.shape[0] <= 0 or img_np_direct.shape[1] <= 0:
                    logger.warning("[Scan] 截图返回空数组，跳过本次扫描")
                    return None
            elif img is None or getattr(img, "width", 0) <= 0 or getattr(img, "height", 0) <= 0:
                logger.warning(
                    "[Scan] 截图返回空图像(method=%s)，跳过本次扫描", screenshot_method
                )
                return None

            # 🚀 性能监控：截图完成
            if PERF_MONITOR_AVAILABLE:
                perf_monitor.mark_screenshot_done(method=screenshot_method, image_size=(img.width, img.height))
            
            # 🔍 QR检测阶段
            
            # 🚀 准备多个候选图像（用于并行识别）
            # OpenCV 预处理（比 PIL 快 8 倍，实测 81ms→10ms）：
            # 截图是 PIL Image，转 numpy 一次，之后全走 cv2。
            _pooled_buf = None  # 池化 buffer（OpenCV 路径按需分配）
            # 零拷贝路径（DXGI）直接拿到 BGR numpy，无需转换。
            if OPENCV_AVAILABLE:
                if img_np_direct is not None:
                    # 零拷贝：BGR 直送，try_decode_array 用 color="BGR"
                    img_arr = img_np_direct
                    arr_color = img_color  # "BGR"
                else:
                    img_np = np.asarray(img)
                    if img_np.ndim == 2:
                        img_arr = cv2.cvtColor(img_np, cv2.COLOR_GRAY2BGR)
                        arr_color = "BGR"
                    else:
                        # PIL 是 RGB，直接用 color="RGB"（免一次转换）
                        img_arr = img_np
                        arr_color = "RGB"
                # 截图降采样（4K屏）：screen_capture_downscale<1.0 时先缩小，
                # 省后续 resize+解码时间。默认 1.0（不降采样）。
                # buffer 复用：dst 写入池化 buffer，省一次分配
                from utils.config_manager import config_manager as _cm2
                from utils.ndarray_pool import ndarray_pool as _pool
                _downscale = _cm2.get("screen_capture_downscale", 1.0)
                if _downscale < 1.0 and _downscale > 0.1:
                    _dh, _dw = img_arr.shape[:2]
                    _nw, _nh = max(1, int(_dw * _downscale)), max(1, int(_dh * _downscale))
                    _pooled_buf = _pool.get((_nh, _nw, 3), np.uint8)
                    cv2.resize(img_arr, (_nw, _nh), dst=_pooled_buf,
                               # 优化18：降采样用 INTER_AREA（缩小场景质量更好，
                               # QR 边缘更锐利；放大才用 LINEAR）
                               interpolation=cv2.INTER_AREA)
                    img_arr = _pooled_buf
                h, w = img_arr.shape[:2]

                # numpy 数组直接走 try_decode_array，免 PIL→numpy 转换
                # 单候选（默认）：benchmark 证明 WeChatQR@0.4 单遍 120-650px
                # 全 3/3 检出，三候选的边际收益抵不过 3 倍串行耗时。
                # 可通过 screen_scan_candidates=3 切回三候选。
                from utils.config_manager import config_manager as _cm
                _n_candidates = _cm.get("screen_scan_candidates", 1)
                if _n_candidates == 1:
                    candidates = [("original", img_arr)]
                else:
                    target_width = 1280
                    target_height = 720
                    width_ratio = target_width / w
                    height_ratio = target_height / h
                    scale_ratio = min(width_ratio, height_ratio)
                    new_width = max(1, int(w * scale_ratio))
                    new_height = max(1, int(h * scale_ratio))

                    # 优化18：降采样用 INTER_AREA（边缘更锐利，QR 识别率更高）
                    img_1280 = cv2.resize(img_arr, (new_width, new_height),
                                          interpolation=cv2.INTER_AREA)
                    img_40 = cv2.resize(
                        img_arr,
                        (max(1, int(w * 0.4)), max(1, int(h * 0.4))),
                        interpolation=cv2.INTER_AREA,
                    )
                    candidates = [
                        ("original", img_arr),       # 原图（优先）
                        ("1280x720", img_1280),       # 标准尺寸
                        ("40%", img_40),              # 缩小版本
                    ]
            else:
                # 无 OpenCV 回退：PIL 路径（慢，但能用）
                _n_candidates_fb = _cm.get("screen_scan_candidates", 1)
                if _n_candidates_fb == 1:
                    candidates = [("original", img)]
                else:
                    target_width = 1280
                    target_height = 720
                    width_ratio = target_width / img.width
                    height_ratio = target_height / img.height
                    scale_ratio = min(width_ratio, height_ratio)
                    new_width = max(1, int(img.width * scale_ratio))
                    new_height = max(1, int(img.height * scale_ratio))
                    img_1280 = img.resize((new_width, new_height), Image.Resampling.BILINEAR)
                    img_40 = img.resize(
                        (max(1, int(img.width * 0.4)), max(1, int(img.height * 0.4))),
                        Image.Resampling.BILINEAR,
                    )
                    candidates = [
                        ("original", img),
                        ("1280x720", img_1280),
                        ("40%", img_40),
                    ]
            
            # 🚀 调试：打印扫描信息
            if self.debug_mode:
                logger.info(f"[Scan] Trying {len(candidates)} candidates, size: {img.width}x{img.height}")
            
            # 热路径：候选只跑 WeChatQR（~15ms/个），跳过 pyzbar 兜底
            # （~200ms/个）。WeChatQR 在各尺寸二维码上 3/3 检出（见 benchmarks），
            # pyzbar 的边际收益不足以抵消它在 UI 线程上的阻塞。
            parallel_result = self.try_decode_parallel(
                candidates, allow_slow_fallback=False,
                array_color=arr_color if OPENCV_AVAILABLE else "RGB",
            )
            # 归还池化 buffer（try_decode_parallel 已阻塞等待完成）
            if _pooled_buf is not None:
                try:
                    from utils.ndarray_pool import ndarray_pool as _pool2
                    _pool2.put(_pooled_buf)
                except Exception:
                    pass
            
            if parallel_result:
                qr_code, method = parallel_result
                decoder = "WeChat" if self.wechat_detector else "pyzbar"
                
                # 🚀 性能监控：QR检测完成
                if PERF_MONITOR_AVAILABLE:
                    perf_monitor.mark_qr_detect_done(method=method, decoder=decoder)
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

    def shutdown(self) -> None:
        """关闭并行解码线程池（进程退出时调用）。

        用 ``wait=False`` 避免 UI 线程被 hang 住的 worker 拖死；
        ``cancel_futures=True`` 丢弃排队中的任务。注意：若某个
        worker 正卡在 native 调用里，非守护线程仍会拖住进程退出——
        这是保底手段，真正的 hang 隔离靠 try_decode_parallel 的超时。
        """
        try:
            self.parallel_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


# 全局AI扫描器实例
ai_qr_scanner = AIQRScanner()

