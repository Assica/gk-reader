# -*- coding: utf-8 -*-
"""WKWebView 运行时风险自查：直接从 @capacitor/ios 源码里找答案，不靠印象。

    python tools/audit_wkwebview.py
"""
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\apple app")
IOS = ROOT / "app" / "node_modules" / "@capacitor" / "ios"
WEB = ROOT / "web"


def find(pattern, glob="*.swift", limit=6):
    rx = re.compile(pattern)
    hits = []
    for p in IOS.rglob(glob):
        try:
            t = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(t.splitlines(), 1):
            if rx.search(line):
                hits.append((p.name, i, line.strip()))
                if len(hits) >= limit:
                    return hits
    return hits


def show(title, pattern, glob="*.swift", limit=6):
    print(f"\n--- {title} ---")
    hits = find(pattern, glob, limit)
    if not hits:
        print("    （没找到，需要人工确认）")
    for name, i, line in hits:
        print(f"    {name}:{i}  {line[:150]}")


print("=== 1. 资源加载 scheme ===")
show("URL scheme / host", r"capacitor://|CAPBridgeViewController|serverURL")
show("本地文件服务", r"localURL|WebViewAssetHandler|assetHandler", limit=8)

print("\n=== 2. 媒体自动播放策略 ===")
show("mediaTypesRequiringUserActionForPlayback", r"mediaTypesRequiringUserActionForPlayback", limit=8)
show("allowsInlineMediaPlayback", r"allowsInlineMediaPlayback", limit=6)
show("AVAudioSession（原生侧）", r"AVAudioSession", glob="*.swift", limit=8)

print("\n=== 3. 配置项实际生效点 ===")
cfg = (ROOT / "app" / "capacitor.config.json").read_text(encoding="utf-8")
print(f"    capacitor.config.json: {cfg.strip()[:300]}")

print("\n=== 4. 前端 viewport / safe-area ===")
html = (WEB / "index.html").read_text(encoding="utf-8")
m = re.search(r'<meta[^>]+viewport[^>]*>', html, re.I)
print(f"    viewport meta: {m.group(0) if m else '❌ 没有 viewport meta'}")
css = (WEB / "style.css").read_text(encoding="utf-8")
print(f"    env(safe-area-inset-*): {'✅ 有' if 'safe-area-inset' in css else '❌ 没有'}")
print(f"    viewport-fit=cover: {'✅ 有' if 'viewport-fit=cover' in html else '❌ 没有'}")

print("\n=== 5. 音频 API 用法（iOS 兼容性） ===")
js = (WEB / "app.js").read_text(encoding="utf-8")
for api, why in [
    ("createObjectURL", "Blob 播放"),
    ("revokeObjectURL", "内存释放"),
    ("preservesPitch", "变速不变调"),
    ("playbackRate", "语速"),
    ("requestAnimationFrame", "播到 stopAt 轮询"),
    ("currentTime", "seek"),
    ("localStorage", "进度持久化"),
]:
    n = js.count(api)
    print(f"    {api:24} 出现 {n} 次    {why}")
print(f"    revoke 次数 < createObjectURL 次数? {'❌ 有泄漏风险' if js.count('revokeObjectURL') < js.count('createObjectURL') else '✅ 配对'}")

print("\n=== 6. rAF 在后台是否可靠 ===")
m = re.search(r"requestAnimationFrame\(([^)]*)\)", js)
print(f"    第一次 rAF 调用: {m.group(0) if m else '无'}")
print("    注意：iOS 切后台/锁屏时 rAF 停摆 → 若只靠 rAF 判断 stopAt，音频会继续播")
print(f"    有没有 visibilitychange 兜底: {'✅ 有' if 'visibilitychange' in js else '❌ 没有'}")

print("\n=== 7. 音频会话（原生侧是否真的被注入） ===")
patch = (ROOT / "app" / "scripts" / "patch-ios.mjs").read_text(encoding="utf-8")
print(f"    patch-ios.mjs 注入 AVAudioSession: {'✅' if 'AVAudioSession' in patch else '❌'}")
print(f"    注入点: {'didFinishLaunching 函数体' if 'didFinishLaunching' in patch else '未知'}")
