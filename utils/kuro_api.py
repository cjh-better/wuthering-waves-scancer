# -*- coding: utf-8 -*-
"""库街区 API 封装 - 终极网络优化版"""
import requests
import socket
from typing import Dict, Optional, Any
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from utils.log import get_logger


logger = get_logger("Network")

# 尝试导入 HTTP/2 支持
try:
    from requests_http2 import HTTP2Adapter
    HTTP2_AVAILABLE = True
except ImportError:
    HTTP2_AVAILABLE = False
    logger.info("[Network] HTTP/2 not available (pip install requests-http2 for better performance)")


class KuroAPI:
    """库街区 API 接口封装 - 极速优化版（多人抢码专用）"""
    
    BASE_URL = "https://api.kurobbs.com"
    
    def __init__(self):
        # 创建终极优化的 Session
        self.session = requests.Session()
        # 优化49：慢请求告警——包装 session.request，>3s 打 warning
        _orig_request = self.session.request
        def _timed_request(method, url, **kwargs):
            import time as _t
            start = _t.time()
            try:
                return _orig_request(method, url, **kwargs)
            finally:
                elapsed = _t.time() - start
                if elapsed > 3.0:
                    # 脱敏 URL 中的 token（优化48）
                    safe_url = url
                    try:
                        import re as _re
                        safe_url = _re.sub(r"(token|ticket|qrCode)=[^&]*", r"\1=***", url)
                    except Exception:
                        pass
                    logger.warning("[HTTP] 慢请求 %.1fs %s %s", elapsed, method, safe_url)
        self.session.request = _timed_request
        
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
                logger.info("[Network] ✓ HTTP/2 enabled (faster multiplexing)")
            except Exception as e:
                logger.warning(f"[Network] HTTP/2 init failed, fallback to HTTP/1.1: {e}")
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
        覆盖游戏 API + 抖音/哔哩哔哩直播域名（抢码链路全覆盖）。
        """
        try:
            import threading
            def resolve():
                hosts = []
                try:
                    hosts.append(self.BASE_URL.replace("https://", "").replace("http://", "").split("/")[0])
                except Exception:
                    pass
                # 直播域名（抖音/B站拉流、API）
                hosts.extend([
                    "live.douyin.com",
                    "webcast.amemv.com",
                    "pull-hs-f11.douyincdn.com",
                    "pull-flv-f11.douyincdn.com",
                    "api.live.bilibili.com",
                    "live.bilibili.com",
                    "cn-hbxy-ct-01-08.bilivideo.com",
                ])
                for host in hosts:
                    try:
                        socket.gethostbyname(host)
                    except Exception:
                        pass
            # 异步解析，不阻塞启动
            threading.Thread(target=resolve, daemon=True).start()
        except Exception:
            pass
    
    @staticmethod
    def _load_timeout_ladder(key: str, default: list) -> list:
        """从配置加载超时阶梯，校验为正数列表（防配错导致无限等待）。"""
        try:
            from utils.config_manager import config_manager
            raw = config_manager.get(key, default)
            ladder = [float(x) for x in raw]
            ladder = [x for x in ladder if x > 0]
            if ladder:
                return ladder[:5]  # 上限 5 阶，防误配超长
        except Exception:
            pass
        return list(default)

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
    
    def set_token(self, token: str) -> None:
        """设置认证 token"""
        self.token = token
        self.headers["token"] = token
        # 设置token后立即预热连接
        if not self._connection_warmed:
            self.warm_up_connection()
    
    def warm_up_connection(self) -> None:
        """
        🚀 预热网络连接（在扫码前调用，提前建立TCP+TLS连接，节省100-300ms）
        """
        try:
            # 发送一个轻量级的HEAD请求来建立连接
            url = f"{self.BASE_URL}/user/role/roleInfos"
            self.session.head(url, timeout=0.3, headers=self.headers)
            self._connection_warmed = True
            import time as _t
            self._last_warmup_ts = _t.time()
        except Exception:
            pass  # 预热失败不影响正常功能

    def speculative_warmup(self, cooldown_s: float = 30.0) -> None:
        """投机预热：帧差分变热时调用，提前建连。

        有冷却（默认30s），避免每帧都打。后台线程执行，不阻塞解码。
        """
        import time as _t
        import threading as _th
        now = _t.time()
        last = getattr(self, "_last_warmup_ts", 0.0)
        if now - last < cooldown_s:
            return
        # L3修复：成功后才更新时间戳；失败时允许下次重试（而非冷却30s）
        # 仍需防并发重复：用独立的 _warming 标记
        if getattr(self, "_warming", False):
            return
        self._warming = True
        def _do():
            try:
                url = f"{self.BASE_URL}/user/role/roleInfos"
                self.session.head(url, timeout=0.5, headers=self.headers)
                # 成功才更新冷却时间戳
                self._last_warmup_ts = _t.time()
            except Exception:
                pass
            finally:
                self._warming = False
        _th.Thread(target=_do, daemon=True).start()
    
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
    
    def get_role_infos(
        self, qr_code: str, smart_retry: bool = True,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
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
        
        # 阶梯式重试（超时才进下一阶）：默认值 0.6s -> 1.2s -> 2.0s，
        # 可通过配置 roleinfo_retry_timeouts 调整
        timeouts = self._load_timeout_ladder(
            "roleinfo_retry_timeouts", [0.6, 1.2, 2.0]
        ) if smart_retry else [1.0]
        hdrs = headers if headers is not None else self.headers

        last_error = None
        for attempt, timeout in enumerate(timeouts, 1):
            try:
                response = self.session.post(url, data=data, headers=hdrs, timeout=timeout)
                return response.json()
            # M3修复：ConnectionError（DNS失败/连接被拒/重置）与 Timeout
            # 同属瞬时网络故障，同等进阶梯重试；抢码窗口内一次瞬断不应直接失败
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = f"请求超时(>{timeout}s)" if isinstance(e, requests.exceptions.Timeout) else f"连接失败: {e}"
                if attempt < len(timeouts):
                    continue
                return {"code": -1, "msg": last_error}
            except Exception as e:
                return {"code": -1, "msg": f"请求异常: {e}"}
        return {"code": -1, "msg": last_error or "未知错误"}
    
    def scan_login(
        self, qr_code: str, verify_code: str = "", auto_login: bool = False,
        smart_retry: bool = True, headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
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
        # 优化40：幂等 key——同一 qrCode 的重复提交用同一 key，
        # 服务端可去重，避免网络重试导致重复登录。
        # H1修复：verify_code 纳入 key——短信验证重试时验证码变化，
        # 若 key 不变且服务端处理该头，会返回缓存的"需要验证码"
        # 响应导致死循环；服务端忽略该头时行为零变化。
        import uuid as _uuid
        idem_key = str(_uuid.uuid5(
            _uuid.NAMESPACE_URL, f"{qr_code}|{verify_code}"))
        data = {
            "autoLogin": "true" if auto_login else "false",
            "qrCode": qr_code,
            "id": "",
            "verifyCode": verify_code
        }
        req_headers = dict(headers or {})
        req_headers["X-Idempotency-Key"] = idem_key
        
        # 阶梯式重试（超时才进下一阶）：默认值 0.8s -> 1.5s -> 2.5s，
        # 可通过配置 login_retry_timeouts 调整（抢码场景可压首阶）
        timeouts = self._load_timeout_ladder(
            "login_retry_timeouts", [0.8, 1.5, 2.5]
        ) if smart_retry else [1.5]
        hdrs = req_headers  # 带幂等 key 的头（优化40）

        last_error = None
        for attempt, timeout in enumerate(timeouts, 1):
            try:
                response = self.session.post(url, data=data, headers=hdrs, timeout=timeout)
                return response.json()
            # M3修复：ConnectionError 同等进阶梯重试（见上）
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                last_error = f"请求超时(>{timeout}s)" if isinstance(e, requests.exceptions.Timeout) else f"连接失败: {e}"
                if attempt < len(timeouts):
                    continue  # Try next timeout
            except Exception as e:
                last_error = f"请求失败: {str(e)}"
                break  # Don't retry on non-timeout errors
        
        return {"code": -1, "msg": last_error or "请求失败"}
    
    def send_sms(self, gee_test_data: str = "") -> Dict[str, Any]:
        """
        发送短信验证码

        Args:
            gee_test_data: GeeTest 验证结果 JSON（服务端要求验证时传入，
                照搬 KuRo_Scanner C++ 逻辑：验证通过后把
                ``captchaObj.getValidate()`` 的 JSON 作为 geeTestData 重发）

        Returns:
            发送结果字典
        """
        url = f"{self.BASE_URL}/user/sms/scanSms"
        data = {"geeTestData": gee_test_data}

        try:
            response = self.session.post(url, data=data, headers=self.headers, timeout=5)
            result = response.json()
            return result
        except Exception as e:
            return {"code": -1, "msg": f"请求失败: {str(e)}"}

    # 服务端要求 GeeTest 验证时的典型文案（启发式；命中新的 code/msg
    # 时可随时扩充——见 is_captcha_required）。
    _CAPTCHA_KEYWORDS = ("geetest", "极验", "滑块", "captcha")

    @classmethod
    def is_captcha_required(cls, result: Any) -> bool:
        """启发式判断短信接口是否要求 GeeTest 验证。

        保守策略：只有明确命中验证码相关文案才返回 True，避免误伤
        正常失败（如"发送频繁"），那样会无故弹验证窗口。
        """
        if not isinstance(result, dict):
            return False
        if result.get("code") == 200:
            return False
        msg = str(result.get("msg", "")).lower()
        return any(k in msg for k in cls._CAPTCHA_KEYWORDS)


# 全局 API 实例
kuro_api = KuroAPI()

