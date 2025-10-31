# 鸣潮抢码器

一款专为《鸣潮》游戏设计的高性能二维码扫描登录工具，支持屏幕扫描和直播流扫描。

![Version](https://img.shields.io/badge/version-1.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-green.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

---

## ✨ 功能特点

- **📸 屏幕扫描** - 半透明可拖动扫描框，实时识别屏幕二维码
- **🎥 直播流扫描** - 支持抖音直播间实时流扫描（专为直播抢码设计）
- **🚀 自动登录** - 检测到二维码自动提交，响应速度快
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
├── main.py                  # 程序入口
├── config.json              # 配置文件
├── requirements.txt         # Python依赖
├── mingchao_scanner.spec    # PyInstaller打包配置
├── ui/                      # UI界面模块
│   ├── main_window.py       # 主窗口
│   ├── login_dialog.py      # 登录对话框
│   └── scan_window.py       # 扫描窗口
├── utils/                   # 工具模块
│   ├── kuro_api.py          # 库街区API
│   ├── ai_qr_scanner.py     # AI扫描器
│   ├── dxgi_screenshot.py   # GPU加速截图
│   ├── live_stream_scanner.py  # 直播流扫描
│   └── ...                  # 其他工具
└── ScanModel/               # AI模型文件
    ├── detect.caffemodel    # QR检测模型
    └── sr.caffemodel        # 超分辨率模型
```

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
