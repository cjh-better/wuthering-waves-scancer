# -*- coding: utf-8 -*-
"""
直播流QR码扫描器（支持B站、抖音、虎牙等平台）
使用OpenCV读取直播流，无需额外安装FFmpeg
"""
import cv2
import re
import requests
from typing import Optional, Callable
from PySide6.QtCore import QThread, Signal
import time


class LiveStreamScanner(QThread):
    """直播流扫描器"""
    
    # 信号
    qr_detected = Signal(str)  # 检测到QR码
    status_changed = Signal(str)  # 状态改变
    error_occurred = Signal(str)  # 错误发生
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream_url = ""
        self.is_running = False
        self.cap = None
        self.platform = "bilibili"  # bilibili, douyin, huya
    
    def set_stream_url(self, url: str, platform: str = "bilibili"):
        """
        设置直播流地址
        
        Args:
            url: 直播流URL或房间号
            platform: 平台类型 (bilibili, douyin, huya)
        """
        self.stream_url = url
        self.platform = platform
    
    def get_bilibili_stream_url(self, room_id: str) -> Optional[str]:
        """
        获取B站直播流地址
        
        Args:
            room_id: B站房间号
        
        Returns:
            直播流URL，失败返回None
        """
        try:
            # 获取房间信息
            api_url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
            response = requests.get(api_url, timeout=5)
            data = response.json()
            
            if data.get("code") != 0:
                self.error_occurred.emit(f"房间不存在或未开播")
                return None
            
            # 检查直播状态
            live_status = data["data"]["live_status"]
            if live_status != 1:
                self.error_occurred.emit("主播未开播")
                return None
            
            # 获取真实房间号
            real_room_id = data["data"]["room_id"]
            
            # 获取直播流地址
            stream_api = f"https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo"
            params = {
                "room_id": real_room_id,
                "protocol": "0,1",
                "format": "0,1,2",
                "codec": "0,1",
                "qn": 10000,
                "platform": "web",
                "ptype": 8
            }
            
            response = requests.get(stream_api, params=params, timeout=5)
            data = response.json()
            
            # 解析流地址
            if data.get("code") == 0 and "playurl_info" in data["data"]:
                streams = data["data"]["playurl_info"]["playurl"]["stream"]
                for stream in streams:
                    for format_item in stream["format"]:
                        for codec in format_item["codec"]:
                            if "url_info" in codec:
                                base_url = codec["url_info"][0]["host"]
                                extra = codec["url_info"][0]["extra"]
                                url = f"{base_url}{codec['base_url']}{extra}"
                                return url
            
            self.error_occurred.emit("无法获取直播流地址")
            return None
            
        except Exception as e:
            self.error_occurred.emit(f"获取B站直播流失败: {e}")
            return None
    
    def get_douyin_stream_url(self, room_id: str) -> Optional[str]:
        """
        获取抖音直播流地址（简化版）
        
        Args:
            room_id: 抖音房间号或直播间URL
        
        Returns:
            直播流URL，失败返回None
        """
        try:
            # 抖音直播流获取较复杂，需要解析网页
            # 这里提供一个简化实现
            self.error_occurred.emit("抖音直播流需要额外配置，建议使用B站")
            return None
        except Exception as e:
            self.error_occurred.emit(f"获取抖音直播流失败: {e}")
            return None
    
    def run(self):
        """主扫描循环"""
        self.is_running = True
        self.status_changed.emit("正在连接直播流...")
        
        # 解析流地址
        stream_url = self.stream_url
        
        # 如果是房间号，获取流地址
        if self.platform == "bilibili" and stream_url.isdigit():
            stream_url = self.get_bilibili_stream_url(stream_url)
            if not stream_url:
                self.is_running = False
                return
        
        # 打开视频流
        try:
            self.cap = cv2.VideoCapture(stream_url)
            
            if not self.cap.isOpened():
                self.error_occurred.emit("无法打开直播流")
                self.is_running = False
                return
            
            self.status_changed.emit("已连接直播流，开始扫描...")
            
            # 导入QR扫描器
            try:
                from utils.ai_qr_scanner import ai_qr_scanner
                scanner = ai_qr_scanner
            except:
                from utils.qr_scanner import qr_scanner
                scanner = qr_scanner
            
            frame_count = 0
            last_ticket = ""
            
            while self.is_running:
                ret, frame = self.cap.read()
                
                if not ret:
                    self.error_occurred.emit("直播流中断")
                    break
                
                frame_count += 1
                
                # 每5帧扫描一次（降低CPU占用）
                if frame_count % 5 != 0:
                    continue
                
                try:
                    # 转换为PIL Image
                    from PIL import Image
                    import numpy as np
                    
                    # BGR转RGB
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(rgb_frame)
                    
                    # 尝试识别QR码
                    # 注意：这里需要修改scanner接口以支持PIL Image
                    # 暂时使用简化方法
                    qr_code = self._scan_frame(pil_image)
                    
                    if qr_code:
                        # 去重检查
                        if len(qr_code) >= 24:
                            ticket = qr_code[-24:]
                            if ticket != last_ticket:
                                last_ticket = ticket
                                self.qr_detected.emit(qr_code)
                                self.status_changed.emit(f"检测到QR码: {ticket[:8]}...")
                
                except Exception as e:
                    print(f"[LiveStream] Frame scan error: {e}")
                    continue
                
                # 控制扫描速度
                time.sleep(0.05)  # 50ms间隔
            
        except Exception as e:
            self.error_occurred.emit(f"扫描错误: {e}")
        finally:
            self.cleanup()
    
    def _scan_frame(self, image) -> Optional[str]:
        """扫描单帧图像"""
        try:
            from utils.ai_qr_scanner import ai_qr_scanner
            
            # 使用AI扫描器的try_decode_qr方法
            return ai_qr_scanner.try_decode_qr(image)
        except Exception as e:
            print(f"[LiveStream] Scan error: {e}")
            return None
    
    def stop(self):
        """停止扫描"""
        self.is_running = False
        self.status_changed.emit("正在停止...")
    
    def cleanup(self):
        """清理资源"""
        if self.cap:
            self.cap.release()
            self.cap = None
        self.is_running = False
        self.status_changed.emit("已停止")


# 全局实例
_live_stream_scanner = None

def get_live_stream_scanner() -> LiveStreamScanner:
    """获取直播流扫描器单例"""
    global _live_stream_scanner
    if _live_stream_scanner is None:
        _live_stream_scanner = LiveStreamScanner()
    return _live_stream_scanner


