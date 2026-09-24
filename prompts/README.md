# Prompts

*[中文版](README.zh-CN.md)*

| File | Purpose | Used by |
|---|---|---|
| `topic_ideation_zh.md` | **Topic ideation** — paste into ChatGPT | You, manually; produces `topics.json`. `dig batch` passes each topic's `title` / `type` / `beats_preview` / `hashtags` to the script writer |
| — | Shot-script system prompt | In code: `SYSTEM` in [`dig/script_gen.py`](../dig/script_gen.py) |
| — | Script repair prompt (one pass when validation fails) | In code: `REPAIR_TMPL` in [`dig/script_gen.py`](../dig/script_gen.py) |
| — | Style-derivation prompt | In code: `STYLE_SYSTEM` in [`dig/style.py`](../dig/style.py) |
| — | Character-sheet prompt | In code: `CHAR_SYSTEM` in [`dig/character.py`](../dig/character.py) |
| — | Per-panel prompt assembly | In code: [`dig/prompt_builder.py`](../dig/prompt_builder.py) |

The built-in prompts live in code on purpose: each is paired with JSON parsing and
character-count cleanup logic, and editing the prompt without editing the parser is a good
way to break things. To tune them, edit the corresponding `.py` — they are all declared at
the top of the file.

## Why `topic_ideation_zh.md` is in Chinese

It has to produce Chinese topics, Chinese hook lines and Chinese captions for a Chinese
platform. Writing the instructions in English would add a translation hop that costs output
quality for no benefit. Here is what it does, in English:

It tells the model to act as a Douyin content strategist for this specific format, then:

1. **Explains the format's mechanics** — 5–7 images, two panels each, 5–14 characters per
   caption, so one post is 10–14 information points that viewers swipe through.
2. **States five hard criteria** a topic must pass. The decisive one: the topic must split
   into **10–14 parallel, drawable points**. Abstract advice ("be patient") fails; concrete
   scenes ("queued three hours for one photo") pass.
3. **Supplies six proven topic templates** — glossary, contrast, checklist, process,
   counter-intuitive, identity — and requires at least four to be represented.
4. **Takes your account context** — niche, target audience, protagonist, art style, and
   topics you have already covered.
5. **Forces self-validation**: for every topic the model must write out the first four
   captions, proving the topic actually decomposes. If it cannot, it must pick a different one.
6. **Returns strict JSON** that feeds directly into `dig batch --file topics.json`.

Follow-up instructions at the bottom of the file let you re-score and replace weak topics,
expand one topic into a full 12-caption script, generate variants for a running series, or
reverse-engineer the template behind a competitor's post.
