# -*- coding: utf-8 -*-
"""
GeeTest v4 滑块验证码对话框（搬运自 KuRo_Scanner 的 WindowGeeTest）。

C++ 原版用 WebView2 + 本地 HTTP 服务承载 ``gt4.js``；Python 版用
``QWebEngineView`` + 标准库 ``http.server`` 实现对等能力
（``captchaId`` 与 C++ 原版一致）。

验证结果经 ``window.__geetest_result`` 回传，Python 侧用
``runJavaScript`` 轮询读取（比 QWebChannel 少一个 JS 依赖，更稳）。
WebEngine 不可用时优雅降级：显示明确错误而不是崩溃。

触发逻辑（照搬 C++ WindowLogin）：发送短信验证码前/失败要求验证时
弹出本窗口；``postMessage``（C++）/ ``get_validate_result()``（本实现）
拿到验证 JSON 后，把它作为 ``geeTestData`` 重发短信接口。
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
)

from utils.log import get_logger


logger = get_logger("GeeTest")

#: 与 KuRo_Scanner C++ 原版一致的 GeeTest v4 captchaId
GT4_CAPTCHA_ID = "3f7e2d848ce0cb7e7d019d621e556ce2"

#: 等待用户完成验证的最长时间（秒）
VERIFY_TIMEOUT_SECONDS = 180

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEBENGINE_AVAILABLE = True
except Exception as e:  # 缺系统库 / 未安装 QtWebEngine
    WEBENGINE_AVAILABLE = False
    logger.warning("[GeeTest] QtWebEngine unavailable: %s", e)


_HTML_TEMPLATE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>GeeTest</title>
<style>
  html,body {{ margin:0; padding:0; background:#F5F5F7; }}
  #geetest-div {{ width:340px; margin:30px auto; }}
  .hint {{ text-align:center; color:#8E8E93; font-size:13px; margin-top:12px;
           font-family:"Microsoft YaHei",sans-serif; }}
</style></head>
<body>
<div id="geetest-div"></div>
<div class="hint">请完成滑块验证</div>
<script src="https://static.geetest.com//v4/gt4.js"></script>
<script>
    initGeetest4({{
        captchaId: "{captcha_id}",
        product: "bind"
    }}, function(captchaObj) {{
        captchaObj.onReady(function() {{
            captchaObj.showCaptcha();
        }}).onSuccess(function() {{
            var result = captchaObj.getValidate();
            if (!result) {{ return; }}
            window.__geetest_result = JSON.stringify(result);
        }}).onError(function() {{
            window.__geetest_result = JSON.stringify({{error: "geetest_failed"}});
        }});
    }});
</script>
</body></html>
"""


class _GeeTestHandler(BaseHTTPRequestHandler):
    """只服务验证码页面，其他一律 404。"""

    html = ""

    def do_GET(self):
        if self.path != "/":
            self.send_error(404)
            return
        body = self.html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 压住 http.server 的 stderr 噪音
        pass


class GeeTestDialog(QDialog):
    """GeeTest v4 滑块验证对话框。

    ``exec()`` 返回 ``Accepted`` 且 :meth:`get_validate_result` 非空时，
    表示验证通过；否则为用户取消 / 验证失败 / 组件不可用。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._result: Optional[dict] = None
        self._server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._poll_timer: Optional[QTimer] = None

        self.setWindowTitle("安全验证")
        self.setFixedSize(400, 460)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)

        layout = QVBoxLayout(self)

        if not WEBENGINE_AVAILABLE:
            hint = QLabel(
                "当前环境缺少浏览器组件（QtWebEngine），无法显示验证码。\n"
                "请在能正常显示的 Windows 电脑上完成验证，或稍后重试。"
            )
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignCenter)
            layout.addWidget(hint)
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn)
            return

        try:
            self._view = QWebEngineView(self)
        except Exception as e:
            logger.warning("[GeeTest] QWebEngineView init failed: %s", e)
            hint = QLabel("浏览器组件初始化失败，无法显示验证码。")
            hint.setAlignment(Qt.AlignCenter)
            layout.addWidget(hint)
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(self.reject)
            layout.addWidget(close_btn)
            return

        layout.addWidget(self._view)
        self._start_local_server()
        if self._server is None:
            QMessageBox.warning(self, "验证", "本地验证服务启动失败")
            self.reject()
            return

        port = self._server.server_address[1]
        self._view.load(QUrl("http://127.0.0.1:%d/" % port))

        # 轮询页面里的验证结果（比 QWebChannel 少依赖，更稳）
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(400)
        self._poll_timer.timeout.connect(self._poll_result)
        self._poll_timer.start()

        # 总超时：用户长时间不验证则自动关闭
        QTimer.singleShot(VERIFY_TIMEOUT_SECONDS * 1000, self._on_timeout)

    # ------------------------------------------------------------------
    # 本地 HTTP 服务
    # ------------------------------------------------------------------

    def _start_local_server(self):
        try:
            _GeeTestHandler.html = _HTML_TEMPLATE.format(
                captcha_id=GT4_CAPTCHA_ID
            )
            self._server = HTTPServer(("127.0.0.1", 0), _GeeTestHandler)
            self._server_thread = threading.Thread(
                target=self._server.serve_forever,
                name="GeeTestHTTP",
                daemon=True,
            )
            self._server_thread.start()
        except Exception as e:
            logger.warning("[GeeTest] local server start failed: %s", e)
            self._server = None

    def _stop_local_server(self):
        if self._poll_timer is not None:
            self._poll_timer.stop()
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
            self._server = None

    # ------------------------------------------------------------------
    # 结果轮询
    # ------------------------------------------------------------------

    def _poll_result(self):
        try:
            self._view.page().runJavaScript(
                "window.__geetest_result || ''", self._on_js_result
            )
        except Exception:
            pass

    def _on_js_result(self, value):
        if not value:
            return
        try:
            data = json.loads(value) if isinstance(value, str) else value
        except Exception:
            return
        if not isinstance(data, dict):
            return
        if data.get("error"):
            logger.warning("[GeeTest] verification failed on page")
            self.reject()
            return
        self._result = data
        self.accept()

    def _on_timeout(self):
        if self._result is None and self.isVisible():
            logger.warning("[GeeTest] verification timed out")
            self.reject()

    # ------------------------------------------------------------------
    # Qt 生命周期
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        self._stop_local_server()
        super().closeEvent(event)

    def done(self, result):
        self._stop_local_server()
        super().done(result)

    # ------------------------------------------------------------------
    # 结果
    # ------------------------------------------------------------------

    def get_validate_result(self) -> Optional[dict]:
        """返回 GeeTest 验证结果 dict（`captchaObj.getValidate()`），
        未通过时返回 None。调用方应将其 JSON 序列化后作为
        ``geeTestData`` 传给短信接口（照搬 C++ 逻辑）。"""
        return self._result
