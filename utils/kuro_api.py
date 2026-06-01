# -*- coding: utf-8 -*-
"""库街区 API 封装 - 终极网络优化版"""
import requests
import socket
from typing import Dict, Optional, Any
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 尝试导入 HTTP/2 支持
try:
    from requests_http2 import HTTP2Adapter
    HTTP2_AVAILABLE = True
except ImportError:
    HTTP2_AVAILABLE = False
    print("[Network] HTTP/2 not available (pip install requests-http2 for better performance)")

# 全局DNS缓存 - 避免重复DNS解析
_DNS_CACHE = {}

# 🚀 使用更快的公共DNS服务器（阿里云/腾讯云/Google）
_FAST_DNS_SERVERS = [
    "223.5.5.5",      # 阿里云DNS（中国大陆最快）
    "119.29.29.29",   # 腾讯DNSPod（中国大陆）
    "8.8.8.8",        # Google DNS（海外）
]


def patched_create_connection(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, socket_options=None):
    """
    🚀 终极优化的连接创建函数：
    1. 智能DNS缓存（使用快速DNS服务器）
    2. TCP_NODELAY（禁用Nagle算法，减少40ms延迟）
    3. TCP_QUICKACK（快速确认，减少延迟）
    4. SO_KEEPALIVE（保持连接活跃）
    5. 优化的 Socket 缓冲区
    """
    host, port = address
    
    # 🚀 智能DNS缓存（使用快速DNS服务器）
    if host in _DNS_CACHE:
        ip = _DNS_CACHE[host]
    else:
        # 尝试使用快速DNS服务器解析
        try:
            # 优先使用系统DNS
            ip = socket.gethostbyname(host)
        except socket.gaierror:
            # 如果失败，尝试使用快速公共DNS
            import dns.resolver
            resolver = dns.resolver.Resolver()
            resolver.nameservers = _FAST_DNS_SERVERS
            resolver.timeout = 0.5
            resolver.lifetime = 1.0
            try:
                answers = resolver.resolve(host, 'A')
                ip = str(answers[0])
            except Exception:
                # 最后回退到系统DNS
                ip = socket.gethostbyname(host)
        
        _DNS_CACHE[host] = ip
    
    # 创建socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    # 🚀 TCP优化参数（降低延迟）
    # 1. TCP_NODELAY - 禁用Nagle算法（减少20-40ms延迟）
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    
    # 2. SO_KEEPALIVE - 保持连接活跃
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    
    # 3. 优化接收/发送缓冲区（提升吞吐量）
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 262144)  # 256KB
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 262144)  # 256KB
    except (OSError, AttributeError):
        pass  # 某些系统可能不支持
    
    # 4. TCP_QUICKACK - 快速确认（Linux特有，减少延迟）
    try:
        if hasattr(socket, 'TCP_QUICKACK'):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_QUICKACK, 1)
    except (OSError, AttributeError):
        pass
    
    # 设置超时
    if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
        sock.settimeout(timeout)
    
    # 连接
    sock.connect((ip, port))
    
    return sock


class KuroAPI:
    """库街区 API 接口封装 - 极速优化版（多人抢码专用）"""
    
    BASE_URL = "https://api.kurobbs.com"
    
    def __init__(self):
        # 创建终极优化的 Session
        self.session = requests.Session()
        
        # 🚀 尝试使用 HTTP/2 适配器（连接复用，头部压缩，多路复用）
        if HTTP2_AVAILABLE:
            try:
                adapter = HTTP2Adapter(
                    pool_connections=50,
                    pool_maxsize=200,
                    max_retries=0,
                    pool_block=False
                )
                self.session.mount('https://', adapter)
                print("[Network] ✓ HTTP/2 enabled (faster multiplexing)")
            except Exception as e:
                print(f"[Network] HTTP/2 init failed, fallback to HTTP/1.1: {e}")
                # Fallback to HTTP/1.1
                adapter = HTTPAdapter(
                    pool_connections=30,
                    pool_maxsize=100,
                    max_retries=Retry(total=0, backoff_factor=0, status_forcelist=[]),
                    pool_block=False
                )
                self.session.mount('https://', adapter)
        else:
            # 🚀 HTTP/1.1 极速连接池配置
            adapter = HTTPAdapter(
                pool_connections=30,
                pool_maxsize=100,
                max_retries=Retry(total=0, backoff_factor=0, status_forcelist=[]),
                pool_block=False
            )
            self.session.mount('https://', adapter)
        
        # HTTP 也使用相同配置
        http_adapter = HTTPAdapter(
            pool_connections=30,
            pool_maxsize=100,
            max_retries=Retry(total=0, backoff_factor=0, status_forcelist=[]),
            pool_block=False
        )
        self.session.mount('http://', http_adapter)
        
        # 🚀 终极优化的 headers（减少传输大小，启用压缩）
        self.headers = {
            "devCode": "",
            "source": "android",
            "version": "2.5.0",
            "versionCode": "2500",
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "Connection": "keep-alive",           # 保持连接
            "Accept-Encoding": "gzip, deflate, br",  # 支持多种压缩（Brotli最快）
            "Accept": "application/json",         # 明确返回格式
            "Accept-Language": "zh-CN,zh;q=0.9",  # 减少协商
            "Cache-Control": "no-cache",          # 避免缓存问题
            "User-Agent": "okhttp/4.9.0",         # 精简UA（减少头部大小）
        }
        self.token = ""
        self._connection_warmed = False  # 连接预热标志
        
        # 🚀 预解析DNS（启动时立即解析，避免首次请求延迟）
        self._pre_resolve_dns()
    
    def _pre_resolve_dns(self):
        """
        🚀 预解析DNS（启动时立即解析，避免首次请求延迟）
        """
        try:
            import threading
            def resolve():
                try:
                    host = self.BASE_URL.replace("https://", "").replace("http://", "")
                    socket.gethostbyname(host)
                except Exception:
                    pass
            # 异步解析，不阻塞启动
            threading.Thread(target=resolve, daemon=True).start()
        except Exception:
            pass
    
    def measure_network_latency(self) -> float:
        """
        🚀 测量到API服务器的网络延迟（RTT）
        
        Returns:
            延迟时间（毫秒），失败返回 -1
        """
        try:
            import time
            start = time.perf_counter()
            # 使用 HEAD 请求测量延迟（最小开销）
            response = self.session.head(self.BASE_URL, timeout=2)
            latency = (time.perf_counter() - start) * 1000
            return latency
        except Exception:
            return -1
    
    def set_token(self, token: str):
        """设置认证 token"""
        self.token = token
        self.headers["token"] = token
        # 设置token后立即预热连接
        if not self._connection_warmed:
            self.warm_up_connection()
    
    def warm_up_connection(self):
        """
        🚀 预热网络连接（在扫码前调用，提前建立TCP+TLS连接，节省100-300ms）
        """
        try:
            # 发送一个轻量级的HEAD请求来建立连接
            url = f"{self.BASE_URL}/user/role/roleInfos"
            self.session.head(url, timeout=0.3, headers=self.headers)
            self._connection_warmed = True
        except Exception:
            pass  # 预热失败不影响正常功能
    
    def login(self, mobile: str, code: str) -> Dict[str, Any]:
        """
        使用手机号和验证码登录
        
        Args:
            mobile: 手机号
            code: 验证码
            
        Returns:
            登录结果字典
        """
        url = f"{self.BASE_URL}/user/sdkLogin"
        data = {
            "mobile": mobile,
            "code": code
        }
        
        try:
            response = self.session.post(url, data=data, headers=self.headers, timeout=5)
            result = response.json()
            
            if result.get("code") == 200:
                data = result.get("data", {})
                self.set_token(data.get("token", ""))
                
            return result
        except Exception as e:
            return {"code": -1, "msg": f"请求失败: {str(e)}"}
    
    def get_role_infos(self, qr_code: str, smart_retry: bool = True) -> Dict[str, Any]:
        """
        ⚡ 获取角色信息（验证二维码）- 智能重试版
        
        Args:
            qr_code: 二维码内容
            smart_retry: 是否启用智能阶梯式重试
            
        Returns:
            角色信息字典
        """
        url = f"{self.BASE_URL}/user/auth/roleInfos"
        data = {"qrCode": qr_code}
        
        # 🚀 平衡的阶梯式重试：0.6s -> 1.2s -> 2.0s（稳定性优先）
        timeouts = [0.6, 1.2, 2.0] if smart_retry else [1.0]
        
        last_error = None
        for attempt, timeout in enumerate(timeouts, 1):
            try:
                response = self.session.post(url, data=data, headers=self.headers, timeout=timeout)
                return response.json()
            except requests.exceptions.Timeout:
                last_error = f"请求超时(>{timeout}s)"
                if attempt < len(timeouts):
                    continue  # Try next timeout
            except Exception as e:
                last_error = f"请求失败: {str(e)}"
                break  # Don't retry on non-timeout errors
        
        return {"code": -1, "msg": last_error or "请求失败"}
    
    def scan_login(self, qr_code: str, verify_code: str = "", auto_login: bool = False, smart_retry: bool = True) -> Dict[str, Any]:
        """
        ⚡ 扫码登录 - 智能重试版
        
        Args:
            qr_code: 二维码内容
            verify_code: 短信验证码（首次登录需要）
            auto_login: 是否记住设备（False=单次登录，首次后不需要验证码）
            smart_retry: 是否启用智能阶梯式重试
            
        Returns:
            登录结果字典
        """
        url = f"{self.BASE_URL}/user/auth/scanLogin"
        data = {
            "autoLogin": "true" if auto_login else "false",
            "qrCode": qr_code,
            "id": "",
            "verifyCode": verify_code
        }
        
        # 🚀 平衡的阶梯式重试：0.8s -> 1.5s -> 2.5s（稳定性优先）
        timeouts = [0.8, 1.5, 2.5] if smart_retry else [1.5]
        
        last_error = None
        for attempt, timeout in enumerate(timeouts, 1):
            try:
                response = self.session.post(url, data=data, headers=self.headers, timeout=timeout)
                return response.json()
            except requests.exceptions.Timeout:
                last_error = f"请求超时(>{timeout}s)"
                if attempt < len(timeouts):
                    continue  # Try next timeout
            except Exception as e:
                last_error = f"请求失败: {str(e)}"
                break  # Don't retry on non-timeout errors
        
        return {"code": -1, "msg": last_error or "请求失败"}
    
    def send_sms(self) -> Dict[str, Any]:
        """
        发送短信验证码
        
        Returns:
            发送结果字典
        """
        url = f"{self.BASE_URL}/user/sms/scanSms"
        data = "geeTestData="
        
        try:
            response = self.session.post(url, data=data, headers=self.headers, timeout=5)
            result = response.json()
            return result
        except Exception as e:
            return {"code": -1, "msg": f"请求失败: {str(e)}"}


# 全局 API 实例
kuro_api = KuroAPI()

