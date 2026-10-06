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
        if self.method == "dxcam" and self.camera:
            return self._grab_with_dxcam(x, y, width, height)
        elif self.method == "mss" and self.mss_instance:
            return self._grab_with_mss(x, y, width, height)
        else:
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


