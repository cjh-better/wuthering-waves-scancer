# -*- coding: utf-8 -*-
"""
多线程池QR码扫描器（参考MHY_Scanner的QThreadPool实现）
"""
from PySide6.QtCore import QThreadPool, QRunnable, Signal, QObject
from typing import Optional, Callable
import threading


class WorkerSignals(QObject):
    """Worker信号（用于线程间通信）"""
    result = Signal(str)  # QR码识别成功
    error = Signal(str)   # 识别错误
    finished = Signal()   # 任务完成


class QRDecodeWorker(QRunnable):
    """QR码识别Worker（在线程池中运行）"""
    
    def __init__(self, img_data, decode_func):
        """
        初始化Worker
        
        Args:
            img_data: 图像数据
            decode_func: 解码函数
        """
        super().__init__()
        self.img_data = img_data
        self.decode_func = decode_func
        self.signals = WorkerSignals()
        self.setAutoDelete(True)  # 自动删除
    
    def run(self):
        """执行QR码识别（在线程池线程中运行）"""
        try:
            result = self.decode_func(self.img_data)
            if result:
                self.signals.result.emit(result)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


class ThreadPoolScanner:
    """
    多线程池扫描器（参考MHY_Scanner）
    
    特点：
    1. 使用QThreadPool并发处理图像增强和识别
    2. thread_local确保每个线程独立的扫描器实例
    3. try_lock机制避免重复提交
    """
    
    # thread_local存储（每个线程独立的扫描器实例）
    _thread_local = threading.local()
    
    def __init__(self, max_workers: int = None):
        """
        初始化线程池扫描器
        
        Args:
            max_workers: 最大线程数（None=自动检测CPU核心数）
        """
        import os
        
        # 🚀 自动检测CPU核心数（与MHY_Scanner相同）
        if max_workers is None:
            max_workers = os.cpu_count() or 4  # 自动检测，失败则默认4
        
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(max_workers)
        
        # 处理锁（类似MHY的mutex.try_lock()）
        self.processing_lock = threading.Lock()
        self.is_processing = False
        
        print(f"[ThreadPool] Initialized with {max_workers} workers (MHY-style)")
    
    def submit_decode_task(self, img_data, decode_func, on_success: Optional[Callable] = None):
        """
        提交QR码识别任务到线程池（类似MHY的threadPool.tryStart）
        
        Args:
            img_data: 图像数据
            decode_func: 解码函数
            on_success: 成功回调
        
        Returns:
            bool: 是否成功提交（如果正在处理则返回False）
        """
        # 🚀 MHY优化：try_lock机制（非阻塞锁）
        if not self.processing_lock.acquire(blocking=False):
            # print("[ThreadPool] Previous task still processing, skipping")
            return False
        
        try:
            # 创建Worker
            worker = QRDecodeWorker(img_data, decode_func)
            
            # 连接信号
            if on_success:
                worker.signals.result.connect(on_success)
            
            worker.signals.finished.connect(lambda: self._on_task_finished())
            
            # 🚀 提交到线程池（类似MHY的threadPool.tryStart）
            success = self.thread_pool.tryStart(worker)
            
            if success:
                self.is_processing = True
                return True
            else:
                # 线程池满了，释放锁
                self.processing_lock.release()
                return False
                
        except Exception as e:
            print(f"[ThreadPool] Failed to submit task: {e}")
            self.processing_lock.release()
            return False
    
    def _on_task_finished(self):
        """任务完成回调"""
        self.is_processing = False
        if self.processing_lock.locked():
            self.processing_lock.release()
    
    def active_thread_count(self) -> int:
        """获取活跃线程数"""
        return self.thread_pool.activeThreadCount()
    
    def max_thread_count(self) -> int:
        """获取最大线程数"""
        return self.thread_pool.maxThreadCount()
    
    def wait_for_done(self, timeout: int = 5000):
        """等待所有任务完成（毫秒）"""
        return self.thread_pool.waitForDone(timeout)


# 全局线程池实例
_global_thread_pool = None

def get_thread_pool_scanner(max_workers: int = None) -> ThreadPoolScanner:
    """获取全局线程池扫描器单例"""
    global _global_thread_pool
    if _global_thread_pool is None:
        _global_thread_pool = ThreadPoolScanner(max_workers)
    return _global_thread_pool

