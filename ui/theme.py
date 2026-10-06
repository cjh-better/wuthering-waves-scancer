# -*- coding: utf-8 -*-
"""
设计系统：鸣潮抢码器双主题（深色 / 浅色）。

设计语言：
- 深色：深空暗色基调（长时间挂机不刺眼，与游戏暗色 UI 融合）
- 浅色：干净纸白基调（日间使用不刺眼，对比清晰）
- 共通：鎏金主色（鸣潮品牌金），青成功 / 红危险 / 琥珀警告
- 大圆角卡片 + 细腻描边
- 排版：标题 20 Bold / 分区 14 Semibold / 正文 13 / 辅助 12
- 留白：卡片内 16，卡片间 12，页面边距 20
- 动效：150-250ms ease-out，克制（工具软件，效率优先）
"""
from __future__ import annotations

# ------------------------------------------------------------------
# 主题名常量
# ------------------------------------------------------------------
THEME_DARK = "dark"
THEME_LIGHT = "light"

# ------------------------------------------------------------------
# 色板：深色（默认）
# ------------------------------------------------------------------
DARK_PALETTE = {
    "BG_BASE": "#0B0D12",        # 页面底
    "BG_CARD": "#131722",        # 卡片
    "BG_CARD_HOVER": "#171D2A",  # 卡片悬停（极 subtle）
    "BG_INPUT": "#0F131B",       # 输入框底
    "BG_LOG": "#0D1117",         # 日志底

    "BORDER": "#232B3D",         # 描边
    "BORDER_FOCUS": "#C9A86A",   # 聚焦描边（金）

    "TEXT_PRIMARY": "#EDEFF5",    # 主文字
    "TEXT_SECONDARY": "#9AA4B8", # 次级文字
    "TEXT_MUTED": "#5C6678",     # 辅助文字

    "GOLD": "#C9A86A",           # 鎏金主色
    "GOLD_HOVER": "#D9B97E",
    "GOLD_PRESSED": "#B8965A",
    "GOLD_DIM": "rgba(201, 168, 106, 0.14)",

    "TEAL": "#3ED6A4",           # 成功
    "TEAL_DIM": "rgba(62, 214, 164, 0.12)",
    "RED": "#F0665E",            # 危险
    "RED_DIM": "rgba(240, 102, 94, 0.12)",
    "RED_HOVER": "#FF7A72",
    "AMBER": "#E8B44A",          # 警告
    "BLUE": "#5B9CF6",           # 信息

    # 以下为样式表内部使用的衍生色（深色专用）
    "BTN_DISABLED_BG": "#232B3D",
    "INPUT_FOCUS_BG": "#11151F",
    "INPUT_DISABLED_BG": "#141922",
    "CHECKBOX_BORDER": "#3A4560",
    "GHOST_HOVER_BG": "rgba(255, 255, 255, 0.04)",
    "GHOST_HOVER_BORDER": "#2E3850",
    "GHOST_PRESSED_BG": "rgba(255, 255, 255, 0.07)",
    "TABLE_GRID": "#1B2232",
    "TABLE_ALT_BG": "#10141D",
    "LOG_TEXT": "#C9D2E3",
    "SCROLLBAR_HANDLE": "#2A3448",
    "SCROLLBAR_HANDLE_HOVER": "#3A465E",
    "TOOLTIP_BG": "#1C2333",
    "STATUS_PILL_BG": "rgba(255, 255, 255, 0.03)",
    "LOGIN_BTN_BORDER": "rgba(62, 214, 164, 0.35)",
    "LOGIN_BTN_HOVER": "rgba(62, 214, 164, 0.22)",
    "LOGIN_BTN_PRESSED": "rgba(62, 214, 164, 0.28)",
    "STOP_BTN_BORDER": "rgba(240, 102, 94, 0.35)",
    "STOP_BTN_HOVER": "rgba(240, 102, 94, 0.22)",
}

# ------------------------------------------------------------------
# 色板：浅色
# ------------------------------------------------------------------
LIGHT_PALETTE = {
    "BG_BASE": "#F2F4F7",        # 页面底
    "BG_CARD": "#FFFFFF",        # 卡片
    "BG_CARD_HOVER": "#F8F9FB",  # 卡片悬停
    "BG_INPUT": "#FFFFFF",       # 输入框底
    "BG_LOG": "#FAFBFC",         # 日志底

    "BORDER": "#E1E5EB",         # 描边
    "BORDER_FOCUS": "#C9A86A",   # 聚焦描边（金）

    "TEXT_PRIMARY": "#1A1D24",    # 主文字
    "TEXT_SECONDARY": "#5C6678", # 次级文字
    "TEXT_MUTED": "#9AA4B8",     # 辅助文字

    "GOLD": "#A8843C",           # 鎏金主色（浅色底加深，保证对比）
    "GOLD_HOVER": "#B8965A",
    "GOLD_PRESSED": "#96742F",
    "GOLD_DIM": "rgba(168, 132, 60, 0.12)",

    "TEAL": "#0E9F6E",           # 成功（加深）
    "TEAL_DIM": "rgba(14, 159, 110, 0.10)",
    "RED": "#D64541",            # 危险（加深）
    "RED_DIM": "rgba(214, 69, 65, 0.08)",
    "RED_HOVER": "#E85D59",
    "AMBER": "#C78A1B",          # 警告（加深）
    "BLUE": "#2B7DE0",           # 信息（加深）

    # 浅色衍生色
    "BTN_DISABLED_BG": "#E8EBF0",
    "INPUT_FOCUS_BG": "#FFFFFF",
    "INPUT_DISABLED_BG": "#F2F4F7",
    "CHECKBOX_BORDER": "#C5CCD8",
    "GHOST_HOVER_BG": "rgba(0, 0, 0, 0.03)",
    "GHOST_HOVER_BORDER": "#D0D6E0",
    "GHOST_PRESSED_BG": "rgba(0, 0, 0, 0.06)",
    "TABLE_GRID": "#EDEFF3",
    "TABLE_ALT_BG": "#F8F9FB",
    "LOG_TEXT": "#3A4150",
    "SCROLLBAR_HANDLE": "#C5CCD8",
    "SCROLLBAR_HANDLE_HOVER": "#A8B2C4",
    "TOOLTIP_BG": "#FFFFFF",
    "STATUS_PILL_BG": "rgba(0, 0, 0, 0.03)",
    "LOGIN_BTN_BORDER": "rgba(14, 159, 110, 0.35)",
    "LOGIN_BTN_HOVER": "rgba(14, 159, 110, 0.14)",
    "LOGIN_BTN_PRESSED": "rgba(14, 159, 110, 0.20)",
    "STOP_BTN_BORDER": "rgba(214, 69, 65, 0.35)",
    "STOP_BTN_HOVER": "rgba(214, 69, 65, 0.14)",
}

# ------------------------------------------------------------------
# 向后兼容：模块级常量（深色默认值）
# ------------------------------------------------------------------
BG_BASE = DARK_PALETTE["BG_BASE"]
BG_CARD = DARK_PALETTE["BG_CARD"]
BG_CARD_HOVER = DARK_PALETTE["BG_CARD_HOVER"]
BG_INPUT = DARK_PALETTE["BG_INPUT"]
BG_LOG = DARK_PALETTE["BG_LOG"]
BORDER = DARK_PALETTE["BORDER"]
BORDER_FOCUS = DARK_PALETTE["BORDER_FOCUS"]
TEXT_PRIMARY = DARK_PALETTE["TEXT_PRIMARY"]
TEXT_SECONDARY = DARK_PALETTE["TEXT_SECONDARY"]
TEXT_MUTED = DARK_PALETTE["TEXT_MUTED"]
GOLD = DARK_PALETTE["GOLD"]
GOLD_HOVER = DARK_PALETTE["GOLD_HOVER"]
GOLD_PRESSED = DARK_PALETTE["GOLD_PRESSED"]
GOLD_DIM = DARK_PALETTE["GOLD_DIM"]
TEAL = DARK_PALETTE["TEAL"]
TEAL_DIM = DARK_PALETTE["TEAL_DIM"]
RED = DARK_PALETTE["RED"]
RED_DIM = DARK_PALETTE["RED_DIM"]
RED_HOVER = DARK_PALETTE["RED_HOVER"]
AMBER = DARK_PALETTE["AMBER"]
BLUE = DARK_PALETTE["BLUE"]

# ------------------------------------------------------------------
# 字体
# ------------------------------------------------------------------
FONT_SANS = '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif'
FONT_MONO = '"JetBrains Mono", "SF Mono", "Consolas", "Microsoft YaHei", monospace'


def get_palette(theme: str) -> dict:
    """按主题名返回色板（未知主题回退深色）。"""
    if theme == THEME_LIGHT:
        return LIGHT_PALETTE
    return DARK_PALETTE


def build_stylesheet(p: dict) -> str:
    """用给定色板构建全局样式表。"""
    return f"""
/* ============ 基础 ============ */
QMainWindow {{
    background-color: {p['BG_BASE']};
}}
QWidget {{
    color: {p['TEXT_PRIMARY']};
    font-family: {FONT_SANS};
    font-size: 13px;
}}
QLabel {{
    color: {p['TEXT_PRIMARY']};
    background: transparent;
}}

/* ============ 卡片 ============ */
QWidget#infoWidget, QWidget#controlWidget, QWidget#logWidget {{
    background-color: {p['BG_CARD']};
    border-radius: 18px;
    border: 1px solid {p['BORDER']};
}}

/* 分区标题 */
QLabel#sectionTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {p['TEXT_PRIMARY']};
    letter-spacing: 1px;
    border-left: 4px solid {p['GOLD']};
    padding-left: 10px;
    margin: 4px 2px 8px 2px;
}}
/* 分区标题前的金色竖条（用 QLabel#sectionBar 实现） */
QLabel#sectionBar {{
    background-color: {p['GOLD']};
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
    background-color: {p['GOLD']};
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 700;
}}
QPushButton:hover {{
    background-color: {p['GOLD_HOVER']};
}}
QPushButton:pressed {{
    background-color: {p['GOLD_PRESSED']};
    padding-top: 11px;
    padding-bottom: 9px;
}}
QPushButton:disabled {{
    background-color: {p['BTN_DISABLED_BG']};
    color: {p['TEXT_MUTED']};
}}

/* 主要操作（开始扫描） */
QPushButton#primaryBtn {{
    background-color: {p['GOLD']};
    font-size: 14px;
    padding: 12px 28px;
    border-radius: 14px;
}}
QPushButton#primaryBtn:hover {{ background-color: {p['GOLD_HOVER']}; }}
QPushButton#primaryBtn:pressed {{ background-color: {p['GOLD_PRESSED']}; }}

/* 成功（登录/添加账号） */
QPushButton#loginBtn {{
    background-color: {p['TEAL_DIM']};
    color: {p['TEAL']};
    border: 1px solid {p['LOGIN_BTN_BORDER']};
    font-weight: 600;
}}
QPushButton#loginBtn:hover {{
    background-color: {p['LOGIN_BTN_HOVER']};
}}
QPushButton#loginBtn:pressed {{
    background-color: {p['LOGIN_BTN_PRESSED']};
}}

/* 危险（停止） */
QPushButton#stopBtn {{
    background-color: {p['RED_DIM']};
    color: {p['RED']};
    border: 1px solid {p['STOP_BTN_BORDER']};
    font-weight: 600;
}}
QPushButton#stopBtn:hover {{
    background-color: {p['STOP_BTN_HOVER']};
}}

/* 次要（幽灵按钮） */
QPushButton#ghostBtn, QPushButton#clearBtn {{
    background-color: transparent;
    color: {p['TEXT_SECONDARY']};
    border: 1px solid {p['BORDER']};
    font-weight: 500;
}}
QPushButton#ghostBtn:hover, QPushButton#clearBtn:hover {{
    background-color: {p['GHOST_HOVER_BG']};
    color: {p['TEXT_PRIMARY']};
    border-color: {p['GHOST_HOVER_BORDER']};
}}
QPushButton#ghostBtn:pressed, QPushButton#clearBtn:pressed {{
    background-color: {p['GHOST_PRESSED_BG']};
}}

/* 主题切换按钮 */
QPushButton#themeBtn {{
    background-color: transparent;
    color: {p['TEXT_SECONDARY']};
    border: 1px solid {p['BORDER']};
    border-radius: 10px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton#themeBtn:hover {{
    background-color: {p['GHOST_HOVER_BG']};
    color: {p['TEXT_PRIMARY']};
}}

/* ============ 输入框 ============ */
QLineEdit {{
    background-color: {p['BG_INPUT']};
    color: {p['TEXT_PRIMARY']};
    border: 1px solid {p['BORDER']};
    border-radius: 12px;
    padding: 11px 16px;
    font-size: 13px;
    selection-background-color: {p['GOLD_DIM']};
}}
QLineEdit:focus {{
    border-color: {p['BORDER_FOCUS']};
    background-color: {p['INPUT_FOCUS_BG']};
}}
QLineEdit:disabled {{
    background-color: {p['INPUT_DISABLED_BG']};
    color: {p['TEXT_MUTED']};
}}
QLineEdit::placeholder {{
    color: {p['TEXT_MUTED']};
}}

/* ============ 下拉框 ============ */
QComboBox {{
    background-color: {p['BG_INPUT']};
    color: {p['TEXT_PRIMARY']};
    border: 1px solid {p['BORDER']};
    border-radius: 12px;
    padding: 10px 14px;
    font-size: 13px;
}}
QComboBox:focus {{ border-color: {p['BORDER_FOCUS']}; }}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox QAbstractItemView {{
    background-color: {p['BG_CARD']};
    color: {p['TEXT_PRIMARY']};
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
    selection-background-color: {p['GOLD_DIM']};
    selection-color: {p['GOLD']};
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    padding: 8px 12px;
    border-radius: 6px;
}}

/* ============ 复选框 ============ */
QCheckBox {{
    color: {p['TEXT_SECONDARY']};
    font-size: 13px;
    spacing: 8px;
    background: transparent;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1.5px solid {p['CHECKBOX_BORDER']};
    background-color: {p['BG_INPUT']};
}}
QCheckBox::indicator:hover {{
    border-color: {p['GOLD']};
}}
QCheckBox::indicator:checked {{
    background-color: {p['GOLD']};
    border-color: {p['GOLD']};
}}

/* ============ 表格 ============ */
QTableWidget {{
    background-color: {p['BG_INPUT']};
    border: 1px solid {p['BORDER']};
    border-radius: 14px;
    font-size: 13px;
    gridline-color: {p['TABLE_GRID']};
    alternate-background-color: {p['TABLE_ALT_BG']};
}}
QTableWidget::item {{
    padding: 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {p['GOLD_DIM']};
    color: {p['GOLD']};
}}
QTableWidget::item:alternate {{
    background-color: {p['TABLE_ALT_BG']};
}}
QHeaderView::section {{
    background-color: {p['BG_INPUT']};
    border: none;
    border-bottom: 1px solid {p['BORDER']};
    padding: 10px 8px;
    font-weight: 600;
    font-size: 12px;
    color: {p['TEXT_MUTED']};
}}
QHeaderView {{
    background-color: {p['BG_INPUT']};
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}}

/* ============ 日志 ============ */
QTextEdit#logText {{
    background-color: {p['BG_LOG']};
    color: {p['LOG_TEXT']};
    border: 1px solid {p['BORDER']};
    border-radius: 14px;
    padding: 12px 14px;
    font-size: 12.5px;
    font-family: {FONT_MONO};
    line-height: 1.5;
}}

/* ============ 状态胶囊 ============ */
QLabel#statusLabel {{
    color: {p['TEXT_SECONDARY']};
    font-size: 12.5px;
    padding: 8px 16px;
    background-color: {p['STATUS_PILL_BG']};
    border: 1px solid {p['BORDER']};
    border-radius: 20px;
}}
QLabel#statusActive {{
    color: {p['TEAL']};
    background-color: {p['TEAL_DIM']};
    border: 1px solid {p['LOGIN_BTN_BORDER']};
}}

/* ============ 标题 ============ */
QLabel#appTitle {{
    font-size: 22px;
    font-weight: 800;
    color: {p['TEXT_PRIMARY']};
    letter-spacing: 2px;
}}
QLabel#appSubtitle {{
    font-size: 12px;
    color: {p['TEXT_MUTED']};
    letter-spacing: 3px;
}}
QLabel#presetLabel {{
    color: {p['TEXT_SECONDARY']};
    font-size: 12.5px;
}}

/* ============ 滚动条 ============ */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {p['SCROLLBAR_HANDLE']};
    border-radius: 5px;
    min-height: 40px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['SCROLLBAR_HANDLE_HOVER']};
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
    background: {p['SCROLLBAR_HANDLE']};
    border-radius: 5px;
    min-width: 40px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ============ 工具提示 ============ */
QToolTip {{
    background-color: {p['TOOLTIP_BG']};
    color: {p['TEXT_PRIMARY']};
    border: 1px solid {p['BORDER']};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 12px;
}}
"""


def get_stylesheet(theme: str = THEME_DARK) -> str:
    """按主题名返回完整样式表。"""
    return build_stylesheet(get_palette(theme))


# 向后兼容：默认深色样式表
STYLESHEET = get_stylesheet(THEME_DARK)
