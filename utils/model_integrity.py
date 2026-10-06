# -*- coding: utf-8 -*-
"""
WeChatQR 模型文件完整性校验（对应 issue #8 的防护）。

损坏的 caffemodel/prototxt 喂给 OpenCV dnn 是 native segfault 的
高发区。启动时校验 SHA256，不匹配时明确报错（提示重新下载），
而不是在解码时闪退。
"""
import hashlib
import os
from typing import Dict, List, Tuple

from utils.log import get_logger

logger = get_logger("ModelIntegrity")

# 模型文件期望的 SHA256（2026-10-06 实测当前仓库文件）。
# 若上游更新模型，同步更新此处。
EXPECTED_HASHES: Dict[str, str] = {
    "detect.prototxt": "e8acfc395caf443a47f15686a9b9207b36cb8f7e6ceb8fbaf6466665e68a9466",
    "detect.caffemodel": "cc49b8c9babaf45f3037610fe499df38c8819ebda29e90ca9f2e33270f6ef809",
    "sr.prototxt": "8ae41acba97e8b4a8e741ee350481e49b8e01d787193f470a4c95ee1c02d5b61",
    "sr.caffemodel": "e5d36889d8e6ef2f1c1f515f807cec03979320ac81792cd8fb927c31fd658ae3",
}

MODEL_DIR = "ScanModel"


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_models(model_dir: str = MODEL_DIR) -> Tuple[bool, List[str]]:
    """校验模型文件。返回 (全部通过, 问题描述列表)。"""
    problems: List[str] = []
    for name, expected in EXPECTED_HASHES.items():
        path = os.path.join(model_dir, name)
        if not os.path.exists(path):
            problems.append(f"缺失: {name}")
            continue
        try:
            actual = _sha256(path)
        except Exception as e:
            problems.append(f"读取失败 {name}: {e}")
            continue
        if actual != expected:
            problems.append(
                f"损坏: {name} (hash 不匹配，可能下载不完整)"
            )
    ok = not problems
    if ok:
        logger.info("[ModelIntegrity] 模型文件校验通过 (%d 个)", len(EXPECTED_HASHES))
    else:
        for p in problems:
            logger.warning("[ModelIntegrity] %s", p)
    return ok, problems


def verify_or_warn(model_dir: str = MODEL_DIR) -> bool:
    """校验，失败时打日志警告（不阻断启动，调用方决定）。"""
    ok, _ = verify_models(model_dir)
    return ok
