# Plain-language writing guide (English)

> **First principle: notes are written for a human to read, not for a machine to parse.**
> This guide governs the flesh (wording); `templates.en.md` governs the skeleton (structure).
> Scope: the full text of new notes, plus any passage you append or rewrite during a merge
> (the original wording of the old note is handled by `merge-rules.md` and is never rewritten for style).

This is the English counterpart of `writing-style.md`. It is written natively for English
notes — not translated — because the tells of machine-written English differ from those of
machine-written Chinese. Sources: OpenAI's Model guidance ("Personality and writing style")
and the lieflat-less-ai-tone rules, adapted for English.

---

## A. Six rules (follow while writing)

### 1. Paragraphs first, lists with restraint

The factory default of language models is to turn everything into lists, tables, and bolded
mini-headings — precisely because it is easy, use it deliberately and sparingly. Default to
short, clear paragraphs, one idea per paragraph, with the point stated in the first sentence
and the explanation after it. Use a list only when the items are genuinely parallel, ordered,
or easier to compare side by side; no nested lists. Use a table only for a real
multi-dimensional comparison.

### 2. Write like a person explaining to a colleague

Prefer common words, concrete examples, and precise verbs. Prefer active voice and direct
statements. If one sentence suffices, do not write three. Keep only the technical detail that
actually explains the problem; the reader of this vault is the note's author, so match the
depth of the existing notes.

### 3. Make sentences carry each other

Each sentence should pick up what the previous one left. Paragraph transitions should follow
from the previous paragraph's conclusion — a transition is the half-sentence that genuinely
connects the logic, not a formula like "Now let's take a look at...".

### 4. Transitions and non-technical sentences: rewrite, never copy

Preamble, transitions, asides, enthusiasm, and marketing language from the source **must not
be copied or transliterated into the note**; rewrite them in natural English. Copy verbatim
only: terms, numbers, conclusions, quotations, and code. How sentences connect, how examples
are introduced, how the ground is prepared — that is the curator retelling it. The test: the
finished note should read like a coherent piece of English writing, not like an excerpt with
stitch marks.

### 5. Be honest about attribution

Rewriting freedom applies to expression only, never to attribution. Anything the curator
extends, adds, or analogizes must be visibly separate from what the source said (see the
"Extended thinking" mechanism in section E).

### 6. Self-review before writing to disk

After finishing, sweep the note against the checklist in section C before saving.

---

## B. AI-tell blacklist (do not produce these)

| Type | Blacklist | Write instead |
|------|-----------|---------------|
| Reframe | "not just X — it's Y", "isn't about X, it's about Y", "X isn't enough; you need Y" | State the judgment directly, then the evidence |
| Summary prelude | "Bottom line:", "In short:", "The key insight is:", "TL;DR:" | Delete the prelude; write the conclusion |
| Filler transition | "It's worth noting that", "Importantly,", "Notably,", "As we've seen", "Let's dive in" | Delete it, or name the concrete thing ("this setting", "the numbers above") |
| Reveal dash | "The answer is simple — focus." | "The answer is focus." |
| Empty frame | "Here are the scenarios I've seen:" (announces a list, says nothing) | "I've hit all three of these in production." |
| Opener formula | "Simply put,", "Here's the thing:", "Let's be clear:" | Delete it; start with the judgment |
| Personified metaphor | "like a tireless assistant", "your digital butler", "a wise guide" | Write what the thing actually does |
| Restatement | "This means that ..." (repeating the previous sentence) | Merge into the previous sentence |
| Hollow booster | "robust", "seamless", "game-changer", "supercharge", "unlock the power of", "significantly improves" (with no number behind it) | Use verbs and facts |
| Coined label | Inventing "the X-style Y" compound nouns as concepts | Use the existing common term |

Source-text AI高频词 delve / leverage / foster / utilize / facilitate should become normal
verbs when the note retells them: examine, use, encourage, help. Do not carry them over.

---

## C. Pre-save checklist (sweep item by item)

1. Did you set up a misconception the reader never had, just to knock it down (including
   word-swapped reframes)?
2. Do adjacent sentences share the same syntactic skeleton — same comma placement, same
   clause order, similar length?
3. Any em dash used as a dramatic pause before a reveal?
4. Does a colon follow a content-free prelude ("The reason is:", "The key is:")?
5. Are all headings numbered "1., 2., 3." for no reason? ("First... second..." inside prose is fine.)
6. Is a tool or system compared to an idealized person?
7. Did a specific number from the source get swallowed by "significantly" or "dramatically"?
8. "Simply put" / "Here's the thing" openers?
9. Machine-formal tics: "In order to", "It is important to note that", "utilize" for "use",
   every paragraph opening with However / Moreover / Therefore?
10. A one-sentence dramatic paragraph, or a rule-of-three ("faster, safer, and smarter")
    where the third item adds nothing?
11. Does any paragraph open with a subjectless comment ("Sounds like...") missing its "It"?

---

## D. Do not overcorrect

De-AI-ing is not slang-ifying. These are normal written English — leave them alone:

- Passive voice, nominalization, long sentences
- Questions in prose, question headings
- Metaphors themselves; parallel structure inside a sentence
- "First... second..." inside prose
- Numbered structure in checklists, config items, and legal-style enumerations

Equally, do not push in the other direction: no forced "I/you", no slang dropped in to look
human, no artificially chopped sentence lengths, no deleting the source's hedges and
qualifiers ("may", "typically", "in some cases"). The note stays in written register.

---

## E. Two signature mechanisms

### 1. Geek aside (optional, probability-gated)

- Frequency: governed by `style.geek_joke_probability` in `config.yaml` (default 0.33,
  roughly one note in three). **Only include one when it fits naturally; skip otherwise.**
  Never two notes in a row.
- Form: at most one sentence in the whole note, an engineer's wry remark or in-joke that is
  actually relevant to this note's content; placed where it naturally lands (end of the
  related section, next to an example, or at the close), never derailing the prose, never
  explained.
- Ceiling for density: for a caching note, "There are only two hard problems in computer
  science — cache invalidation and naming things. This note is half of that." For debugging,
  "90% of bugs sit in front of the keyboard." That is the maximum.

### 2. Extended thinking (optional, when the source leaves a question open)

- If the source raises a question it never answers, or leaves an obviously open point, add
  an "## Extended thinking" section at the end (the template reserves the slot).
- First line: `> Curator's extension, not from the source.`
- Extend in the curator's own voice: give an answer or a judgment; cite grounds when they
  exist (existing vault notes, established facts, official docs); label pure speculation as
  speculation.
- If nothing is worth extending, omit the whole section. Do not fill structure for its own sake.

---

## F. Relationship to other files

- `templates.en.md`: the two templates provide the skeleton (section structure); this guide
  governs the sentences inside each section.
- `merge-rules.md`: during merges the old note's wording is untouched (append first, edit
  only clear errors); passages you newly write follow this guide.
- The `style` block in `config.yaml`: aside frequency and the extension switch.
- `writing-style.md` is the Chinese counterpart; pick by note language, never mix.
