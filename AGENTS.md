# Operating contract for agents

You are driving a generator that turns one topic into 5–7 postable Douyin carousel images.
Image generation **costs real money per panel** — a 12-panel set is 12 billed calls and
6–10 minutes. Follow this file and you will not waste either.

*[中文版见 README.zh-CN.md](README.zh-CN.md) — this file is the machine-facing contract.*

---

## The one workflow that works

```bash
# 1. Prove the toolchain works. Free, offline, ~10 seconds.
python -m dig doctor
python -m dig run --theme "任意主题" --offline

# 2. Write the script yourself. Do NOT call a text model for this.
#    Copy examples/script.minimal.json and replace the content.

# 3. Check it BEFORE spending anything. Free.
python -m dig validate --script my-script.json

# 4. Check the protagonist BEFORE the full set. One billed image.
python -m dig sheet --script my-script.json          # open the printed path and look at it

# 5. Only when validate is clean and the sheet looks right:
python -m dig render --script my-script.json         # → output/<timestamp>_<theme>/

# 6. Fix single panels, never the whole set:
python -m dig reroll --script output/<run>/script.json --panel 7
```

**Never skip step 3.** `render` runs the same checks and refuses on errors, but finding out
at step 5 means you have already paid for the character sheet.

**Do not skip step 4 for a new character or style.** The sheet anchors every panel and is
cached per character × style × model — a wrong one quietly spoils every set that uses it.
`dig render` reuses the approved sheet from the cache, so step 4 costs nothing extra.

`render` writes to a fresh `output/<timestamp>_<theme>/` when the script lives outside an
output folder (like `my-script.json` in the repo root), and updates in place when it is the
`script.json` of an earlier run. It never scatters files next to a hand-written script.

---

## Hard rules

These are enforced by `dig validate`. Violating them either fails the run or produces
output that cannot be posted.

| Rule | Why |
|---|---|
| **Two beats per page**, always | The reference format is two panels per image. A single beat per page makes the panel portrait-shaped, halves the information density, and the model tends to paint a dead area under the banner |
| Captions fit **one banner line** — 5–14 Chinese characters | `validate` measures the rendered width with the real font. A caption that wraps makes a tall banner that hides the art; one that needs a smaller size shrinks the **whole set** (one type size per set). Over 18 full-width characters is an error |
| **No serial numbers** in captions (`1.`, `第3格：`) | Viewers read content, not indices |
| **Every caption unique** | This format dies on repetition — one repeated beat loses a chunk of the audience |
| **Same beat count on every page** | Mixed 1/2-panel pages make the set look broken |
| **5–7 pages** (3–10 accepted) | Fewer is thin, more never gets swiped to the end |
| **Never ask for text in `scene`** | Panel prompts hard-forbid text in the image. "牌子上写着…" produces garbled glyphs. Captions are typeset locally afterwards |
| **Always define a `character`** | Without one the protagonist changes on every panel — measured, not theoretical |

## The character rule, specifically

This is the single highest-impact thing you control. On a live 12-panel run **without** a
character block, the protagonist went navy Mao suit → red vest → orange shirt with a
different face each time. Unusable as a series.

Put this in the script. No photo needed, no registration:

```json
"character": {
  "name": "阿鼠",
  "sheet": "圆脸卡通小老鼠，浅米色短毛，两只又大又圆的耳朵、内耳浅粉，黑色圆眼睛，短圆鼻头，永远穿同一件藏青色中山装：立领、胸前两个带盖口袋、白色窄袖口，身形矮胖",
  "signature": "藏青色中山装 + 白色窄袖口"
}
```

`sheet` must be concrete and 60+ characters: face, hair, eyes, clothing, one accessory.
Vague sheets do not hold. Then write every `scene` using **主角** to refer to them — never
re-describe their appearance per panel, and never give them a different name mid-set.

The tool also generates a **character sheet** — one scene-free portrait on a plain
background — and feeds it to every panel as a reference image (`run.character_lock` and
`run.character_sheet`, both on by default). Leave them on. The sheet is cached per
character × style × model, so it costs one image the first time and nothing afterwards.
Look at it with `dig sheet` before the first full render; replace it with `--redraw`.

For a **registered photo protagonist** (`--character my_ip`), the sheet is drawn *from the
photo in the current style*: the raw photo is never used as a panel reference, so its
background and photographic look cannot leak in. Key art from `dig character stylize` is
per style and only ever used for that style. A script's `character_id` is honoured by
`validate`, `render` and `reroll` alike; if it isn't registered on this machine, they stop
before spending.

Because the sheet has no scene in it, your `scene` text is the *only* thing deciding
composition. Vary it deliberately across the set — standing/crouching, interior/exterior,
wide/close — or every panel will look like the same shot with new props.

## Writing good captions

The set must read as one list, not twelve unrelated lines. Keep the sentence pattern
identical throughout — all `"X"是Y`, or all four-character phrases, or all imperatives.
That parallelism is what makes people swipe to the end.

First beat is the hook. Last beat is the payoff — the line worth screenshotting.

## Writing good scenes

`谁 + 在哪 + 在干什么 + 什么情绪`, 30–60 characters. Concrete and literal: the picture
should state the caption, not allude to it. Vary interior/exterior and wide/close across
the set while keeping the world consistent.

**Describe a full environment, not just the person.** Name what is behind and around them
— the far buildings, the wall, the sky, the other people. Panels are landscape and the
caption banner is composited *on top of* the artwork, so the art must reach the top edge
with real content. A scene that only describes a person produces a close-up with a dead
area under the banner. This was a measured failure, not a hypothetical: the generator now
checks every panel for it automatically (`run.quality_check`) and redraws once with a
blunter prompt, but a scene with a described background avoids the problem outright.

Good: `主角戴着黄色安全帽蹲在毛坯房里，伸手指着地面裸露的水管接口，身后是脚手架和两名正在抹灰的工人，天花板和墙面都是灰色混凝土，白天自然光`

Thin: `主角在工地检查质量` — no environment, no camera distance, no light.

---

## Cost and failure handling

- Each panel is one billed call, plus one for a new character sheet, plus up to one quality
  redraw per panel. Preflight prints this **worst case** before the first call; read it.
- **Caching is on, per engine and model.** Re-running the same script with the same model
  only regenerates panels whose prompt changed. Editing one scene and re-rendering costs one
  panel, not twelve. `--offline` output is never cached, so it cannot masquerade as real art.
- To re-typeset captions with **zero** image spend: `dig render --script X --skip-images`.
- To redraw specific panels: `dig reroll --script output/<run>/script.json --panel 3,7`
  (one billed call each). Never use `--no-cache` for this — it re-bills every panel.
- Panels that fail fall back to placeholder art so the set still completes, and the command
  exits **1**. `manifest.json` → `errors` names them; `dig reroll` redraws exactly those.
- `manifest.json` → `billing` records the calls actually made (`sheet` / `panel` / `redraw`)
  and cache hits. Report it to the user.
- A rejected key (HTTP 401/403) stops the run after **one** request and exits **2**.

Exit codes: `0` finished with real art everywhere · `1` finished with placeholders (or batch
topics failed) · `2` nothing generated (bad args/config, validation errors, key rejected).

## Provider gotchas (Volcengine AgentPlan, the verified path)

The shipped default config is **pay-as-you-go** Ark (`/api/v3`, Seedream 4.0). The path
verified end-to-end is **AgentPlan** (`/api/plan/v3`, Seedream 5.0 Lite); switching is two
lines in `config.yaml` — see the AgentPlan block in `config.example.yaml`. Ask the user for
their AgentPlan model ID; do not guess one.

Already handled in code — do not "fix" these:

- Endpoint is `/api/plan/v3`, not `/api/v3`.
- Minimum **3,686,400 total pixels** per image; smaller requests are rejected.
- No `seed` field on this endpoint.
- Image-to-image drops connections under concurrency, so `workers` is forced to 1 whenever
  reference images are used. Do not raise it.

Full detail: [docs/provider-notes.md](docs/provider-notes.md).

## Do not

- Do not call AgentPlan's text models. Write the script yourself.
- Do not use `--no-validate` to get past errors. Fix the script.
- Do not raise `run.workers` above 1 for runs that use a character.
- Do not put an API key into a file on the user's behalf — ask them to do it.
- Do not run a 12-panel set to "see if it works". Use `--offline` for that.
- Do not use `--no-cache` to redraw a panel. Use `dig reroll --panel N`.
- Do not treat exit code 1 as success. Placeholders are in the set.

## Before you report done

1. Open `preview.jpg` — the whole set on one sheet plus page 1 in a phone mock-up.
   Actually look at it, then open any page that looks off at full size.
2. Confirm the protagonist is the same person in every panel.
3. Confirm no garbled text appeared inside the art (`dig reroll` any panel that has it).
4. Check the exit code was 0 and `manifest.json` → `errors` is empty.
5. Confirm the footer watermark shows the right Douyin ID.
6. Tell the user how many billed calls were made (`manifest.json` → `billing.requests`).

`caption.txt` in the output directory carries this checklist plus the ready-to-paste post
copy.
