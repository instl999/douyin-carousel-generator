# Prompts

*[中文版](README.zh-CN.md)*

| File | Purpose | Used by |
|---|---|---|
| `topic_ideation_zh.md` | **Topic ideation + book source library**: paste into ChatGPT; agents also pick ideas from it | You, manually; produces `topics.json`. `dig batch` passes each topic's `source` / `title` / `type` / `beats_preview` / `hashtags` to the script writer |
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

It tells the model to act as a Douyin content strategist for this specific format, for an
account whose one promise is **"watch it, then do it"**. Then it:

1. **Explains the format's mechanics**: 5–7 images, two panels each, 5–14 characters per
   caption. One post is therefore 10–14 instructions that viewers swipe through.
2. **States five hard criteria** a topic must pass. The decisive one: the topic must split
   into **10–14 parallel pieces of advice a viewer can act on today**, each drawable as the
   protagonist doing it. Abstract advice ("be patient") fails; a concrete action ("wait a
   night before replying") passes.
3. **Sets the caption voice: plain counsel that works on its own.** Many viewers see one
   image by itself, so each caption states the situation and what to do in everyday words,
   like 刚入行，先把基本功练扎实. Book terms, classical phrases, metaphors and label prefixes
   like 潜龙期： stay off the images; they go in the title, post copy and voice-over note.
4. **Supplies six structures that teach**: rules, stages, steps, don't/do pairs, "when X, do
   Y", and the plain advice behind old sayings. At least four must be represented.
5. **Carries a source library** of the reference books: Munger's *Poor Charlie's Almanack*,
   Schopenhauer's *The Wisdom of Life*, Okada Takehiko's biography of Wang Yangming, 曾仕强's
   lectures on the 易经, Wu Jun's 见识, a book of 66 rules for dealing with people, a six-volume
   set of historical strategy stories, 曲黎敏 on the 黄帝内经, and two proverb and aphorism
   collections. For each it lists only the ideas that turn directly into actions,
   paraphrased rather than quoted, with the structures they suit and an example topic.
   At least 9 of the 12 topics must come from it, drawing on at least 5 books.
6. **Sets content boundaries**: teach self-protection, not scheming (the 66-rules book needs
   that filter); health means daily habits, never diagnosis or remedies; money means habits,
   never stock picks; no absolute claims; the 易经 is about how to act, not fortune-telling;
   no invented quotes.
7. **Takes your account context**: niche, target audience, protagonist, art style, and
   topics you have already covered.
8. **Forces self-validation**: for every topic the model must write out the first four
   captions as plain standalone counsel, proving the topic actually decomposes. If it
   cannot, it must pick a different one.
9. **Returns strict JSON** that feeds directly into `dig batch --file topics.json`. Each
   topic's `source` field travels into the shot-script prompt, so the script stays faithful to
   the book, and is printed in `caption.txt`.

Follow-up instructions at the bottom of the file let you re-score and replace weak topics,
expand one topic into a full 12-caption script, build a running series from one book, or
reverse-engineer the structure behind a competitor's post.

Agents writing scripts by hand ([AGENTS.md](../AGENTS.md)) use the same library: pick one
idea, put it in the script's `source`, and turn it into instructions. The books themselves
are not in this repository; the library is a paraphrased digest.
