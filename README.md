# douyin-carousel-generator

**One topic in → a ready-to-post set of 5–7 Douyin carousel images out.**

[中文文档](README.zh-CN.md) · [**Agent contract**](AGENTS.md) · [Format breakdown](docs/format-analysis.md) · [Provider notes](docs/provider-notes.md)

Generates the "two-panel explainer comic" (双格科普漫画) format that performs well on
Douyin: each image is split into two panels, each panel carries one short caption banner,
and the whole set covers a single theme. Art style is configured up front — pick a preset,
describe one in a sentence, or hand it a reference image and let a vision model derive it.
You can also register **your own photo as the recurring protagonist**, which is what makes
this usable for personal-IP account operation.

The layout constants and content rules were reverse-engineered from 72 real posts across
four accounts — see [docs/format-analysis.md](docs/format-analysis.md).

```
     topic ──► shot script ──► panel art ──► composite ──► postable images
  (you/ChatGPT)     (LLM)     (image model)  (local Pillow)  + caption + hashtags
                                    ▲
                          style preset + character photo
```

> **Language note:** the tool generates **Chinese** content for Chinese-language Douyin
> accounts, so prompts, captions and CLI output are in Chinese by design. This README and
> `docs/` are English; the Chinese originals sit alongside as `*.zh-CN.md`.

---

## Quick start

```bash
pip install -r requirements.txt
python -m dig doctor                                      # check deps, fonts, API keys
python -m dig run --theme "楼盘名字里的暗号" --offline      # dry run, costs nothing
```

`--offline` swaps every engine for a built-in **mock**: no network, no API key, placeholder
art — but the layout, typography, export and caption logic are all real. Use it to confirm
everything works before spending anything.

Then wire up a real model:

```bash
cp config.example.yaml config.yaml     # set your model IDs
cp .env.example .env                   # set your API key
python -m dig run --theme "楼盘名字里的暗号" --style retro_comic --handle your_douyin_id
```

On Windows:

```powershell
.\run.ps1 "楼盘名字里的暗号" -Handle your_douyin_id
```

Output lands in `output/<timestamp>_<theme>/`:

```
pages/01.jpg … 06.jpg   ← the finished images, ready to upload
panels/                 ← raw per-panel art (for re-rolling a single panel)
script.json             ← the shot script; edit it and re-render
caption.txt             ← title, post copy, hashtags, per-panel lines, pre-publish checklist
manifest.json           ← which model/style/seed was used, and which panels failed
```

---

## The three core capabilities

### 1. Art style, configured up front

```bash
python -m dig style list                                   # 6 built-in presets
python -m dig run --theme "..." --style guochao_ink
python -m dig run --theme "..." --style-prompt "1990s Hong Kong comic, heavy linework, high contrast"
```

**Derive a style from a reference image:**

```bash
python -m dig style add --from-image reference.jpg --name 复古港漫 --id hk_retro
python -m dig run --theme "..." --style hk_retro
```

A vision model reads only the **style** — linework, colouring method, palette, texture,
era — and never the subject matter. The result is written to `styles/hk_retro.yaml`, which
you can hand-tune and reuse indefinitely.

Built-in presets: `retro_comic` (closest to the reference posts), `ins_minimal`,
`guochao_ink`, `clay_3d`, `cyber_neon`, `storybook`.

### 2. Your photo as the protagonist (personal IP)

```bash
python -m dig character add --id my_ip --name 小圆 --photo me.jpg --stylize
python -m dig run --theme "第一次租房避坑" --character my_ip --handle your_douyin_id
```

Character consistency across a set uses **three locks** — drop any one and the character
starts drifting between images:

| Lock | Mechanism | Notes |
|---|---|---|
| Text | A vision model writes a "character sheet" from the photo | Hair, features, usual outfit, signature accessory — injected into every panel prompt |
| Reference image | The photo is passed as a reference image | Supported by Seedream, gpt-image-1 edits, and Gemini image |
| **Styled key art** | `--stylize` generates a stylised portrait first | Every later panel references *that* instead, locking identity **and** art style together |
| **Character sheet** | One scene-free portrait on a plain background, referenced by *every* panel | On by default (`run.character_sheet`). Generated once per character × style and cached across posts |

Character locking is not optional in practice. Measured on a live 12-panel set **without**
it, the protagonist changed on every single panel — navy Mao suit → red vest → orange
shirt, with different faces and proportions throughout.

The sheet is deliberately **scene-free**. An earlier version used panel 1 as the anchor,
which locked identity but also leaked its *composition*: later panels inherited its
background — brick buildings and a stray ceiling lamp turning up inside a construction
site — and every frame drifted toward the same camera distance and pose. A plain-background
portrait has no scene to copy, so identity stays locked while framing stays free. Panel 1
is still used as a fallback when no sheet can be produced.

**Mascot series need no photo.** If your protagonist is a drawn character rather than a
real person, describe it inline in `script.json` and skip registration entirely:

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

The script writer also picks up the character's inferred voice, so the copy reads like that
person rather than generic explainer prose.

Photos stay in `characters/<id>/` on your machine (gitignored). They are sent to whichever
model provider you configure at generation time, and nowhere else.

### 3. One command for the whole set

`run` does everything: write script → generate panels concurrently → composite → export copy.

Rewriting captions does **not** require regenerating art:

```bash
python -m dig script --theme "..."                                    # script only
# edit the caption fields in script.json
python -m dig render --script output/xxx/script.json --skip-images    # re-typesets in seconds
```

---

## Guard rails

Image generation bills per panel, so the tool refuses to spend on a script it can tell is
broken. Check any script for free before generating:

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

`run` and `render` apply the same checks and **refuse to start** on errors. Warnings print
and continue. `--strict` promotes warnings to errors; `--no-validate` skips the lot, which
you should not need.

What it catches: captions over length, serial-numbered captions, duplicates, unbalanced
quotes, empty or too-thin scenes, scenes asking for text the renderer forbids, uneven panel
counts, page counts outside the workable range, and a missing character block.

Other rails that are just on:

- **Every panel is inspected after generation.** The compositor lays the caption banner
  *on top of* the artwork, so the art has to reach the top edge. Asking the model to
  "leave space for the title" made it paint a flat void there instead — measured at
  standard deviation below 2, in almost exactly the paper colour. Panels are now checked
  for that and redrawn once with a blunter prompt (`run.quality_check`). The check is
  two-dimensional on purpose: a gradient sky is flat within each scanline but varies
  vertically, and must not be mistaken for a void.
- **Reference images force serial generation.** Image-to-image drops connections under
  concurrency, so `workers` is pinned to 1 whenever a character is in play.
- **Preflight** checks the API key, the model id and the CJK font, and prints the panel
  count and time estimate, before the first billed call.
- **Caching.** Re-running a script only regenerates panels whose prompt changed.
- **Failed panels fall back** to placeholder art so a set always completes, with the
  failures listed in `manifest.json`.

Driving this from an agent? [AGENTS.md](AGENTS.md) is the operating contract, and
[schema/script.schema.json](schema/script.schema.json) plus
[examples/script.minimal.json](examples/script.minimal.json) are the machine-readable
templates.

---

## Batch topics with ChatGPT

1. Copy the content between the `---` rules in
   [prompts/topic_ideation_zh.md](prompts/topic_ideation_zh.md) into ChatGPT and fill in
   your account positioning. It returns a JSON list of topics.
2. Save it as `topics.json`.
3. Generate them all:

```bash
python -m dig batch --file topics.json --style retro_comic --character my_ip --handle your_douyin_id
```

Topic file shape (full example in `examples/topics.sample.json`):

```json
[{ "theme": "楼盘名字里的那些字分别代表什么档次",
   "angle": "从第一次看售楼部的买房小白视角",
   "audience": "准备买房的年轻人", "pages": 6 }]
```

That prompt is deliberately strict about the one constraint that decides whether a topic
works in this format: **it must split into 10–14 parallel, drawable points.** It forces the
model to write out the first four captions as proof before a topic is accepted. The prompt
itself is in Chinese because its output must be Chinese;
[prompts/README.md](prompts/README.md) explains what it does in English.

---

## Web UI

```bash
python -m dig ui        # http://127.0.0.1:8765
```

Fill in a topic, pick a style from a dropdown, drag in a photo to register a protagonist,
click once. Binds to localhost only and is built on `http.server` — no Flask, no Gradio.

---

## Driving it from an agent or script

**Codex or Claude Code is the recommended interface.** Open this repository in
either agent and describe the topic, account voice, style and protagonist in
plain language. Ask it to read [AGENTS.md](AGENTS.md) before doing any work: the
contract makes the agent write and validate the script locally before it starts
image generation, which keeps expensive mistakes out of the billed stage.

Volcengine Ark Agent Plan image calls are **still billed per panel**. They are
usually cheaper than standard pay-as-you-go calls, but they are not free; the
current price and actual charge in the Ark console are the source of truth.

Copy-paste examples for Codex or Claude Code:

**Set up and test without paid calls**

```text
Read AGENTS.md and README.md, install the dependencies, run dig doctor, and complete one --offline test. Do not call any paid model. Tell me what API key, model ID, or CJK font is still missing.
```

**Draft and validate a carousel before generating art**

```text
Create a 6-page, two-panel-per-page script about “Six traps first-time renters miss” in a practical, plainspoken voice. Use examples/script.minimal.json and the schema, define one consistent mascot, and run dig validate. Show me all captions, the panel count, and the number of billed image calls; do not render yet.
```

**Generate the final carousel**

```text
Render the validated rental-traps script with the retro_comic style and Douyin handle my_account. Inspect every finished page, confirm character consistency and readable captions, then check manifest.json for errors. Reuse the cache and regenerate only failed or changed panels.
```

**Register a photo-based protagonist**

```text
Register ./me.jpg once as character id my_ip with the display name 小圆 and create styled key art. Then prepare and validate a carousel about “Mistakes I made buying my first home”. Before any billed image call, report the page count and panel count.
```

Every command is plain CLI. Exit codes: `0` success, `2` bad arguments/config, `1` a batch
where everything failed. Output paths are deterministic:

```bash
python -m dig run --theme "$THEME" --character my_ip --handle "$HANDLE" --out ./out/task123
```

Then read `./out/task123/manifest.json`:

```json
{
  "title": "...", "pages": 6, "panels_per_page": 2,
  "style": { "id": "retro_comic", "name": "复古双格漫画" },
  "character": { "id": "my_ip", "signature": "圆框眼镜 + 藏青外套" },
  "files": ["01.jpg", "…", "06.jpg"],
  "stats": { "panels_ok": 12, "panels_total": 12, "seconds": 96.4 },
  "errors": []
}
```

A non-empty `errors` means some panels fell back to placeholder art, so an agent can decide
whether to re-run. Register the protagonist once with an explicit `--id` (avoids using a
Chinese name as a key) and reuse it forever after.

---

## Swapping models

Defaults to **Volcengine Ark** (Doubao for text, Seedream 4.0 for images). Edit `config.yaml`:

```yaml
providers:
  image:
    provider: ark                          # ark | openai | gemini | mock
    model: doubao-seedream-4-0-250828      # or your own inference endpoint ID
    api_key_env: ARK_API_KEY
```

| provider | Text | Images | Notes |
|---|---|---|---|
| `ark` | Doubao | Seedream 4.0 | Reachable from mainland China, strong Chinese comprehension, multi-reference support |
| `openai` | gpt-4.1 etc. | gpt-image-1 | Also covers any OpenAI-compatible service — DeepSeek, SiliconFlow, vLLM, Ollama |
| `gemini` | gemini-2.5-flash | gemini-2.5-flash-image | Strongest character consistency |
| `mock` | templates | placeholders | Offline, for verifying the pipeline |

The three roles (`text` writes scripts, `vision` reads photos, `image` draws) are configured
independently, so you can pair a cheap text model with the best image model.

---

## Common flags

```bash
python -m dig run \
  --theme "第一次租房避坑" \
  --style retro_comic \          # style preset
  --character my_ip \            # fixed protagonist
  --handle your_douyin_id \      # footer watermark
  --pages 6 --panels 2 \         # 6 images, 2 panels each
  --audience "刚毕业的大学生" \
  --angle "从被坑过三次的过来人视角" \
  --seed 20250918 \              # reproducible composition
  --workers 3 \                  # concurrent image generation
  --zip                          # also produce a zip
```

Other commands: `script`, `render`, `validate`, `batch`, `style list|show|add`,
`character list|add|stylize`, `doctor`, `ui`. All support `--help`.

---

## Image quality

Everything below was measured on real Seedream 5.0 output, then fixed, then re-measured.
Re-rendering existing panels is free (`--skip-images`), so each change was compared
against identical art.

| Finding | Fix | Result |
|---|---|---|
| **69% of every generated panel was discarded.** AgentPlan forces ≥3.7 MP per image, and a 1440×1920 page only uses 1.2 MP of it | Default canvas raised to **1792×2400** — the exact size of the reference originals | Discard drops to 49%. **Generation cost unchanged** — those pixels were already being paid for |
| Print texture was applied *after* the captions, putting grain on the text | Texture now goes on paper and art only; captions and watermark are composited afterwards | Caption banner is pixel-identical with grain on or off. Caption contrast +6.5% |
| Downscaling 1.4–1.8× blurred halftone dots and hatching | Mild unsharp mask after significant downscales only (`page.sharpen`) | Fine-detail edge energy **+19%**. Tuned down after an earlier setting left visible halos on the thickest ink lines |
| A six-panel set looked like six print runs: brightness varied by ~42 levels, warmth by ~22 | Partial per-channel gamma pulling each panel toward the set median (`page.harmonize`) | Brightness spread −23–29%, colour-cast spread −18%, **pure black ink untouched** |

Two details in that last row matter. Harmonisation is deliberately **partial** (50%) —
a night scene should stay darker than a sunlit one. And it uses **gamma curves rather than
a colour shift**: shifting would have lifted the black linework to grey, which is the one
thing this style cannot afford. Gamma pins pure black and pure white in place and moves
only the midtones.

The layout now scales with the canvas, so other sizes work too — including non-3:4
canvases, where it scales by the tighter axis so captions cannot overflow.

---

## Two design decisions worth knowing

**Chinese text is rendered locally by Pillow, never drawn by the image model.**
Image models routinely mangle Chinese glyphs, and a single bad panel ruins a six-image set.
Local rendering is fully deterministic — and it means rewriting copy costs seconds instead
of another round of paid generation. Every panel prompt explicitly forbids text in the image.

**Each panel is generated separately, not as a whole page.**
Asking a model to draw "two panels plus banners plus a footer" gives up control of
composition and guarantees mangled text. Instead each panel is requested at 1.15× its final
box and centre-cropped, so composition stays stable and any single panel can be re-rolled
without touching the others.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Captions render as boxes | No CJK font. Run `python -m dig doctor`; on Linux `apt-get install -y fonts-noto-cjk`, or drop a `.ttf` into `assets/fonts/` |
| "missing API key" | Check `ARK_API_KEY` in `.env`, or use `--offline` |
| Some panels are placeholders | Those generations failed — see `errors` in `manifest.json`. Re-running reuses cached panels, so only the failures are retried |
| Protagonist looks different per image | Run `character stylize` to create the key art; or switch to a provider with reference-image support |
| Garbled text appears inside the art | Expected occasionally — re-roll that panel. `--allow-text-in-image` is off by default |
| Too slow | Raise `--workers`; or lock the copy with `script` first so you generate art only once |

Run the offline smoke tests (no network, no cost):

```bash
python -m pytest tests -q        # or: python tests/test_smoke.py
```

---

## Layout

```
dig/                 source
  cli.py             command-line entry point
  pipeline.py        end-to-end orchestration
  script_gen.py      shot-script generation (content quality lives here)
  prompt_builder.py  per-panel prompt assembly
  imagegen.py        concurrency, retries, caching, fallback
  compositor.py      composition: banners, borders, watermark, aged texture
  character.py       personal-IP protagonist
  style.py           style presets / reference-image derivation
  fonts.py           font discovery + CJK line breaking
  providers/         ark / openai / gemini / mock
styles/              style preset YAML — add your own
prompts/             topic-ideation prompt for ChatGPT
docs/                reference-format breakdown, provider API notes
```

## Status

The **Volcengine AgentPlan** path (Seedream 5.0 Lite) is verified end-to-end against the
live service. The offline path is covered by the test suite. The OpenAI and Gemini paths
are written from documentation and have **not** been exercised — if a request shape needs
adjusting, [docs/provider-notes.md](docs/provider-notes.md) names the exact field, and
`image_extra` / `chat_extra` in `config.yaml` let you inject arbitrary payload fields
without touching code.

Two settings that matter when generating with reference images (character lock, photo
protagonists) against AgentPlan:

```yaml
run:
  workers: 1     # image-to-image drops connections under concurrency
  attempts: 4    # and needs the retries
```

See the verified-behaviour table in the provider notes for why.

## License

MIT — see [LICENSE](LICENSE).
