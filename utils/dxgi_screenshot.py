# -*- coding: utf-8 -*-
"""
DXGI快速截图（GPU加速，与MHY_Scanner相同技术）
使用dxcam库（纯DXGI实现，比BitBlt更快）
"""
from PIL import Image
import numpy as np
import threading
from typing import Optional
from utils.log import get_logger


logger = get_logger("DXGI")

# 尝试导入dxcam（DXGI截图，最快）
try:
    import dxcam
    DXCAM_AVAILABLE = True
except ImportError:
    DXCAM_AVAILABLE = False
    logger.info("[DXGI] dxcam not installed, install with: pip install dxcam")

# 尝试导入mss（跨平台截图，次选）
try:
    import mss
    MSS_AVAILABLE = True
except ImportError:
    MSS_AVAILABLE = False


class DXGIScreenshot:
    """DXGI快速截图工具（GPU加速，与MHY_Scanner相同）"""

    name = "DXGI"  # ScreenshotBackend contract (see utils.screenshot)
    
    def __init__(self):
        """初始化DXGI截图工具"""
        self.camera = None
        self.mss_instance = None
        self.method = "none"
        
        # 🚀 优先使用dxcam（纯DXGI，与MHY_Scanner相同技术）
        if DXCAM_AVAILABLE:
            try:
                self.camera = dxcam.create()
                if self.camera:
                    self.method = "dxcam"
                    logger.info("[DXGI] Using dxcam (GPU-accelerated, same as MHY_Scanner)")
                    return
            except Exception as e:
                logger.warning(f"[DXGI] dxcam init failed: {e}")
        
        # 🔄 备选：使用mss（跨平台，稳定）
        if MSS_AVAILABLE:
            try:
                self.mss_instance = mss.mss()
                self.method = "mss"
                logger.info("[DXGI] Using mss (cross-platform fallback)")
                return
            except Exception as e:
                logger.warning(f"[DXGI] mss init failed: {e}")
        
        logger.info("[DXGI] No DXGI library available, will use fallback")
    
    def grab_region(self, x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """
        🚀 使用DXGI截取屏幕区域（GPU加速，极速）
        
        Args:
            x: 区域左上角X坐标
            y: 区域左上角Y坐标
            width: 区域宽度
            height: 区域高度
        
        Returns:
            PIL.Image: 截图对象
        """
        # 优化11：指数退避重试，避免失败时忙循环打爆 CPU
        import time as _t
        for attempt in range(3):
            try:
                result = None
                if self.method == "dxcam" and self.camera:
                    result = self._grab_with_dxcam(x, y, width, height)
                elif self.method == "mss" and self.mss_instance:
                    result = self._grab_with_mss(x, y, width, height)
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"[DXGI] grab attempt {attempt+1} failed: {e}")
            _t.sleep(0.1 * (2 ** attempt))
        return None

    def grab_region_numpy(
        self, x: int, y: int, width: int, height: int
    ) -> "Optional[tuple[np.ndarray, str]]":
        """零拷贝截图：直接返回 numpy 数组，跳过 PIL 中转。

        安全性：dxcam 的 grab() 每次返回新分配的数组（官方文档行为），
        不存在复用 buffer 的竞态。若某版本 dxcam 出现花屏/撕裂，
        置 config `dxgi_copy_frame=true` 强制 copy 一份（多 ~2ms）。

        Returns:
            (array, color) 元组，color 为 "BGR" 或 "RGB"；
            不支持时返回 None，调用方回退到 grab_region()。
        """
        if self.method == "dxcam" and self.camera:
            try:
                region = (x, y, x + width, y + height)
                frame = self.camera.grab(region=region)
                if frame is None:
                    return None
                # dxcam 返回 BGR numpy
                try:
                    from utils.config_manager import config_manager as _cm
                    if _cm.get("dxgi_copy_frame", False):
                        frame = frame.copy()
                except Exception:
                    pass
                return frame, "BGR"
            except Exception:
                return None
        # 优化13：mss 路径也 numpy 直送（BGRA → BGR，免 PIL 中转）
        if self.method == "mss" and self.mss_instance:
            try:
                import numpy as _np
                monitor = {"top": y, "left": x, "width": width, "height": height}
                sct = self.mss_instance.grab(monitor)
                raw = _np.asarray(sct)  # BGRA
                if raw.ndim == 3 and raw.shape[2] == 4:
                    # BGRA → BGR：直接丢弃 alpha 通道
                    arr = _np.ascontiguousarray(raw[:, :, :3])
                else:
                    arr = _np.ascontiguousarray(raw)
                return arr, "BGR"
            except Exception:
                return None
        return None
    
    def _grab_with_dxcam(self, x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """使用dxcam截图（DXGI，最快）"""
        try:
            # dxcam返回numpy数组（BGR格式）
            region = (x, y, x + width, y + height)
            frame = self.camera.grab(region=region)
            
            if frame is None:
                return None
            
            # 转换为PIL Image（RGB格式）
            # dxcam返回的是BGR格式，需要转换
            img = Image.fromarray(frame[..., ::-1])  # BGR -> RGB
            return img
        except Exception as e:
            logger.warning(f"[DXGI] dxcam grab failed: {e}")
            return None
    
    def _grab_with_mss(self, x: int, y: int, width: int, height: int) -> Optional[Image.Image]:
        """使用mss截图（跨平台备选）"""
        try:
            # mss的monitor格式
            monitor = {
                "top": y,
                "left": x,
                "width": width,
                "height": height
            }
            
            # 截图
            sct = self.mss_instance.grab(monitor)
            
            # 转换为PIL Image
            img = Image.frombytes("RGB", sct.size, sct.bgra, "raw", "BGRX")
            return img
        except Exception as e:
            logger.warning(f"[DXGI] mss grab failed: {e}")
            return None
    
    def __del__(self):
        """清理资源"""
        if self.camera:
            try:
                self.camera.release()
            except Exception:
                pass

        if self.mss_instance:
            try:
                self.mss_instance.close()
            except Exception:
                pass


# 全局单例
_dxgi_screenshot = None
_dxgi_screenshot_lock = threading.Lock()


def get_dxgi_screenshot() -> Optional[DXGIScreenshot]:
    """获取DXGI截图工具单例（线程安全）"""
    global _dxgi_screenshot
    if _dxgi_screenshot is None:
        with _dxgi_screenshot_lock:
            if _dxgi_screenshot is None:
                _dxgi_screenshot = DXGIScreenshot()
                if _dxgi_screenshot.method == "none":
                    _dxgi_screenshot = None
    return _dxgi_screenshot


