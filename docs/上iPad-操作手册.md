# 上 iPad 操作手册

目标：把这个阅读器装到你自己的 iPad 上，离线可用，孩子能直接打开读。

全程不需要 Mac。构建在 GitHub 的 macOS 机器上跑，安装用 SideStore 自签。

---

## 0. 一张图看清整条路

```
你现在的电脑（Windows）          GitHub（免费）               你的 iPad
┌────────────────────┐        ┌──────────────────┐        ┌─────────────────┐
│ 源码 + library/     │  push  │ Actions: macOS   │  下载   │ SideStore        │
│ app/（Capacitor）   │ ─────► │  xcodebuild      │ ─────► │ 用你的 Apple ID  │
│ tools/serve.py      │        │  → 未签名 IPA    │  产物   │ 重签 → 安装      │
└────────────────────┘        └──────────────────┘        └─────────────────┘
                                                                  │
                                                          每 7 天续签一次
```

---

## 1. 先准备三样东西

| 需要一个 | 干什么用 | 注意 |
|---|---|---|
| **GitHub 账号**（免费） | 跑 macOS 构建、存 IPA 产物 | 私有仓库也行，Actions 免费额度 2000 分钟/月，一次构建约 10–15 分钟 |
| **Apple ID**（就是你平时登 App Store 那个） | SideStore 用它给 IPA 签名 | 不要用公司/学校受管的账号 |
| **Windows 上装 SideStore** | 把 IPA 装进 iPad、自动续签 | 见第 5 步 |

⚠️ **免费 Apple ID 的限制**（这不是我们的问题，是苹果的规则）：
- 一个账号同时最多 3 个自签 App、10 个 App ID
- 签名 **7 天过期**，过期后 App 打不开，要重新签名
- 每 7 天必须续签一次（SideStore 可以自动做，但 iPad 要连一下网络）

如果嫌麻烦，花 ￥688/年 买 Apple 开发者账号，有效期变 1 年，其余步骤完全一样。

---

## 2. 把仓库推上 GitHub

```powershell
cd "E:\apple app"

# 首次
git init
git lfs install                     # 关键：library/ 走 LFS
git add .
git commit -m "小书虫 GK：离线点读器"
git branch -M main
git remote add origin https://github.com/<你的用户名>/gk-reader.git
git push -u origin main
```

**为什么用 LFS**：`library/` 有 94 MB（560 张页图 + 70 段音频）。不放 LFS 的话，仓库会很大且每次改动都留一份历史。

> 不想用 LFS：把 `library/` 压成 zip 传到 Releases，然后在 `.github/workflows/ios.yml` 里加一步下载解压。文件末尾有说明。

---

## 3. 触发构建

GitHub 仓库页面 → **Actions** → 左侧 `build-ios` → **Run workflow**。

等 10–15 分钟，成功后在该次运行的页面底部 **Artifacts** 里下载 `gk-reader-ipa`，解压得到 `gk-reader-unsigned.ipa`。

**这个 IPA 是未签名的**，直接双击装不了——下一步用 SideStore 签。

若构建失败，先看这两处：
- 报 `缺少 library/` → 本地没提交 library，或 LFS 没拉全（`git lfs pull`）
- 报 `没找到 .app` → 看 `xcodebuild.log` 尾部，多半是 pod 没装好

---

## 4. 在 iPad 上装 SideStore

SideStore 是一个自签工具，能让你用免费 Apple ID 把 IPA 装到 iPad 上。

1. iPad 用 Safari 打开 <https://sidestore.io/>，按官方文档装（需要先装 AltStore 或直接用 SideStore 的安装方式）
2. Windows 电脑上装 **SideStore 的配对工具**（Pairing file），把 iPad 用数据线连电脑，导出配对文件
3. 配对文件传到 iPad，SideStore 里导入
4. SideStore 里登录你的 Apple ID
5. 把第 3 步的 `gk-reader-unsigned.ipa` 传到 iPad（AirDrop / 文件 App / 网盘都行）
6. SideStore → `+` → 选这个 IPA → 签名安装

装好后桌面出现 **小书虫 GK** 图标。

> 第一次装可能需要在 设置 → 通用 → VPN与设备管理 里信任你的开发者证书。

---

## 5. 每 7 天的续签

免费签名 7 天到期，到期后点图标会提示"无法验证 App"或直接闪退。

**SideStore 的做法**：打开 SideStore，它会自动检测过期并重签（需要 iPad 联网 + 配对文件仍有效）。建议：
- 每周固定一天打开一次 SideStore
- 或在 SideStore 里开启后台刷新

**续签会保数据吗**：会。进度和语速存在 App 沙盒里，重签不删除沙盒。

**过期了怎么办**（已经打不开的情况）：
1. 打开 SideStore → 找到 小书虫 GK → 删除
2. 重新用同一个 IPA 安装
3. ⚠️ 此时进度会丢——这是免费签名的固有代价

> 想避免这个坑：进入 App 的**家长区**（连点三次 + 算术题），有一键导出进度的入口（待实现），或直接换付费开发者账号。

---

## 6. 装完必做的 6 项验收

这几条是**只有真机能测**的，装完请逐条过一遍：

| # | 检查 | 怎么做 | 通过标准 |
|---|---|---|---|
| 1 | **静音键下仍有声音** | 把 iPad 侧边静音键拨到静音，打开一本书点一个词 | 有声音。没声音说明 `AVAudioSession` 没生效，见第 7 节 |
| 2 | 横屏锁定 | 把 iPad 竖过来 | 界面不旋转 |
| 3 | 状态栏隐藏 | 看顶部 | 没有时间/电量条 |
| 4 | 飞行模式可用 | 开飞行模式，读完整一本 | 全部功能正常，不报错 |
| 5 | 点读准确 | 点几个短词（I / a / the）和长词 | 点哪个读哪个，不串词 |
| 6 | 杀进程后进度保留 | 上滑杀掉 App，重开 | 回到上次那一页 |

---

## 7. 常见问题

**Q：没有声音**
1. 检查侧边静音键（最容易）
2. 检查音量
3. 都不行 → 说明 `patch-ios.mjs` 没跑成功，看构建日志里有没有 `✓ AppDelegate：AVAudioSession 设为 .playback`

**Q：打开是白屏**
- 大概率是 `www/library` 没进包。构建日志里搜 `ipa 里没有 library`
- 或看 iPad 上 设置 → 隐私 → 分析与改进 → 分析数据，找 `App-*.ips`

**Q：点词没反应**
- 点到画面空白处会读整句，这是设计如此
- 如果大部分词都点不中，先确认 `library/books/*.json` 里的坐标是新的（跑过 `tools/build_library.py --boxes-only`）

**Q：装的时候报 "Unable to install"**
- 免费账号同时最多 3 个自签 App，先删掉别的
- 或 Apple ID 需要重新登录 SideStore

---

## 8. 改了代码怎么更新

```powershell
# 本地先跑测试，别把坏版本推上去
node tools/webtest.mjs "http://127.0.0.1:8787/web/"
node tools/mutation.mjs

git add -A
git commit -m "改了什么"
git tag v0.1.1
git push && git push --tags     # 打 tag 会自动触发构建
```

重新下载 IPA → SideStore 覆盖安装（**覆盖安装保留数据**，删除重装才丢）。

---

## 附：现在这套东西的状态

| 项 | 状态 |
|---|---|
| Web 内核（书架 / 阅读器 / 点读 / 连播 / 语速） | ✅ 已完成，74 项自动化全绿 |
| `library/` 资源（70 本 / 560 页 / 70 段音频） | ✅ 93.6 MB |
| Capacitor 工程骨架 + 构建脚本 | ✅ 已就位（`app/`） |
| 原生补丁（横屏 / 状态栏 / 音频会话） | ✅ 已写成脚本，构建时自动打 |
| GitHub Actions 出未签名 IPA | ✅ 已写好（`.github/workflows/ios.yml`），**尚未实跑过** |
| App 图标 / 启动图 | ✅ 已生成（`app/resources/`） |
| **实际在 iPad 上装一次** | ❌ 需要你的 GitHub + Apple ID，我做不了 |
| 跟读录音 / 生词本 / 闯关 | ❌ 功能未做 |
