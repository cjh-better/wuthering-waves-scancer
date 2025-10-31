# -*- coding: utf-8 -*-
"""扫描窗口 - AI增强版"""
from PySide6.QtCore import Qt, QTimer, Signal, QRect
from PySide6.QtWidgets import QWidget, QLabel, QApplication
from PySide6.QtGui import QPainter, QPen, QColor, QCursor

# 尝试导入AI扫描器，如果失败则使用普通扫描器
try:
    from utils.ai_qr_scanner import ai_qr_scanner as qr_scanner
    print("[AI] Using AI-enhanced scanner")
except Exception as e:
    print(f"[Warning] AI scanner failed to load, using standard scanner: {e}")
    from utils.qr_scanner import qr_scanner


class ScanWindow(QWidget):
    """扫描窗口 - 半透明可拖动的红框"""
    
    qr_detected = Signal(str)  # 检测到二维码信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.border_width = 3
        self.border_color = QColor(0, 122, 255)  # iOS blue
        self.bg_color = QColor(0, 122, 255, 20)  # semi-transparent iOS blue
        
        # Initial size and position - default center and 800x800
        window_width = 800
        window_height = 800
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - window_width) // 2
        y = (screen.height() - window_height) // 2
        self.setGeometry(x, y, window_width, window_height)
        
        # Drag related
        self.dragging = False
        self.drag_position = None
        
        # Scan timer - 🚀 超高频扫描模式（100ms间隔，确保不漏过二维码）
        self.scan_timer = QTimer(self)
        self.scan_timer.timeout.connect(self.scan_qr_code)
        self.scan_interval = 100  # 100ms = 每秒10次扫描（平衡性能和识别率）
        
        # Hint label - iOS style
        self.hint_label = QLabel("将此框对准二维码\n右键关闭", self)
        self.hint_label.setAlignment(Qt.AlignCenter)
        self.hint_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background-color: rgba(0, 122, 255, 220);
                padding: 12px 20px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
        self.hint_label.adjustSize()
        self.update_hint_position()
        # Let label not block mouse events, can drag through
        self.hint_label.setAttribute(Qt.WA_TransparentForMouseEvents)
        
        # Last detected QR code
        self.last_qr_code = None
        # Whether processing QR code
        self.processing_qr = False
        
        # 🚀 Ticket去重机制（防止重复提交同一个QR码）
        self.last_ticket = ""  # 上次处理的ticket（QR码的最后24位）
    
    def paintEvent(self, event):
        """Paint event"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw background
        painter.fillRect(self.rect(), self.bg_color)
        
        # Draw border
        pen = QPen(self.border_color)
        pen.setWidth(self.border_width)
        painter.setPen(pen)
        
        rect = self.rect()
        offset = self.border_width // 2
        painter.drawRect(
            offset, offset,
            rect.width() - self.border_width,
            rect.height() - self.border_width
        )
    
    def mousePressEvent(self, event):
        """Mouse press event"""
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        elif event.button() == Qt.RightButton:
            self.close()
    
    def mouseMoveEvent(self, event):
        """Mouse move event"""
        if self.dragging and event.buttons() == Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()
    
    def mouseReleaseEvent(self, event):
        """Mouse release event"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
    
    def resizeEvent(self, event):
        """Window resize event"""
        super().resizeEvent(event)
        self.update_hint_position()
    
    def update_hint_position(self):
        """Update hint label position"""
        self.hint_label.adjustSize()
        x = (self.width() - self.hint_label.width()) // 2
        y = (self.height() - self.hint_label.height()) // 2
        self.hint_label.move(x, y)
    
    def start_scanning(self):
        """Start scanning"""
        self.last_ticket = ""  # 🚀 清空上次ticket，允许重新扫描
        self.processing_qr = False  # 🚀 重置处理状态
        self.last_qr_code = None  # 🚀 重置上次识别的二维码
        self.scan_timer.start(self.scan_interval)
        self.hint_label.setText("正在扫描...")
    
    def stop_scanning(self):
        """Stop scanning"""
        self.scan_timer.stop()
        self.hint_label.setText("将此框对准二维码\n右键关闭")
    
    def scan_qr_code(self):
        """🚀 扫描二维码 - 持续扫描模式"""
        # If processing QR code, skip this scan
        if self.processing_qr:
            return
            
        # Get window position and size
        geometry = self.geometry()
        x = geometry.x()
        y = geometry.y()
        width = geometry.width()
        height = geometry.height()
        
        # 🚀 扫描区域（每次都尝试识别）
        qr_code = qr_scanner.scan_region(x, y, width, height)
        
        if qr_code:
            # 🚀 提取Ticket（QR码的最后24位作为唯一标识）
            if len(qr_code) >= 24:
                ticket = qr_code[-24:]
                
                # 🚀 去重检查：如果与上次ticket相同，直接跳过（防止重复提交）
                if ticket == self.last_ticket:
                    # 已经提交过这个二维码，继续扫描（等待新二维码）
                    return
                
                # 🚀 发现新二维码！
                self.last_ticket = ticket
                print(f"[QR] ✓ New QR detected: {ticket[:8]}...")
            
            # 🚀 立即发送信号并停止扫描
            self.last_qr_code = qr_code
            self.processing_qr = True  # Mark as processing
            self.qr_detected.emit(qr_code)
            
            # 更新UI提示
            self.hint_label.setText("✓ 检测到二维码\n正在登录...")
            self.hint_label.setStyleSheet("""
                QLabel {
                    color: #FFFFFF;
                    background-color: rgba(52, 199, 89, 220);
                    padding: 12px 20px;
                    border-radius: 12px;
                    font-size: 14px;
                    font-weight: 600;
                    font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
                }
            """)
            
            # 🚀 继续扫描（不停止），但标记为处理中（避免重复提交）
            # self.scan_timer.stop()  # 注释掉，保持持续扫描
            
            # 3秒后重置处理状态（允许识别新二维码）
            QTimer.singleShot(3000, self.reset_processing)
    
    def reset_processing(self):
        """Reset processing state"""
        # 🚀 只重置处理标志，保留last_ticket（防止重复提交同一个码）
        self.processing_qr = False
        self.last_qr_code = None
        # 如果扫描窗口还在运行，恢复提示
        if not self.scan_timer.isActive():
            self.scan_timer.start(self.scan_interval)
        self.reset_hint_style()
    
    def reset_hint_style(self):
        """Reset hint style"""
        self.hint_label.setText("正在扫描...")
        self.hint_label.setStyleSheet("""
            QLabel {
                color: #FFFFFF;
                background-color: rgba(0, 122, 255, 220);
                padding: 12px 20px;
                border-radius: 12px;
                font-size: 14px;
                font-weight: 600;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
        """)
    
    def closeEvent(self, event):
        """Close event"""
        self.stop_scanning()
        super().closeEvent(event)
