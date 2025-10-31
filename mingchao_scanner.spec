# -*- coding: utf-8 -*-
import os

# pyzbar DLL 文件路径
pyzbar_path = r'C:\Users\junhao\AppData\Local\Programs\Python\Python311\Lib\site-packages\pyzbar'
# 程序图标路径（ICO格式）
icon_path = 'icon.ico'
png_path = '11409B.png'

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[
        # 添加 pyzbar 的 DLL 文件
        (os.path.join(pyzbar_path, 'libiconv.dll'), 'pyzbar'),
        (os.path.join(pyzbar_path, 'libzbar-64.dll'), 'pyzbar'),
    ],
    datas=[
        # 添加程序图标（PNG格式用于窗口显示）
        (png_path, '.'),
        # 添加AI模型文件
        ('ScanModel', 'ScanModel'),
    ],
    hiddenimports=[
        'ui',
        'ui.main_window',
        'ui.login_dialog',
        'ui.scan_window',
        'utils',
        'utils.config_manager',
        'utils.kuro_api',
        'utils.qr_scanner',
        'utils.ai_qr_scanner',  # AI扫描器
        'utils.fast_screenshot',  # BitBlt截图
        'utils.dxgi_screenshot',  # DXGI截图
        'utils.thread_pool_scanner',  # 线程池
        'utils.live_stream_scanner',  # 直播流扫描
        'utils.performance_monitor',  # 🚀 性能监控
        'utils.image_buffer_pool',  # 🚀 内存池
        'utils.smart_roi_detector',  # 🚀 ROI预测
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='鸣潮抢码器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)



