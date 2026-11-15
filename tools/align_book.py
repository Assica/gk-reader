# -*- coding: utf-8 -*-
"""整本联合对齐：一次算出全书每个词的时间，页区间由词的归属推导。

替换旧的"静音切段 + 挑最均匀窗口"做法。旧的假设"一个语音段 = 一页"，
遇到 G1 那种跨页多句的页就会把**一个句子片段当成整页**（实测 G1-107 p8
110 个词只分到 4.67 秒 = 23.6 词/秒，句子栏读出来只有半句）。

做法：
  1. 把一本书所有页的文字按顺序拼起来
  2. 音频**分块**喂给 wav2vec2 编码器（30 s 窗 / 25 s 跳，只保留非重叠段帧），
     因为 encoder 的 attention 是 O(T²)：120 s 音频峰值 6.7 GB，266 s 约 24 GB
  3. 拼好的 logits 只做**一次** Viterbi（强制对齐），得到全书每个词的时间
  4. 每页区间 = 该页第一个词的起点 ~ 最后一个词的终点，再向两侧补到与邻页的中点

    python tools/align_book.py --books G1-107 G1-089 G1-096   # 只跑几本
    python tools/align_book.py --jobs 6                        # 全量
"""
import argparse
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import ctc_align as C  # noqa: E402
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\apple app")
LIB = ROOT / "library"
PS = str(Path(__file__).parent / "mf_transcode.ps1")

CHUNK_SEC = 30.0
HOP_SEC = 25.0
FPS = 50                     # wav2vec2 base: 20 ms / 帧


def to_wav(src: Path, dst: Path) -> bool:
    if dst.exists() and dst.stat().st_size > 20000:
        return True
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS,
                    "-Source", str(src), "-Dest", str(dst), "-AsWav",
                    "-SampleRate", "16000", "-Channels", "1"],
                   capture_output=True, text=True, errors="ignore")
    return dst.exists() and dst.stat().st_size > 20000


def encode_chunked(x: np.ndarray, sr: int = 16000) -> np.ndarray:
    """分块跑 encoder，只保留非重叠段，拼成整本 logits。"""
    C._init()
    total = len(x) / sr
    parts, start = [], 0.0
    while True:
        end = min(start + CHUNK_SEC, total)
        seg = x[int(round(start * sr)):int(round(end * sr))]
        if len(seg) < sr // 10:            # 尾巴太短，丢掉
            break
        logits = C._sess.run(None, {"input_values": seg[None, :].astype(np.float32)})[0][0]
        if end >= total - 1e-6:
            keep = logits.shape[0]
        else:
            keep = min(int(round(HOP_SEC * FPS)), logits.shape[0])
        parts.append(logits[:keep])
        if end >= total - 1e-6:
            break
        start += HOP_SEC
    if not parts:
        return np.zeros((0, 32), dtype=np.float32)
    return np.concatenate(parts, axis=0)


def word_times_full(x: np.ndarray, words):
    """全书一次对齐，返回每个词的 [t0, t1]（相对全书音频）。"""
    labels, word_of = C._labels_for(words)
    logits = encode_chunked(x)
    if logits.shape[0] == 0 or len(labels) == 0:
        return None
    m = logits - logits.max(axis=1, keepdims=True)
    log_probs = m - np.log(np.exp(m).sum(axis=1, keepdims=True))
    states, ext = C._viterbi_states(log_probs, labels)
    T = states.shape[0]

    per_label = [[] for _ in range(len(labels))]
    for t in range(T):
        st = int(states[t])
        if st == 0:
            continue
        li = (st - 1) // 2
        if 0 <= li < len(labels) and ext[st] != 0:
            per_label[li].append(t)

    out = []
    for wi in range(len(words)):
        mine = [f for li, fs in enumerate(per_label) if word_of[li] == wi for f in fs]
        if not mine:
            out.append(None)
            continue
        out.append([min(mine) * C.FRAME_SEC, (max(mine) + 1) * C.FRAME_SEC])
    return out


def tighten(spans, total_dur, min_dur=0.12, max_dur=1.2, pad=0.06):
    """把 CTC 的紧边界整理成可点的词段。

    widen() 会把每段撑到与邻居的中点——遇到长停顿时会造出 "I 占 3.25 秒" 这种。
    这里改成：保留 CTC 的起点，只向后延伸到 min_dur，且不超过 max_dur；
    None（没拿到帧）的词用邻居插值。
    """
    out = []
    for s in spans:
        if s is None:
            out.append(None)
            continue
        a, b = float(s[0]), float(s[1])
        if b - a < min_dur:
            b = a + min_dur
        if b - a > max_dur:
            b = a + max_dur
        out.append([max(0.0, a), min(total_dur, b)])

    # 补齐 None：夹在左右邻居之间，宽度取中位词长
    lens = [b - a for a, b in (x for x in out if x)]
    med = float(np.median(lens)) if lens else min_dur
    for i, s in enumerate(out):
        if s is not None:
            continue
        prev = next((out[j][1] for j in range(i - 1, -1, -1) if out[j]), 0.0)
        nxt = next((out[j][0] for j in range(i + 1, len(out)) if out[j]), total_dur)
        a = prev + pad
        b = min(nxt - pad, a + med)
        if b <= a:
            a, b = prev, prev + min_dur
        out[i] = [max(0.0, a), min(total_dur, b)]

    # 单调：门限要求严格递增（后词起点 > 前词终点），所以相邻要留 2 ms 间隙，
    # 不能简单地把边界设成相等
    EPS = 0.002
    for i in range(1, len(out)):
        if out[i][0] <= out[i - 1][1]:
            out[i][0] = round(out[i - 1][1] + EPS, 3)
        if out[i][1] <= out[i][0]:
            out[i][1] = round(min(total_dur, out[i][0] + min_dur), 3)
        if out[i][1] <= out[i][0]:
            out[i][1] = round(out[i][0] + 0.001, 3)
    return out


def assign_pages(pages, words, spans, total_dur):
    """把词时间摊回每页，并算出页区间（含向邻页中点补齐）。"""
    # words 是按页顺序拼的；记录每页占了多少词
    idx, page_word_ranges = 0, []
    for p in pages:
        n = len(C.words_of(p.get("text") or ""))
        page_word_ranges.append((idx, idx + n))
        idx += n

    spans = list(spans)
    # 没拿到帧的词：用邻居插值，别留 None
    for i, s in enumerate(spans):
        if s is None:
            prev = next((spans[j][1] for j in range(i - 1, -1, -1) if spans[j]), 0.0)
            nxt = next((spans[j][0] for j in range(i + 1, len(spans)) if spans[j]), total_dur)
            spans[i] = [prev, max(prev + 0.06, min(nxt, prev + 0.3))]

    raw = []
    for (a, b) in page_word_ranges:
        if b > a:
            raw.append([spans[a][0], spans[b - 1][1]])
        else:
            raw.append(None)          # 无字页

    # 无字页：夹在邻页之间
    for i, r in enumerate(raw):
        if r is not None:
            continue
        lo = next((raw[j][1] for j in range(i - 1, -1, -1) if raw[j]), 0.0)
        hi = next((raw[j][0] for j in range(i + 1, len(raw)) if raw[j]), total_dur)
        raw[i] = [lo, max(lo + 0.05, hi)]

    # 只在两侧各留一点点余量，不要补到邻页中点：
    # 实测补到中点会把 0.5–3.4 s 的静音包进页首（中位 1.78 s），
    # 点句子栏会"等快 2 秒才出声"。
    PAD = 0.18
    out = []
    for i, r in enumerate(raw):
        a = max(0.0, r[0] - PAD)
        b = min(total_dur, r[1] + PAD)
        out.append([a, b])
    # 相邻页不能重叠（重叠会让连播听两遍）
    for i in range(1, len(out)):
        if out[i][0] < out[i - 1][1]:
            mid = (out[i][0] + out[i - 1][1]) / 2
            out[i - 1][1] = mid
            out[i][0] = mid
    return [[round(max(0.0, a), 2), round(min(total_dur, b), 2)] for a, b in out], page_word_ranges, spans


def _task(args):
    jf_str, dry = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    sid = book["id"]
    if not book.get("audio"):
        return True, "无音频", None

    tmp = Path(tempfile.mkdtemp(prefix="gk-ab-"))
    wav = tmp / "a.wav"
    if not to_wav(LIB / book["audio"], wav):
        return False, "wav 转换失败", None
    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    total = len(x) / sr

    pages = book["pages"]
    words = []
    for p in pages:
        # 必须用 wordBoxes.words 作为词表：前端 pageWords() 优先用它，
        # 而它经过视觉合并（"lit"+"tle" → "little"），与 text.split() 不一定同长。
        # 两边长度不一致会让下游把整页 wordTimes 丢掉。
        wb = (p.get("wordBoxes") or {}).get("words")
        if wb:
            words.extend(C.words_of(" ".join(wb)))
        else:
            words.extend(C.words_of((p.get("text") or "")))
    if len(words) < 3:
        return True, "词太少", None

    spans = word_times_full(x, words)
    if spans is None:
        return False, "对齐失败", None
    # CTC 给的是紧边界，短词可能只有一两帧；widen 会把每段撑到与邻居的中点，
    # 并保证最小 0.12 s —— 否则会出现 "0.00~0.04 s" 这种点下去听不见的词
    spans = tighten(spans, total)

    page_spans, ranges, wtimes = assign_pages(pages, words, spans, total)
    noframe = sum(1 for s in wtimes if s is None)

    if not dry:
        for p, (a, b), rng in zip(pages, page_spans, ranges):
            p["audio"] = [a, b]
            dur = max(b - a, 0.05)
            n = rng[1] - rng[0]
            if n:
                # 前端是 `base = p.audio[0]; playRange(base + wordTimes[k][0], ...)`，
                # 所以 wordTimes 必须是**页相对**时间，不是全书绝对时间。
                rel = [[round(t[0] - a, 3), round(t[1] - a, 3)] for t in wtimes[rng[0]:rng[1]]]
                ok = all(0 <= x[0] < x[1] <= dur + 0.05 for x in rel if x)
                if ok and len(rel) == n:
                    p["wordTimes"] = rel
                else:
                    p.pop("wordTimes", None)
            else:
                p.pop("wordTimes", None)
        book["alignMethod"] = "book"
        # 原子写：测试/服务可能同时在读这个文件，不能让它读到半截 JSON
        tmp = jf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(jf)

    demo = max((len(C.words_of(p.get("text") or "")) / max(b - a, 0.1)
                for p, (a, b) in zip(pages, page_spans)), default=0)
    wav.unlink(missing_ok=True)
    try:
        tmp.rmdir()
    except Exception:
        pass
    return True, f"词={len(words)} 无帧={noframe} 最坏词/秒={demo:.1f}", demo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--books", nargs="*", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    tasks = []
    for b in books:
        if args.books and b["id"] not in args.books:
            continue
        jf = LIB / "books" / b["series"] / f'{b["no"]:03d}.json'
        tasks.append((b["id"], (str(jf), args.dry_run)))

    jobs = args.jobs or default_jobs(8)
    print(f"整本对齐 {len(tasks)} 本，{jobs} 进程{'（dry-run）' if args.dry_run else ''}", flush=True)
    res = run_tasks(tasks, _task, jobs)
    ok = sum(1 for _, o, _, _ in res if o)
    rates = [p for _, o, _, p in res if o and p is not None]
    rates.sort()
    print(f"\n成功 {ok}/{len(tasks)}")
    if rates:
        print(f"最坏页词/秒: 中位 {rates[len(rates)//2]:.2f}  p90 {rates[int(len(rates)*0.9)]:.2f}  max {rates[-1]:.1f}")
    bad = [(k, i) for k, o, i, _ in res if not o]
    if bad:
        print("失败:", bad[:8])


if __name__ == "__main__":
    main()
