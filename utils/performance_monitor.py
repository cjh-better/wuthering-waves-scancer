# -*- coding: utf-8 -*-
"""Performance monitoring system for QR code scanning"""
import time
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict


@dataclass
class PerformanceMetrics:
    """Performance metrics for a single scan operation"""
    # Timestamps
    scan_start: float = 0.0
    screenshot_end: float = 0.0
    qr_detect_end: float = 0.0
    api_roleinfo_end: float = 0.0
    api_scanlogin_end: float = 0.0
    scan_end: float = 0.0
    
    # Individual timings (ms)
    screenshot_time: float = 0.0
    qr_detect_time: float = 0.0
    api_roleinfo_time: float = 0.0
    api_scanlogin_time: float = 0.0
    total_time: float = 0.0
    
    # Detection details
    detection_method: str = ""  # "1280x720", "40%", "original", "enhanced", "parallel"
    screenshot_method: str = ""  # "DXGI", "BitBlt", "PIL"
    qr_decoder: str = ""  # "WeChat", "pyzbar"
    
    # Memory info
    image_size: tuple = (0, 0)  # (width, height)
    memory_reused: bool = False
    
    # ROI optimization
    roi_predicted: bool = False
    roi_accuracy: bool = False


class PerformanceMonitor:
    """Global performance monitor singleton"""
    
    def __init__(self):
        self.current_scan: Optional[PerformanceMetrics] = None
        self.history: List[PerformanceMetrics] = []
        self.max_history = 100  # Keep last 100 scans
        
        # Statistics
        self.stats = {
            "total_scans": 0,
            "successful_scans": 0,
            "failed_scans": 0,
            "avg_total_time": 0.0,
            "avg_screenshot_time": 0.0,
            "avg_qr_detect_time": 0.0,
            "avg_api_roleinfo_time": 0.0,
            "avg_api_scanlogin_time": 0.0,
            "fastest_scan": float('inf'),
            "slowest_scan": 0.0,
        }
        
        # Method usage counts
        self.method_counts = defaultdict(int)
    
    def start_scan(self):
        """Start timing a new scan"""
        self.current_scan = PerformanceMetrics()
        self.current_scan.scan_start = time.perf_counter()
    
    def mark_screenshot_done(self, method: str = "unknown", image_size: tuple = (0, 0), memory_reused: bool = False):
        """Mark screenshot phase complete"""
        if not self.current_scan:
            return
        
        now = time.perf_counter()
        self.current_scan.screenshot_end = now
        self.current_scan.screenshot_time = (now - self.current_scan.scan_start) * 1000
        self.current_scan.screenshot_method = method
        self.current_scan.image_size = image_size
        self.current_scan.memory_reused = memory_reused
    
    def mark_qr_detect_done(self, method: str = "unknown", decoder: str = "unknown", roi_predicted: bool = False, roi_accuracy: bool = False):
        """Mark QR detection phase complete"""
        if not self.current_scan:
            return
        
        now = time.perf_counter()
        self.current_scan.qr_detect_end = now
        self.current_scan.qr_detect_time = (now - self.current_scan.screenshot_end) * 1000 if self.current_scan.screenshot_end else 0
        self.current_scan.detection_method = method
        self.current_scan.qr_decoder = decoder
        self.current_scan.roi_predicted = roi_predicted
        self.current_scan.roi_accuracy = roi_accuracy
        
        # Update method usage
        self.method_counts[method] += 1
    
    def mark_api_roleinfo_done(self):
        """Mark roleInfos API call complete"""
        if not self.current_scan:
            return
        
        now = time.perf_counter()
        self.current_scan.api_roleinfo_end = now
        self.current_scan.api_roleinfo_time = (now - self.current_scan.qr_detect_end) * 1000 if self.current_scan.qr_detect_end else 0
    
    def mark_api_scanlogin_done(self):
        """Mark scanLogin API call complete"""
        if not self.current_scan:
            return
        
        now = time.perf_counter()
        self.current_scan.api_scanlogin_end = now
        self.current_scan.api_scanlogin_time = (now - self.current_scan.api_roleinfo_end) * 1000 if self.current_scan.api_roleinfo_end else 0
    
    def end_scan(self, success: bool = True):
        """End current scan and save to history"""
        if not self.current_scan:
            return
        
        now = time.perf_counter()
        self.current_scan.scan_end = now
        self.current_scan.total_time = (now - self.current_scan.scan_start) * 1000
        
        # Add to history
        self.history.append(self.current_scan)
        if len(self.history) > self.max_history:
            self.history.pop(0)
        
        # Update statistics
        self.stats["total_scans"] += 1
        if success:
            self.stats["successful_scans"] += 1
        else:
            self.stats["failed_scans"] += 1
        
        # Update timing stats (only successful scans)
        if success:
            total = self.current_scan.total_time
            self.stats["fastest_scan"] = min(self.stats["fastest_scan"], total)
            self.stats["slowest_scan"] = max(self.stats["slowest_scan"], total)
            
            # Rolling average
            n = self.stats["successful_scans"]
            self.stats["avg_total_time"] = (self.stats["avg_total_time"] * (n-1) + total) / n
            self.stats["avg_screenshot_time"] = (self.stats["avg_screenshot_time"] * (n-1) + self.current_scan.screenshot_time) / n
            self.stats["avg_qr_detect_time"] = (self.stats["avg_qr_detect_time"] * (n-1) + self.current_scan.qr_detect_time) / n
            self.stats["avg_api_roleinfo_time"] = (self.stats["avg_api_roleinfo_time"] * (n-1) + self.current_scan.api_roleinfo_time) / n
            self.stats["avg_api_scanlogin_time"] = (self.stats["avg_api_scanlogin_time"] * (n-1) + self.current_scan.api_scanlogin_time) / n
        
        self.current_scan = None
    
    def get_last_scan_summary(self) -> str:
        """Get summary of last scan"""
        if not self.history:
            return "No scans yet"
        
        last = self.history[-1]
        
        summary = f"""
┌─ Scan Performance Report ─────────────────────┐
│ Total Time:     {last.total_time:6.1f}ms              │
├───────────────────────────────────────────────┤
│ 📸 Screenshot:  {last.screenshot_time:6.1f}ms ({last.screenshot_method:<8s})│
│ 🔍 QR Detect:   {last.qr_detect_time:6.1f}ms ({last.detection_method:<8s})│
│ ⚡ RoleInfos:   {last.api_roleinfo_time:6.1f}ms              │
│ 🚀 ScanLogin:   {last.api_scanlogin_time:6.1f}ms              │
├───────────────────────────────────────────────┤
│ Method: {last.qr_decoder:<8s} | Size: {last.image_size[0]}x{last.image_size[1]}│
│ Memory Reused: {'✓' if last.memory_reused else '✗'} | ROI: {'✓' if last.roi_predicted else '✗'}    │
└───────────────────────────────────────────────┘
"""
        return summary.strip()
    
    def get_statistics_summary(self) -> str:
        """Get overall statistics summary"""
        if self.stats["total_scans"] == 0:
            return "No statistics yet"
        
        success_rate = (self.stats["successful_scans"] / self.stats["total_scans"]) * 100
        
        summary = f"""
┌─ Overall Statistics ──────────────────────────┐
│ Total Scans:    {self.stats['total_scans']:4d}                    │
│ Success Rate:   {success_rate:5.1f}%                  │
├───────────────────────────────────────────────┤
│ Average Time:   {self.stats['avg_total_time']:6.1f}ms              │
│ Fastest:        {self.stats['fastest_scan'] if self.stats['fastest_scan'] != float('inf') else 0:6.1f}ms              │
│ Slowest:        {self.stats['slowest_scan']:6.1f}ms              │
├───────────────────────────────────────────────┤
│ Avg Screenshot: {self.stats['avg_screenshot_time']:6.1f}ms              │
│ Avg QR Detect:  {self.stats['avg_qr_detect_time']:6.1f}ms              │
│ Avg RoleInfos:  {self.stats['avg_api_roleinfo_time']:6.1f}ms              │
│ Avg ScanLogin:  {self.stats['avg_api_scanlogin_time']:6.1f}ms              │
└───────────────────────────────────────────────┘
"""
        return summary.strip()
    
    def get_method_distribution(self) -> str:
        """Get detection method distribution"""
        if not self.method_counts:
            return "No method data"
        
        total = sum(self.method_counts.values())
        lines = ["Detection Method Distribution:"]
        for method, count in sorted(self.method_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total) * 100
            lines.append(f"  {method:<12s}: {count:3d} ({pct:5.1f}%)")
        
        return "\n".join(lines)


# Global singleton
perf_monitor = PerformanceMonitor()

