# -*- coding: utf-8 -*-
"""
设计系统：鸣潮抢码器深色高级主题。

设计语言：
- 深空暗色基调（长时间挂机不刺眼，与游戏暗色 UI 融合）
- 鎏金主色（鸣潮品牌金），青成功 / 红危险 / 琥珀警告
- 大圆角卡片 + 细腻描边，无重阴影（暗色下阴影显脏）
- 排版：标题 20 Bold / 分区 14 Semibold / 正文 13 / 辅助 12
- 留白：卡片内 16，卡片间 12，页面边距 20
- 动效：150-250ms ease-out，克制（工具软件，效率优先）
"""
from __future__ import annotations

# ------------------------------------------------------------------
# 色板
# ------------------------------------------------------------------
BG_BASE = "#0B0D12"        # 页面底
BG_CARD = "#131722"        # 卡片
BG_CARD_HOVER = "#171D2A"  # 卡片悬停（极 subtle）
BG_INPUT = "#0F131B"       # 输入框底
BG_LOG = "#0D1117"         # 日志底

BORDER = "#232B3D"         # 描边
BORDER_FOCUS = "#C9A86A"   # 聚焦描边（金）

TEXT_PRIMARY = "#EDEFF5"    # 主文字
TEXT_SECONDARY = "#9AA4B8" # 次级文字
TEXT_MUTED = "#5C6678"     # 辅助文字

GOLD = "#C9A86A"           # 鎏金主色
GOLD_HOVER = "#D9B97E"
GOLD_PRESSED = "#B8965A"
GOLD_DIM = "rgba(201, 168, 106, 0.14)"  # 金色淡底

TEAL = "#3ED6A4"           # 成功
TEAL_DIM = "rgba(62, 214, 164, 0.12)"
RED = "#F0665E"            # 危险
RED_DIM = "rgba(240, 102, 94, 0.12)"
RED_HOVER = "#FF7A72"
AMBER = "#E8B44A"          # 警告
BLUE = "#5B9CF6"           # 信息

# ------------------------------------------------------------------
# 字体
# ------------------------------------------------------------------
FONT_SANS = '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif'
FONT_MONO = '"JetBrains Mono", "SF Mono", "Consolas", "Microsoft YaHei", monospace'

# ------------------------------------------------------------------
# 全局样式表
# ------------------------------------------------------------------
STYLESHEET = f"""
/* ============ 基础 ============ */
QMainWindow {{
    background-color: {BG_BASE};
}}
QWidget {{
    color: {TEXT_PRIMARY};
    font-family: {FONT_SANS};
    font-size: 13px;
}}
QLabel {{
    color: {TEXT_PRIMARY};
    background: transparent;
}}

/* ============ 卡片 ============ */
QWidget#infoWidget, QWidget#controlWidget, QWidget#logWidget {{
    background-color: {BG_CARD};
    border-radius: 18px;
    border: 1px solid {BORDER};
}}

/* 分区标题 */
QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {TEXT_PRIMARY};
    letter-spacing: 1px;
}}
/* 分区标题前的金色竖条（用 QLabel#sectionBar 实现） */
QLabel#sectionBar {{
    background-color: {GOLD};
    border-radius: 2px;
    min-width: 4px;
    max-width: 4px;
    min-height: 16px;
    max-height: 16px;
}}

/* ============ 按钮 ============ */
QPushButton {{
    padding: 10px 22px;
    border: none;
    border-radius: 12px;
    background-color: {GOLD};
    color: #1A1408;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton:hover {{
    background-color: {GOLD_HOVER};
}}
QPushButton:pressed {{
    background-color: {GOLD_PRESSED};
    padding-top: 11px;
    padding-bottom: 9px;
}}
QPushButton:disabled {{
    background-color: #232B3D;
    color: {TEXT_MUTED};
}}

/* 主要操作（开始扫描） */
QPushButton#primaryBtn {{
    background-color: {GOLD};
    font-size: 14px;
    padding: 12px 28px;
    border-radius: 14px;
}}
QPushButton#primaryBtn:hover {{ background-color: {GOLD_HOVER}; }}
QPushButton#primaryBtn:pressed {{ background-color: {GOLD_PRESSED}; }}

/* 成功（登录/添加账号） */
QPushButton#loginBtn {{
    background-color: {TEAL_DIM};
    color: {TEAL};
    border: 1px solid rgba(62, 214, 164, 0.35);
    font-weight: 600;
}}
QPushButton#loginBtn:hover {{
    background-color: rgba(62, 214, 164, 0.22);
}}
QPushButton#loginBtn:pressed {{
    background-color: rgba(62, 214, 164, 0.28);
}}

/* 危险（停止） */
QPushButton#stopBtn {{
    background-color: {RED_DIM};
    color: {RED};
    border: 1px solid rgba(240, 102, 94, 0.35);
    font-weight: 600;
}}
QPushButton#stopBtn:hover {{
    background-color: rgba(240, 102, 94, 0.22);
}}

/* 次要（幽灵按钮） */
QPushButton#ghostBtn, QPushButton#clearBtn {{
    background-color: transparent;
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    font-weight: 500;
}}
QPushButton#ghostBtn:hover, QPushButton#clearBtn:hover {{
    background-color: rgba(255, 255, 255, 0.04);
    color: {TEXT_PRIMARY};
    border-color: #2E3850;
}}
QPushButton#ghostBtn:pressed, QPushButton#clearBtn:pressed {{
    background-color: rgba(255, 255, 255, 0.07);
}}

/* ============ 输入框 ============ */
QLineEdit {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 11px 16px;
    font-size: 13px;
    selection-background-color: {GOLD_DIM};
}}
QLineEdit:focus {{
    border-color: {BORDER_FOCUS};
    background-color: #11151F;
}}
QLineEdit:disabled {{
    background-color: #141922;
    color: {TEXT_MUTED};
}}
QLineEdit::placeholder {{
    color: {TEXT_MUTED};
}}

/* ============ 下拉框 ============ */
QComboBox {{
    background-color: {BG_INPUT};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 10px 14px;
    font-size: 13px;
}}
QComboBox:focus {{ border-color: {BORDER_FOCUS}; }}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {GOLD_DIM};
    selection-color: {GOLD};
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 6px;
}}

/* ============ 复选框 ============ */
QCheckBox {{
    color: {TEXT_SECONDARY};
    font-size: 13px;
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1.5px solid #3A4560;
    background-color: {BG_INPUT};
}}
QCheckBox::indicator:hover {{
    border-color: {GOLD};
}}
QCheckBox::indicator:checked {{
    background-color: {GOLD};
    border-color: {GOLD};
}}

/* ============ 表格 ============ */
QTableWidget {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 14px;
    font-size: 13px;
    gridline-color: #1B2232;
    alternate-background-color: #10141D;
}}
QTableWidget::item {{
    padding: 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {GOLD_DIM};
    color: {GOLD};
}}
QTableWidget::item:alternate {{
    background-color: #10141D;
}}
QHeaderView::section {{
    background-color: {BG_INPUT};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 10px 8px;
    font-weight: 600;
    font-size: 12px;
    color: {TEXT_MUTED};
}}
QHeaderView {{
    background-color: {BG_INPUT};
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}}

/* ============ 日志 ============ */
QTextEdit#logText {{
    background-color: {BG_LOG};
    color: #C9D2E3;
    border: 1px solid {BORDER};
    border-radius: 14px;
    padding: 12px 14px;
    font-size: 12.5px;
    font-family: {FONT_MONO};
    line-height: 1.5;
}}

/* ============ 状态胶囊 ============ */
QLabel#statusLabel {{
    color: {TEXT_SECONDARY};
    font-size: 12.5px;
    padding: 8px 16px;
    background-color: rgba(255, 255, 255, 0.03);
    border: 1px solid {BORDER};
    border-radius: 20px;
}}
QLabel#statusActive {{
    color: {TEAL};
    background-color: {TEAL_DIM};
    border: 1px solid rgba(62, 214, 164, 0.3);
}}

/* ============ 标题 ============ */
QLabel#appTitle {{
    font-size: 22px;
    font-weight: 800;
    color: {TEXT_PRIMARY};
    letter-spacing: 2px;
}}
QLabel#appSubtitle {{
    font-size: 12px;
    color: {TEXT_MUTED};
    letter-spacing: 3px;
}}

/* ============ 滚动条 ============ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: #2A3448;
    border-radius: 5px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{
    background: #3A465E;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 4px;
}}
QScrollBar::handle:horizontal {{
    background: #2A3448;
    border-radius: 5px;
    min-width: 40px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ============ 工具提示 ============ */
QToolTip {{
    background-color: #1C2333;
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
}}
"""
