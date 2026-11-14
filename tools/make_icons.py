# -*- coding: utf-8 -*-
"""生成 App 图标与启动图（@capacitor/assets 的输入）。

   python tools/make_icons.py
   → app/resources/icon.png     1024×1024（不透明，iOS 会自己切圆角）
   → app/resources/splash.png   2732×2732
   → app/resources/splash-dark.png（同一张，深色模式也用浅色底，避免绘本 App 变黑）
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"E:\apple app")
OUT = ROOT / "app" / "resources"
OUT.mkdir(parents=True, exist_ok=True)

ACCENT = (232, 118, 86)
PAPER = (253, 248, 242)
WHITE = (255, 255, 255)
INK = (58, 46, 40)

SS = 4                      # 超采样
S = 1024


def draw_icon(size=S):
    n = size * SS
    img = Image.new("RGB", (n, n), ACCENT)
    d = ImageDraw.Draw(img)

    # 柔和的顶部高光，让纯色不呆板
    for i in range(int(n * 0.55)):
        a = int(28 * (1 - i / (n * 0.55)))
        d.line([(0, i), (n, i)], fill=(ACCENT[0] + a, ACCENT[1] + a // 2, ACCENT[2] + a // 2))

    # 摊开的书：左右两页，中间书脊
    cx, cy = n / 2, n * 0.47
    w, h = n * 0.62, n * 0.40
    left = [cx - w / 2, cy - h / 2, cx - n * 0.012, cy + h / 2]
    right = [cx + n * 0.012, cy - h / 2, cx + w / 2, cy + h / 2]
    d.rounded_rectangle(left, radius=int(n * 0.035), fill=WHITE)
    d.rounded_rectangle(right, radius=int(n * 0.035), fill=WHITE)

    # 书页上的“文字行”
    for k in range(3):
        yy = cy - h * 0.22 + k * h * 0.22
        d.rounded_rectangle([cx - w * 0.38, yy, cx - w * 0.14, yy + n * 0.016],
                            radius=int(n * 0.008), fill=(226, 214, 204))
        d.rounded_rectangle([cx + w * 0.14, yy, cx + w * 0.38, yy + n * 0.016],
                            radius=int(n * 0.008), fill=(226, 214, 204))

    # 书脊
    d.rounded_rectangle([cx - n * 0.012, cy - h / 2, cx + n * 0.012, cy + h / 2],
                        radius=int(n * 0.01), fill=ACCENT)

    # 底部 GK
    f = None
    for name in ("segoeuib.ttf", "arialbd.ttf"):
        try:
            f = ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / name), int(n * 0.17))
            break
        except Exception:  # noqa: BLE001
            continue
    text = "GK"
    tw = d.textlength(text, font=f)
    d.text((cx - tw / 2, cy + h * 0.72), text, font=f, fill=WHITE)

    return img.resize((size, size), Image.LANCZOS)


def draw_splash(size=2732):
    n = size * 2
    img = Image.new("RGB", (n, n), PAPER)
    icon = draw_icon(int(n * 0.26))
    off = (n - icon.width) // 2
    img.paste(icon, (off, off - int(n * 0.03)))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(str(Path(r"C:\Windows\Fonts") / "msyhbd.ttc"), int(n * 0.045))
    text = "小书虫 GK"
    tw = d.textlength(text, font=f)
    d.text(((n - tw) / 2, off + icon.height + int(n * 0.045)), text, font=f, fill=INK)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    icon = draw_icon()
    icon.save(OUT / "icon.png")
    splash = draw_splash()
    splash.save(OUT / "splash.png")
    splash.save(OUT / "splash-dark.png")
    print("saved:", [p.name for p in OUT.iterdir()])
