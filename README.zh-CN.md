# 抖音图文轮播一键生成器

[English](README.md) · [**Agent 使用契约**](AGENTS.md) · [版式拆解](docs/format-analysis.zh-CN.md) · [引擎对接备忘](docs/provider-notes.zh-CN.md)

一个主题 → 5~7 张「双格科普漫画」→ 直接发布。
画风提前设定，全套统一；可以把**你自己的照片**设成固定主角，做个人 IP 连更。

版式和内容规则来自对 72 张真实样例的拆解，见 [docs/format-analysis.zh-CN.md](docs/format-analysis.zh-CN.md)。

```
       主题 ──► 分镜脚本 ──► 每格底图 ──► 排版合成 ──► 可发布成图
    (你/ChatGPT)   (LLM)      (画图模型)    (本地Pillow)   + 文案 + 话题
                                  ▲
                          画风预设 + 角色照片
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

接真模型：

```bash
cp config.example.yaml config.yaml     # 填模型名
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
panels/                 ← 每格的原始底图（想单独换某一格时用）
script.json             ← 分镜脚本，可以改完重出图
caption.txt             ← 标题、发布文案、话题、逐格文案、发布前自检清单
manifest.json           ← 这次用了什么模型/画风/种子，哪几格失败了
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

内置预设：`retro_comic`（复古双格漫画，最接近参考样例）、`ins_minimal`、
`guochao_ink`、`clay_3d`、`cyber_neon`、`storybook`。

### 2. 上传照片，把你设成主角（个人 IP）

```bash
python -m dig character add --name 小圆 --photo me.jpg --stylize
python -m dig run --theme "第一次租房避坑" --character 小圆 --handle your_douyin_id
```

角色一致性靠**四层锁定**，缺一层都容易崩人设：

| 层 | 做什么 | 说明 |
|---|---|---|
| 文字层 | 视觉模型把照片写成"角色设定卡" | 发型、五官、常穿服装、标志性配饰，注入每一格提示词 |
| 参考图层 | 照片作为 reference image 传给画图模型 | Seedream / gpt-image-1 / nano-banana 都支持 |
| 定妆图层 | `--stylize` 先生成一张**风格化定妆图** | 之后所有格以它为参考，同时锁住长相和画风 |
| **锚点格** | 先画第 1 格，再把它喂给后面每一格当参考图 | 默认开启（`run.character_lock`），真正撑住一整套的是这一层 |

锚点格不是可选项。实测一套 12 格**不加锚点**，主角每一格都在变 ——
藏青中山装 → 红背心 → 橙上衣，脸型比例全不一样，整套没法用。加上之后，
测到的每一格都是同一个人。

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
（当然，生图时会发给你配置的那家模型服务商）。

### 3. 一键出整套

`run` 一条命令跑完：写脚本 → 并发生图 → 排版 → 导出文案。
改文案不用重新生图：

```bash
python -m dig script --theme "..."                              # 只出脚本
# 手工改 script.json 里的 caption
python -m dig render --script output/xxx/script.json --skip-images   # 几秒重排
```

---

## 安全栏：生图之前先体检

生图按格计费，所以脚本里能提前查出来的问题，一律不让它烧到钱上。
体检是免费的：

```bash
python -m dig validate --script my-script.json
```

```
体检结果：2 个错误，1 个警告

✗ [caption-too-long] 第1张·第1格：短标题 23 字，超过硬上限 18
      改法：砍到 14 字以内：「1. 这是一个非常非常长的短」
✗ [caption-duplicate] 第3张·第1格：和 第2张·第1格 的短标题完全重复：「重复的标题」
      改法：每一格必须给新信息，重复一格就掉一批观众
△ [no-character] 脚本：没有设定主角，整套图的人物会一格一个样
      改法：在 script.json 里加 character 块（吉祥物不需要照片）
```

`run` 和 `render` 会跑同样的检查，**有错误直接拦住不开工**，警告只提示不挡路。
`--strict` 把警告也当错误；`--no-validate` 全部跳过，正常情况下用不到。

查的东西：标题超长、带序号、重复、引号不成对、场景空/太薄、场景要求画文字、
每页格数不齐、页数超范围、没设定主角。

其它默认就开着的保险：

- **带参考图时强制串行**：图生图并发会被网关掐断，用到主角就把 `workers` 锁成 1。
- **预检**：开工前先查 API Key、模型 ID、中文字体，并打印格数和预计耗时。
- **缓存**：重跑同一份脚本，只重画提示词变了的那几格。
- **失败兜底**：某格反复失败就用占位图顶上，保证整套能出完，失败名单写进 `manifest.json`。

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
python -m dig batch --file topics.json --style retro_comic --character 小圆 --handle your_douyin_id
```

选题文件长这样（`examples/topics.sample.json` 有完整示例）：

```json
[{ "theme": "楼盘名字里的那些字分别代表什么档次",
   "angle": "从第一次看售楼部的买房小白视角",
   "audience": "准备买房的年轻人", "pages": 6 }]
```

那份提示词里写清了这个形式的硬约束——**一个选题必须能拆出 10~14 个能画出来的并列小点**，
拆不出来的选题做这个形式必翻车。它还会让模型当场写出前 4 格标题来自我验证。

---

## 网页版

```bash
python -m dig ui        # 默认 http://127.0.0.1:8765
```

浏览器里填主题、下拉选画风、拖照片登记主角、点一下出图，成图直接显示。
只监听本机，只用标准库实现（没有 Flask/Gradio 依赖）。

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
用 retro_comic 画风和抖音号 my_account 渲染已经通过校验的租房脚本。完成后逐张检查成图，确认主角一致、字幕清楚，再检查 manifest.json 是否有错误。复用缓存，只重画失败或内容有变化的格子。
```

**把本人照片设成固定主角**

```text
把 ./me.jpg 登记为 id 为 my_ip、显示名为“小圆”的固定主角，并生成风格化定妆图；然后为“第一次买房我踩过的坑”准备并校验一套图。任何付费生图调用开始前，先告诉我页数和总格数。
```

所有命令都是纯 CLI，成功返回 0、失败返回 2（参数/配置错）或 1（批量里全失败），
产物路径固定，适合被 Agent 编排：

```bash
python -m dig run --theme "$THEME" --character "$CHAR" --handle "$HANDLE" --out ./out/task123
```

跑完读 `./out/task123/manifest.json` 就知道结果：

```json
{
  "title": "...", "pages": 6, "panels_per_page": 2,
  "style": { "id": "retro_comic", "name": "复古双格漫画" },
  "character": { "id": "小圆", "signature": "圆框眼镜 + 藏青外套" },
  "files": ["01.jpg", "…", "06.jpg"],
  "stats": { "panels_ok": 12, "panels_total": 12, "seconds": 96.4 },
  "errors": []
}
```

`errors` 非空就说明有格子是占位图兜底的，Agent 可以据此决定要不要重跑。

Agent 接主角照片的完整两步（用 `--id` 显式指定，避免中文名当 key）：

```bash
python -m dig character add --id my_ip --name "小圆" --photo "$PHOTO_PATH" --stylize
python -m dig run --theme "$THEME" --character my_ip --out ./out/task123
```

主角只需登记一次，之后所有作品复用同一个 `--character my_ip`。

---

## 换模型

默认走**火山方舟 Ark**（豆包写文案 + Seedream 4.0 画图），改 `config.yaml`：

```yaml
providers:
  image:
    provider: ark                          # ark | openai | gemini | mock
    model: doubao-seedream-4-0-250828      # 换成你自己的接入点 ID
    api_key_env: ARK_API_KEY
```

| provider | 文案 | 画图 | 备注 |
|---|---|---|---|
| `ark` | 豆包 | Seedream 4.0 | 国内直连，中文理解好，支持多张参考图 |
| `openai` | gpt-4.1 等 | gpt-image-1 | 也兼容 DeepSeek / 硅基流动 / vLLM 等任何 OpenAI 协议服务 |
| `gemini` | gemini-2.5-flash | gemini-2.5-flash-image | 角色一致性最强 |
| `mock` | 模板 | 占位图 | 离线，用于验证流程 |

三个环节（`text` 写脚本 / `vision` 读照片 / `image` 画图）可以分别配不同家，
比如文案用便宜的，画图用最好的。

---

## 常用参数

```bash
python -m dig run \
  --theme "第一次租房避坑" \
  --style retro_comic \          # 画风预设
  --character 小圆 \              # 固定主角
  --handle your_douyin_id \      # 页脚抖音号
  --pages 6 --panels 2 \         # 6 张图，每张 2 格
  --audience "刚毕业的大学生" \
  --angle "从被坑过三次的过来人视角" \
  --seed 20250918 \              # 固定种子，可复现
  --workers 3 \                  # 并发生图
  --zip                          # 额外打个包
```

其它命令：`script`（只出脚本）、`render`（用脚本出图）、`validate`（脚本体检）、`batch`（批量）、
`style list/show/add`、`character list/add/stylize`、`doctor`、`ui`。
每个都可以 `--help`。

---

## 设计上的两个关键取舍

**中文由本地字体渲染，不让画图模型写字。**
AI 画中文经常缺笔画、串字，一套 6 张糊一张就得重跑。本地渲染 100% 可控，
而且改文案不用重新烧钱生图。所以每条生图提示词里都硬写了"画面中不要出现任何文字"。

**每格单独生图，而不是一次生成整页。**
让模型一次画出"两格 + 横幅 + 页脚"，构图不可控、文字必糊。
本工具给每格单独要一张比画格大 1.15 倍的图再居中裁切，构图稳定，
某一格不满意也可以单独重画。

---

## 故障排查

| 现象 | 原因 / 解法 |
|---|---|
| 标题是方块 | 没有中文字体。`python -m dig doctor` 看提示；Linux: `apt-get install -y fonts-noto-cjk`；或把 .ttf 丢进 `assets/fonts/` |
| 提示缺 API Key | 检查 `.env` 里的 `ARK_API_KEY`；或先用 `--offline` |
| 某几格是占位图 | 那几格生图失败了，看 `manifest.json` 的 `errors`。重跑时相同 prompt 会命中缓存，只补失败的那几格 |
| 主角长得不一样 | 先确认 script.json 里有 `character` 块；锚点格默认开着，别关 |
| 画面里冒出乱码文字 | 正常现象，重跑那一格；或把 `--allow-text-in-image` 关掉（默认就是关的） |
| 连接被掐断 | 图生图并发的问题，`run.workers` 设 1、`run.attempts` 设 4 |
| 出图太慢 | 用到主角时必须串行，急不来；先 `script` 定稿文案再生图，避免反复生成 |

`python -m pytest tests -q` 跑离线冒烟测试（不联网、不花钱）。
没装 pytest 就 `python tests/test_smoke.py`。

---

## 目录

```
dig/                 代码
  cli.py             命令行入口
  pipeline.py        一键流水线
  script_gen.py      分镜脚本生成（内容质量在这里）
  prompt_builder.py  单格提示词拼装
  imagegen.py        并发/重试/缓存/兜底
  compositor.py      排版合成（横幅、边框、水印、做旧质感）
  character.py       个人 IP 主角
  style.py           画风预设 / 参考图反推
  fonts.py           字体发现 + 中文避头尾排版
  providers/         ark / openai / gemini / mock
styles/              画风预设 YAML，可自己加
prompts/             选题提示词（喂给 ChatGPT）
docs/                样例拆解
```
