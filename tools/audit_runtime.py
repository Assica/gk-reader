# -*- coding: utf-8 -*-
"""WKWebView 运行时完整审查：把每条结论落到源码行/数据上。

    python tools/audit_runtime.py
"""
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\apple app")
IOS = ROOT / "app" / "node_modules" / "@capacitor" / "ios"
JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "style.css").read_text(encoding="utf-8")
CFG = json.loads((ROOT / "app" / "capacitor.config.json").read_text(encoding="utf-8"))


def grep_cap(pattern, limit=4):
    rx = re.compile(pattern)
    out = []
    for p in IOS.rglob("*.swift"):
        try:
            for i, ln in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if rx.search(ln):
                    out.append(f"{p.name}:{i}  {ln.strip()[:120]}")
                    if len(out) >= limit:
                        return out
        except Exception:
            continue
    return out


print("=== 1. 资源加载 scheme ===")
for line in grep_cap(r"caps?acitor://|localURL|serverURL|appOrigin|startPath"):
    print("   ", line)

print("\n=== 2. 媒体策略 ===")
for line in grep_cap(r"mediaTypesRequiringUserActionForPlayback|allowsInlineMediaPlayback|allowsAirPlay"):
    print("   ", line)

print("\n=== 3. WKWebView 其它配置 ===")
for line in grep_cap(r"scrollEnabled|contentInset|bounces|decelerationRate|keyboardDisplayRequiresUserAction"):
    print("   ", line)

print("\n=== 4. 播放停止逻辑（app.js）===")
for m in re.finditer(r"audio\.addEventListener\('(timeupdate|loadedmetadata|ended)',\s*(\w+)", JS):
    print(f"    addEventListener('{m.group(1)}', {m.group(2)})")
print("   removeEventListener 次数:", JS.count("removeEventListener"))
print("   playRange 里 finish() 调用次数:", JS.count("finish()"))

# 是否存在监听器叠加：每次 playRange 都 add，但只有 finish 里 remove
play_range = JS[JS.index("function playRange"):JS.index("document.addEventListener('visibilitychange'")]
print("   playRange 内 addEventListener:", play_range.count("addEventListener"))
print("   playRange 内 removeEventListener:", play_range.count("removeEventListener"))

print("\n=== 5. Blob 生命周期 ===")
print("   createObjectURL:", JS.count("createObjectURL"), "  revokeObjectURL:", JS.count("revokeObjectURL"))
for m in re.finditer(r".{60}revokeObjectURL.{40}", JS):
    print("   ", m.group(0).replace("\n", " ").strip()[:110])

print("\n=== 6. 语速 API ===")
for name in ("preservesPitch", "mozPreservesPitch", "webkitPreservesPitch", "playbackRate"):
    print(f"   {name:22}", "✅ 有" if name in JS else "❌ 无")

print("\n=== 7. 首页加载与首屏 ===")
print("   index.html 里有 loading 占位:", "✅" if re.search(r"加载|loading|spinner", HTML, re.I) else "❌ 无")
man_bytes = (ROOT / "library" / "manifest.json").stat().st_size
print(f"   manifest.json: {man_bytes/1024:.1f} KB")
covers = list((ROOT / "library" / "covers").rglob("*.jpg"))
avg = sum(c.stat().st_size for c in covers) / max(len(covers), 1) / 1024
print(f"   封面 {len(covers)} 张, 平均 {avg:.1f} KB → 首屏若全加载约 {avg*len(covers)/1024:.1f} MB")
print("   封面是否 lazy:", "✅" if 'loading="lazy"' in JS else "❌ 无")

print("\n=== 8. 页图尺寸与翻页 ===")
pages = list((ROOT / "library" / "books").rglob("p*.jpg"))
pavg = sum(p.stat().st_size for p in pages) / max(len(pages), 1) / 1024
print(f"   页图 {len(pages)} 张, 平均 {pavg:.1f} KB")

print("\n=== 9. capacitor.config 实际取值 ===")
print("   ios:", json.dumps(CFG.get("ios", {}), ensure_ascii=False))

print("\n=== 10. 音频文件大小（Blob 内存） ===")
auds = list((ROOT / "library" / "audio").rglob("*.m4a"))
aavg = sum(a.stat().st_size for a in auds) / max(len(auds), 1) / 1024
print(f"   音频 {len(auds)} 条, 平均 {aavg:.0f} KB, 单条最大 {max(a.stat().st_size for a in auds)/1024:.0f} KB")

print("\n=== 11. 词时间戳精度（seek 目标） ===")
b = json.loads((ROOT / "library" / "books" / "GK" / "001.json").read_text(encoding="utf-8"))
p = b["pages"][0]
print("   示例页 audio:", p.get("audio"), " wordTimes[0]:", (p.get("wordTimes") or [None])[0])
print("   词段最短(全库抽样):")
mins = []
for f in list((ROOT / "library" / "books").rglob("*.json"))[:60]:
    d = json.loads(f.read_text(encoding="utf-8"))
    for pg in d["pages"]:
        for t in (pg.get("wordTimes") or []):
            if t:
                mins.append(t[1] - t[0])
mins.sort()
if mins:
    print(f"      n={len(mins)} 最短 {mins[0]*1000:.0f}ms  p10 {mins[len(mins)//10]*1000:.0f}ms")
"""
"""
