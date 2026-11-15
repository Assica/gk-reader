# 上 iPad 操作手册

目标：把这个阅读器装到你自己的 iPad 上，离线可用，孩子能直接打开读。全程不需要 Mac。

> **2026-11-15 重写**。旧版把 SideStore 当唯一路线，那套流程已经过时，而且它依赖的 VPN 组件在中国区 App Store 已下架。现在有三条路，默认走 **Sideloadly**。

---

## 0. 先选路线

| 路线 | 电脑上要装 | iPad 上要装 | 续签 | 中国区 Apple ID | 结论 |
|---|---|---|---|---|---|
| **A. Sideloadly** | iTunes + iCloud + Sideloadly | 什么都不用 | 7 天，可后台自动重签 | ✅ 可以 | **首选** |
| **B. SideStore** | iTunes + iloader | LocalDevVPN + SideStore | 7 天 | ❌ 需要非国区 Apple ID | 不推荐 |
| **C. 付费开发者账号** | Sideloadly 或爱思助手 | 什么都不用 | **1 年** | ✅ 可以 | 想省心就花钱 |

**TrollStore 不用考虑**：只支持 iPadOS 14.0 b2 – 16.6.1、16.7 RC、17.0，**17.0.1 起永久不支持**。这台 iPad 是 **18.7.8**，用不了。

### 为什么不再默认 SideStore

SideStore 必须在 iPad 本机签名，所以它需要一个"本机 VPN 隧道"组件，而这个组件在中国区拿不到：

| 组件 | 现状 |
|---|---|
| **LocalDevVPN**（当前官方主推） | 中国区 App Store **2025-12-18 下架**，174/175 个区可用 |
| **StosVPN**（上一代） | **全部 175 个区都已下架**（2025-11-25 起），别再找了 |
| **WireGuard**（更早） | 中国区 2019 起下架，且官方标注只兼容旧版 SideStore |

来源：[applecensorship 的 App Store 监测](https://applecensorship.com/app-store-monitor/app/6755608044)。走 A 路线可以完全绕开这一串麻烦——**不需要 VPN App、不需要配对文件**。

### 0.1 还没装之前，先用浏览器试玩

```powershell
python tools/serve.py --port 8787 --dir "E:\apple app"
```

浏览器开 <http://127.0.0.1:8787/web/>。iPad 想先试就加 `--bind 0.0.0.0`，iPad 和电脑同一个 Wi-Fi，Safari 开 `http://<电脑局域网 IP>:8787/web/`。

---

## 1. 先出一个 IPA（三条路线都要）

仓库：<https://github.com/Assica/gk-reader>（private，默认分支 `main`）

1. 打开 **Actions** → 左侧 `build-ios` → **Run workflow**
   （或者打 tag 自动触发：`git tag v0.1.0 && git push --tags`）
2. 等 2–3 分钟（实测 **2 分 26 秒**）。跑在 GitHub 的 macOS 机器上（`macos-15`）
3. 在该次运行的页面底部 **Artifacts** 下载 `gk-reader-ipa`，解压得到 **`gk-reader-unsigned.ipa`**

**这个 IPA 是未签名的**，双击装不了——下一步用 Sideloadly 签。

> **额度怎么算**（以仓库实际状态为准，2026-11-15 实测）：`library/` **不在仓库里**，已打包成 `library.zip`（239 MB / 1984 文件）挂在 [Release `library-data-v1`](https://github.com/Assica/gk-reader/releases/tag/library-data-v1)，CI 第一步通过 GitHub API 下载解压。所以**不消耗 Git LFS 带宽，也不占 Actions 缓存**。
>
> | 额度 | 免费额 | 单次消耗 | 折算 |
> |---|---|---|---|
> | Actions 分钟 | 2,000 分钟/月（仅私有仓库计费） | 实测一次 **2 分 26 秒** | 公开仓库**完全不计**；私有仓库也够几十次 |
> | Actions 产物存储 | 500 MB（私有仓库） | 一个 IPA ≈ 240 MB，保留 7 天 | 1 个产物轻松放下，第 3 个会超 |
> | Git LFS | 1 GB 存储 + 1 GB/月带宽 | **0**（只剩 `app/resources` 的 161 KB 图标） | 不再受限 |
>
> 仓库现在是 **public**，Actions 分钟对标准 runner 免费，这条已经不用算了。

构建失败先看这三处：

| 报错 | 原因 |
|---|---|
| `找不到附件 library.zip` | Release tag 写错，或 token 无 contents 读权限；`LIBRARY_TAG` 在 workflow 里 |
| `没找到 .app` | 看日志尾部 `xcodebuild.log`，多半是 pod 没装好 |
| `包里没有 library/manifest.json` | `app/scripts/build-www.mjs` 没把 `library/` 拷进 `www/` |

---

## 2. 路线 A：Sideloadly（推荐）

Sideloadly 是**装在电脑上的**桌面程序，在电脑上完成签名，通过 USB 把 App 推进 iPad。iPad 端不需要装任何东西。

### 2.1 电脑上装三样（顺序别乱）

1. **iTunes 官网版**：<https://www.apple.com/itunes/download/win64>
   ⚠️ **必须是非 Microsoft Store 版**。Store 版是沙盒化的，拿不到设备通信库，Sideloadly 官方明确说会失败。装过 Store 版的先卸载再重启。
   它装的是 **Apple Mobile Device Support**（USB 驱动 + `AppleMobileDeviceService`），Sideloadly 靠这个才能通过数据线跟 iPad 通信。
2. **Sideloadly**：<https://sideloadly.io>（当前 v0.71.0，要求 Windows 7+）
3. **iCloud 官网版（按需）**：<https://updates.cdn-apple.com/2020/windows/001-39935-20200911-1A70AA56-F448-11EA-8CC0-99D41950005E/iCloudSetup.exe>
   **不是严格必需**。它提供 Apple Application Support 运行库；Sideloadly 文档把它列进要求，但只在个别环境下才真的用得上。
   判断标准：装完 iTunes 后打开 Sideloadly，**左上角能看到 iPad 名字和型号就不用装**；看不到设备、或 Apple ID 登录报认证错误时再装。

装完重启一次。用无线安装还要 Apple **Bonjour**（iTunes 会带）。

> 注意：iTunes 和 iCloud **都不能用 Microsoft Store 版**（沙盒，不装驱动到系统目录）。
> AltServer/SideStore 那条路则**必须**有官网版 iCloud，否则直接报 `iCloud Not Found`。

### 2.2 登录 Apple ID 的几个坑（国内最容易卡在这）

- 登录时 Sideloadly 会模仿 Xcode 去连 Apple 的 `gsa.apple.com`，**国内经常需要挂代理才通**。电脑上那个 `127.0.0.1:23292` 开着就行。
- 二次验证码要选**这台电脑能立刻收到**的那种（同一台设备弹窗最稳）。别人实测过：App 专用密码、手机短信码这两条路都失败过。
- **同一个账号别反复试**，试多了会被 Apple 临时限制，等几小时再试。
- 一定要用**最新版**。Apple 会不定期把第三方登录打死：2026-09-09 全线 429、2026-10-12 起全线 `-80045`，都是 Sideloadly 更新后恢复的。

### 2.3 装

1. iPad 用数据线连电脑 → 解锁 → 弹窗点「**信任**」→ 输密码
2. 打开 Sideloadly → 把 `gk-reader-unsigned.ipa` **拖进 IPA 框**
3. `Apple account` 填你的 Apple ID（**免费账号就行，不需要开发者账号、不需要美区**）
4. 安装方式保持默认的 **Apple ID sideload** → 点 **Start**
   **约 240–260 MB** 的包，USB 推过去大约 2–5 分钟

### 2.4 首次打开前必须做的两步

iOS 16 起，本地安装的开发签名 App 必须开 **开发者模式**，否则点图标直接闪退或提示"无法验证"（[Apple 官方说明](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)）。

顺序是「**先装 → 再去开 → 重启 → 信任 → 打开**」：

1. 装完先别打开。去 设置 → **隐私与安全性** → 拉到最底 → **开发者模式** → 打开 → **重启** → 解锁后确认
   （这个开关通常在装过一次开发签名 App 之后才会出现）
2. 再回 设置 → 通用 → **VPN与设备管理** → 「开发者 App」里点你的 Apple ID → **信任** → 输密码
3. 这时桌面上的「小书虫 GK」才能正常打开

### 2.5 续签和数据

- 免费账号签的 App **7 天过期**，过期后点图标打不开，但**数据还在**。
- 三种续签方式：
  - **自动**：Sideloadly 带后台守护进程，会每隔几天自动重签（[官网 Features](https://sideloadly.io)）。前提是电脑开着。
  - **手动**：插线重跑 2.3 的步骤，1 分钟。
  - 支持 Wi-Fi 安装的话，同一局域网不用插线（Windows 需要 Bonjour）。
- bundle id 固定为 `com.gkreader.app`，**覆盖安装会保留沙盒数据**——阅读进度、语速设置都不会丢。**别删 App 再装**，删了就清空。
- 免费账号固有的上限：同时最多 3 个自签 App、每 7 天最多 10 个 App ID。

### 2.6 报错对照

| 报错 | 怎么办 |
|---|---|
| `Guru Meditation` | 多半是 Apple ID 认证失败：换网络/挂代理、确认 2FA 码、别反复试 |
| `404` / `429` | Apple 接口变了或限流：更新 Sideloadly 到最新、隔一段时间再试 |
| `-80045 This action cannot be completed` | 第三方登录被 Apple 拒：升级 Sideloadly，或隔天再试 |
| `Untrusted Developer` | 没做 2.4 的第 2 步 |
| 装完点开闪退 | 没开开发者模式（2.4 第 1 步） |
| `maximum number of apps` | 免费账号 3 个 App 上限，先删别的自签 App |
| 看不到设备 | iTunes 是 Store 版；或没点「信任」；或数据线是充电线 |

---

## 3. 路线 B：SideStore（仅当你有非国区 Apple ID）

不想用电脑续签、或者已经有美区账号时可用。代价是 iPad 上多装两个东西，还多一个"配对文件"要维护。

### 3.1 前置

- iPad：**必须设锁屏密码**，iPadOS 15+
- iPad：**LocalDevVPN**（[App Store](https://apps.apple.com/app/id6755608044)）——中国区下架，要用非国区 Apple ID 下
- 电脑：iTunes 官网版 + **iloader**（<https://iloader.app>）

### 3.2 步骤（按 [官方文档](https://docs.sidestore.io/docs/installation/install)）

1. iPad：装好 LocalDevVPN → 点 **Connect** → 允许 VPN 配置 → 输密码。**安装/续签期间它必须一直开着**
2. 电脑：数据线连 iPad → 解锁 → 信任
3. 打开 iloader → 登录 Apple ID（大小写敏感）→ 选设备 → **Install SideStore (Stable)**
4. iPad：设置 → 通用 → VPN与设备管理 → 信任你的 Apple ID → 允许并重启 → 输密码
5. iPad：设置 → 隐私与安全性 → **开发者模式** → 打开 → 重启
6. 开 LocalDevVPN → 打开 SideStore → 登录同一个 Apple ID → 我的 App → 点 SideStore 右边的 **7 DAYS** 手动刷新一次

### 3.3 配对文件

SideStore 依赖一份 Apple 的「配对记录」，第一次由 iloader 自动放进去。它会**在 iOS 升级、抹掉重装、甚至毫无理由的时候失效**（官方原话：*"This also occurs at random times. This is Apple's fault"*）。失效后：

iloader → **Delete Stored Pairing** → 选设备 → **Manage Pairing File** → 在 SideStore 那一行点 **Place**（[文档](https://docs.sidestore.io/docs/advanced/pairing-file)）。

手动传文件时注意：微信/AirDrop 会把 `.mobiledevicepairing` 改成 `.txt`，或者把结尾 `ing` 截掉。**先压成 zip 再传**。

---

## 4. 路线 C：付费开发者账号（一年有效）

嫌 7 天续签烦，就花 **$99/年**（≈¥688）买 Apple Developer Program：

- 用 **Ad Hoc** 描述文件（把 iPad 的 UDID 加进设备列表）签名，**有效期 1 年**
- 需要改 `.github/workflows/ios.yml`：在 CI 里导入证书（`p12`）和描述文件，改掉 `CODE_SIGNING_ALLOWED=NO`
- 产出的就是**已签名 IPA**，用 Sideloadly 的 Normal Install 或爱思助手直接装，不用再签
- 一年到期重签一次

**这条路还没动**，要做得先加 GitHub Secrets：`BUILD_CERTIFICATE_BASE64`、`P12_PASSWORD`、`PROVISIONING_PROFILE_BASE64`、`KEYCHAIN_PASSWORD`、`TEAM_ID`。

---

## 5. 装完必做的 6 项验收

这几条**只有真机能测**，装完请逐条过一遍：

| # | 检查 | 怎么做 | 通过标准 |
|---|---|---|---|
| 1 | **静音键下仍有声音** | 侧边静音键拨到静音，打开一本书点一个词 | 有声音。没声音说明 `AVAudioSession` 没生效 |
| 2 | 横屏锁定 | 把 iPad 竖过来 | 界面不旋转 |
| 3 | 状态栏隐藏 | 看顶部 | 没有时间/电量条 |
| 4 | 飞行模式可用 | 开飞行模式，读完整一本 | 全部功能正常，不报错 |
| 5 | 点读准确 | 点几个短词（I / a / the）和长词 | 点哪个读哪个，不串词 |
| 6 | 杀进程后进度保留 | 上滑杀掉 App，重开 | 回到上次那一页 |

---

## 6. 常见问题

**Q：没有声音**
1. 先看侧边静音键（最常见）
2. 看音量
3. 都不行 → `patch-ios.mjs` 没打成功，构建日志里搜 `AVAudioSession 设为 .playback`

**Q：打开是白屏**
- 大概率是 `www/library` 没进包。构建日志里搜 `ipa 里没有 library`
- 或看 iPad 上 设置 → 隐私 → 分析与改进 → 分析数据，找 `App-*.ips`

**Q：点词没反应**
- 点到空白处会读整句，这是设计如此
- 大部分词点不中 → `library/books/*.json` 里的坐标不对，本地跑 `python tools/build_library.py --boxes-only` 重算

**Q：装不上 / 装完点不开**
- 见 2.6 的对照表（开发者模式、信任、3 个 App 上限）
- 先确认 IPA 本身是好的：解压后 `.app` 里应该有 `Info.plist` 和 `public/library/manifest.json`

**Q：7 天后打不开了**
- 证书过期，重新签一次即可，**数据还在**（覆盖安装）
- 别删 App，删了就清空

**Q：SideStore 报 `AFC was unable to manage files on the device`**
- 配对文件失效 → 按 3.3 重新 Place

**Q：深链接 `#/b/G1-001` 打不开**
- 已在 `26ec68f` 修好（路由正则从 `[A-Z]{2}` 放宽到 `[A-Z0-9]{2}`）。旧构建会打不开 G1/G2 的书

---

## 7. 改了代码怎么更新

```powershell
# 1) 本地先跑测试，别把坏版本推上去
node tools/webtest.mjs "http://127.0.0.1:8787/web/"
node tools/mutation.mjs

# 2) 提交 + 打 tag（tag 会触发构建）
git add -A
git commit -m "改了什么"
git tag v0.1.1
git push && git push --tags
```

然后重新下载 IPA → 用 Sideloadly 覆盖安装（**保留数据**）。

> 提醒：每次构建第一步会从 Release 下载 239 MB 附件（不占 LFS 额度，占约 10 秒），产物另有 240 MB 存储。频繁改动时先在电脑上用浏览器验（见 0.1），验好了再出包。
>
> **资源怎么更新**：改了 `library/` 之后重新打包上传为 Release 的**新 tag**（`library-data-v2` …），再把 `.github/workflows/ios.yml` 里的 `LIBRARY_TAG` 改成新 tag。**仓库里不再有 `library/`**（`.gitignore` 已忽略），提交代码不会带上它。

---

## 附：现在这套东西的状态

| 项 | 状态 |
|---|---|
| Web 内核（书架 / 阅读器 / 点读 / 连播 / 语速） | ✅ 用例已扩到 T1–T20，判定看输出里 `RESULT pass=N fail=0` |
| `library/` 资源 | ✅ **180 本 / 1443 页 / 180 段音频**，246.8 MB（GK 70 + G1 110），打包为 Release 附件 [library-data-v1](https://github.com/Assica/gk-reader/releases/tag/library-data-v1) |
| Git 仓库 | ✅ [Assica/gk-reader](https://github.com/Assica/gk-reader)（**public**）；`library/` **不进仓库**，走 Release 附件 |
| Capacitor 工程骨架 + 构建脚本 | ✅ 已就位（`app/`，bundle id `com.gkreader.app`） |
| 原生补丁（横屏 / 状态栏 / 音频会话） | ✅ `app/scripts/patch-ios.mjs`，构建时自动打 |
| GitHub Actions 出未签名 IPA | ✅ **已实跑通过**（2026-11-15，2 分 26 秒；产物 240.17 MB） |
| IPA 产物自检 | ✅ `com.gkreader.app`、仅横屏、状态栏隐藏、180 本、2174 个 library 文件 / 246.8 MB、无签名（符合预期） |
| 构建额度 | ✅ 仓库已 public，Actions 分钟不计费；LFS 已解除；只剩产物存储 500 MB（1 个 IPA 240 MB，保留 7 天） |
| **实际在 iPad 上装一次** | ❌ 待做（iPadOS 18.7.8，走路线 A） |
| 跟读录音 / 生词本 / 闯关 | ❌ 功能未做 |
