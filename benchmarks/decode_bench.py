# -*- coding: utf-8 -*-
"""解码路径 benchmark：量化 pyzbar / WeChatQR / 帧差分的耗时与检出率。

运行：cd ~/workspace/wuthering-waves-scancer && python3 benchmarks/decode_bench.py
用途：为"解码级联顺序""帧差分阈值"等优化决策提供数据支撑，不许拍脑袋。
"""
import os
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import qrcode
from pyzbar.pyzbar import decode as pyzbar_decode

MODEL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ScanModel"
)

PAYLOAD = "https://kurobbs.com/qr?G152#KURO" + "A" * 40  # 模拟库街区登录码


def make_qr_image(px: int) -> np.ndarray:
    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(PAYLOAD)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    img = img.resize((px, px))
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def make_stream_frame(qr_px: int, blur: bool, bg_noise: bool) -> np.ndarray:
    """模拟 1280x720 直播帧：二维码贴在复杂背景上，可选模糊（模拟压制画质）。"""
    rng = np.random.default_rng(42)
    frame = np.full((720, 1280, 3), 60, dtype=np.uint8)
    # 背景纹理
    frame += (rng.random((720, 1280, 3)) * 40).astype(np.uint8)
    # 游戏 UI 色块
    cv2.rectangle(frame, (900, 500), (1280, 720), (30, 30, 120), -1)
    cv2.circle(frame, (200, 150), 80, (120, 30, 30), -1)
    qr = make_qr_image(qr_px)
    if blur:
        qr = cv2.GaussianBlur(qr, (5, 5), 1.5)
    # 位置自适应：大 QR 放左上，保证不越界
    x = min(960, 1280 - qr_px)
    y = min(80, 720 - qr_px)
    frame[y:y + qr_px, x:x + qr_px] = qr
    return frame


def bench_decode(name, fn, frames, expect_found: bool):
    times = []
    found = 0
    for f in frames:
        t0 = time.perf_counter()
        ok = fn(f)
        times.append((time.perf_counter() - t0) * 1000)
        found += 1 if ok else 0
    times.sort()
    p50 = times[len(times) // 2]
    p95 = times[int(len(times) * 0.95)]
    print(
        f"{name:28s} p50={p50:8.1f}ms p95={p95:8.1f}ms "
        f"检出率={found}/{len(frames)}"
        + ("" if (found > 0) == expect_found else "  <-- 与预期不符!")
    )
    return p50, found


def main():
    print("== 测试帧 ==")
    clean = [make_stream_frame(300, blur=False, bg_noise=True) for _ in range(5)]
    blurry = [make_stream_frame(300, blur=True, bg_noise=True) for _ in range(5)]
    small = [make_stream_frame(160, blur=True, bg_noise=True) for _ in range(5)]
    noqr = [make_stream_frame(300, blur=False, bg_noise=True) for _ in range(3)]
    for f in noqr:  # 无码帧：盖掉二维码
        f[80:380, 960:1260] = (60, 60, 60)

    print("== pyzbar（BGR->灰度直解） ==")
    def pyz(f):
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
        ds = pyzbar_decode(g)
        return any(PAYLOAD.encode() in (d.data or b"") for d in ds)
    bench_decode("pyzbar clean", pyz, clean, True)
    bench_decode("pyzbar blurry", pyz, blurry, True)
    bench_decode("pyzbar small+blur", pyz, small, True)
    bench_decode("pyzbar no-qr", pyz, noqr, False)

    print("== WeChatQR（detect 模型，scaleFactor 0.4） ==")
    det_proto = os.path.join(MODEL_DIR, "detect.prototxt")
    det_model = os.path.join(MODEL_DIR, "detect.caffemodel")
    if all(os.path.exists(p) for p in (det_proto, det_model)):
        wq = cv2.wechat_qrcode_WeChatQRCode(det_proto, det_model)
        wq.setScaleFactor(0.4)
        # 预热（首次最慢）
        wq.detectAndDecode(np.zeros((100, 100, 3), np.uint8))
        def wchat(f):
            res, _ = wq.detectAndDecode(f)
            if isinstance(res, str):
                res = [res]
            return any(PAYLOAD in r for r in (res or []))
        bench_decode("wechat clean", wchat, clean, True)
        bench_decode("wechat blurry", wchat, blurry, True)
        bench_decode("wechat small+blur", wchat, small, True)
        bench_decode("wechat no-qr", wchat, noqr, False)
    else:
        print("模型缺失，跳过 WeChatQR")

    print("== 多尺度 QR：WeChatQR 检出率/耗时（对抗：故意放大） ==")
    def pyz_half(f):
        small = cv2.resize(f, (640, 360))
        g = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        ds = pyzbar_decode(g)
        return any(PAYLOAD.encode() in (d.data or b"") for d in ds)
    det_proto = os.path.join(MODEL_DIR, "detect.prototxt")
    det_model = os.path.join(MODEL_DIR, "detect.caffemodel")
    if all(os.path.exists(p) for p in (det_proto, det_model)):
        wq = cv2.wechat_qrcode_WeChatQRCode(det_proto, det_model)
        wq.setScaleFactor(0.4)
        wq.detectAndDecode(np.zeros((100, 100, 3), np.uint8))  # 预热
        def wchat(f):
            res, _ = wq.detectAndDecode(f)
            if isinstance(res, str):
                res = [res]
            return any(PAYLOAD in r for r in (res or []))
        for px in (120, 300, 500, 650):
            frames = [make_stream_frame(px, blur=True, bg_noise=True) for _ in range(3)]
            bench_decode(f"wechat QR={px}px", wchat, frames, True)
        # scaleFactor 1.0 对超大 QR 是否更好
        wq1 = cv2.wechat_qrcode_WeChatQRCode(det_proto, det_model)
        wq1.setScaleFactor(1.0)
        wq1.detectAndDecode(np.zeros((100, 100, 3), np.uint8))
        def wchat1(f):
            res, _ = wq1.detectAndDecode(f)
            if isinstance(res, str):
                res = [res]
            return any(PAYLOAD in r for r in (res or []))
        frames650 = [make_stream_frame(650, blur=True, bg_noise=True) for _ in range(3)]
        bench_decode("wechat@1.0 QR=650px", wchat1, frames650, True)
        # pyzbar@360p 对大 QR
        bench_decode("pyzbar@360p QR=650px", pyz_half, frames650, True)
    else:
        print("模型缺失，跳过")

    print("== 随机位置 QR 的帧差分响应（对抗：随机位置） ==")
    rng = np.random.default_rng(7)
    base_frame = make_stream_frame(300, blur=False, bg_noise=True)
    base_frame[80:380, 960:1260] = (60, 60, 60)  # 抹掉固定位置的码
    prev_small = cv2.cvtColor(cv2.resize(base_frame, (64, 36)), cv2.COLOR_BGR2GRAY)
    for trial in range(5):
        f = base_frame.copy()
        qr = make_qr_image(300)
        qx, qy = int(rng.integers(0, 1280 - 300)), int(rng.integers(0, 720 - 300))
        f[qy:qy + 300, qx:qx + 300] = qr
        t0 = time.perf_counter()
        g = cv2.cvtColor(cv2.resize(f, (64, 36)), cv2.COLOR_BGR2GRAY)
        score = float(np.mean(cv2.absdiff(prev_small, g)))
        ms = (time.perf_counter() - t0) * 1000
        print(f"  trial{trial}: QR@({qx},{qy}) 差分耗时={ms:.3f}ms 变化分数={score:.2f}")

    print("== 帧差分成本（64x36 灰度 absdiff） ==")
    prev = cv2.cvtColor(cv2.resize(clean[0], (64, 36)), cv2.COLOR_BGR2GRAY)
    diffs = []
    for f in clean[1:] + blurry[:2]:
        t0 = time.perf_counter()
        g = cv2.cvtColor(cv2.resize(f, (64, 36)), cv2.COLOR_BGR2GRAY)
        d = cv2.absdiff(prev, g)
        score = float(np.mean(d))
        diffs.append(((time.perf_counter() - t0) * 1000, score))
        prev = g
    for ms, s in diffs:
        print(f"  差分耗时={ms:.3f}ms 变化分数={s:.2f}")
    # 无码帧之间的差分（基线噪声）
    t0 = time.perf_counter()
    g1 = cv2.cvtColor(cv2.resize(noqr[0], (64, 36)), cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(cv2.resize(noqr[1], (64, 36)), cv2.COLOR_BGR2GRAY)
    base = float(np.mean(cv2.absdiff(g1, g2)))
    print(f"  静态帧基线噪声={base:.2f}（差分耗时={(time.perf_counter()-t0)*1000:.3f}ms）")


if __name__ == "__main__":
    main()
