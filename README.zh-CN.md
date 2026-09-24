# 抖音图文轮播一键生成器

[English](README.md) · [**Agent 使用契约**](AGENTS.md) · [版式拆解](docs/format-analysis.zh-CN.md) · [引擎对接备忘](docs/provider-notes.zh-CN.md)

一个主题 → 5~7 张「双格科普漫画」→ 直接发布。
画风提前设定，全套统一；可以把**你自己的照片**设成固定主角，做个人 IP 连更。

版式和内容规则来自对 72 张真实样例的拆解，见 [docs/format-analysis.zh-CN.md](docs/format-analysis.zh-CN.md)。

```
       主题 ──► 分镜脚本 ──► 每格底图 ──► 排版合成 ──► 可发布成图
    (你/ChatGPT)   (LLM)      (画图模型)    (本地Pillow)   + 文案 + 话题 + 预览
                                  ▲
                    画风预设 + 定妆图（每个「主角 × 画风」一张）
```

---

## 快速开始

```bash
pip install -r requirements.txt
python -m dig doctor                                    # 体检：依赖、字体、Key
python -m dig run --theme "楼盘名字里的暗号" --offline   # 不花钱先跑通流程
```

`--offline` 用内置 mock 引擎，不联网、不需要任何 API Key，出的是占位图，
但**排版、字体、导出、文案全是真的**——先用它确认一切正常，再接真模型。
mock 画的图不会进缓存，离线预览过的脚本，真跑时不会被当成"已经画好"。

接真模型：

```bash
cp config.example.yaml config.yaml     # 填模型名（里面有 AgentPlan 的现成写法）
cp .env.example .env                   # 填 API Key
python -m dig run --theme "楼盘名字里的暗号" --style retro_comic --handle your_douyin_id
```

Windows 也可以直接：

```powershell
.\run.ps1 "楼盘名字里的暗号" -Handle your_douyin_id
```

产物在 `output/时间戳_主题/`：

```
pages/01.jpg … 06.jpg   ← 直接发布的成图
preview.jpg             ← 整套一张图 + 第 1 张在手机里的样子（检查用，不是用来发的）
panels/                 ← 每格的原始底图（想换某一格：dig reroll）
character_sheet.png     ← 这套图所有格共用的定妆图
script.json             ← 分镜脚本，改完可以重出图（存的是相对路径，整个目录能拷走）
caption.txt             ← 标题、发布文案、话题、逐格文案、发布前自检清单
manifest.json           ← 用了什么模型/画风、每格状态、失败名单、实际发了多少次计费请求
```

---

## 三个核心能力

### 1. 画风提前设定

```bash
python -m dig style list                                  # 看内置的 6 种
python -m dig run --theme "..." --style guochao_ink        # 直接用
python -m dig run --theme "..." --style-prompt "90年代港漫风，粗线条，高对比"
```

**用一张参考图反推画风**（你说的"指定参考风格"）：

```bash
python -m dig style add --from-image 抄来的图.jpg --name 复古港漫 --id hk_retro
python -m dig run --theme "..." --style hk_retro
```

视觉模型只读**画风**（线条、上色、色调、质感、年代感），不读画面内容，
结果存成 `styles/hk_retro.yaml`，可以手工微调后长期复用。

| 预设 | 画面 | 标题横幅 |
|---|---|---|
| `retro_comic` | 做旧印刷、半调网点、粗墨线（最接近参考样例） | 暖黄圆角条 |
| `ins_minimal` | 干净的扁平插画、低饱和 | 白色卡片，左对齐 |
| `guochao_ink` | 水墨 + 国潮配色 | 朱红匾额，内收细线 |
| `clay_3d` | 黏土定格动画 | 白色胶囊 |
| `cyber_neon` | 霓虹夜景 | 深色条 + 霓虹光晕 |
| `storybook` | 水彩绘本 | 撕开的纸胶带 |

横幅形状是画风预设的一部分（`banner.shape`：`rounded` / `pill` / `plaque` / `tape` / `glow`，
另有 `banner.position: left`），自定义画风可以任选。

### 2. 上传照片，把你设成主角（个人 IP）

```bash
python -m dig character add --id my_ip --name 小圆 --photo me.jpg
python -m dig sheet --character my_ip --style retro_comic     # 只画 1 张定妆图，先看再花 12 张的钱
python -m dig run --theme "第一次租房避坑" --character my_ip --handle your_douyin_id
```

角色一致性是分层锁定的，缺一层都容易崩人设：

| 层 | 做什么 | 说明 |
|---|---|---|
| 文字层 | 视觉模型把照片写成"角色设定卡" | 发型、五官、常穿服装、标志性配饰，注入每一格提示词 |
| **定妆图** | 一张只有人、纯色背景的定妆图，**每一格**都拿它当参考图 | 默认开启（`run.character_sheet`）。每个「主角 × 画风 × 模型」画一张，跨作品缓存。照片主角会**按当前画风用照片转绘**这张图，照片的背景和照片质感不会带进漫画 |
| 画风专属定妆图 | `character stylize --style X` 为**这一个画风**存一张 | 这个画风里优先用它。复古漫画的定妆图不会拿去锚国潮水墨 |
| 第 1 格锚点 | 画不出定妆图时的退路 | 能锁住长相，但构图会向第 1 格靠拢，所以只做退路 |

角色锁定不是可选项。实测一套 12 格**不锁**，主角每一格都在变 ——
藏青中山装 → 红背心 → 橙上衣，脸型比例全不一样，整套没法用。

定妆图**故意不带场景**。早先拿第 1 格当锚点：长相锁住了，但构图也被抄了 ——
工地那一格里冒出第 1 格的红砖楼和一盏吊灯，所有格的机位、景别都向第 1 格靠拢。
纯色背景的定妆图没有场景可抄，长相锁住，构图自由。

**整套开跑之前先看一眼定妆图。** `dig sheet` 只画定妆图（1 次计费）并打印路径。
不对就改描述或者 `dig sheet --redraw`；对了，整套出图时直接命中缓存，不再计费。
否则一张画歪的定妆图会被缓存下来，悄悄毁掉这个主角之后的每一套图。

**吉祥物账号不需要照片。** 主角是画出来的角色时，直接在 `script.json` 里写：

```json
{
  "character": {
    "name": "阿鼠",
    "sheet": "圆脸卡通小老鼠，浅米色短毛，永远穿同一件藏青色中山装：立领、胸前两个带盖口袋、白色窄袖口",
    "signature": "藏青色中山装 + 白色窄袖口"
  },
  "pages": [ "…" ]
}
```

写脚本时也会带上人设口吻，文案会更像"这个人"在说话，而不是通用科普腔。

照片只存在本机 `characters/<id>/`，不上传到本工具以外的任何地方
（当然，生图时会发给你配置的那家模型服务商）。角色设置 `"use_photo_as_ref": false`
则照片完全不会发给画图模型。

### 3. 一键出整套，一条命令换一格

`run` 一条命令跑完：写脚本 → 体检 → 生图 → 排版 → 导出文案和预览。
改文案不用重新生图：

```bash
python -m dig script --theme "..."                              # 只出脚本
# 手工改 script.json 里的 caption
python -m dig render --script output/xxx/script.json --skip-images   # 几秒重排
```

只重画一格，就只花一格的钱：

```bash
python -m dig reroll --script output/xxx/script.json --panel 7              # 1 次计费
python -m dig reroll --script output/xxx/script.json --panel 3,9            # 2 次计费
python -m dig reroll --script output/xxx/script.json --panel 7 --scene "主角…" # 顺便换这一格的画面
```

其余格原样沿用，整套在原目录里重新排版。

---

## 安全栏：生图之前先体检

生图按格计费，所以脚本里能提前查出来的问题，一律不让它烧到钱上。
体检是免费的：

```bash
python -m dig validate --script my-script.json
```

```
体检结果：2 个错误，1 个警告

✗ [caption-too-long] 第1张·第1格：短标题 23 个字宽，超过硬上限 18
      改法：砍到 14 字以内：「1. 这是一个非常非常长的短」
✗ [caption-duplicate] 第3张·第1格：和 第2张·第1格 的短标题完全重复：「重复的标题」
      改法：每一格必须给新信息，重复一格就掉一批观众
△ [no-character] 脚本：没有设定主角，整套图的人物会一格一个样
      改法：在 script.json 里加 character 块（吉祥物不需要照片）
```

`run`、`render`、`reroll` 会跑同样的检查，**有错误直接拦住不开工**，警告只提示不挡路。
`--strict` 把警告也当错误；`--no-validate` 全部跳过，正常情况下用不到。

查的东西：标题一行放不下（**用真实字体和版式量**，所以 `iPhone 16 Pro Max 值不值` 能过，
16 个汉字会折行）、带序号、重复、引号不成对、场景空/太薄、场景要求画文字、
每页格数不齐、页数超范围、没设定主角、`character_id` 在这台机器上没登记。

其它默认就开着的保险：

- **预检**：开工前先查 API Key、模型 ID、中文字体，打印格数、**最坏情况要发多少次计费请求**
  （格数 + 定妆图 + 质检重画）和预计耗时。
- **缓存按引擎和模型分开**：重跑同一份脚本只重画提示词变了的格；换模型（或从 `--offline`
  换成真跑）就全部重画 —— 别的模型画的图不是你要的图。*从 0.3 升级：缓存键和提示词都变了，
  旧脚本第一次重跑会重新生成。*
- **Key 被拒，第一次请求就停**：401/403 整批停下；400 这类参数错误不重试；只有断连、429、5xx 才重试。
- **每格生成后自动质检**：标题横幅是**压在画面上**的，所以画面必须一直画到顶边。
  早期提示词写"上方留出空白"，模型就真的画了一整片空地（实测 sd<2，颜色几乎等于纸色）。
  现在每格都查这种废图，发现就换更直白的提示词重画一次（`run.quality_check`）；
  两次都不过，留**更好的那张**（两张都付过钱）。大块平涂的画风在预设里放宽口径（`quality.max_dead_bands`）。
- **带参考图时强制串行**：图生图并发会被网关掐断，用到主角就把 `workers` 锁成 1。
- **失败兜底**：某格反复失败就用占位图顶上，保证整套能出完，失败名单写进 `manifest.json`，
  并且**退出码是 1** —— 下游不会把半成品当成成品。

要让 Agent 来开这个工具，先让它读 [AGENTS.md](AGENTS.md)，
配套还有 [schema/script.schema.json](schema/script.schema.json) 和
[examples/script.minimal.json](examples/script.minimal.json) 两个模板。

---

## 配合 ChatGPT 批量选题

1. 把 [prompts/topic_ideation_zh.md](prompts/topic_ideation_zh.md) 分隔线之间的内容
   复制进 ChatGPT，填上你的账号定位，它会产出一份 JSON 选题清单；
2. 存成 `topics.json`；
3. 批量出片：

```bash
python -m dig batch --file topics.json --style retro_comic --character my_ip --handle your_douyin_id
```

选题文件长这样（`examples/topics.sample.json` 有完整示例）：

```json
[{ "theme": "楼盘名字里的那些字分别代表什么档次",
   "angle": "从第一次看售楼部的买房小白视角",
   "audience": "准备买房的年轻人", "pages": 6,
   "title": "楼盘名里的暗号，第4个我笑出声",
   "beats_preview": ["“湾”是附近有河流", "“府”是想卖贵一点"],
   "hashtags": ["#买房"] }]
```

`title`、`type`、`beats_preview`、`hashtags` 会作为参考交给写脚本的模型 ——
选题时已经验证过前几格能拆，没理由丢掉。

那份提示词里写清了这个形式的硬约束——**一个选题必须能拆出 10~14 个能画出来的并列小点**，
拆不出来的选题做这个形式必翻车。它还会让模型当场写出前 4 格标题来自我验证。

文本模型写完脚本会立刻体检；有它自己改得掉的问题（重复、超长、带序号、要求画字），
就把体检结果喂回去**改一轮**，取问题更少的那版。

---

## 网页版

```bash
python -m dig ui        # 默认 http://127.0.0.1:8765
```

和命令行同一个原则：先改好、再花钱。

1. **写脚本**：填主题生成脚本（或载入示例脚本）；
2. **改文案**：每一格的标题和画面都是可编辑的一行，标题带实时字宽；边改边体检，
   显示最坏情况的计费次数，有错误时"出图"按钮是灰的；
3. **出图**：每格画完就出现在进度区，最后给出成图、`preview.jpg` 和可直接复制的发布文案；
4. **单格重画**：结果区每一格都有"重画这一格"（1 格 = 1 次计费）。

只用标准库 `http.server` 实现（没有 Flask/Gradio 依赖）。只接受本机 Host 的请求，
所有接口都要带页面下发的一次性令牌 —— 浏览器里开着的其它网站没法替你触发计费生图。

---

## 给 Agent / 脚本调用

**推荐直接在 Codex 或 Claude Code 中使用。** 打开本仓库，用自然语言告诉 Agent
选题、账号口吻、画风和主角即可。开始前让它先读 [AGENTS.md](AGENTS.md)：这份契约
要求 Agent 在本地写好并校验脚本，确认无误后才进入付费生图阶段，能避免把明显错误
烧成一整套图片。

火山方舟 Agent Plan 生图**仍然按格计费**，只是通常比标准按量调用成本低，并不是
免费额度；最新单价和实际费用请以火山方舟控制台为准。

下面这些提示词可以直接复制给 Codex 或 Claude Code：

**首次安装，不调用付费模型**

```text
阅读 AGENTS.md 和 README.zh-CN.md，安装依赖，运行 dig doctor，再完成一次 --offline 测试。不要调用任何付费模型；把还缺的 API Key、模型 ID 或中文字体列给我。
```

**先写脚本和体检，不生图**

```text
参考 examples/script.minimal.json 和 schema，为“第一次租房最容易踩的 6 个坑”写一套 6 页、每页双格的脚本，口吻实用直白，并设定一个全程一致的吉祥物主角。运行 dig validate，把全部短标题、总格数和预计付费生图调用数给我看；先不要 render。
```

**生成整套图并检查结果**

```text
用 retro_comic 画风和抖音号 my_account 渲染已经通过校验的租房脚本。先运行 dig sheet 让我看定妆图。出图后打开 preview.jpg，确认主角一致、字幕清楚，再检查 manifest.json 的 errors 和 billing。有问题的格子用 dig reroll 单独重画。
```

**把本人照片设成固定主角**

```text
把 ./me.jpg 登记为 id 为 my_ip、显示名为“小圆”的固定主角，用 dig sheet 生成 retro_comic 画风的定妆图给我看；然后为“第一次买房我踩过的坑”准备并校验一套图。任何付费生图调用开始前，先告诉我页数和总格数。
```

所有命令都是纯 CLI，退出码有明确含义：

| 退出码 | 含义 |
|---|---|
| `0` | 跑完了，每一格都是真图 |
| `1` | 跑完了，但有格子是占位图（看 `manifest.json` 的 `errors`），或者批量里有选题失败 |
| `2` | 什么都没生成：参数/配置错、体检有错误、或者 Key 被拒 |

产物路径固定，适合被 Agent 编排：

```bash
python -m dig run --theme "$THEME" --character my_ip --handle "$HANDLE" --out ./out/task123
```

跑完读 `./out/task123/manifest.json` 就知道结果：

```json
{
  "title": "...", "pages": 6, "panels_per_page": 2,
  "style": { "id": "retro_comic", "name": "复古双格漫画" },
  "character": { "id": "my_ip", "signature": "圆框眼镜 + 藏青外套" },
  "files": ["01.jpg", "…", "06.jpg"],
  "preview": "preview.jpg",
  "stats": { "panels_ok": 12, "panels_total": 12, "seconds": 96.4 },
  "billing": { "billed": true, "requests": 13, "by_kind": { "sheet": 1, "panel": 12 }, "cache_hits": {} },
  "panels": [ { "panel": 1, "caption": "…", "image": "panels/01.png", "status": "ok" } ],
  "errors": []
}
```

`errors` 非空就说明有格子是占位图兜底的，`dig reroll --panel N` 只重画那几格。
主角用 `--id` 显式登记一次（避免中文名当 key），之后所有作品复用。
`render --script` 读的是某个作品目录里的脚本时，就在那个目录里原地更新；
别处手写的脚本会新建 `output/时间戳_主题/`，不会往脚本旁边写东西。

---

## 换模型

出厂默认是**按量付费的火山方舟 Ark**（豆包写文案 + Seedream 4.0 画图，`/api/v3`）。
对着线上服务完整验证过的是 **Ark AgentPlan**（`/api/plan/v3`，Seedream 5.0 Lite）——
`config.example.yaml` 里有现成的写法。改 `config.yaml`：

```yaml
providers:
  image:
    provider: ark                          # ark | openai | gemini | mock
    model: doubao-seedream-4-0-250828      # 换成你自己的接入点 ID
    api_key_env: ARK_API_KEY
```

| provider | 文案 | 画图 | 备注 |
|---|---|---|---|
| `ark` | 豆包 | Seedream 4.0 / 5.0 | 国内直连，中文理解好，支持多张参考图 |
| `openai` | gpt-4.1 等 | gpt-image-1 | 也兼容 DeepSeek / 硅基流动 / vLLM 等任何 OpenAI 协议服务 |
| `gemini` | gemini-2.5-flash | gemini-2.5-flash-image | 角色一致性最强；Key 走请求头，不进 URL |
| `mock` | 模板 | 占位图 | 离线，用于验证流程；不进缓存 |

三个环节（`text` 写脚本 / `vision` 读照片 / `image` 画图）可以分别配不同家，
比如文案用便宜的，画图用最好的。

---

## 常用参数

```bash
python -m dig run \
  --theme "第一次租房避坑" \
  --style retro_comic \          # 画风预设
  --character my_ip \            # 固定主角
  --handle your_douyin_id \      # 页脚抖音号
  --pages 6 --panels 2 \         # 6 张图，每张 2 格
  --audience "刚毕业的大学生" \
  --angle "从被坑过三次的过来人视角" \
  --zip                          # 额外打个包
```

`--seed` 只在支持 seed 的引擎上能复现构图（按量付费的 Seedream 4.0）；AgentPlan 没有 seed 字段，会被忽略。
`--workers` 只对没有主角的套图有用 —— 用到参考图就一定串行。

其它命令：`script`（只出脚本）、`render`（用脚本出图）、`validate`（脚本体检）、`sheet`（定妆图）、
`reroll`（单格重画）、`batch`（批量）、`style list/show/add`、`character list/add/stylize`、`doctor`、`ui`。
每个都可以 `--help`。

---

## 画质

第一张表都是在真实 Seedream 5.0 出图上量出来、改掉、再量一遍的。重排已有底图不花钱
（`--skip-images`），所以每项改动都是对着同一批画比的。

| 发现 | 改法 | 结果 |
|---|---|---|
| **每格生成的像素丢掉 69%**：AgentPlan 强制每张 ≥370 万像素，1440×1920 的成图只用了 120 万 | 默认画布提到 **1792×2400**，正是参考原图的尺寸 | 丢弃降到 49%，**生图成本不变**（这些像素本来就在付钱） |
| 纸张质感叠在标题之后，颗粒糊到字上 | 质感只作用于纸和画，标题和水印最后贴 | 质感开关前后标题条逐像素一致，标题对比度 +6.5% |
| 缩小 1.4~1.8 倍后半调网点和排线发糊 | 只在明显缩小之后做轻度 USM（`page.sharpen`） | 细节边缘能量 **+19%** |
| 一套 6 张像六个印刷批次：亮度差 ~42 级、冷暖差 ~22 级 | 每个通道用 gamma 往整套中位数拉一半（`page.harmonize`） | 亮度离散 −23~29%，偏色离散 −18%，**纯黑墨线不动** |

本地画的部分（横幅、水印、纸张）也是这样量出来的：

| 发现 | 改法 | 结果 |
|---|---|---|
| Linux（CI、Agent 容器）上标题是**日文字形**：Noto CJK 字体集合的第 0 个是 JP，示例脚本 10 条标题全部中招（房、没、次、退…） | 字体集合按名字挑简体中文；`doctor` 打印字体名，不是简体会提醒 | Noto Sans CJK **SC** Black |
| 标题字**偏上 10px**（墨迹上方 48px、下方 68px）：横幅按字体行高算 | 按**墨迹**居中、上下留白相等 | 各预设误差 ≤1px；横幅高 208 → 173~180px，多露出一块画 |
| 一句长标题只缩它自己那条，一套里出现两种字号 | 整套统一字号（取最长那句需要的字号） | 横幅一致；`validate` 会在长标题拖小整套之前提醒 |
| 白色水印对 6 套里 5 套纸色的对比度只有 **1.06~1.28:1**；音符没描边 | `watermark.color: auto`：浅纸用墨色字、深底用浅色字；图标和文字一样画 | 各预设 ≥4.5:1，缩到信息流缩略图也看得清 |
| "颗粒"其实是往灰色混 6%：纯黑被抬到 ~7，纸白被压到 ~247 | 零均值噪点，只加在中间调 | 纯黑纯白一个像素都不动；中间调均值偏移 <1 级 |
| 6 个预设只有颜色不同 | 每个画风自己的横幅形状（圆角/胶囊/匾额/纸胶带/霓虹/左对齐），纸边做旧改成自然的曲线 | — |

版式随画布等比缩放，其它尺寸也能用 —— 包括非 3:4 画布，会按更紧的那一边缩，标题不会溢出。

---

## 设计上的两个关键取舍

**中文由本地字体渲染，不让画图模型写字。**
AI 画中文经常缺笔画、串字，一套 6 张糊一张就得重跑。本地渲染 100% 可控，
而且改文案不用重新烧钱生图。所以每条生图提示词里都硬写了"画面中不要出现任何文字"，
色板也写成颜色词，而不是模型可能照着画出来的色号。

**每格单独生图，而不是一次生成整页。**
让模型一次画出"两格 + 横幅 + 页脚"，构图不可控、文字必糊。
本工具给每格按画格自己的比例要一张略大一点的图，再在本地贴合，构图稳定，
某一格不满意也可以单独重画。

---

## 故障排查

| 现象 | 原因 / 解法 |
|---|---|
| 标题是方块 | 没有中文字体。`python -m dig doctor` 看提示；Linux: `apt-get install -y fonts-noto-cjk`；或把 .ttf 丢进 `assets/fonts/` |
| 有的字像日文写法 | 字体不是简体中文版本。`dig doctor` 会显示字体名；在 `config.yaml` 的 `text.font` / `text.font_index` 指定 |
| 提示缺 API Key | 检查 `.env` 里的 `ARK_API_KEY`；或先用 `--offline` |
| "图像服务拒绝了请求（HTTP 401/403）" | Key 无效/过期，或者账号没开通这个模型。发了一次请求就停下了 |
| 某几格是占位图 | 那几格生图失败了，看 `manifest.json` 的 `errors`，然后 `dig reroll --panel N` |
| 某一格画得不好 | `dig reroll --script output/xxx/script.json --panel N`（可以加 `--scene "…"`） |
| 主角长得不一样 | 用 `dig sheet` 看定妆图；确认 script.json 里有 `character` 块或已登记的 `character_id` |
| 画面里冒出乱码文字 | 偶尔会有，`dig reroll` 那一格；`--allow-text-in-image` 默认就是关的 |
| 连接被掐断 | 图生图并发的问题，`run.workers` 设 1、`run.attempts` 设 4 |
| 出图太慢 | 用到主角时必须串行，急不来；先 `script` + `validate` 定稿文案再生图，避免反复生成 |

`python -m pytest tests -q` 跑离线测试（不联网、不花钱）。
没装 pytest 就 `python tests/test_smoke.py`。

---

## 目录

```
dig/                 代码
  cli.py             命令行入口和退出码
  pipeline.py        一键流水线、单格重画、批量
  validate.py        花钱前的脚本体检（标题按真实字体量）
  script_gen.py      分镜脚本生成 + 体检后自动修正一轮
  prompt_builder.py  单格提示词拼装
  imagegen.py        并发/重试/缓存/兜底/单格重画
  charsheet.py       无场景定妆图（每个「主角 × 画风 × 模型」一张）
  quality.py         出图后的底图质检
  compositor.py      排版合成（横幅、边框、水印、做旧质感）
  harmonize.py       整套调色统一
  preview.py         preview.jpg：接触印样 + 手机示意
  ledger.py          计费台账（写进 manifest.json）
  character.py       个人 IP 主角
  style.py           画风预设 / 参考图反推
  fonts.py           字体发现（挑简体字形）+ 中文避头尾排版
  webui.py           本地网页版
  providers/         ark / openai / gemini / mock
styles/              画风预设 YAML，可自己加
prompts/             选题提示词（喂给 ChatGPT）
docs/                样例拆解、引擎对接备忘
```
