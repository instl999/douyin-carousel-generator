# Reference breakdown: the two-panel explainer comic

*[中文版](format-analysis.zh-CN.md)*

Analysed from 72 images spanning four accounts/series: a Jerry-the-mouse folk-proverb
series, two Squidward series (property-naming explainers and personality contrasts), and a
white-cat-lady series (posing tips and property explainers). This document records where
the tool's layout constants come from.

## 1. The shared layout skeleton

Every sample uses the identical structure:

```
┌──────────────────────────┐  ← aged paper ground, 3–5% margin all round
│ ┌──────────────────────┐ │
│ │      ╭──────────╮    │ │  ← caption banner: rounded rect, warm yellow/cream
│ │      │  caption  │    │ │     fill, thin dark stroke, centred heavy black CJK type
│ │      ╰──────────╯    │ │
│ │                      │ │  ← art fills the panel, subject centred and low
│ │        [art]         │ │
│ └──────────────────────┘ │
│ ┌──────────────────────┐ │  ← second panel, structurally identical
│ │      ╭──────────╮    │ │
│ │      │  caption  │    │ │
│ │      ╰──────────╯    │ │
│ │        [art]         │ │
│ └──────────────────────┘ │
│      ♪ 抖音号：XXXXXX      │  ← footer watermark, white text with dark outline
└──────────────────────────┘
```

| Element | Observed | Tool default |
|---|---|---|
| Canvas ratio | 3:4 (originals at 1792×2400 and 1080×1440) | `1440×1920` |
| Outer margin | ~2.5–3.5% of edge length | `margin: 46` |
| Gap between panels | ~1.5% of height | `gap: 26` |
| Panel border | Dark brown/black, 4–6px | `border: 5`, `#2B2622` |
| Banner fill | Warm yellow `#E9C877` / cream-tan `#D9C3A0` | `#E9C877` |
| Banner position | ~3% down from the panel top | `top: 34` |
| Banner width | Tracks text length, max ~88% of panel | `max_width: 0.88` |
| Caption typeface | Heavy black sans (Source Han Sans Heavy class), pure black | Auto-detected system CJK bold |
| Caption length | **5–14 characters**, most commonly 6–10 | `clean_caption` caps at 14 |
| Footer | Music-note glyph + `抖音号：xxx`, white with dark outline | `footer: 128` |
| Texture | Halftone + paper grain + vignette + worn edges | Four `texture` toggles |

## 2. Content rules (these matter more than the layout)

1. **One post = one theme = 10–14 parallel information points.** Six images × two panels
   = twelve points.
   - Property series: 湾 / 岸 / 馆 / 府 / 城 / 山 — one glossary entry per panel.
   - Personality series: 稳重的人 / 共情能力差 — one trait per panel, alternating positive
     and negative.
   - Proverb series: 「女婿本是墙外树」「再粗不是顶梁柱」 — the two panels of one image form
     a couplet.

2. **Sentence structure stays parallel across the whole set.** Either everything is
   `"X" means Y`, or everything is a four-character phrase. That rhythm is the direct cause
   of people swiping all the way to the end.

3. **The protagonist is fixed.** The same character appears in every image of a series
   (Jerry / Squidward / the white cat), identical in face, clothing and accessories. That is
   exactly the personal-IP play, and what `--character` exists to reproduce.

4. **The art states the caption literally**, with no metaphor. "Living by the water" means
   drawing a balcony with a river outside it. The viewer should not have to think.

5. **Scenes vary, the world does not.** Interior/exterior, day/night, wide/close alternate,
   while the art style, palette and character design stay locked.

## 3. Two engineering decisions that follow from this

**① Text is rendered locally, not drawn by the model.**
The Chinese in the sample banners has clean, uniform strokes — it was composited afterwards.
AI-generated Chinese routinely drops strokes or swaps characters, and one bad panel out of
six means regenerating. Local rendering is fully deterministic, and it means copy edits cost
nothing: `dig render --script script.json --skip-images` re-typesets in seconds. Hence every
panel prompt hard-forbids text in the image.

**② Panel art is generated per panel, not per page.**
Asking a model to draw a complete page — two panels, banners, footer — surrenders control of
composition and guarantees mangled text. Instead each panel is requested at 1.15× its final
box and centre-cropped, so composition stays stable and any single panel can be re-rolled
independently.

## 4. Douyin's hard constraints

- Carousel posts allow up to 35 images; 3:4 or 9:16 are recommended. This tool defaults to 3:4.
- The app UI covers roughly the bottom 200–260px (caption area and buttons), so nothing
  important belongs there. The footer watermark is placed at the top edge of that zone,
  right on the safe line.
- The first image decides click-through, which is why `prompt_builder.cover_hint()` adds
  extra emphasis to panel 1.
