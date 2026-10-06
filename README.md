# 鸣潮抢码器

一款专为《鸣潮》游戏设计的高性能二维码扫描登录工具，支持屏幕扫描和直播流扫描。

![Version](https://img.shields.io/badge/version-3.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

---

## ✨ 功能特点

- **📸 屏幕扫描** - 半透明可拖动扫描框，实时识别屏幕二维码
- **🎥 直播流扫描** - 支持抖音直播间实时流扫描（专为直播抢码设计）
- **🚀 自动登录** - 检测到二维码自动提交，响应速度快
- **🔐 Token 加密存储** - Windows 下使用 DPAPI 保护账号 token，仅当前系统用户可解密
- **🤖 AI增强** - Caffe深度学习模型，提升模糊二维码识别率
- **⚡ GPU加速** - DXGI截图技术，识别速度提升5-10倍
- **🎨 现代UI** - iOS风格界面，简洁美观

---

## 🚀 快速开始

### 方法一：直接运行（推荐）

1. 下载 `dist/鸣潮抢码器.exe`
2. 双击运行
3. 登录库街区账号即可使用

### 方法二：从源码运行

```bash
# 1. 克隆仓库
git clone https://github.com/your-username/wuthering-waves-scanner.git

# 2. 安装依赖
pip install -r requirements.txt

# 3. 运行程序
python main.py
```

---

## 📖 使用说明

### 1. 登录账号

首次使用需要登录库街区账号：
- 点击【登录账号】→ 输入手机号 → 获取验证码 → 登录
- 登录信息会自动保存，下次无需重新登录

### 2. 屏幕扫描模式

适合扫描电脑屏幕上的二维码：
1. 点击【开始扫码】
2. 拖动红色扫描框对准二维码
3. 程序自动识别并登录

### 3. 直播流扫描模式（推荐）

适合从抖音直播间抢码：
1. 输入抖音直播间ID或粘贴分享链接
2. 点击【扫描抖音直播】
3. 程序自动从直播流识别二维码并登录

**提示**：直播流模式比屏幕扫描更快更稳定，推荐使用。

---

## 🏗️ 项目结构

```
wuthering-waves-scanner/
├── main.py                  # 程序入口（崩溃诊断 + 资源自检 + QApplication）
├── mypy.ini                 # 类型检查配置（utils.abogus 为 vendored 第三方，排除）
├── mingchao_scanner.spec    # PyInstaller 打包配置
├── ui/                      # 界面层（只做展示与交互，不含业务逻辑）
│   ├── main_window.py       # 主窗口：账号管理 / 扫描控制 / 日志面板
│   ├── login_dialog.py      # 库街区登录
│   ├── sms_dialog.py        # 短信验证码（服务端要求时弹 GeeTest）
│   ├── geetest_dialog.py    # GeeTest v4 滑块验证（QWebEngine + 本地 HTTP 服务）
│   └── scan_window.py       # 屏幕扫描框（可拖动半透明窗口）
├── utils/                   # 业务逻辑层
│   ├── platforms/           # ★ 直播平台适配器（取流地址，与抓帧解码解耦）
│   │   ├── base.py          #   LiveStreamStatus / StreamError / 适配器基类
│   │   ├── bilibili.py      #   B站：room_init → getRoomPlayInfo
│   │   └── douyin.py        #   抖音：房间页(含ttwid)→HTML提取→签名API
│   ├── live_stream_scanner.py  # ★ 抓帧→有界队列→解码工作线程（QThread）
│   ├── ai_qr_scanner.py     # ★ WeChatQR/Caffe 解码（模型懒加载，线程安全）
│   ├── qr_scanner.py        # pyzbar 降级解码；与 ai_qr_scanner 共享
│   │                        #   ImageDecoder 契约：decode(image) -> str | None
│   ├── screenshot.py        # ★ 截图后端抽象（DXGI → BitBlt → PIL 链）
│   ├── kuro_api.py          # 库街区 API（登录/扫码/短信，含连接预热）
│   ├── abogus.py            # ★ 抖音 a_bogus 签名（vendored，MIT）
│   ├── http.py              # 共享 HTTP 工具（Session 工厂/JSON/诊断日志）
│   ├── resources.py         # ★ 打包资源完整性自检（ScanModel 缺失告警）
│   ├── config_manager.py    # 配置（schema 化：类型+默认值+说明）
│   ├── account_manager.py   # 多账号管理
│   ├── secure_token_store.py# Token 加密存储（Windows DPAPI）
│   ├── thread_pool_scanner.py# 通用线程池
│   ├── smart_roi_detector.py# 屏幕扫描 ROI 预测（仅屏幕路径使用）
│   ├── performance_monitor.py# 性能统计
│   └── log.py               # ★ 统一日志出口（get_logger）
└── ScanModel/               # AI 模型文件（detect/sr prototxt + caffemodel）
```

### 数据流（5 分钟看懂）

```
直播流模式                          屏幕扫描模式
─────────                          ──────────
抖音/B站房间号                       拖动扫描框
    │                                   │
    ▼                                   ▼
platforms 适配器取流地址            screenshot 后端链截图
 (HTML提取→签名API双通道)             (DXGI→BitBlt→PIL)
    │                                   │
    ▼                                   ▼
VideoCapture 抓帧 ──有界队列──▶ 解码工作线程 ──▶ ImageDecoder.decode()
    (丢旧帧保实时)      (EWMA自适应步长)      (WeChatQR→pyzbar降级)
    │                                               │
    └────────────▶ 扫到二维码 ──▶ kuro_api 扫码登录 ──┘
```

关键设计取舍（为什么这样写）：
- **抓帧与解码分离**：解码（WeChatQR 在高清帧上可达数百毫秒）一旦和抓帧串行，
  TCP 缓冲区就会积压，延迟越积越高。分离 + 队列满丢旧帧 = 永远解最新的帧。
- **EWMA 自适应步长**：解码耗时是动态的（画面复杂度/机器性能），固定步长要么
  浪费 CPU 要么积压。用指数滑动平均跟踪耗时，超预算才降频，抖动小。
- **抖音双通道**：`web/enter` JSON 接口会被风控掐成空 body，但房间 HTML 页
  照常返回且内嵌同样的数据。HTML 提取在前（快、无签名开销），签名 API
  在后（权威），两个都挂才报细分错误。
- **a_bogus 签名**：抖音要求请求带签名才给数据。签名算法是公开实现
  （vendored），签的是 urlencode 后的 query + 同一份 UA；ttwid 必须来自
  服务器 Set-Cookie，自己编的会被拒绝——所以先 GET 房间页。
- **解码锁**：WeChatQR/Caffe dnn 内部有状态、非线程安全，并发调即 native
  segfault（issue #8 的根因）。所有原生解码调用经同一把锁串行。
- **模型懒加载**：Caffe 模型加载阻塞启动数秒，移到首次解码/后台预热线程，
  import 只做轻量初始化。

---

## 🔧 技术栈

### 核心技术
- **PySide6** - Qt6图形界面
- **OpenCV** - 图像处理和AI模型
- **pyzbar** - 二维码识别
- **requests** - HTTP网络请求

### 性能优化
- **DXGI截图** - GPU加速，比PIL快5-10倍
- **WeChat QR识别器** - 比pyzbar更强大
- **智能ROI预测** - 卡尔曼滤波预测二维码位置
- **多线程池** - 并行处理图像增强
- **内存池复用** - 减少内存分配开销
- **智能重试** - 网络请求阶梯式重试（0.6s→1.2s→2.0s）
- **Ticket去重** - 防止重复提交

### 库街区API
- `POST /user/sdkLogin` - 手机验证码登录
- `POST /user/auth/roleInfos` - 验证二维码
- `POST /user/auth/scanLogin` - 扫码登录
- `POST /user/sms/scanSms` - 发送验证码

**API Base**: `https://api.kurobbs.com`

---

## ⚙️ 配置说明

配置文件 `config.json`：

```json
{
    "uid": "",                      // 用户ID
    "token": "",                    // 认证令牌
    "scan_interval": 0.1,           // 扫描间隔（秒）
    "auto_login": false,            // 自动登录（检测到QR立即登录）
    "auto_retry": true,             // 自动重试（QR过期后继续扫描）
    "thread_pool_enabled": false,   // 多线程池（复杂场景使用）
    "theme": "dark"                 // 主题（dark/light）
}
```

---

## 🛠 常见问题排查

### 抖音提示"接口返回空响应(疑似被风控)"

抖音的 `web/enter` 接口有时会返回 HTTP 200 但 body 为空（疑似风控），程序会自动改用**HTML 备用通道**（抓取房间页面内嵌的流地址）继续尝试。如果备用通道也失败，日志会给出具体原因（如"页面未包含直播流地址"），可据此判断是房间未开播还是页面结构变化。

### 点击"开始扫码"闪退

程序启动时会自动记录崩溃日志，请按以下步骤提供信息：

1. 打开文件：`%TEMP%\wuthering-waves-scancer\crash.log`
   （在文件资源管理器地址栏粘贴上面的路径回车即可）
2. 把日志内容完整贴到 issue 里

常见原因自查：
- **AI 模型缺失**：启动日志若提示"AI 模型未加载"，请确认 `ScanModel` 目录下 4 个模型文件都在（打包版若缺失请重新下载完整 release 包）
- **截图权限/多显示器**：尝试把扫描框拖到主显示器再试

---

## 📦 打包发布

```bash
# 安装PyInstaller
pip install pyinstaller

# 打包为exe
pyinstaller mingchao_scanner.spec

# 输出位置：dist/鸣潮抢码器.exe
```

---

## ⚠️ 注意事项

- **首次登录**：需要短信验证码，之后不再需要
- **Token过期**：定期需要重新登录
- **网络要求**：建议使用稳定网络，避免高峰期
- **识别精度**：二维码建议不小于200x200像素
- **高DPI屏幕**：可能需要手动调整扫描框位置

---

## 🐛 常见问题

**Q: 识别不出二维码？**  
A: 确保扫描框完全覆盖二维码，二维码清晰且不小于100px

**Q: 提示需要验证码？**  
A: 首次扫码登录需要验证，输入验证码后以后不再需要

**Q: 直播扫描失败？**  
A: 检查直播间是否正在直播，网络连接是否正常

**Q: Token已过期？**  
A: 点击【登录账号】重新登录即可

---

## 📄 开源协议

本项目采用 [MIT License](LICENSE) 开源。

---

## ⚖️ 免责声明

**本项目仅供学习交流使用，请勿用于商业用途。**

- 本工具不修改游戏客户端，仅通过公开API进行正常的扫码登录
- 使用本程序产生的任何后果由使用者自行承担
- 请遵守《鸣潮》游戏服务条款和库街区用户协议
- 如官方明确禁止使用此类工具，请立即停止使用

---

## 🙏 致谢

本项目参考了以下开源项目的技术实现：
- MHY_Scanner - 米哈游抢码器
- BBH3ScanLaunch - 崩坏三扫码工具
- Kuro_login - 库街区登录实现

感谢所有提供技术支持的开发者！

---

<div align="center">

**如果这个项目对你有帮助，请给个 ⭐ Star！**

Made with ❤️ for Wuthering Waves Players

</div>
