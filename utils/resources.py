# -*- coding: utf-8 -*-
"""
打包资源定位与完整性自检。

为什么需要：issue #8 的教训——模型文件缺失时旧代码只记一行
日志就静默降级，用户看到的是"识别率低"而非"模型没打进包"。
``check_resources()`` 在启动时跑一遍，缺什么、影响什么，一次说清。
"""
import os
import sys
from typing import List

from utils.log import get_logger


logger = get_logger("Resources")

#: ScanModel 下必须存在的四个文件（缺一不可，否则 WeChatQR 不可用）
MODEL_FILES = [
    "detect.prototxt",
    "detect.caffemodel",
    "sr.prototxt",
    "sr.caffemodel",
]

#: 主窗口图标
ICON_FILE = "11409B.png"


def resource_base() -> str:
    """资源根目录：打包环境用 ``sys._MEIPASS``，开发环境用仓库根。"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS  # type: ignore[attr-defined]
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def model_dir() -> str:
    """ScanModel 目录的绝对路径。"""
    return os.path.join(resource_base(), "ScanModel")


def model_paths() -> dict:
    """四个模型文件的绝对路径（key 为文件名）。"""
    directory = model_dir()
    return {name: os.path.join(directory, name) for name in MODEL_FILES}


def check_resources() -> List[str]:
    """检查打包资源完整性，返回人类可读的问题列表（空 = 一切正常）。

    只做检查、不抛异常：调用方决定是报错还是降级。
    """
    problems: List[str] = []
    directory = model_dir()
    if not os.path.isdir(directory):
        problems.append("ScanModel 目录缺失：%s" % directory)
        return problems
    for name in MODEL_FILES:
        path = os.path.join(directory, name)
        if not os.path.isfile(path):
            problems.append("模型文件缺失：%s" % path)
        elif os.path.getsize(path) == 0:
            problems.append("模型文件为空：%s" % path)
    icon = os.path.join(resource_base(), ICON_FILE)
    if not os.path.isfile(icon):
        problems.append("图标缺失：%s（仅影响窗口图标显示）" % icon)
    return problems


def log_resource_status() -> None:
    """启动时调用：有问题记 warning，无问题记一条 info。"""
    problems = check_resources()
    if problems:
        logger.warning("[Resources] 资源完整性检查发现 %d 个问题：", len(problems))
        for p in problems:
            logger.warning("[Resources]   - %s", p)
        logger.warning(
            "[Resources] 缺失模型将导致 WeChatQR/AI 增强不可用，"
            "已自动降级为 pyzbar（识别率会下降）"
        )
    else:
        logger.info("[Resources] 资源完整性检查通过")
