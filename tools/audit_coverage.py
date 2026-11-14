# -*- coding: utf-8 -*-
"""按功能分类复盘测试覆盖，找出"结构合法但内容错误"的盲区。"""
import io
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"E:\apple app")

src = io.open(ROOT / "tools" / "webtest.mjs", encoding="utf-8").read()

# 抽出每个用例块，统计其断言
cases = re.split(r"\n  \['(T\d+)', '([^']+)',", src)
blocks = []
for i in range(1, len(cases), 3):
    tid, title, body = cases[i], cases[i + 1], cases[i + 2]
    ids = re.findall(r"(?:eq|near|truthy|record)\('(T[\d.]+[a-z]?)'", body)
    blocks.append((tid, title, ids))

print("=== 现有用例与断言数 ===")
total = 0
for tid, title, ids in blocks:
    total += len(ids)
    print(f"  {tid:4} {len(ids):2d} 条  {title}")
print(f"  合计静态断言 {total}（动态循环会展开更多）")

# 断言"动词"分布：看每类到底在验证什么
verbs = defaultdict(int)
for _, _, ids in blocks:
    for i in ids:
        verbs[i.split(".")[0]] += 1

print("\n=== 按功能分类的覆盖矩阵 ===")
matrix = [
    ("书架渲染", "卡数量、tab 计数", "✅ 有", "188 张卡片、G1 110 张"),
    ("书架封面", "图片是否加载出来", "❌ 无", "**180 张全白也没发现**"),
    ("书架封面", "图片内容是否非空白", "❌ 无", "**这次事故就在这**"),
    ("开书/返回", "点卡片、回流、hash 清理", "✅ 有", "T2/T3"),
    ("页图渲染", "图片尺寸、位置", "✅ 部分", "img rect 被用于坐标换算"),
    ("页图内容", "页图是否白图/错图", "❌ 无", "同类风险"),
    ("文字提取", "text 是否为空、是否乱码", "❌ 无（只在 qa 里查空）", "GK-045 印前批注就是这么漏的"),
    ("词框", "数量、位置、吸附、不重叠", "✅ 强", "T4 共 11 条"),
    ("音频存在", "audio 字段、Blob 加载", "✅ 有", "T5 间接"),
    ("音频内容", "是否静音、是否人声", "❌ 无", "换成语静音也照样绿"),
    ("点词", "命中、起点、停点、高亮", "✅ 很强", "T5 35 条 + T12"),
    ("点句", "整句播放、停点", "✅ 有", "T6/T14"),
    ("连播", "翻页、结束态、不循环", "✅ 有", "T9"),
    ("语速", "实际推进量", "✅ 有", "T8"),
    ("进度", "杀进程后恢复", "⚠️ 仅 localStorage 写入", "没测真正重启"),
    ("错误路径", "404/坏数据/空文字页", "❌ 无", "一直没做"),
    ("跨系列", "G1 可读、深链接", "✅ 部分", "T12/T13/T14"),
]

print(f"  {'功能':12} {'验证点':26} {'覆盖':18} 说明")
for cat, point, cov, note in matrix:
    print(f"  {cat:12} {point:26} {cov:18} {note}")

gaps = [m for m in matrix if m[2].startswith("❌")]
print(f"\n=== 覆盖盲区 {len(gaps)} 处 ===")
for cat, point, _, note in gaps:
    print(f"  · {cat} / {point}  ——  {note}")

print("\n=== 为什么白封面没被测出 ===")
print("  1. T1 只查 `document.querySelectorAll('#grid .card').length`，卡片在就算过")
print("  2. 没有任何断言读 img.naturalWidth（就算读了，白图也是合法图像，值为真）")
print("  3. 断言的都是**行为**（点击、播放、停点），没有一条断言**内容**")
print("  4. qa_library 只查文件存在，不查文件里是什么")
print("  → 整类缺陷：结构合法 + 内容错误。测试设计层面就没设防。")

out = ROOT / ".work" / "coverage-audit.json"
out.write_text(json.dumps({
    "cases": [{"id": t, "title": ti, "assertions": len(i)} for t, ti, i in blocks],
    "gaps": [{"category": c, "point": p, "note": n} for c, p, _, n in gaps],
}, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"\n写入 {out}")
