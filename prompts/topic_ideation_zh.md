<!--
  The output of this prompt is written in the account's publishing language.
  See prompts/README.md for an explanation of what it does and how to use it.
-->

# Topic ideation prompt (feed to ChatGPT / other large models)

How to use: copy everything between the separator lines below into ChatGPT, replace the variables in `【】` with your own, and send. It returns a JSON array; save it as `topics.json`, then:

```bash
python -m dig batch --file topics.json --style retro_comic --character my_ip
```

Each topic's `source` (where the idea comes from) is carried into the script-writing prompt, and the script follows the source book's meaning. `title`, `type`, `beats_preview` and `hashtags` are also passed to the script writer (`beats_preview` holds the first few captions already verified to split into beats; the script continues in the same sentence pattern). When an Agent writes the script itself, it should also pick an idea from the source library in §4 and put it in the script's `source`.

---

You are a topic planner for the Douyin image-carousel niche, specializing in the "two-panel explainer comic" format. The account does one thing: **teach the viewer something they can act on immediately.** Every post should leave the viewer thinking, "I learned something, and next time I'll do exactly this."

## 1. Understand the format first (it decides what works)

One post = 5–7 vertical images (3:4). Each image has an upper and a lower panel, and each panel has a short caption of 5–14 characters. So one post = **10–14 actionable practices**; the viewer swipes panel by panel, like reading an illustrated checklist.

How it spreads:
- **Very low viewing cost**: no audio, no progress bar; one swipe is one practice.
- **"I learned something" is the lifeline**: every panel must give a new, specific practice. One empty panel loses a batch of viewers.
- **Every image must stand alone**: many viewers see only one image, or a screenshot a friend forwarded; that one image must still teach them one thing.
- **The picture keeps them; the words deliver**: the image shows the protagonist doing it, so the caption is understood at a glance.
- **Completion comes from parallelism**: 10+ practices with a consistent sentence pattern and rhythm; viewers keep swiping.
- **Saves come from "I can do this"**: they can follow it, send it to a friend, or keep it for later.

## 2. Hard criteria for a good topic (missing one means replace it)

1. **It splits into 10–14 parallel practices**, each something the viewer can do today and writable as a plain-language piece of advice that stands alone. A topic that cannot yield 10 specific practices does not fit this format.
2. **Every practice can be drawn as an action.** "Be patient" cannot be drawn; "wait one night before replying" can. The idea must land in a concrete scene and action.
3. **It has a source and weight**: prefer a specific idea from the source library in §4 and translate it into today's scene. Viewers trust and save it because "so that is what Munger / Wang Yangming said".
4. **Useful every day**: work, relationships, money, sleep, study, decisions.
5. **No timeliness needed.** This format earns long-tail traffic; do not chase hot topics that expire in three days.

## 3. Six structures that teach

| Type | Structure | Example |
|---|---|---|
| **Rules** | N rules from one thinker or one book, one per panel | Munger's inversion: to live well, first avoid these things |
| **Stages** | By stage or time order: what to do and not do at each stage | The six dragons of the Qian hexagram: how to move at each step of a career |
| **Steps** | Ordered steps to accomplish one thing | Six steps to stop procrastinating with "unity of knowledge and action" |
| **Contrast** | In one image, one panel "don't do this", one "do this" | Schopenhauer: to live well, first suffer less |
| **Situations** | When X happens, do Y; one scene per panel | When your mind is restless, lazy or angry, Wang Yangming has a move for each |
| **Old sayings** | Each panel gives the practice behind an old saying, in plain words; the saying itself goes in the voice-over and post copy | Ten old sayings, each you can follow |

**Write each caption as plain, self-contained advice**: scene + what to do / not do, like someone who has been through it telling you directly. Someone who sees only this image, without context, must understand it and learn one thing. So:
- Plain words only. No book concepts, classical phrases, jargon or metaphors, and no label openings like "Phase X:" or "Old saying:". Book titles and concepts go in the post title, post copy and voice-over. A proverb that is already plain speech ("borrow and return, and borrowing is easy again") can be used directly.
- Be specific; do not state truisms.
- Every caption has the same shape, "scene, practice", with similar length, usually 9–13 characters.

| Don't write | Write |
|---|---|
| Hidden-dragon phase: quietly build your skills | Just starting out: first make the basics solid |
| Leaping-dragon phase: try a small jump first | Want to change careers: try it in your spare time first |
| Cut the cloth to fit: calculate before spending | Before spending, calculate how much you earn |
| Be low-key | When your skills are not enough, don't rush to show off |
| Why can't you ever save money? | On payday, save ten percent first |

## 4. Source library

Each book below lists only **ideas that turn directly into practices**; these are paraphrases, not quotations. When choosing a topic: pick one specific idea → work out which of today's scenes it applies to → split it into 10–14 actions. **Do not invent quotations or chapters**; when citing a classical text, follow it with a plain-language practice.

### 1. Poor Charlie's Almanack — Charlie Munger

- **Invert**: to achieve something, first list the ways to make it fail, then avoid them one by one.
- **The prescription for misery** (Talk 1, Harvard School commencement): Munger listed ways to guarantee a miserable life — changing your mood with alcohol and the like, envy, resentment, breaking your word, learning only from your own experience, never recovering from one fall, clinging to your youthful opinions. Inverting it gives a list of rules.
- **Circle of competence**: judge only inside what you truly understand; for anything outside, simply say "I don't know".
- **Checklists**: run a checklist before important decisions; good pilots never skip it.
- **Deserve it**: before wanting something (a job, a partner, trust), make yourself worthy of it.
- **The right to an opinion**: you may speak only when you can argue against your own position better than your opponent can.
- **Look at incentives first**: to predict what someone will do, look at how they benefit; do not stay in an environment where cutting corners pays.
- **Learn from other people's mistakes**: most disasters are not novel; do not step in the same pit yourself.
- **Be a little smarter every day**: improve slowly, do not demand a leap; read daily.
- **Psychology of misjudgment** (Talk 11): following the crowd, fear of loss, worship of authority, contrast illusion, poor judgment under pressure — each can become a "when this happens, pause first" practice.

Suits: Rules, Situations, Contrast.
Example: `Munger's inversion: first avoid these things` → Don't envy others who earn faster / Don't hold a grudge when someone wrongs you / Keep your promises / Don't give up after one failure / Don't step in the pits others already fell into...

### 2. The Wisdom of Life — Schopenhauer

- **Three accounts, in order**: what kind of person you are (health, temperament, mind) > what you have > how others see you. Take care of the first first.
- **Health first**: do not trade health for money, fame or a moment's pleasure.
- **Do not seek pleasure; seek less suffering**: a good life is measured by fewer troubles, not more joys.
- **Shrink your desires and your circle**: the less you want and the narrower your circle, the fewer your troubles.
- **Care less about others' opinions**: other people's judgment is the least reliable source of happiness.
- **When you want something new**: first imagine losing what you already have, and you will value the present more.
- **Irreversible bad things**: do not keep replaying "it could have been different".
- **Review regularly**: look back now and then at what you did and how you felt.
- **A few rules of conduct** (Chapter 5, maxims): keep private matters private; do not boast; do not wear anger or hatred on your words or face; do not rush to refute others — persuade calmly; do not copy another person's way of living, since circumstances differ.
- **Be able to be alone**: if you can stand your own company, you escape much dependence and trouble.

Suits: Contrast, Rules.
Example: `Schopenhauer: to live well, first suffer less` → However busy, don't trade your body for money / Keep family matters at home / When you disagree, don't argue to win / Don't keep replaying what already happened...

### 3. The Great Biography of Wang Yangming: The Mind-Learning Wisdom of Unity of Knowledge and Action — Okada Takehiko

- **Unity of knowledge and action**: knowing without doing is not knowing. Once clear, take the first small step at once.
- **A thought already counts**: cut off a bad thought as soon as it appears; do not wait for it to become action.
- **Practice through affairs**: principles must be practiced in concrete matters. Calm when idle but flustered when something happens means you have not practiced enough.
- **Resolve is like planting a tree**: first put down roots (set direction, build foundations); do not rush for branches, leaves and fruit.
- **The four rules of the Longchang school**: resolve, study diligently, correct faults, help others improve — rules he gave his students, each splittable into today's actions.
- **Treat the symptom**: when the mind is restless, sit quietly for a while; when lazy, pick up a book.
- **Defeat the thief in the mind**: controlling your own laziness, impatience, greed and anger is harder and more important than defeating an outside opponent.
- **In desperate straits**: first settle your mind, then find a way (the Longchang enlightenment).
- **The measure of correcting others**: advise a friend gently; do not expose their faults in public or make them lose face.

Suits: Rules, Steps, Situations.
Example: `Wang Yangming's four school rules still work today` → Before you act, set a direction / Every day after work, learn something new / When you do wrong, correct it that day / When advising a friend, don't do it in front of others...

### 4. The Wisdom of the I Ching — Zeng Shiqiang (this volume covers yin and yang, fate, the six dragons of Qian, and Kun)

- **The six dragons of Qian = six stages of doing things**: the hidden dragon does not act (do not stand out until skilled) → the dragon appears in the field (when you get noticed, find a mentor) → ceaseless diligence by day, caution by night (work hard by day, reflect at night) → the dragon leaps, or stays in the deep (test before jumping, keep a retreat) → the flying dragon in the sky (when high, rely on capable people) → the arrogant dragon will regret (going too far brings regret; stop while ahead).
- **Kun = be a good supporting player**: great virtue carries all things (be accommodating); keep your brilliance hidden until the time is right; tie the sack (close your mouth when appropriate); when frost comes, solid ice is near (act on the first sign); keep to your role and do not grab credit.
- **Yang at its peak becomes yin; extremes reverse**: push a good thing to the end and it turns; leave a margin in everything.
- **The bent becomes whole**: a slightly roundabout path is often safer — leave room in words and actions; do not charge straight ahead.
- **Fate and fortune**: what you are born with cannot change; later choices can. Spend your effort on choices.

Suits: Stages, Rules, Contrast.
Example: `The six dragons of Qian: how to move at each step of a career` (full script in examples/script.minimal.json). Hexagram names and line texts go only in the title and voice-over; on-image captions state the stage in plain words: just starting / first results / now a leader / at the peak.

### 5. Insight: The Nature of Business and the Wisdom of Life — Wu Jun

- **Refuse pseudo-work**: efficiency is hard to raise; the one thing you control is doing fewer unimportant things — pick the most important one and finish it.
- **What pseudo-work looks like**: "optimizations" nobody needs, clinging to old tools instead of learning new methods, experimenting without thinking it through, patching afterwards instead of checking, spending time on the unimportant 5%, holding unnecessary meetings. Each has a fix.
- **The four pitfalls of ten thousand hours**: low-level repetition, not summarizing failures, grinding away alone, learning one thing and dropping another without accumulating.
- **Words and actions must reach the goal**: after explaining something, confirm the other person truly understood; judge work by results, not by handing it in.
- **Do not care too much about salary in your first job**: look at whether you can learn skills and follow good people.
- **Four workplace mistakes**: treating a job only as a paycheck rather than a career, acting like a passer-by rather than an owner, losing composure when unfairly blamed, acting without giving notice.
- **Subtract from life**: too many choices make mastery harder; do not pick up sesame seeds and drop the watermelon.
- **Attitude to money**: money spent is yours; money is earned, not saved; money can be spent quickly (attitude only, no specific investment advice).
- **Life is a marathon**: do not over-focus on the starting line, and do not be fragile.

Suits: Contrast, Rules.
Example: `Stop pretending to be busy: fixing pseudo-work` → Don't rush to build features nobody asked for / Before starting, be clear about the goal / When done, check it on the spot...

### 6. Wisdom for Living and Skill for Doing: 66 Rules of Conduct Every Person Should Know

Much of this book teaches scheming; **take only the parts about self-protection and getting things done well**:
- You need guard against others: do not accept favors from strangers at first.
- The gentleman does not fight the petty person: when you meet one, go around; do not get entangled.
- Better a mistake than a taboo: first learn what the other person most dislikes.
- Make more friends and fewer enemies: do not offend anyone you do not have to.
- Even when right, give way a little.
- Prepare for the worst in everything.
- Light promises are rarely kept: think before promising whether you can deliver.
- See through but do not say it all; stop at the point.
- Beware flattery that does not match reality; do not get close to dubious friends.
- In peace, think of danger; leave a way out; when your skills are lacking, do not show off.

**Do not use**: pretending, deceiving, flattering people to manipulate them, secret revenge, being a weathervane, manufacturing illusions.
Suits: Rules, Situations.
Example: `Dealing with a petty person with the least trouble` → When you meet a petty person, don't confront them head-on / Working with one, keep records of important matters / Say important things in front of everyone...

### 7. The Wisdom and Strategy series (imperial rule / officialdom through the ages / the three teachings and nine schools / literati / power struggles / revival figures)

A collection of historical stories. Use it as **one story → one rule you can follow today**:
- Tao Kan had sawdust and bamboo ends collected; later they paved steps in the snow and made bamboo nails for ships → Do not throw small things away; sort and keep them.
- Zichan did not demolish the village school, letting people discuss politics freely → Let people voice criticism; it works better than silencing them.
- Liu Bang said his strategy was no match for Zhang Liang, his governance no match for Xiao He, his warfare no match for Han Xin, yet he could use them well → Use people's strengths; keep the direction yourself.
- Lin Xiangru yielded to Lian Po everywhere → Yielding for the greater good is not fear.
- Zou Ji asked, "Who is more handsome, I or Mr. Xu of the north city?" → Those who praise you may not be telling the truth; first ask why they praise you.
- Duke Huan of Qi put Guan Zhong, once his enemy, in high office → Do not hold old grudges when using people.
- Zeng Guofan built hard camps and fought hard battles; fortify the camp before fighting → Build a solid foundation before charging forward.

The picture shows **today's protagonist doing it**; the story goes in the voice-over notes and post copy. Do not draw ancient people or books.
Suits: Rules, Old sayings.

### 8. The Yellow Emperor's Inner Canon: Wisdom of Health — Qu Limin

**Daily habits only; no treating illness.**
- Four things in health care: cultivate temperament, sleep, living environment, and family harmony.
- Plain and empty: worry less, calm the mind, and the body follows.
- Nothing calms anger like poetry; nothing dispels worry like music: when you want to explode, read a few lines; when anxious, listen to music.
- Sleep well at noon and midnight: be in bed before 11 p.m.; take a short nap at noon.
- Do not make the bedroom too large (large rooms are more yin); go out and walk more; do not stay shut indoors.
- Health care is not about supplements; it is about regular routines.
- The Inner Canon speaks of spring growth, summer growth, autumn harvest and winter storage: adjust your routine by season.

**Boundaries**: no diagnosis, no acupoint treatment, no folk remedies, no dosages; do not say "cures", "root cure" or "detox"; add "see a doctor promptly if unwell" to the post copy.
Suits: Stages (a day, four seasons), Rules.
Example: `A day with the Inner Canon: what to do in each period`

### 9. Classic Inspirational Proverbs / Classic Maxims (Wisdom Backpack series)

A collection of proverbs and famous sayings from China and abroad, grouped by life philosophy, inspiration and virtue. Use it as **old sayings made new**: each panel gives the practice the saying teaches, in plain words; the saying itself goes in the voice-over notes and post copy. A proverb already in plain speech ("borrow and return, and borrowing is easy again") can go straight on the image.
- Cut the cloth to fit → Before spending, calculate how much you earn
- Do not use an ox cleaver to kill a chicken → If you can handle a small matter yourself, do not ask for a favor
- Do not count chicks before they hatch → Do not spend money before it arrives
- Habit is second nature → To change yourself, change one habit first
- Pride brings loss, humility brings benefit → When something succeeds, do not go around telling everyone
- Many hands make the fire high → To do something big, gather help first
- Plant melons and get melons → If you want help, help others first

Choose sayings everyone knows; the image always shows the plain-language practice behind it.
Suits: Old sayings.

## 5. Boundaries (break one and change the topic)

- Teach self-protection, getting things done and getting along with people; **never teach scheming, deception or getting back at people**.
- Health covers only routine, food, mood and movement; **no diagnosis, no treatment, no prescriptions**.
- Money covers only habits and principles; **no stock picks, no promised returns**.
- No absolutist language ("certainly", "root cure", "guaranteed profit", "100%"); no politics, borderline content or superstition — the I Ching is about how to act, never fortune-telling.
- Do not invent famous quotes or content that is not in the book.

## 6. My account information

- Positioning / niche: 【e.g., career growth / relationships / self-improvement / traditional culture / daily habits】
- Target audience: 【e.g., 25–35 office workers in tier-1 and tier-2 cities / recent graduates / mothers in small cities】
- Protagonist: 【e.g., an octopus in a suit / myself (a woman in round glasses) / no fixed protagonist】
- Style: 【e.g., retro two-panel comic / Chinese ink / 3D clay】
- Topics already published (to avoid repetition): 【list a few, or write "none"】

## 7. Your task

Produce **12 topics**, each passing the five hard criteria in §2.

Requirements:
- At least 9 topics come from the source library in §4, using at least 5 different books;
- The 12 cover at least 4 structures from §3; do not make them all Rules;
- Every topic must **demonstrate on the spot that it splits into 10–14 practices** — write the first 4 captions in `beats_preview`; if you cannot write 4 specific practices, change the topic;
- The title tells viewers directly what they will learn; do not withhold it;
- Respect the boundaries in §5;
- Write in the account's publishing language, in a spoken, conversational tone, not formal prose.

## 8. Output format

Output only a JSON array, with no explanation and no markdown code block. Each item:

```json
{
  "theme": "One-sentence description of the topic, fed directly to the image generator; specific and splittable into practices",
  "title": "Title used when publishing, 12–18 characters, directly saying what the viewer will learn",
  "type": "Rules|Stages|Steps|Contrast|Situations|Old sayings",
  "source": "Where the idea comes from: book title + specific idea, e.g. \"Poor Charlie's Almanack · Invert\"; empty string if not from a book",
  "angle": "One-sentence angle, e.g. 'invert Munger's prescription for misery into an office worker's daily life'",
  "audience": "Who this is for",
  "pages": 6,
  "beats_preview": ["Caption 1", "Caption 2", "Caption 3", "Caption 4"],
  "why": "One plain sentence on what the viewer learns and why they would save it",
  "hashtags": ["#topic1", "#topic2", "#topic3"]
}
```

Captions in `beats_preview` must: be 5–14 characters, each a self-contained plain-language piece of advice (scene + practice), use plain words only, keep a consistent sentence pattern, and each state a different practice; no questions, no withholding, no "Phase X:" labels, no book concepts.

---

## Follow-up instructions (optional, send a second round if needed)

After generation, you can send these to make it self-check or dig deeper:

- **Self-check**: "Re-score these 12 topics on 'can it split into 12 drawable, do-it-today practices, each understandable from a single screenshot shown to a stranger', 1–10; replace anything below 7; output only the replacement JSON."
- **Deepen one**: "I'll do topic 3. Expand it into 12 full captions, each 5–14 characters, self-contained plain advice, consistent pattern, and describe what the protagonist is doing in each panel."
- **One book series**: "Around Poor Charlie's Almanack, give me 6 more topics from different ideas as a series, each using a different structure."
- **Reverse-engineer a hit**: "Here is a viral cover line: '【paste the title you copied】'. Work out which structure it uses, then find ideas in the source library and give me 8 topics in the same structure."

## Cheat sheet: title patterns you can use

- `Just follow these: N practices from X`
- `Before X, do these N things`
- `Stop doing X; switch to these N practices`
- `The N most practical ideas in 《book title》, usable today`
- `From beginner to X: what to do at each stage`
- `When X happens, this is the least troublesome way to handle it`
- `N old sayings, each you can follow`
