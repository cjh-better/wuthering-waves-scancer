# -*- coding: utf-8 -*-
"""
Windows BitBlt快速截图（参考MHY_Scanner）
比PIL.ImageGrab快5-10倍
"""
import numpy as np
import threading
from PIL import Image
import win32gui
import win32ui
import win32con
import win32api
from utils.log import get_logger


logger = get_logger("FastScreenshot")


class FastScreenshot:
    """Windows BitBlt快速截图工具"""

    name = "BitBlt"  # ScreenshotBackend contract (see utils.screenshot)
    
    def __init__(self):
        """初始化截图工具"""
        # 获取屏幕尺寸（考虑DPI缩放）
        self.screen_width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
        self.screen_height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
        
        # 获取DPI缩放比例
        self.scale_factor = self._get_scale_factor()
        
        # 实际物理尺寸
        self.physical_width = int(self.screen_width * self.scale_factor)
        self.physical_height = int(self.screen_height * self.scale_factor)
        
        # 创建设备上下文（复用，避免重复创建）
        self.hwndDC = win32gui.GetWindowDC(0)
        self.mfcDC = win32ui.CreateDCFromHandle(self.hwndDC)
        self.saveDC = self.mfcDC.CreateCompatibleDC()
        
        # 创建位图对象（复用）
        self.saveBitMap = win32ui.CreateBitmap()
        self.saveBitMap.CreateCompatibleBitmap(self.mfcDC, self.physical_width, self.physical_height)
        self.saveDC.SelectObject(self.saveBitMap)
    
    def _get_scale_factor(self):
        """获取屏幕DPI缩放比例"""
        try:
            # 获取主显示器的DPI缩放
            hdc = win32gui.GetDC(0)
            dpi = win32ui.CreateDCFromHandle(hdc).GetDeviceCaps(88)  # LOGPIXELSX
            win32gui.ReleaseDC(0, hdc)
            return dpi / 96.0  # 96 DPI = 100% 缩放
        except Exception:
            return 1.0
    
    def grab_screen(self):
        """
        🚀 使用BitBlt截取整个屏幕（极速）
        
        Returns:
            PIL.Image: 截图对象
        """
        # BitBlt复制屏幕到内存DC（这是最快的方式）
        self.saveDC.BitBlt((0, 0), (self.physical_width, self.physical_height),
                           self.mfcDC, (0, 0), win32con.SRCCOPY)
        
        # 转换为numpy数组
        bmpinfo = self.saveBitMap.GetInfo()
        bmpstr = self.saveBitMap.GetBitmapBits(True)
        
        # 创建PIL图像
        img = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1
        )
        
        return img
    
    def grab_region(self, x, y, width, height):
        """
        🚀 使用BitBlt截取屏幕区域（极速）
        
        Args:
            x: 区域左上角X坐标
            y: 区域左上角Y坐标
            width: 区域宽度
            height: 区域高度
        
        Returns:
            PIL.Image: 截图对象
        """
        # 考虑DPI缩放
        x_scaled = int(x * self.scale_factor)
        y_scaled = int(y * self.scale_factor)
        width_scaled = int(width * self.scale_factor)
        height_scaled = int(height * self.scale_factor)
        
        # 创建临时位图（仅限于区域大小）
        saveBitMap = win32ui.CreateBitmap()
        saveBitMap.CreateCompatibleBitmap(self.mfcDC, width_scaled, height_scaled)
        saveDC = self.mfcDC.CreateCompatibleDC()
        saveDC.SelectObject(saveBitMap)
        
        # BitBlt复制指定区域
        saveDC.BitBlt((0, 0), (width_scaled, height_scaled),
                      self.mfcDC, (x_scaled, y_scaled), win32con.SRCCOPY)
        
        # 转换为numpy数组
        bmpinfo = saveBitMap.GetInfo()
        bmpstr = saveBitMap.GetBitmapBits(True)
        
        # 创建PIL图像
        img = Image.frombuffer(
            'RGB',
            (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1
        )
        
        # 清理临时对象
        saveDC.DeleteDC()
        saveBitMap.DeleteObject()
        
        return img
    
    def __del__(self):
        """清理资源"""
        try:
            self.saveBitMap.DeleteObject()
            self.saveDC.DeleteDC()
            self.mfcDC.DeleteDC()
            win32gui.ReleaseDC(0, self.hwndDC)
        except Exception:
            pass


# 全局单例（避免重复创建）
_fast_screenshot = None
_fast_screenshot_lock = threading.Lock()


def get_fast_screenshot():
    """获取快速截图工具单例（线程安全）"""
    global _fast_screenshot
    if _fast_screenshot is None:
        with _fast_screenshot_lock:
            if _fast_screenshot is None:
                try:
                    _fast_screenshot = FastScreenshot()
                    logger.info("[FastScreenshot] BitBlt快速截图已启用（比PIL快5-10倍）")
                except Exception as e:
                    logger.warning(f"[FastScreenshot] 初始化失败，将使用PIL: {e}")
                    _fast_screenshot = None
    return _fast_screenshot


