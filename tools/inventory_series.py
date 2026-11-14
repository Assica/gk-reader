# -*- coding: utf-8 -*-
"""盘点三套素材：去重、PDF↔音频配对、正文页范围、缺失项、预估体积。"""
import json
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"E:\apple app")

DUP = re.compile(r"\s*\(\d+\)$")
IND = re.compile(r"\S*\.indd\s+[\d\-]*\s*[\d/]*\s*[\d:]*\s*(?:AM|PM)?", re.I)


def dedupe(files):
    """同名的 (1)(2) 副本只留一份：优先无后缀那个，否则取体积最大的。"""
    groups = {}
    for p in files:
        stem = DUP.sub("", p.stem).strip()
        groups.setdefault(stem.lower(), []).append(p)
    out = {}
    for key, ps in groups.items():
        ps.sort(key=lambda x: (bool(DUP.search(x.stem)), -x.stat().st_size))
        out[key] = ps[0]
    return out


def clean(t):
    return re.sub(r"\s+", " ", IND.sub(" ", t or "")).strip()


def content_range(pdf_path):
    """正文页范围：从第 4 页起，到 'The Play'/剧本页之前。

    返回 (start, end) 1-based，闭区间。找不到剧本页就一直到倒数第二页。
    """
    r = PdfReader(str(pdf_path))
    n = len(r.pages)
    texts = [clean(p.extract_text()) for p in r.pages]
    end = n - 1 if n >= 6 else n          # 最后一页通常是收尾，仍算正文
    for i in range(3, n):
        t = texts[i]
        if not t:
            continue
        if re.search(r"The Play\b|Characters\b", t) and i >= 4:
            end = i                            # 0-based i → 前一页是正文末页
            break
        end = i + 1
    start = 4
    if end < start:
        end = start
    return start, end, [t for t in texts[start - 1:end]]


SERIES = [
    ("GK", "02、GK 有声绘本PDF 70", "03、GK 音频-男声 70"),
    ("G1", "1、G1 有声PDF110本", "海尼曼G1男音版"),
    ("G2", "2、G2 有声绘本PDF118", "3、G2 音频118"),
]


def num_of(stem, widths=(1, 2, 3)):
    m = re.search(r"(\d{1,3})", stem)
    return int(m.group(1)) if m else None


def main():
    total_pages = 0
    report = {}
    for key, pdf_dir, aud_dir in SERIES:
        pdfs = dedupe(list((ROOT / pdf_dir).glob("*.pdf")))
        auds = dedupe([p for p in (ROOT / aud_dir).iterdir()
                       if p.suffix.lower() in (".wma", ".mp3")])
        pdf_by_num = {}
        for stem, p in pdfs.items():
            n = num_of(p.name)
            if n is not None:
                pdf_by_num.setdefault(n, p)
        aud_by_num = {}
        for stem, p in auds.items():
            n = num_of(p.stem)
            if n is not None:
                aud_by_num.setdefault(n, p)

        only_pdf = sorted(set(pdf_by_num) - set(aud_by_num))
        only_aud = sorted(set(aud_by_num) - set(pdf_by_num))
        pair = sorted(set(pdf_by_num) & set(aud_by_num))

        # 正文页统计（抽全部，量不大）
        pages_dist = {}
        bad = []
        for n in pair:
            try:
                s, e, texts = content_range(pdf_by_num[n])
                k = e - s + 1
                pages_dist[k] = pages_dist.get(k, 0) + 1
                total_pages += k
                if any(len(t) < 3 for t in texts):
                    bad.append((n, pdf_by_num[n].name, "有空白正文页"))
            except Exception as ex:  # noqa: BLE001
                bad.append((n, pdf_by_num[n].name, f"解析失败 {ex}"))

        report[key] = {
            "pdf_unique": len(pdfs), "audio_unique": len(auds),
            "paired": len(pair), "pdf_only": only_pdf, "audio_only": only_aud,
            "content_pages_dist": dict(sorted(pages_dist.items())),
            "total_content_pages": sum(k * v for k, v in pages_dist.items()),
            "issues": bad[:10],
        }
        print(f"\n===== {key} =====")
        print(f"  PDF 去重后 {len(pdfs)} 本 / 音频去重后 {len(auds)} 条 / 按编号配上 {len(pair)} 对")
        if only_pdf:
            print(f"  ⚠ 有 PDF 没音频 {len(only_pdf)} 本: {only_pdf[:10]}")
        if only_aud:
            print(f"  ⚠ 有音频没 PDF {len(only_aud)} 条: {only_aud[:10]}")
        print(f"  正文页数分布: {report[key]['content_pages_dist']}")
        print(f"  正文总页数: {report[key]['total_content_pages']}")
        if bad:
            print(f"  ⚠ 数据异常 {len(bad)} 条: {bad[:5]}")
        ex = pdf_by_num[pair[0]].name if pair else "-"
        print(f"  示例: {ex}")

    print(f"\n正文总页数（三套合计）: {total_pages}")
    print(f"估计图片 {total_pages * 0.16:.0f} MB（1600px JPEG ~160KB/页）"
          f" + 音频待测")
    (ROOT / ".work" / "series-inventory.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
