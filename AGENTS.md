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
#    Pick the idea from the source library first (prompts/topic_ideation_zh.md §四),
#    then copy examples/script.minimal.json and replace the content.

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
| **Every caption is an instruction** the viewer can carry out | The account's promise is "watch it, then do it". A question or a teaser panel teaches nothing. `dig validate` warns on question marks, trailing ellipses and teaser words (`caption-teaser`) |
| **No serial numbers** in captions (`1.`, `第3格：`) | Viewers read content, not indices |
| **Every caption unique** | This format dies on repetition — one repeated beat loses a chunk of the audience |
| **Same beat count on every page** | Mixed 1/2-panel pages make the set look broken |
| **5–7 pages** (3–10 accepted) | Fewer is thin, more never gets swiped to the end |
| **Never ask for text in `scene`** | Panel prompts hard-forbid text in the image. "牌子上写着…" produces garbled glyphs. Captions are typeset locally afterwards |
| **No 《book titles》 in `scene`** | "主角翻开《易经》" makes the model paint the title as garbled glyphs on the cover. Put the book in `source` and the post copy (`scene-book-title`) |
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
character × style, so it costs one image the first time and nothing afterwards.

Because the sheet has no scene in it, your `scene` text is the *only* thing deciding
composition. Vary it deliberately across the set — standing/crouching, interior/exterior,
wide/close — or every panel will look like the same shot with new props.

## Choosing and framing the topic

The goal of every set: **a viewer finishes it knowing what to do.** Not "that was
interesting", but "I learned something, and next time I'll do exactly this."

Frame topics from the books in the source library,
[prompts/topic_ideation_zh.md](prompts/topic_ideation_zh.md) §四 取材库. It covers Munger,
Schopenhauer, Wang Yangming, 曾仕强's 易经, Wu Jun, the 66 rules for dealing with people,
the historical strategy stories, 黄帝内经 daily habits and the proverb collections. Each entry
lists only ideas that turn directly into actions. Then:

1. Pick **one specific idea** from one book, e.g. Munger's inversion or the six dragons of 乾.
2. Put it in the script's `source` field: `"《穷查理宝典》· 反过来想"`. It is printed in
   `caption.txt` for the operator and never drawn.
3. Choose a structure: rules, stages, steps, don't/do pairs, "when X, do Y", or old saying
   plus today's action. The library says which structures suit each book.
4. Translate the idea into **today's situations**: work, people, money, sleep, study,
   decisions. Stay faithful to the book. Never invent quotes or chapters.

Boundaries. Break one and the topic is out:

- Teach people to protect themselves, get things done and get along. Never teach scheming,
  deceiving or getting back at people (the 66-rules book has plenty of that; skip it).
- Health means daily habits only (sleep, food, mood, movement). No diagnosis, treatment,
  remedies or dosages. Add "身体不适请及时就医" to the post copy.
- Money means habits and principles only. No stock picks, no promised returns.
- No absolute claims (一定, 根治, 稳赚). 易经 is about how to act, never fortune-telling.

## Writing good captions

Each caption is **one instruction, in the imperative, concrete enough to act on today**:

- Start with the action: `先…` / `别…` / `…前先…` / `遇到…就…` / `把…换成…`.
- Name the act, the object or the test. `要有耐心` fails. `等一晚再回消息` works.
- State the answer on the panel. No questions, no `第4个绝了`, no `看到最后`. Suspense
  belongs in the post copy, if anywhere.
- When you use a classical term or a book's concept, follow it straight away with the plain
  action: `潜龙期：闷头练本事`, `量体裁衣：先算再花`.

The set must read as one list, not twelve unrelated lines. Keep the sentence pattern
identical throughout: all `先X`, or all `别X`, or all `阶段：做Y`. That parallelism is
what makes people swipe to the end.

The two panels on one image are a pair: one "do this" and one "don't do that", or two
consecutive steps, or two responses to the same situation.

First beat is the hook: the most useful or least obvious instruction, stated plainly. Last
beat is the payoff, the one line that sums up the set and is worth screenshotting. The `note`
on each beat says why the instruction works; it feeds the voice-over and is never drawn.

Good (from `examples/script.minimal.json`): `潜龙期：闷头练本事` / `潜龙期：别急着出头`.

Thin: `心态决定一切` (no action), `第3个我笑了` (teaser), `你为什么总存不下钱？` (question).

## Writing good scenes

`谁 + 在哪 + 在干什么 + 什么情绪`, 30–60 characters. Concrete and literal: the picture
should state the caption, not allude to it. **Show the protagonist carrying out this panel's
instruction**, in a situation viewers meet today. For a `别…` caption, draw the moment they
stop, hold back or say no. Draw neither the book nor the historical figures; the story goes
into `note` and the post copy. Vary interior/exterior and wide/close across the set while
keeping the world consistent.

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
  changed. Editing one caption and re-rendering costs one panel, not twelve. The cache is
  kept per engine, so `--offline` placeholders are never served to a real render.
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
5. Read the captions in order. Each one must be an instruction a viewer could act on today.
   If the idea comes from a book, `source` and the post copy both name it.

`caption.txt` in the output directory carries this checklist plus the ready-to-paste post
copy.
