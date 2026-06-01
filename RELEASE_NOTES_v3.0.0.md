# 鸣潮抢码器 v3.0.0

## 主要更新

- 升级为 Release 3.0，主窗口、配置版本和发布产物统一到 `3.0.0`。
- 账号 token 改为安全存储：Windows 下使用 DPAPI 加密，只有当前 Windows 用户能解密。
- 旧版明文 token 会在账号数据加载时自动迁移为受保护 token。
- 保留账号状态列、手动刷新状态、登录并发保护和自适应扫描频率。
- 去除 `kuro_api.py` 导入时全局替换 urllib3 连接函数的副作用，降低对其他网络请求的影响。
- 增加 `release.ps1`，支持测试、构建、打包、SHA256 生成，并在配置 GitHub CLI/Token 后发布 Release。

## 构建信息

- 版本标签：`v3.0.0`
- 构建方式：PyInstaller `mingchao_scanner.spec`
- 构建环境：Windows 10，Python 3.14.4
- 验证：`pytest -q`

## 文件

- `鸣潮抢码器-v3.0.0.exe`：Windows 单文件可执行程序
- `README.md`：项目说明
- `LICENSE`：MIT 许可证
- `RELEASE_NOTES_v3.0.0.md`：发布说明
- `SHA256SUMS.txt`：文件校验值

## 注意

本工具仅供学习交流使用。使用前请确认符合游戏服务条款和库街区用户协议。
