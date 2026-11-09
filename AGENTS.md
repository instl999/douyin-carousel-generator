# Operating contract for agents

You are driving a generator that turns one topic into 5–7 postable Douyin carousel images.
Image generation **costs real money per panel** — a 12-panel set is 12 billed calls and
6–10 minutes. Follow this file and you will not waste either.

*This file is the machine-facing contract.*

---

## The one workflow that works

```bash
# 1. Prove the toolchain works. Free, offline, ~10 seconds.
python -m dig doctor
python -m dig run --theme "any topic" --offline

# 2. Write the script yourself. Do NOT call a text model for this.
#    Pick the idea from the source library first (prompts/topic_ideation_zh.md §4),
#    then copy examples/script.minimal.json and replace the content.

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
| **Every caption stands alone** as plain counsel | Many viewers see one image by itself: the cover, a single swipe, a forwarded screenshot. A caption that needs the rest of the set, a book's term or a metaphor teaches them nothing. `dig validate` warns on teasers and questions (`caption-teaser`) and on label prefixes such as `Hidden-dragon phase:` (`caption-label`) |
| **No serial numbers** in captions (`1.`, `第3格：`) | Viewers read content, not indices |
| **Every caption unique** | This format dies on repetition — one repeated beat loses a chunk of the audience |
| **Same beat count on every page** | Mixed 1/2-panel pages make the set look broken |
| **5–7 pages** (3–10 accepted) | Fewer is thin, more never gets swiped to the end |
| **Never ask for text in `scene`** | Panel prompts hard-forbid text in the image. "the sign says..." produces garbled glyphs. Captions are typeset locally afterwards |
| **No book titles in `scene`** | "the protagonist opens the I Ching" makes the model paint the title as garbled glyphs on the cover. Put the book in `source` and the post copy (`scene-book-title`) |
| **Always define a `character`** | Without one the protagonist changes on every panel — measured, not theoretical |

## The character rule, specifically

This is the single highest-impact thing you control. On a live 12-panel run **without** a
character block, the protagonist went navy Mao suit → red vest → orange shirt with a
different face each time. Unusable as a series.

Put this in the script. No photo needed, no registration:

```json
"character": {
  "name": "A Shu",
  "sheet": "round-faced cartoon mouse, short light-cream fur, two big round ears with pale-pink inner ears, black round eyes, a short round nose, always wearing the same navy Zhongshan suit: stand collar, two flap chest pockets, narrow white cuffs, short and stout",
  "signature": "navy Zhongshan suit + narrow white cuffs"
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

## Choosing and framing the topic

The goal of every set: **a viewer finishes it knowing what to do.** Not "that was
interesting", but "I learned something, and next time I'll do exactly this."

Frame topics from the books in the source library,
[prompts/topic_ideation_zh.md](prompts/topic_ideation_zh.md) §4 Source library. It covers Munger,
Schopenhauer, Wang Yangming, Zeng Shiqiang's I Ching, Wu Jun, the 66 rules for dealing with people,
the historical strategy stories, the Yellow Emperor's Inner Canon daily habits and the proverb collections. Each entry
lists only ideas that turn directly into actions. Then:

1. Pick **one specific idea** from one book, e.g. Munger's inversion or the six dragons of Qian.
2. Put it in the script's `source` field: `"Poor Charlie's Almanack · Invert"`. It is printed in
   `caption.txt` for the operator and never drawn.
3. Choose a structure: rules, stages, steps, don't/do pairs, "when X, do Y", or the plain
   advice behind old sayings. The library says which structures suit each book.
4. Translate the idea into **today's situations and everyday words**: work, people, money,
   sleep, study, decisions. Stay faithful to the book. Never invent quotes or chapters.
   The book's own terms go in the title, the post copy and `note`, never on the images.

Boundaries. Break one and the topic is out:

- Teach people to protect themselves, get things done and get along. Never teach scheming,
  deceiving or getting back at people (the 66-rules book has plenty of that; skip it).
- Health means daily habits only (sleep, food, mood, movement). No diagnosis, treatment,
  remedies or dosages. Add "see a doctor promptly if unwell" to the post copy.
- Money means habits and principles only. No stock picks, no promised returns.
- No absolute claims (certainly, root cure, guaranteed profit). the I Ching is about how to act, never fortune-telling.

## Writing good captions

Many viewers see one image by itself: the cover, a single swipe, a screenshot a friend
forwarded. **Every caption must stand alone.** Someone who sees only that one image, with
no idea what the set is about, should understand it at a glance and learn something to do.

So write each caption as **plain, straightforward counsel**, the way someone who has been
through it would tell you: *the situation* + *what to do or not do*.

- `Just starting out, first make the basics solid` · `Lending to a friend, lend only what you can lose` · `When skills are not enough, don't rush to show off`
- Everyday words only. No book concepts, classical phrases, jargon or metaphors on the
  image, and no label prefixes like `Hidden-dragon phase:` or `老话：`. The frame (the six dragons of Qian, the book,
  the proverb) goes in the title, the post copy and `note`. A saying that is already
  everyday counsel, like `borrow and return, and borrowing is easy again`, can go on the image as it is.
- Concrete, not a platitude. Name the situation and the action. `Be low-key` is true and
  teaches nothing.
- State the answer on the panel. No questions, no `第4个绝了`, no `看到最后`.
- Aim for 9–13 characters: room for the situation and the advice without shrinking the font.

| Instead of | Write |
|---|---|
| `Hidden-dragon phase: quietly build your skills` (a label only the set explains) | `Just starting out, first make the basics solid` |
| `Leaping-dragon phase: try a small jump first` (label and metaphor) | `Want to change careers: try it in your spare time first` |
| `Cut the cloth to fit: calculate before spending` (proverb as label) | `Before spending, calculate how much you earn` |
| `Attitude decides everything` (no action) | `When criticized, hear it out before explaining` |
| `Why can't you ever save money?` (question) | `On payday, save ten percent first` |

The set must still read as one list. Give every caption the same shape, situation then
advice, at roughly the same length. That parallelism is what makes people swipe to the end.

The two panels on one image are a pair: one "do this" and one "don't do that", or two
consecutive steps, or two responses to the same situation.

First beat is the hook: the most useful or least obvious advice. Last beat is the payoff,
the one line that sums up the set and is worth screenshotting. The `note` on each beat says
why the advice works and carries the book's own term (`The hidden dragon does not act: when skills are not enough, build strength first`); it
feeds the voice-over and is never drawn.

## Writing good scenes

`who + where + doing what + what emotion`, 30–60 characters. Concrete and literal: the picture
should state the caption, not allude to it. **Show the protagonist carrying out this panel's
instruction**, in a situation viewers meet today. For a `don't...` caption, draw the moment they
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

Good: `The protagonist crouches in a bare concrete room wearing a yellow hard hat, pointing at an exposed pipe joint in the floor, scaffolding and two plasterers behind him, grey concrete ceiling and walls, natural daylight`

Thin: `The protagonist inspects quality at a construction site` — no environment, no camera distance, no light.

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
5. Read each caption on its own, as a stranger would. It must make sense without the others
   and tell them something they can do today. If the idea comes from a book, `source` and
   the post copy both name it.
6. Tell the user how many billed calls were made (`manifest.json` → `billing.requests`).

`caption.txt` in the output directory carries this checklist plus the ready-to-paste post
copy.
