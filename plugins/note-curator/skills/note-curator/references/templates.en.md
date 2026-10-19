# Note templates (English)

Templates are picked by content type; the note language follows the source and the target
folder (English here). `write_note.py new` renders the note from these templates;
frontmatter fields follow `config.yaml.frontmatter`.

Division of labor: templates provide the skeleton (section structure), `writing-style.en.md`
provides the flesh (how the sentences inside each section are written); the formatting style
of existing notes in the target folder (from `analyze_style.py`) takes precedence over the
template's default shape.

---

## 1. Knowledge template

For concepts, principles, techniques, definitions. Goal: **distill + sharpen vague
definitions**.

```markdown
---
author: {{from config}}
created: {{today}}
tags: [{{topic1}}, {{topic2}}]
---

# {{English title}}

## Definition

{{One or two sentences that say clearly what this is. If the source's definition is vague,
circular, or missing a subject, complete it here into a clear, self-contained definition.}}

## Key points

{{Explain the mechanism in coherent paragraphs first; use a list only for genuinely parallel
points, no nesting. Where it helps, add one small example or analogy.}}

## Extended thinking

> Curator's extension, not from the source.

{{Optional: keep this section only when the source raised a question it never answered, or
left an obviously open point; extend in the curator's own voice. Omit the whole section
otherwise.}}

## Related

- Related: [[existing note title]]   {{wikilink only to notes that already exist; omit the section if none}}

---
Source: {{URL or "local draft"}}
```

Frontmatter rules:

- **Only `author` / `created` / `tags`** — no more, no fewer.
- `tags`: **at most 3, each summarizing what this note is about** (domain or topic words,
  e.g. `[caching, redis, backend]`); zero-information tags like "notes" or "knowledge" do
  not count. Fewer is better than filler.

### Writing requirements

- **Complete vague definitions**: if the source only says "X is a kind of Y" and Y is just
  as vague, expand until the reader needs no second lookup.
- **Distill, don't shred**: follow `writing-style.en.md` — paragraphs first, plain language,
  point first. Key points are the product of distillation, but expressed as coherent
  English, not bullet confetti.
- **Rewrite transitions and non-technical sentences**; copy terms, numbers, and conclusions
  verbatim.
- **Geek aside**: per the probability mechanism in `writing-style.en.md` section E
  (default ~1/3 of notes); at most one sentence per note, placed next to the content.
- **Wikilinks only to existing notes**, see `obsidian-adapter.md` section 3.

---

## 2. Experiment template

For experiments, benchmarks, case studies, comparative tests. Goal: **summarize the
experiment + state the conclusion**; do not reproduce every number.

```markdown
---
author: {{from config}}
created: {{today}}
tags: [{{topic1}}, {{topic2}}]
---

# {{English title}}

## Background

{{One or two coherent paragraphs: why this experiment was run and what it set out to verify.}}

## Experiment summary

- **Setup**: {{subject under test, dataset/scenario, key variables}}
- **Method**: {{how it was measured; control group / parameters}}
- **Key numbers**: {{only the few figures the conclusion needs, at the source's precision}}

## Conclusion

{{State it conclusively: what was demonstrated / what did not hold / the boundary of
validity. If the conclusion is uncertain, say "to be verified" explicitly.}}

## Extended thinking

> Curator's extension, not from the source.

{{Optional: keep only when the experiment leaves an unanswered question or a limitation
worth discussing; omit otherwise.}}

## Related

- Related: [[existing note title]]

---
Source: {{URL or "local draft"}}
```

Frontmatter rules as above: three fields only; tags ≤ 3 and each summarizes this note.

### Writing requirements

- **Summarize, don't hoard data**: keep only the numbers that support the conclusion; a
  concrete number from the source must never become "significantly improved".
- **The conclusion must be definite**: better "holds under X, fails under Y" than vague.
- Point out limitations of a fuzzy experiment (missing control group, unclear sample size)
  in the conclusion.
- Language follows `writing-style.en.md`; geek-aside mechanism as above.

---

## 3. Type criteria (for automatic classification)

After fetching/reading the source, classify by these features:

| Feature | → Knowledge | → Experiment |
|---------|-------------|--------------|
| Nature | concept / principle / definition / mechanism | one specific test / review / comparison |
| Marker words | "is", "refers to", "principle", "structure" | "experiment", "control group", "sample", "results", "tested on X" |
| Conclusive data | no (general knowledge) | yes (specific numbers backing a conclusion) |

When the boundary is fuzzy, prefer **Knowledge** (broader coverage, and its
"complete the definition" step is also useful for experiment background).
