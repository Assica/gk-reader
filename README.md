# 小书虫 GK —— 运行说明

把 70 本 GK 有声绘本做成 iPad 上可点读的离线阅读器。

## 目录

```
02、GK 有声绘本PDF 70/     原始绘本 PDF（未改动）
03、GK 音频-男声 70/        原始音频 WMA（未改动）
library/                   ← 由 tools/ 生成，App 只读这里
  manifest.json            书架索引
  covers/NN.jpg            70 张封面
  books/NN/p04..p11.jpg    560 张正文页
  books/NN.json            每页文字 + 词框 + 音频区间 + 逐词时间戳
  audio/NN.m4a             70 段 AAC 音频
web/                       阅读器（原生 JS，无构建步骤）
  index.html / style.css / app.js
tools/                     素材流水线
docs/                      效果图与验证图
方案.md                    完整实施方案
```

## 跑起来

```powershell
python tools/serve.py --port 8787 --dir "E:\apple app"
```

浏览器打开 <http://127.0.0.1:8787/web/>

- 深链接直接打开某本书：`http://127.0.0.1:8787/web/#/b/35`
- 看热区位置（调坐标用）：`http://127.0.0.1:8787/web/?debug=1#/b/1`

> **不要用 `python -m http.server`**：它不支持 HTTP Range，音频无法 seek，
> 点读会变成"永远从第 1 页开始播"。`tools/serve.py` 补上了 Range 支持。
> （阅读器自己也把音频转成 Blob 了，所以对 Range 不敏感；但用对服务器仍然更省事。）

**不能用 `file://` 直接双击打开 HTML** —— 浏览器会拦掉对 `library/*.json` 的请求。

### 在 iPad 上看

把 `--bind 127.0.0.1` 换成 `--bind 0.0.0.0`，iPad 和电脑连同一个 Wi-Fi，Safari 打开
`http://<电脑局域网 IP>:8787/web/`，分享 → 添加到主屏幕。

## 测试

```powershell
# 1) 服务（支持 Range）
python tools/serve.py --port 8787 --dir "E:\apple app"
# 2) 带调试端口的浏览器
msedge --headless=new --remote-debugging-port=9223 about:blank
# 3) 108 项断言（真实指针点击 + 就近吸附，按 iPad 横屏尺度）
node tools/webtest.mjs
```

**判定要看 `RESULT pass=108 fail=0` 这一行**，不要只看退出码：
某个用例中途抛错会让后续断言不执行，总数会从 108 掉到 30 多。

| 用例 | 覆盖 |
|---|---|
| T1–T3 | 书架、真实点击卡片开书、返回书架 |
| T4 | 热区高度 ≥44px、互不重叠、词心落在自己热区 |
| T5 | 逐词真实点击：`stopAt`=词尾、只有该词高亮、播完停住 |
| T6 | "再读一遍"整句播放到句尾 |
| T7 | 播放中翻页 → 旧音频必须停 |
| T8 | 语速 0.75× 的实际推进量 ≈ 75% |
| T9 | 整本连播到底、结束态、不循环 |
| T10 | 快速连点不串词 |

### 变异测试（证明测试不是假绿）

```powershell
node tools/mutation.mjs        # 需要在 8790 上跑沙箱副本
```

在 `.work/mut/www` 副本上把功能一个个改坏（点词退化成整句、热区错位 40px、
删掉 `audio.play()`、翻页不暂停、语速不生效、最后一页循环），逐个跑套件，
**7 个变异全部被检出**，跑完自动还原并校验哈希。

## 重新生成 library

```powershell
$py = "<python 路径>"

# 全量：渲染页面 + 提取文字词框 + 转码音频 + 切句对齐（约 15 分钟）
& $py tools/build_library.py

# 只重算文字/词框（改了坐标逻辑时用，约 1 分钟）
& $py tools/build_library.py --boxes-only

# 逐词时间戳（需要 .work/models 里的 wav2vec2 模型，约 4 分钟）
& $py tools/align_library.py
& $py tools/check_wordtimes.py      # 校验，剔掉不可信的页

# 体检
& $py tools/qa_library.py
```

## 关键实现说明

- **音频**：WMA 用 Windows 自带 Media Foundation 转 AAC 64 kbps 单声道，不需要 ffmpeg。
- **坐标**：PDF 的 CropBox 相对 MediaBox 有偏移，词框必须先减 CropBox 原点再归一化。
- **点读**：不切音频文件——播放器 seek 到词级 `[t0,t1]` 播完即停。
- **逐词时间戳**：wav2vec2-base-960h（int8 ONNX）+ CTC 强制对齐，纯 CPU。
- **失败兜底**：某页没有可信的 `wordTimes` 时，点词自动改为读整句。

## 上 iPad

完整步骤见 [docs/上iPad-操作手册.md](docs/上iPad-操作手册.md)。一句话版本：

```powershell
cd app
npm install
npm run www            # 组装 web/ + library/ → app/www（93.6 MB）
npx cap add ios        # 需要 macOS
node scripts/patch-ios.mjs   # 横屏 / 状态栏 / 音频会话
```

没有 Mac 就走 GitHub Actions（`.github/workflows/ios.yml`）出**未签名 IPA**，
再用 SideStore 在 iPad 上用免费 Apple ID 重签安装，7 天续签一次。

## 已知问题

- 42 The Puppet Show 第 11 页文字层是空的，需要手填。
- 560 页中 408 页有可信的逐词时间戳，其余回落整句。
- 13 本长书的句子切分是靠"窗口选取"猜的，自动翻页可能错位（见 `tools/qa_library.py`）。

## 上 iPad 前必须补的（真机才有）

1. `AVAudioSession` 设成 `.playback` —— 否则侧边静音键会掐掉声音（最常见翻车点）。
2. `orientation: 'landscape'` 锁横屏。
3. 状态栏隐藏（StatusBar 插件）。
4. `capacitor.config.ts`：`webDir: 'www'`，把 `index.html / app.js / style.css / library/` 放进去，整包约 95 MB。

前端不依赖任何服务器或构建步骤：`www/` 里就是静态文件，改完刷新即可。
