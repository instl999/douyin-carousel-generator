# Operating contract for agents

You are driving a generator that turns one topic into 5–7 postable Douyin carousel images.
Image generation **costs real money per panel** — a 12-panel set is 12 billed calls and
6–10 minutes. Follow this file and you will not waste either.

*[中文版见 README.zh-CN.md](README.zh-CN.md) — this file is the machine-facing contract.*

---

## The one workflow that works

```bash
# 1. Prove the toolchain works. Free, offline, ~7 seconds.
python -m dig doctor
python -m dig run --theme "任意主题" --offline

# 2. Write the script yourself. Do NOT call a text model for this.
#    Copy examples/script.minimal.json and replace the content.

# 3. Check it BEFORE spending anything. Free.
python -m dig validate --script my-script.json

# 4. Only when validate is clean:
python -m dig render --script my-script.json
```

**Never skip step 3.** `render` runs the same checks and refuses on errors, but finding out
at step 4 means you have already paid for the anchor panel.

---

## Hard rules

These are enforced by `dig validate`. Violating them either fails the run or produces
output that cannot be posted.

| Rule | Why |
|---|---|
| **Two beats per page**, always | The reference format is two panels per image. A single beat per page makes the panel portrait-shaped, halves the information density, and the model tends to paint a dead area under the banner |
| Captions are **5–14 Chinese characters** | Longer and the layout shrinks the font, so sizes differ between panels in one set |
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

The tool also generates panel 1 first and feeds it to every later panel as a reference
image (`run.character_lock`, on by default). Leave it on.

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

- Each panel is one billed call. `pages × panels` = your bill. Check it before running.
- **Caching is on.** Re-running the same script only regenerates panels whose prompt
  changed. Editing one caption and re-rendering costs one panel, not twelve.
- To re-typeset captions with **zero** image spend: `dig render --script X --skip-images`.
- Panels that fail fall back to placeholder art so the set still completes. Check
  `manifest.json` → `errors` afterwards and re-run to fill them in.

## Provider gotchas (Volcengine AgentPlan, the default)

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

## Before you report done

1. Open the generated images. Actually look at them.
2. Confirm the protagonist is the same person in every panel.
3. Confirm no garbled text appeared inside the art.
4. Check `manifest.json` → `errors` is empty.
5. Confirm the footer watermark shows the right Douyin ID.

`caption.txt` in the output directory carries this checklist plus the ready-to-paste post
copy.
