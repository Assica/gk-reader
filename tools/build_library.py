# -*- coding: utf-8 -*-
"""把三套绘本（GK / G1 / G2）加工成 App 用的 library/。

    python tools/build_library.py                 # 全量
    python tools/build_library.py --series G1     # 只跑一套
    python tools/build_library.py --limit 3       # 每套只跑 3 本（试跑）
    python tools/build_library.py --boxes-only    # 只重算文字/词框

输出：
    library/manifest.json
    library/covers/{SERIES}/{NNN}.jpg
    library/books/{SERIES}/{NNN}/p{页面号}.jpg     # 只含正文页
    library/books/{SERIES}/{NNN}.json
    library/audio/{SERIES}/{NNN}.m4a
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from mutagen.mp4 import MP4
from PIL import Image
from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

ROOT = Path(r"E:\apple app")
LIB = ROOT / "library"
PS_TRANSCODE = ROOT / "tools" / "mf_transcode.ps1"

LONG_EDGE = 1400          # 图片长边（1600→1400，体积降约 25%）
AUDIO_BPS = 48000         # 音频码率
FPS = 100

# ── 素材目录 ──────────────────────────────────────────────
# G2 暂时不收录：三套全上约 600 MB，SideStore 每 7 天重签会很慢。
# 想恢复就把下面注释掉的那一行放开，再跑 `python tools/build_library.py --series G2`。
SERIES = [
    {"key": "GK", "pdf": "02、GK 有声绘本PDF 70", "audio": "03、GK 音频-男声 70",
     "label": "GK", "order": 0},
    {"key": "G1", "pdf": "1、G1 有声PDF110本", "audio": "海尼曼G1男音版",
     "label": "G1", "order": 1},
    # {"key": "G2", "pdf": "2、G2 有声绘本PDF118", "audio": "3、G2 音频118",
    #  "label": "G2", "order": 2},
]

DUP = re.compile(r"\s*\(\d+\)$")

# ───────────────────────────── 文字清洗
IND_PATTERNS = [
    re.compile(r"\S*\.indd\s+[\d\-]*\s*[\d/]*\s*[\d:]*\s*(?:AM|PM)?", re.I),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{2}\b"),
]
KEEP = {"I", "A"}
TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


# 弯引号/长破折号等先归一化成 ASCII。
# 原来的写法是"词里含非 ASCII 就整词丢掉"，结果 sister’s / “Hello, / don’t 全被删，
# 影响 403 页 / 2017 个词，而且 word_boxes 用同样的 ASCII 假设，两层一起错 → 互相掩盖。
CHAR_MAP = {
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2026": "...", "\u00a0": " ", "\u2009": " ", "\u200a": " ", "\u200b": "",
    "\u00e9": "e", "\u00e8": "e", "\u00ea": "e", "\u00e0": "a", "\u00e7": "c",
    "\u00ee": "i", "\u00f4": "o", "\u00fb": "u",
}
_TRANS = str.maketrans(CHAR_MAP)

# 印前批注行：只删这一类行，不要整页清空。
# 事故：GK-045 p4/p5/p8 和 G1-080 p4 被整页清空，把真正文一起删了。
BAD_LINE = re.compile(
    r"interior art|art\s*page|adjust|overall:|delete|\.indd|^\s*\d+\s*$|^\s*isbn", re.I)


def normalize_chars(s: str) -> str:
    s = (s or "").translate(_TRANS)
    return "".join(ch for ch in s if 32 <= ord(ch) <= 126 or ch in "\n\t")


def strip_annotation_lines(raw: str) -> str:
    keep = [ln for ln in (raw or "").splitlines() if not BAD_LINE.search(ln)]
    return "\n".join(keep)


def clean_sentence(raw: str) -> str:
    t = normalize_chars(raw).replace("\r", " ").replace("\n", " ")
    for p in IND_PATTERNS:
        t = p.sub(" ", t)
    toks = []
    for tok in t.split():
        if not re.search(r"[A-Za-z]", tok):
            continue
        toks.append(tok)
    while len(toks) > 1 and toks[0] not in KEEP and toks[0].isupper():
        toks.pop(0)
    while len(toks) > 1 and toks[-1] not in KEEP and toks[-1].isupper():
        toks.pop()
    s = " ".join(toks)
    return re.sub(r"\s+([.,!?;:])", r"\1", s).strip()


# ───────────────────────────── 词框
def word_boxes(tp, ox, oy, crop_w, crop_h):
    """逐词包围盒；坐标从 MediaBox 平移到 CropBox 再归一化。"""
    out, cur = [], None
    n = tp.count_chars()
    for i in range(n):
        ch = tp.get_text_range(i, 1)
        x0, y0, x1, y1 = tp.get_charbox(i)
        if not ch or not ch.strip() or ch in "\r\n":
            if cur:
                out.append(cur)
            cur = None
            continue
        cur = [cur[0] + ch, min(cur[1], x0), min(cur[2], y0), max(cur[3], x1), max(cur[4], y1)] if cur \
            else [ch, x0, y0, x1, y1]
    if cur:
        out.append(cur)

    top_y = oy + crop_h
    words = []
    for w, x0, y0, x1, y1 in out:
        # 放宽：只要含至少一个字母就收。原来的 [A-Za-z][A-Za-z'’,.!?\-]* 会把
        # 以弯引号开头/结尾的 run（“Hello, / sister’s）整个拒掉，丢 27.9% 的 run。
        w = normalize_chars(w).strip()
        if not re.search(r"[A-Za-z]", w) or len(w) > 40:
            continue
        h = y1 - y0
        if h < 6 or h > 110:
            continue
        top = (top_y - y1) / crop_h
        bottom = (top_y - y0) / crop_h
        if top < 0.02 or bottom > 0.98:
            continue
        words.append({
            "w": w,
            "box": [round((x0 - ox) / crop_w, 4), round(top, 4),
                    round((x1 - ox) / crop_w, 4), round(bottom, 4)],
            "h": h,
            "hn": h / crop_h,
            # 每字符平均宽度（页面单位）：和字号成正比，且不受字形高低影响
            # （hn 是墨迹高度，'a'/'is' 这类无升降部的词天然就矮，按它筛会切碎正常句子）
            "cw": (x1 - x0) / max(len(w), 1),
        })
    return words


def drop_annotation_runs(runs, gap=1.6):
    """丢掉印前批注：它们的字号明显小于正文。

    不能用单字符的 cw 判断（'I' 天生窄）。做法：
      1. 只用 ≥3 字符的 run 估字号（cw = 宽度/字符数）
      2. 对这些 cw 做二聚类；只有两簇中心相差 ≥1.6 倍才认为是"正文 vs 批注"
      3. 保留高字号那一簇所在的**整行**（同行的短词跟着走）

    实测：GK-001（正常）cw≈13；GK-045/G1-080（批注页）批注 4–7、正文仍 13。
    """
    if len(runs) < 4:
        return runs
    solid = [r for r in runs if len(r["w"]) >= 3]
    if len(solid) < 3:
        return runs

    vals = [r["cw"] for r in solid]
    c_lo, c_hi = min(vals), max(vals)
    if c_hi / max(c_lo, 1e-6) < gap:
        return runs
    for _ in range(30):
        g_lo = [v for v in vals if abs(v - c_lo) <= abs(v - c_hi)]
        g_hi = [v for v in vals if abs(v - c_lo) > abs(v - c_hi)]
        if not g_lo or not g_hi:
            return runs
        c_lo, c_hi = sum(g_lo) / len(g_lo), sum(g_hi) / len(g_hi)
    if c_hi / max(c_lo, 1e-6) < gap:
        return runs

    # 高字号 run 所在的行走保留
    keep_lines = set()
    for ln in order_lines(runs):
        big = [r for r in ln if len(r["w"]) >= 3 and abs(r["cw"] - c_hi) < abs(r["cw"] - c_lo)]
        if big and len(big) * 2 >= len(ln):
            keep_lines.add(id(ln[0]))
    if not keep_lines:
        return runs
    out = []
    for ln in order_lines(runs):
        if id(ln[0]) in keep_lines:
            out.extend(ln)
    return out if len(out) >= 2 else runs


def order_lines(words):
    if not words:
        return []
    med_h = float(np.median([x.get("hn", 0.05) for x in words]))

    def cy(x):
        return (x["box"][1] + x["box"][3]) / 2

    lines, cur = [], []
    for w in sorted(words, key=cy):
        if cur and abs(cy(cur[-1]) - cy(w)) > med_h * 0.65:
            lines.append(cur)
            cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [sorted(line, key=lambda x: x["box"][0]) for line in lines]


_NORM = lambda s: re.sub(r"[^a-z]", "", s.lower())


def merge_to_tokens(runs, text):
    """字母偏移对齐：把文字 token 映射到视觉 run 上。

    不再要求 token 与 run 逐个相等（`little` vs `lit tle` 会被拆），
    而是把两边的字母流按顺序走一遍，记录每个 token 覆盖的字母区间。
    落在同一个 run 里的多个 token 合并成一个词（以视觉拼写为准）。
    """
    tokens = TOKEN.findall(text)
    if not tokens or not runs:
        return None
    A = [re.sub(r"[^a-z]", "", r["w"].lower()) for r in runs]
    B = [re.sub(r"[^a-z]", "", t.lower()) for t in tokens]
    if sum(map(len, A)) != sum(map(len, B)) or not sum(map(len, A)):
        return None

    spans, ri, pos = [], 0, 0
    for letters in B:
        need = len(letters)
        first, last = ri, ri
        while need > 0:
            if ri >= len(runs):
                return None
            take = min(need, len(A[ri]) - pos)
            last = ri
            need -= take
            pos += take
            if pos >= len(A[ri]):
                ri += 1
                pos = 0
        spans.append((first, last))

    # 相邻 token 若共用同一个 run，就合并（否则一个视觉词会有两个热区）
    groups = []          # [[first_run, last_run, [token idx...]]]
    for idx, (f, l) in enumerate(spans):
        if groups and f <= groups[-1][1]:
            groups[-1][1] = max(groups[-1][1], l)
            groups[-1][2].append(idx)
        else:
            groups.append([f, l, [idx]])

    merged = []
    for f, l, idxs in groups:
        grp = runs[f:l + 1]
        merged.append({
            "w": "".join(g["w"] for g in grp),
            "box": [min(g["box"][0] for g in grp), min(g["box"][1] for g in grp),
                    max(g["box"][2] for g in grp), max(g["box"][3] for g in grp)],
        })
    return merged


def canonical_from_runs(runs, keep_ratio=0.72):
    """已弃用：按 run 墨迹高度筛字号不可行。

    实测 `hn` 是字形墨迹高度，`a`/`is` 这类没有升降部的词天然就矮，
    与"正文 vs 印前批注"的字号差异混在一起，按高度切会把正常句子切碎
    （GK-001 p4 的 "I can see the apples." 被切成 "I the apples."）。
    真正的修复靠 C1（窗口上限）+ C2（引号归一化）+ C3（run 正则）+ 字母偏移，
    评审在 379 个无框页上实测可达 378 页出框。
    """
    raise NotImplementedError("已弃用")


def _task_placeholder():  # 占位，避免误改到下面的并行入口
    raise NotImplementedError


def select_sentence(words, text):
    """在页面文字里挑出与 text 对应的那一块。

    两套匹配：
      1. 贪心消费——每一步挑"是剩余目标的严格前缀"的那一行。与行的 y 顺序无关，
         能处理拟声词被排到句子前面这类情况（G1-001 p4 的 Cock-a-doodle-doo!）。
      2. 连续窗口——原来的做法，处理跨行的整句。
    取命中行数最多的那个。
    """
    lines = order_lines(words)
    if not lines:
        return [], None
    target = _NORM(text)
    if not target:
        return [], None

    best = None      # (i, j) 闭区间

    # 方案 1：贪心消费
    left = target
    used = []
    pool = list(range(len(lines)))
    while left and pool:
        pick, pick_len = None, 0
        for i in pool:
            ln = _NORM(" ".join(w["w"] for w in lines[i]))
            if ln and left.startswith(ln) and len(ln) > pick_len:
                pick, pick_len = i, len(ln)
        if pick is None:
            break
        left = left[pick_len:]
        used.append(pick)
        pool.remove(pick)
    if not left and used:
        if len(used) == 1:
            best = (used[0], used[0])
        else:
            best = (min(used), max(used)) if used == sorted(used) else None
            if best is None:
                chosen = [w for i in used for w in lines[i]]
                merged = merge_to_tokens(chosen, text)
                if merged is not None:
                    return merged, {"words": [w["w"] for w in merged],
                                    "boxes": [w["box"] for w in merged]}
                return chosen, None

    # 方案 2：连续窗口
    for i in range(len(lines)):
        acc = ""
        for j in range(i, len(lines)):
            acc += _NORM(" ".join(w["w"] for w in lines[j]))
            if acc == target:
                if best is None or (j - i) > (best[1] - best[0]):
                    best = (i, j)
                break
            if not target.startswith(acc):
                break

    if best is None:
        return [], None
    chosen = [w for line in lines[best[0]: best[1] + 1] for w in line]
    merged = merge_to_tokens(chosen, text)
    if merged is None:
        return chosen, None
    return merged, {"words": [w["w"] for w in merged], "boxes": [w["box"] for w in merged]}


def bbox(words):
    if not words:
        return None
    return [round(min(w["box"][0] for w in words), 4), round(min(w["box"][1] for w in words), 4),
            round(max(w["box"][2] for w in words), 4), round(max(w["box"][3] for w in words), 4)]


# ───────────────────────────── 正文页范围
def content_pages(reader):
    """正文页（0-based 索引列表）：跳过封面/版权/书名页，遇到剧本页就停。

    P4：批注行在 clean 之前就被逐行删掉，所以"只剩批注"的页现在会得到空文字，
    但**不再因此被整页丢弃**——它仍然是一张有图的正文页，只是无字。
    """
    n = len(reader.pages)
    if n <= 3:
        return []
    texts = [clean_sentence(strip_annotation_lines(p.extract_text() or "")) for p in reader.pages]
    last = n - 1
    for i in range(3, n):
        t = texts[i]
        if not t:
            continue
        if re.search(r"\bThe Play\b|\bCharacters\b", t) and i >= 4:
            last = i - 1
            break
        last = i
    return list(range(3, last + 1))


# ───────────────────────────── 音频
def transcode(src: Path, dst: Path) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS_TRANSCODE),
         "-Source", str(src), "-Dest", str(dst), "-Bitrate", str(AUDIO_BPS), "-Channels", "1"],
        capture_output=True, text=True, errors="ignore")
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 20000


def wav_segments(wav: Path):
    with wave.open(str(wav), "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    hop = sr // FPS
    m = len(x) // hop
    rms = np.sqrt(np.mean(x[: m * hop].reshape(m, hop) ** 2, axis=1))
    db = 20 * np.log10(np.maximum(rms, 1e-9))
    db = np.convolve(db, np.ones(5) / 5, mode="same")
    floor = float(np.percentile(db, 10))
    on = db > floor + 6
    runs, st = [], None
    for i, v in enumerate(on):
        if v and st is None:
            st = i
        elif not v and st is not None:
            runs.append((st / FPS, i / FPS))
            st = None
    if st is not None:
        runs.append((st / FPS, m / FPS))
    runs = [r for r in runs if r[1] - r[0] >= 0.15]
    merged = []
    for a, b in runs:
        if merged and a - merged[-1][1] < 1.0:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return [r for r in merged if r[1] - r[0] >= 0.30]


def pick_alignment(segs, n_pages):
    if len(segs) < n_pages:
        return None, "too_few_segments"
    if len(segs) == n_pages:
        return segs, "exact"
    best, best_key = None, None
    for start in range(0, len(segs) - n_pages + 1):
        win = segs[start:start + n_pages]
        d = np.array([b - a for a, b in win])
        score = float(d.std() / max(d.mean(), 1e-6))
        if best_key is None or score < best_key:
            best, best_key = win, score
    return best, "window"


# ───────────────────────────── 素材索引
# 三套素材的命名完全不一样，编号要按"先具体后通用"的顺序试：
#   GK 音频：GK1-A At the Market.wma
#   G1 音频：Book 1 Level A Waking up.wma
#   G2 音频：01 The Little Red Hen.mp3
NUM_PATTERNS = [
    re.compile(r"\bGK\s*(\d{1,3})", re.I),
    re.compile(r"\bG[123]\s*-\s*(\d{1,3})", re.I),   # G2 有本叫 "C G2-08 Down the river"
    re.compile(r"\bBook\s*(\d{1,3})", re.I),
    re.compile(r"^(\d{1,3})"),
]


def num_from(stem: str):
    for p in NUM_PATTERNS:
        m = p.search(stem)
        if m:
            return int(m.group(1))
    return None


def index_series(series):
    pdf_dir = ROOT / series["pdf"]
    aud_dir = ROOT / series["audio"]
    pdfs, auds = {}, {}
    seen_isbn = {}
    dropped = []
    for p in sorted(pdf_dir.glob("*.pdf")):
        if DUP.search(p.stem):
            continue
        n = num_from(p.stem)
        if n is None:
            continue
        # 同一本书可能被编号两次（G2 的 005 与 008 就是同一个 ISBN）
        try:
            head = PdfReader(str(p)).pages[0].extract_text() or ""
            m = re.search(r"ISBN-13[:\s]*([\d\-]{10,20})", head)
            isbn = re.sub(r"[^\d]", "", m.group(1)) if m else ""
        except Exception:  # noqa: BLE001
            isbn = ""
        if isbn and isbn in seen_isbn:
            dropped.append((p.name, seen_isbn[isbn]))
            continue
        if isbn:
            seen_isbn[isbn] = p.name
        pdfs[n] = p
    for p in aud_dir.iterdir():
        if p.suffix.lower() not in (".wma", ".mp3") or DUP.search(p.stem):
            continue
        n = num_from(p.stem)
        if n is not None:
            auds[n] = p
    if dropped:
        print(f'  ⚠ {series["key"]} 去掉重复书 {len(dropped)}: {dropped[:3]}', flush=True)
    return pdfs, auds


def level_of(audio_name: str, fallback: str = "") -> str:
    m = re.search(r"Level\s+([A-Z])\b", audio_name, re.I)      # G1：Book 1 Level A ...
    if m:
        return m.group(1).upper()
    m = re.search(r"^GK\d+-([A-Z])\b", audio_name, re.I)       # GK：GK1-A ...
    if m:
        return m.group(1).upper()
    return fallback


# ───────────────────────────── 单本
def build_book(series, no, pdf_path, aud_path, tmpdir):
    sid = f'{series["key"]}-{no:03d}'
    reader = PdfReader(str(pdf_path))
    doc = pdfium.PdfDocument(str(pdf_path))
    idxs = content_pages(reader)
    if not idxs:
        raise RuntimeError("找不到正文页")

    bdir = LIB / "books" / series["key"] / f"{no:03d}"
    bdir.mkdir(parents=True, exist_ok=True)

    pages = []
    for idx in idxs:
        page = doc[idx]
        cx0, cy0, cx1, cy1 = page.get_cropbox()
        pw, ph = cx1 - cx0, cy1 - cy0
        scale = LONG_EDGE / max(pw, ph)
        img = page.render(scale=scale).to_pil().convert("RGB")
        rel = f"books/{series['key']}/{no:03d}/p{idx + 1:02d}.jpg"
        img.save(LIB / rel, quality=84, optimize=True, progressive=True)

        text = clean_sentence(strip_annotation_lines(reader.pages[idx].extract_text() or ""))
        runs_all = word_boxes(page.get_textpage(), cx0, cy0, pw, ph)
        runs = drop_annotation_runs(runs_all)
        if len(runs) != len(runs_all):
            # 这一页有印前批注被过滤掉 → 文字层不可信，以视觉层为准
            text = " ".join(r["w"] for r in runs)
        chosen, per_word = select_sentence(runs, text)
        # 词框合并后（"lit tle" → "little"）词数与 text 不一致，会让下游对齐对不上；
        # 以视觉层的拼写为准重写 text，保证 text / wordBoxes / wordTimes 三者同索引。
        if per_word and len(per_word["words"]):
            text = " ".join(per_word["words"])
        pages.append({"n": idx + 1, "image": rel, "w": img.width, "h": img.height,
                      "text": text, "textBox": bbox(chosen), "wordBoxes": per_word, "audio": None})

    # 封面（第 2 页通常是封面右半，需按书判断；先用第 1 页右半）
    c = doc[0]   # 第 1 页是封面跨页；第 2 页是版权页，裁右半会是白纸
    cw_, chh = c.get_cropbox()[2] - c.get_cropbox()[0], c.get_cropbox()[3] - c.get_cropbox()[1]
    cover_img = c.render(scale=900 / max(cw_, chh)).to_pil().convert("RGB")
    front = cover_img.crop((cover_img.width // 2, 0, cover_img.width, cover_img.height))
    front.thumbnail((360, 360), Image.LANCZOS)
    (LIB / "covers" / series["key"]).mkdir(parents=True, exist_ok=True)
    rel_cover = f"covers/{series['key']}/{no:03d}.jpg"
    front.save(LIB / rel_cover, quality=88, optimize=True)
    doc.close()

    # 音频
    rel_audio = f"audio/{series['key']}/{no:03d}.m4a"
    dur = None
    segs = []
    if aud_path is not None:
        if not transcode(aud_path, LIB / rel_audio):
            raise RuntimeError("转码失败")
        dur = round(float(MP4(str(LIB / rel_audio)).info.length), 2)
        wav = tmpdir / f"{series['key']}{no:03d}.wav"
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                        str(PS_TRANSCODE), "-Source", str(aud_path), "-Dest", str(wav), "-AsWav",
                        "-SampleRate", "16000", "-Channels", "1"],
                       capture_output=True, text=True, errors="ignore")
        if wav.exists():
            segs = wav_segments(wav)
            wav.unlink(missing_ok=True)

    win, how = pick_alignment(segs, len(pages))
    aligned = win is not None
    if aligned:
        for p, (a, b) in zip(pages, win):
            p["audio"] = [round(a, 2), round(b, 2)]
    elif dur:
        span = dur / max(len(pages), 1)
        for i, p in enumerate(pages):
            p["audio"] = [round(i * span, 2), round((i + 1) * span, 2)]

    title = re.sub(r"^\d{1,3}\s*", "", pdf_path.stem).replace("&#39;", "'").strip()
    book = {
        "id": sid, "series": series["key"], "no": no, "title": title,
        "level": level_of(aud_path.stem if aud_path else "", series["key"]) or series["key"],
        "cover": rel_cover, "audio": (rel_audio if aud_path else None),
        "duration": dur, "pageCount": len(pages), "aligned": aligned, "alignMethod": how,
        "hasAudio": aud_path is not None,
        "segments": [[round(a, 2), round(b, 2)] for a, b in segs],
        "pages": pages,
    }
    jf = LIB / "books" / series["key"] / f"{no:03d}.json"
    jf.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return {k: book[k] for k in ("id", "series", "no", "title", "level", "cover",
                                 "audio", "duration", "pageCount", "aligned",
                                 "alignMethod", "hasAudio")}




# ───────────────────────────── 并行入口
def _task(args):
    """子进程里跑一本。args 必须可 pickle。"""
    series_key, no, pdf_str, aud_str, tmp_str = args
    series = next(s for s in SERIES if s["key"] == series_key)
    try:
        meta = build_book(series, no, Path(pdf_str),
                          Path(aud_str) if aud_str else None, Path(tmp_str))
        return True, f'{meta["no"]:03d} {meta["title"][:24]:26} pages={meta["pageCount"]} {meta["alignMethod"]}', meta
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="")
    ap.add_argument("--limit", type=int, default=0, help="每套只跑前 N 本（试跑用）")
    ap.add_argument("--jobs", type=int, default=0, help="并发进程数，默认 CPU-1")
    args = ap.parse_args()

    jobs = args.jobs or default_jobs()
    LIB.mkdir(exist_ok=True)
    tmpdir = Path(tempfile.mkdtemp(prefix="gk-audio-"))

    # 1) 先把所有任务列出来（索引阶段是 I/O，串行即可）
    tasks, skipped = [], []
    for series in SERIES:
        if args.series and series["key"] != args.series:
            continue
        pdfs, auds = index_series(series)
        nums = sorted(pdfs)
        if args.limit:
            nums = nums[:args.limit]
        for no in nums:
            tasks.append((f'{series["key"]}-{no:03d}',
                          (series["key"], no, str(pdfs[no]),
                           str(auds[no]) if no in auds else None, str(tmpdir))))
            if no not in auds:
                skipped.append(f'{series["key"]}-{no:03d}')

    print(f"共 {len(tasks)} 本，{jobs} 个进程并发"
          + (f"；无音频 {len(skipped)} 本: {skipped}" if skipped else ""), flush=True)

    # 2) 并发加工
    results = run_tasks(tasks, _task, jobs)

    # 3) 汇总 manifest
    manifest = [payload for _, ok, _, payload in results if ok and payload]
    _order = {s["key"]: i for i, s in enumerate(SERIES)}
    manifest.sort(key=lambda b: (_order.get(b["series"], 99), b["no"]))
    problems = [(key, info) for key, ok, info, _ in results if not ok]
    manifest_path = LIB / "manifest.json"
    if manifest_path.exists() and args.limit:
        print("（--limit 试跑，不覆盖已有 manifest）")
    else:
        manifest_path.write_text(
            json.dumps({"books": manifest,
                        "series": [{"key": s["key"], "label": s["label"]}
                                   for s in SERIES if not args.series or s["key"] == args.series]},
                       ensure_ascii=False, indent=1), encoding="utf-8")

    pages = sum(b["pageCount"] for b in manifest)
    size = sum(f.stat().st_size for f in LIB.rglob("*") if f.is_file())
    print(f"\n完成 {len(manifest)} 本 / {pages} 页，library {size / 1e6:.1f} MB")
    if problems:
        print(f"失败 {len(problems)}:")
        for k, v in problems[:20]:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
