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
  (you/ChatGPT)     (LLM)     (image model)  (local Pillow)  + caption + hashtags + preview
                                    ▲
                    style preset + character sheet (one per character × style)
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
everything works before spending anything. Mock output is never written to the image cache,
so an offline preview can never be mistaken for real art later.

Then wire up a real model:

```bash
cp config.example.yaml config.yaml     # set your model IDs (AgentPlan block included)
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
preview.jpg             ← the whole set on one sheet + page 1 inside a phone mock-up (not for upload)
panels/                 ← raw per-panel art (redraw one with `dig reroll`)
character_sheet.png     ← the scene-free portrait every panel was anchored to
script.json             ← the shot script; edit it and re-render (relative paths: the folder is portable)
caption.txt             ← title, post copy, hashtags, per-panel lines, pre-publish checklist
manifest.json           ← model/style used, per-panel status, errors, and the billed calls actually made
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

| Preset | Look | Caption banner |
|---|---|---|
| `retro_comic` | aged print, halftone, heavy ink (closest to the reference posts) | warm-yellow rounded bar |
| `ins_minimal` | clean flat illustration, muted palette | white card, left-aligned |
| `guochao_ink` | ink wash + guochao colours | cinnabar plaque with inset line |
| `clay_3d` | clay stop-motion | white pill |
| `cyber_neon` | neon night city | dark bar with neon glow |
| `storybook` | watercolour picture book | torn washi tape |

The banner shape is part of the preset (`banner.shape`: `rounded` / `pill` / `plaque` /
`tape` / `glow`, plus `banner.position: left`), so a custom style can pick any of them.

### 2. Your photo as the protagonist (personal IP)

```bash
python -m dig character add --id my_ip --name 小圆 --photo me.jpg
python -m dig sheet --character my_ip --style retro_comic     # one image: look before you buy twelve
python -m dig run --theme "第一次租房避坑" --character my_ip --handle your_douyin_id
```

Character consistency is layered — drop one and the character starts drifting:

| Lock | Mechanism | Notes |
|---|---|---|
| Text | A vision model writes a "character sheet" from the photo | Face, hair, usual outfit, signature accessory — injected into every panel prompt |
| **Character sheet** | One scene-free portrait on a plain background, referenced by *every* panel | On by default (`run.character_sheet`). One per character × style × model, cached across posts. For a photo protagonist it is **drawn from the photo in the current style**, so the photo's background and photographic look never leak into the panels |
| Per-style key art | `character stylize --style X` saves key art for **that style only** | Takes priority for that style. A `retro_comic` portrait is never used to anchor a `guochao_ink` set |
| Panel-1 anchor | Fallback when no sheet can be produced | Locks identity but also leaks composition, so it is only the fallback |

Character locking is not optional in practice. Measured on a live 12-panel set **without**
it, the protagonist changed on every single panel — navy Mao suit → red vest → orange
shirt, with different faces and proportions throughout.

The sheet is deliberately **scene-free**. An earlier version used panel 1 as the anchor,
which locked identity but also leaked its *composition*: later panels inherited its
background — brick buildings and a stray ceiling lamp turning up inside a construction
site — and every frame drifted toward the same camera distance and pose. A plain-background
portrait has no scene to copy, so identity stays locked while framing stays free.

**Look at the sheet before a full run.** `dig sheet` draws only the sheet (one billed call)
and prints its path. If it's wrong, fix the description or `dig sheet --redraw`; once it's
right, the full render reuses it from the cache for free. A bad sheet would otherwise be
cached and quietly spoil every set that uses that character.

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
model provider you configure at generation time, and nowhere else. Set
`"use_photo_as_ref": false` on a character to never send the photo to the image model at all.

### 3. One command for the whole set — and one command to fix one panel

`run` does everything: write script → validate → generate panels → composite → export copy
and preview.

Rewriting captions does **not** require regenerating art:

```bash
python -m dig script --theme "..."                                    # script only
# edit the caption fields in script.json
python -m dig render --script output/xxx/script.json --skip-images    # re-typesets in seconds
```

Redrawing one panel costs one panel:

```bash
python -m dig reroll --script output/xxx/script.json --panel 7             # 1 billed call
python -m dig reroll --script output/xxx/script.json --panel 3,9           # 2 billed calls
python -m dig reroll --script output/xxx/script.json --panel 7 --scene "主角…" # new scene for that panel
```

Every other panel is reused as-is and the set is re-composited in place.

---

## Guard rails

Image generation bills per panel, so the tool refuses to spend on a script it can tell is
broken. Check any script for free before generating:

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

`run`, `render` and `reroll` apply the same checks and **refuse to start** on errors.
Warnings print and continue. `--strict` promotes warnings to errors; `--no-validate` skips
the lot, which you should not need.

What it catches: captions that won't fit on one banner line (**measured with the real font
and layout**, so `iPhone 16 Pro Max 值不值` passes while sixteen CJK characters wrap),
serial-numbered captions, duplicates, unbalanced quotes, empty or too-thin scenes, scenes
asking for text the renderer forbids, uneven panel counts, page counts outside the workable
range, a missing character block, and a `character_id` that isn't registered on this machine.

Other rails that are just on:

- **Preflight** checks the API key, the model id and the CJK font, then prints the panel
  count, the **worst-case number of billed calls** (panels + sheet + quality redraws) and a
  time estimate — before the first billed call.
- **Caching is per engine and model.** Re-running a script only regenerates panels whose
  prompt changed; switching models (or going from `--offline` to a real run) regenerates
  everything, because another model's picture is not your picture. *Upgrading from 0.3:
  the key and the prompts changed, so the first re-render of an old script regenerates.*
- **A rejected key stops the run at the first request.** 401/403 abort the set; 400-class
  errors are not retried; only network drops, 429 and 5xx are.
- **Every panel is inspected after generation.** The compositor lays the caption banner
  *on top of* the artwork, so the art has to reach the top edge. Asking the model to
  "leave space for the title" made it paint a flat void there instead — measured at
  standard deviation below 2, in almost exactly the paper colour. Panels are checked for
  that and redrawn once with a blunter prompt (`run.quality_check`); if both attempts fail,
  the **better** one is kept (both were paid for). Styles built on flat colour planes loosen
  the threshold (`quality.max_dead_bands` in the preset).
- **Reference images force serial generation.** Image-to-image drops connections under
  concurrency, so `workers` is pinned to 1 whenever a character is in play.
- **Failed panels fall back** to placeholder art so a set always completes, with the
  failures listed in `manifest.json` — and the command **exits 1**, so nothing downstream
  mistakes a partial set for a finished one.

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
   "audience": "准备买房的年轻人", "pages": 6,
   "title": "楼盘名里的暗号，第4个我笑出声",
   "beats_preview": ["“湾”是附近有河流", "“府”是想卖贵一点"],
   "hashtags": ["#买房"] }]
```

`title`, `type`, `beats_preview` and `hashtags` are passed to the script writer as a head
start — the ideation prompt already proved those first captions decompose, so they're worth
keeping.

That prompt is deliberately strict about the one constraint that decides whether a topic
works in this format: **it must split into 10–14 parallel, drawable points.** It forces the
model to write out the first four captions as proof before a topic is accepted. The prompt
itself is in Chinese because its output must be Chinese;
[prompts/README.md](prompts/README.md) explains what it does in English.

When the text model writes a script, it is validated immediately; if the check finds
problems the model can fix (duplicates, over-long captions, serial numbers, scenes asking
for text), the issues are fed back for **one** repair pass and the better version is kept.

---

## Web UI

```bash
python -m dig ui        # http://127.0.0.1:8765
```

A two-step flow that mirrors the CLI's "check before you spend" rule:

1. **Write** — enter a topic (or load the example script) and generate a script.
2. **Edit** — every caption and scene is an editable row with a live width counter; the
   full validation runs as you type, with the worst-case billed-call count. "出图" stays
   disabled while there are errors.
3. **Render** — panels appear as they finish, then the pages, `preview.jpg` and the
   ready-to-paste post copy.
4. **Redraw** — any panel can be re-rolled from the results (1 panel = 1 billed call).

Built on `http.server` — no Flask, no Gradio. It only accepts requests whose `Host` is the
local machine, and every API call must carry a per-session token from the page, so other
websites open in your browser cannot trigger billed generation.

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
Render the validated rental-traps script with the retro_comic style and Douyin handle my_account. First run dig sheet and show me the character sheet. After rendering, open preview.jpg, confirm character consistency and readable captions, then check manifest.json for errors and billing. Redraw only failed or flawed panels with dig reroll.
```

**Register a photo-based protagonist**

```text
Register ./me.jpg once as character id my_ip with the display name 小圆. Run dig sheet for the retro_comic style and show me the result. Then prepare and validate a carousel about “Mistakes I made buying my first home”. Before any billed image call, report the page count and panel count.
```

Every command is plain CLI with meaningful exit codes:

| Exit | Meaning |
|---|---|
| `0` | Finished; every panel is real art |
| `1` | Finished, but some panels are placeholders (see `errors` in `manifest.json`), or some batch topics failed |
| `2` | Nothing was generated: bad arguments or config, validation errors, or the API key was rejected |

Output paths are deterministic:

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
  "preview": "preview.jpg",
  "stats": { "panels_ok": 12, "panels_total": 12, "seconds": 96.4 },
  "billing": { "billed": true, "requests": 13, "by_kind": { "sheet": 1, "panel": 12 }, "cache_hits": {} },
  "panels": [ { "panel": 1, "caption": "…", "image": "panels/01.png", "status": "ok" } ],
  "errors": []
}
```

A non-empty `errors` means some panels fell back to placeholder art; `dig reroll --panel N`
redraws exactly those. Register the protagonist once with an explicit `--id` (avoids using
a Chinese name as a key) and reuse it forever after. `render --script` on a script that
lives in an output folder updates that folder in place; a hand-written script elsewhere
gets a fresh `output/<timestamp>_<theme>/`, so nothing is written next to it.

---

## Swapping models

The shipped default is **pay-as-you-go Volcengine Ark** (Doubao for text, Seedream 4.0 for
images, `/api/v3`). The path verified end-to-end against the live service is **Ark
AgentPlan** (`/api/plan/v3`, Seedream 5.0 Lite) — `config.example.yaml` has a ready block
for it. Edit `config.yaml`:

```yaml
providers:
  image:
    provider: ark                          # ark | openai | gemini | mock
    model: doubao-seedream-4-0-250828      # or your own inference endpoint ID
    api_key_env: ARK_API_KEY
```

| provider | Text | Images | Notes |
|---|---|---|---|
| `ark` | Doubao | Seedream 4.0 / 5.0 | Reachable from mainland China, strong Chinese comprehension, multi-reference support |
| `openai` | gpt-4.1 etc. | gpt-image-1 | Also covers any OpenAI-compatible service — DeepSeek, SiliconFlow, vLLM, Ollama |
| `gemini` | gemini-2.5-flash | gemini-2.5-flash-image | Strongest character consistency; the key travels in a header, never in the URL |
| `mock` | templates | placeholders | Offline, for verifying the pipeline; never cached |

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
  --zip                          # also produce a zip
```

`--seed` makes compositions reproducible on engines that accept a seed (pay-as-you-go
Seedream 4.0); AgentPlan has no seed field and ignores it. `--workers` only matters for sets
without a protagonist — any run that uses reference images is serial.

Other commands: `script`, `render`, `validate`, `sheet`, `reroll`, `batch`,
`style list|show|add`, `character list|add|stylize`, `doctor`, `ui`. All support `--help`.

---

## Image quality

Everything in the first table was measured on real Seedream 5.0 output, then fixed, then
re-measured. Re-rendering existing panels is free (`--skip-images`), so each change was
compared against identical art.

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

The page chrome — everything drawn locally — was measured the same way:

| Finding | Fix | Result |
|---|---|---|
| On Linux (CI, agent containers) captions rendered with **Japanese glyph forms** — Noto CJK's collection index 0 is JP; all 10 captions of the example script were affected (房、没、次、退…) | Collection faces are picked by name, preferring Simplified Chinese; `doctor` prints the face and warns if it isn't SC | Noto Sans CJK **SC** Black |
| Caption text sat **10 px above centre** (48 px above the ink, 68 below) because the band was sized from the font's line height | Band sized and centred on the **ink box**, equal padding | Within 1 px in every preset; band 208 → 173–180 px, returning art |
| One long caption shrank only its own banner, so a set showed two type sizes | One caption size per set (the size the longest caption needs) | Uniform banners; `validate` warns *before* a long line shrinks the set |
| The white watermark had **1.06–1.28:1** contrast against five of six paper colours; the ♪ had no outline | `watermark.color: auto` — ink on light paper, light on dark; icon drawn like the text | ≥ 4.5:1 in every preset, readable at feed-thumbnail size |
| "Grain" was a 6% blend toward grey: black ink lifted to ~7, paper white down to ~247 | Zero-mean noise weighted to midtones | Pure black and white exactly untouched; midtone mean shift < 1 level |
| Six presets differed only in colour | Per-style banner shapes (`rounded`, `pill`, `plaque`, `tape`, `glow`, left-aligned) and organic paper-edge wear | — |

The layout scales with the canvas, so other sizes work too — including non-3:4
canvases, where it scales by the tighter axis so captions cannot overflow.

---

## Two design decisions worth knowing

**Chinese text is rendered locally by Pillow, never drawn by the image model.**
Image models routinely mangle Chinese glyphs, and a single bad panel ruins a six-image set.
Local rendering is fully deterministic — and it means rewriting copy costs seconds instead
of another round of paid generation. Every panel prompt explicitly forbids text in the image,
and the palette is described in colour words rather than hex codes that a model could paint.

**Each panel is generated separately, not as a whole page.**
Asking a model to draw "two panels plus banners plus a footer" gives up control of
composition and guarantees mangled text. Instead each panel is requested at the panel's
own aspect ratio, a little larger than its box, and fitted locally — so composition stays
stable and any single panel can be re-rolled without touching the others.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Captions render as boxes | No CJK font. Run `python -m dig doctor`; on Linux `apt-get install -y fonts-noto-cjk`, or drop a `.ttf` into `assets/fonts/` |
| Some characters look Japanese | The font face isn't Simplified Chinese. `dig doctor` names the face; set `text.font` / `text.font_index` in `config.yaml` |
| "missing API key" | Check `ARK_API_KEY` in `.env`, or use `--offline` |
| "图像服务拒绝了请求（HTTP 401/403）" | Key invalid or expired, or the model isn't enabled on the account. The run stopped after one request |
| Some panels are placeholders | Those generations failed — see `errors` in `manifest.json`, then `dig reroll --panel N` |
| One panel looks wrong | `dig reroll --script output/xxx/script.json --panel N` (optionally `--scene "…"`) |
| Protagonist looks different per image | Check the sheet with `dig sheet`; make sure the script has a `character` block or a registered `character_id` |
| Garbled text appears inside the art | Expected occasionally — `dig reroll` that panel. `--allow-text-in-image` is off by default |
| Too slow | Runs with a protagonist are serial by design (image-to-image drops concurrent connections). Lock the copy with `script` + `validate` first so you generate art only once |

Run the offline test suite (no network, no cost):

```bash
python -m pytest tests -q        # or: python tests/test_smoke.py
```

---

## Layout

```
dig/                 source
  cli.py             command-line entry point and exit codes
  pipeline.py        end-to-end orchestration, reroll, batch
  validate.py        pre-spend script checks (captions measured with the real font)
  script_gen.py      shot-script generation + one validate→repair pass
  prompt_builder.py  per-panel prompt assembly
  imagegen.py        concurrency, retries, caching, fallback, single-panel redraw
  charsheet.py       scene-free character sheet (one per character × style × model)
  quality.py         post-generation panel inspection
  compositor.py      composition: banners, borders, watermark, aged texture
  harmonize.py       set-wide colour harmonisation
  preview.py         preview.jpg: contact sheet + phone mock-up
  ledger.py          billed-call accounting for manifest.json
  character.py       personal-IP protagonist
  style.py           style presets / reference-image derivation
  fonts.py           font discovery (SC face selection) + CJK line breaking
  webui.py           local web UI
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
