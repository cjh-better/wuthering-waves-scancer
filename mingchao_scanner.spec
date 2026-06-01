# -*- mode: python ; coding: utf-8 -*-
import os

import pyzbar


pyzbar_path = os.path.dirname(pyzbar.__file__)
icon_path = "icon.ico"
png_path = "11409B.png"
block_cipher = None

release_excludes = [
    "pytest",
    "unittest",
    "pydoc",
    "doctest",
    "tkinter",
    "matplotlib",
    "IPython",
    "jupyter",
    "notebook",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtPdf",
    "PySide6.QtVirtualKeyboard",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[
        (os.path.join(pyzbar_path, "libiconv.dll"), "pyzbar"),
        (os.path.join(pyzbar_path, "libzbar-64.dll"), "pyzbar"),
    ],
    datas=[
        (png_path, "."),
        ("ScanModel", "ScanModel"),
    ],
    hiddenimports=[
        "ui",
        "ui.main_window",
        "ui.login_dialog",
        "ui.scan_window",
        "ui.sms_dialog",
        "utils",
        "utils.account_manager",
        "utils.config_manager",
        "utils.kuro_api",
        "utils.qr_payload",
        "utils.qr_scanner",
        "utils.secure_token_store",
        "utils.ai_qr_scanner",
        "utils.fast_screenshot",
        "utils.dxgi_screenshot",
        "utils.thread_pool_scanner",
        "utils.live_stream_scanner",
        "utils.performance_monitor",
        "utils.image_buffer_pool",
        "utils.smart_roi_detector",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=release_excludes,
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
    name="鸣潮抢码器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["python3.dll", "python314.dll"],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)
