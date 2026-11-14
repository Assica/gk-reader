# -*- coding: utf-8 -*-
"""只重刷封面图，不重建整库（几秒钟）。

封面 = 第 1 页（跨页封面）的**右半**。
之前误用了第 2 页（版权页），裁出来是白纸，180 张平均只有 1 KB。

    python tools/rebuild_covers.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pypdfium2 as pdfium  # noqa: E402
from PIL import Image  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"E:\apple app")
LIB = ROOT / "library"

# 与 build_library.py 里的 SERIES 保持一致
SERIES = {
    "GK": "02、GK 有声绘本PDF 70",
    "G1": "1、G1 有声PDF110本",
}


def make_cover(pdf_path: Path, out_path: Path) -> int:
    doc = pdfium.PdfDocument(str(pdf_path))
    page = doc[0]                     # 第 1 页才是封面跨页
    cx0, cy0, cx1, cy1 = page.get_cropbox()
    pw, ph = cx1 - cx0, cy1 - cy0
    img = page.render(scale=900 / max(pw, ph)).to_pil().convert("RGB")
    doc.close()

    front = img.crop((img.width // 2, 0, img.width, img.height))   # 右半 = 正面封面
    front.thumbnail((360, 360), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    front.save(out_path, quality=88, optimize=True)
    return out_path.stat().st_size


def main():
    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    done, bad, sizes = 0, [], []
    for i, b in enumerate(books, 1):
        folder = SERIES.get(b["series"])
        if not folder:
            bad.append((b["id"], "未知系列"))
            continue
        # 按编号找 PDF（文件名前缀是编号，可能有 001 / 01 / GK1 等格式）
        cands = [p for p in (ROOT / folder).glob("*.pdf")
                 if p.stem.split()[0].endswith(str(b["no"]).zfill(3))
                 or p.stem.split()[0].endswith(str(b["no"]))]
        cands = [p for p in cands if "(" not in p.stem]
        if not cands:
            bad.append((b["id"], "找不到 PDF"))
            continue
        try:
            size = make_cover(cands[0], LIB / b["cover"])
            sizes.append(size)
            done += 1
        except Exception as e:  # noqa: BLE001
            bad.append((b["id"], f"{type(e).__name__}: {e}"))
        if i % 40 == 0:
            print(f"  {i}/{len(books)} ...", flush=True)

    print(f"\n重刷 {done} 张")
    if sizes:
        print(f"  平均 {sum(sizes)/len(sizes)/1024:.1f} KB   最小 {min(sizes)/1024:.1f} KB   "
              f"最大 {max(sizes)/1024:.1f} KB")
        tiny = sum(1 for s in sizes if s < 6000)
        print(f"  仍小于 6 KB 的: {tiny} 张")
    if bad:
        print(f"  失败 {len(bad)}: {bad[:8]}")


if __name__ == "__main__":
    main()
