# -*- coding: utf-8 -*-
"""二维码扫描器 - 增强版（支持图像预处理和多次识别）"""
from PIL import ImageGrab, Image, ImageEnhance
from pyzbar.pyzbar import decode
from typing import Optional, List
import ctypes
import numpy as np

# 尝试导入OpenCV，如果没有就使用基础版本
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False
    print("[警告] OpenCV未安装，将使用基础图像处理（建议: pip install opencv-python）")


class QRScanner:
    """二维码扫描器 - 支持直播间低质量QR码识别"""
    
    def __init__(self):
        # 获取屏幕缩放因子
        try:
            self.scale_factor = ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
        except Exception:
            self.scale_factor = 1.0
    
    def enhance_image_basic(self, img: Image.Image) -> List[Image.Image]:
        """
        基础图像增强（不依赖OpenCV）
        返回多个增强版本，提高识别率
        """
        enhanced_images = [img]  # 原图
        
        try:
            # 1. 提高对比度
            enhancer = ImageEnhance.Contrast(img)
            enhanced_images.append(enhancer.enhance(2.0))  # 2倍对比度
            
            # 2. 提高亮度
            enhancer = ImageEnhance.Brightness(img)
            enhanced_images.append(enhancer.enhance(1.5))  # 1.5倍亮度
            
            # 3. 锐化
            enhancer = ImageEnhance.Sharpness(img)
            enhanced_images.append(enhancer.enhance(2.0))  # 2倍锐化
            
            # 4. 综合增强（对比度+锐化）
            temp = ImageEnhance.Contrast(img).enhance(1.8)
            temp = ImageEnhance.Sharpness(temp).enhance(1.8)
            enhanced_images.append(temp)
            
        except Exception as e:
            print(f"[警告] 基础图像增强失败: {e}")
        
        return enhanced_images
    
    def enhance_image_opencv(self, img: Image.Image) -> List[Image.Image]:
        """
        OpenCV高级图像增强（针对直播间低质量QR码）
        返回多个增强版本，提高识别率
        """
        enhanced_images = [img]  # 原图
        
        if not OPENCV_AVAILABLE:
            return self.enhance_image_basic(img)
        
        try:
            # 转换为OpenCV格式
            img_cv = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
            
            # 1. 自适应直方图均衡化（CLAHE）- 提高对比度
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            enhanced_images.append(Image.fromarray(enhanced))
            
            # 2. 自适应二值化
            binary = cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
                cv2.THRESH_BINARY, 11, 2
            )
            enhanced_images.append(Image.fromarray(binary))
            
            # 3. 去噪 + 二值化
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            binary2 = cv2.adaptiveThreshold(
                denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY, 11, 2
            )
            enhanced_images.append(Image.fromarray(binary2))
            
            # 4. 形态学处理（增强QR码边缘）
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            morph = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
            enhanced_images.append(Image.fromarray(morph))
            
            # 5. 锐化滤波
            kernel_sharp = np.array([[-1,-1,-1], 
                                     [-1, 9,-1], 
                                     [-1,-1,-1]])
            sharpened = cv2.filter2D(gray, -1, kernel_sharp)
            enhanced_images.append(Image.fromarray(sharpened))
            
            # 6. 综合增强：去噪 + CLAHE + 锐化
            denoised = cv2.fastNlMeansDenoising(gray, None, 10, 7, 21)
            enhanced = clahe.apply(denoised)
            sharpened = cv2.filter2D(enhanced, -1, kernel_sharp)
            enhanced_images.append(Image.fromarray(sharpened))
            
        except Exception as e:
            print(f"[警告] OpenCV图像增强失败: {e}")
            # 降级到基础增强
            return self.enhance_image_basic(img)
        
        return enhanced_images
    
    def try_decode_qr(self, img: Image.Image) -> Optional[str]:
        """
        尝试解码单张图片的QR码
        """
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
    
    def scan_region(self, x: int, y: int, width: int, height: int) -> Optional[str]:
        """
        扫描指定区域的二维码 - 增强版（多次尝试识别）
        
        Args:
            x: 区域左上角 x 坐标
            y: 区域左上角 y 坐标
            width: 区域宽度
            height: 区域高度
            
        Returns:
            二维码内容，如果没有检测到则返回 None
        """
        try:
            # 考虑屏幕缩放
            x_scaled = int(x * self.scale_factor)
            y_scaled = int(y * self.scale_factor)
            width_scaled = int(width * self.scale_factor)
            height_scaled = int(height * self.scale_factor)
            
            # 截图
            img = ImageGrab.grab(bbox=(
                x_scaled,
                y_scaled,
                x_scaled + width_scaled,
                y_scaled + height_scaled
            ))
            
            # 🚀 多次尝试识别（原图 + 多个增强版本）
            # 先尝试原图（最快）
            result = self.try_decode_qr(img)
            if result:
                return result
            
            # 如果原图失败，使用增强版本
            if OPENCV_AVAILABLE:
                enhanced_images = self.enhance_image_opencv(img)
            else:
                enhanced_images = self.enhance_image_basic(img)
            
            # 遍历所有增强版本尝试识别
            for enhanced_img in enhanced_images[1:]:  # 跳过原图（已尝试）
                result = self.try_decode_qr(enhanced_img)
                if result:
                    return result
            
            return None
            
        except Exception as e:
            print(f"扫描二维码失败: {e}")
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
            
            # 使用增强版本
            if OPENCV_AVAILABLE:
                enhanced_images = self.enhance_image_opencv(img)
            else:
                enhanced_images = self.enhance_image_basic(img)
            
            for enhanced_img in enhanced_images[1:]:
                result = self.try_decode_qr(enhanced_img)
                if result:
                    return result
            
            return None
            
        except Exception as e:
            print(f"从剪贴板扫描二维码失败: {e}")
            return None


# 全局扫描器实例
qr_scanner = QRScanner()
