# -*- coding: utf-8 -*-
"""library/ 体检：结构、对齐置信度、数据完整性。

    python tools/qa_library.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
man = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))
books = man["books"]

print(f"系列: {[s['key'] for s in man.get('series', [])]}")
print(f"书籍: {len(books)} 本")
by_series = Counter(b["series"] for b in books)
print(f"  分布: {dict(by_series)}")

conf = {"high": [], "medium": [], "low": [], "no_audio": []}
missing_files, empty_text, bad_audio, bad_pages = [], [], [], []
pages_total = 0
words_total = 0
with_words = 0

for b in books:
    jf = LIB / "books" / b["series"] / f'{b["no"]:03d}.json'
    if not jf.exists():
        missing_files.append(str(jf))
        continue
    book = json.loads(jf.read_text(encoding="utf-8"))

    if not book.get("hasAudio"):
        conf["no_audio"].append(b["id"])
    else:
        segs = len(book.get("segments") or [])
        if book.get("alignMethod") == "exact" or segs <= book["pageCount"] + 1:
            conf["high"].append(b["id"])
        elif segs <= book["pageCount"] + 6:
            conf["medium"].append(b["id"])
        else:
            conf["low"].append(b["id"])

    for rel in [b["cover"]] + ([book["audio"]] if book.get("audio") else []):
        if rel and not (LIB / rel).exists():
            missing_files.append(rel)

    if book["pageCount"] < 4:
        bad_pages.append((b["id"], book["pageCount"]))

    for p in book["pages"]:
        pages_total += 1
        if not (LIB / p["image"]).exists():
            missing_files.append(p["image"])
        if not (p.get("text") or "").strip():
            empty_text.append((b["id"], p["n"]))
        if p.get("wordTimes"):
            with_words += 1
            words_total += len(p["wordTimes"])
        if p.get("audio"):
            a, e = p["audio"]
            if not (0 <= a < e) or (book.get("duration") and e > book["duration"] + 0.1):
                bad_audio.append((b["id"], p["n"], p["audio"]))

print(f"\n正文页: {pages_total}   有逐词时间戳: {with_words} ({with_words/max(pages_total,1):.1%})"
      f"   词次: {words_total}")
print(f"封面: {len(list((LIB / 'covers').rglob('*.jpg')))}   "
      f"音频: {len(list((LIB / 'audio').rglob('*.m4a')))}   "
      f"book.json: {len(list((LIB / 'books').rglob('*.json')))}")
print(f"\n对齐置信度: 高 {len(conf['high'])} / 中 {len(conf['medium'])} / 低 {len(conf['low'])}"
      f" / 无音频 {len(conf['no_audio'])}")
if conf["low"]:
    print(f"  低置信（切句可能错位）: {conf['low'][:12]}")
if conf["no_audio"]:
    print(f"  无音频（只看图）: {conf['no_audio'][:12]}")
print(f"\n空文字页: {len(empty_text)} {empty_text[:6]}")
print(f"异常的页音频区间: {len(bad_audio)} {bad_audio[:4]}")
print(f"缺文件: {len(missing_files)} {missing_files[:4]}")
print(f"页数过少的书: {len(bad_pages)} {bad_pages[:4]}")

# 封面检查：体积只是弱信号（9 KB 的纯灰图能过 6 KB 线），内容必须看像素。
# 曾经因为裁了第 2 页（版权页）导致 180 张全是白纸，这条用来兜住同类事故。
covers = list((LIB / "covers").rglob("*.jpg"))
if covers:
    avg_c = sum(c.stat().st_size for c in covers) / len(covers) / 1024
    tiny = [(c.name, round(c.stat().st_size / 1024, 1)) for c in covers if c.stat().st_size < 6000]
    print(f"\n封面: {len(covers)} 张，平均 {avg_c:.1f} KB")
    if tiny:
        print(f"  ⚠ 体积可疑（<6 KB）: {len(tiny)} 张 {tiny[:5]}")
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from audit_content import img_stat, SD_MIN_COVER, WHITE_MAX  # noqa: E402
        blank = []
        for c in covers:
            _, sd, white = img_stat(c)
            if sd < SD_MIN_COVER or white > WHITE_MAX:
                blank.append((c.name, round(sd, 1), round(white, 2)))
        if blank:
            print(f"  ⚠ 真的空白封面（像素标准差 <{SD_MIN_COVER}）: {len(blank)} 张 {blank[:5]}")
        else:
            print("  ✅ 无空白封面（体积 + 像素双重检查）")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ 像素检查不可用: {e}")
    print("  页图/音频内容级全量检查: python tools/audit_content.py")

size = sum(f.stat().st_size for f in LIB.rglob("*") if f.is_file())
print(f"\nlibrary 体积: {size/1e6:.1f} MB")
