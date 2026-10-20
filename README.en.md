[简体中文](README.md) | **English**

# note-curator

Turn links and rough drafts into structured Chinese notes that fit your Obsidian vault and match the style of your existing notes.

note-curator is an open-source Agent Skill for Chinese note curation. It fetches an article or reads a draft, checks the vault for duplicates, merges into an existing note or creates a new one, adds Obsidian backlinks, and follows the formatting and voice of the target folder. It uses only Python's standard library and ships as a standalone skill plus thin plugins for ZCode, Claude Code, and Codex / ChatGPT.

## Features

- **Link or draft → note**: fetch a URL or read a local draft, then produce a structured Chinese note.
- **Source integrity and honesty (B08)**: a unified SourceDocument pipeline — URL/file → structured segments (tables and code kept in order) → seven extraction statuses (truncated / login wall / dynamic page / short body / missing pagination / missing table / fetch failure); incomplete sources ask for more material instead of pretending to be read; source content is data, never executed; URL normalization + content fingerprints detect duplicates and updates.
- **Two note types**: knowledge notes for concepts and explanations, experiment notes for setup, method, data, and conclusions.
- **Vault-wide deduplication**: keyword pre-filter plus semantic judgment before writing; queries are matched within the same language by default, with light English stemming (caching/cache/caches share a root) and title weighting.
- **Full-text search with evidence (B07)**: `index_vault.py` builds a chunked full-text index with incremental updates; `search_notes.py` returns candidates with evidence chunk and position — tail content of long notes is recallable. Cross-language hits come through concept bridges (flagged `cross_language`, never auto-merged).
- **Link verification before write (B07)**: `link_resolver.py` resolves wiki links via path / basename disambiguation / aliases / heading anchors / block IDs; ambiguous links get a candidate list and broken links block the write, so every inserted link opens in Obsidian.
- **Merge instead of duplicate**: append new knowledge, correct only clear errors, preview the diff, then write through a plan → apply → undo transaction.
- **Write safety**: every write goes through a WritePlan with base-hash conflict checks, atomic replacement, controlled backups, path containment (no absolute paths, `..`, symlink escapes, Windows reserved names, or case-only collisions), an undo command, and a write log.
- **Obsidian backlinks**: link concepts to existing notes with title-first matching and a confidence threshold; links live where the concept appears in the body — no "Related notes" list at the end.
- **Fact-fidelity check (B04)**: before writing, the draft is checked against source-critical facts (numbers and units, dates, qualifiers, negations), plus a length budget (crossing the hard cap flags a split review) and a tail "Related notes" list violation detector; at most two revision rounds.
- **Topic focus**: one note answers one question; longer side topics are deduplicated first and split into complete child notes when truly needed, linked from the body.
- **Style-aware formatting**: mirror the target folder's frontmatter, heading levels, list markers, emphasis, and structural density.
- **Local voice profile**: measure sentence length, punctuation, pronouns, particles, connectors, sentence openers, and rhetorical habits; the agent reads sample notes and completes a qualitative `voice.md`.
- **Pre-write style check**: compare a draft with the profile and flag clear deviations.
- **Bilingual profile isolation (B02)**: profiles live at `<folder>-<language>` with a composite key (user + vault + language + scope); Chinese and English samples in one folder never pollute each other, and code blocks, inline code, and long quoted foreign-language paragraphs are excluded from the statistics.
- **Language decision**: output language = explicit request > target note language (merge) > config `output_language` > source primary language; all four source/output combinations are supported, and cross-language curation preserves facts, figures, and attribution while keeping terms, code, and quotes in the original.
- **Migratable profiles**: legacy profiles are migrated into the new namespace with `migrate_profiles.py` (old folders kept; delete the new folder to roll back), and moved vaults can be re-linked.
- **Repeated edits keep teaching**: learning identifies revisions by content hash, so the 2nd and 3rd edit of the same note refresh the statistics; re-learning unchanged content is a no-op.
- **Two-step edit learning (B05)**: `learn_edit.py diff` classifies edit diffs (fact/content/structure/expression/formatting) and distills preference candidates from expression and formatting only; candidates take effect after explicit `confirm` (`reject`/`undo` supported), and fact fixes never masquerade as style preferences.
- **Learning modes and preference management (B06)**: four modes — off / explicit / assisted / auto (auto needs the same candidate across 2+ independent notes before it takes effect); preferences can be disabled (reversible), forgotten (evidence deleted), exported/imported (no raw evidence included), and checked for conflicts; active preferences automatically feed the pre-write check within their language scope.
- **Structured language packs (B03)**: first release under `language-packs/zh-CN` and `en` — 8 Chinese / 6 English rule categories (grouped AI-tell regexes with good/bad examples and exceptions), terminology first-mention tables, and example sentences with provenance (author/source/license). A missing or corrupt pack falls back to built-in word lists. User allow/deny phrases (config `style.allowed_phrases`/`banned_phrases`) override default rules.
- **Small frontmatter contract**: `author`, `created`, and `tags` only; tags are capped at three and must describe the note.
- **No third-party Python dependencies**: the standard library only; syntax supports Python 3.8+, and CI tests 3.10 / 3.13 on Windows and Linux (scripts force UTF-8 stdio, so the default Windows codepage works).

## Obsidian native plugin (B09 preview)

`apps/obsidian-plugin/`: organize the current note (generate → preview → apply/undo),
learn this edit (candidates require explicit confirmation), preference management and
the write log — sharing the same core and state as the external Agent Skill. Save
events are discovery-only (never auto-learning); the API key goes through an env
var or the plugin's local data, never into notes or logs. See
[plugin README](apps/obsidian-plugin/README.md).

## Install## Install

The plugin root is `plugins/note-curator/`; the skill itself is `plugins/note-curator/skills/note-curator/`. The same skill is used by every target.

### ZCode

1. Open **Plugin Marketplace → Add → Add Plugin Marketplace**.
2. Paste `https://github.com/Huayudong/note-curator`.
3. Install **Note Curator (笔记管家)** from `note-curator-market`.

This is a custom marketplace source, not an official ZCode marketplace listing.

### Claude Code

```bash
/plugin marketplace add Huayudong/note-curator
/plugin install note-curator@note-curator-market
```

### Codex / ChatGPT

Codex CLI:

```bash
codex plugin marketplace add Huayudong/note-curator
codex plugin add note-curator@note-curator-market
```

In the ChatGPT desktop app, open the Plugins directory, add or import the repository as a marketplace, then install `note-curator`. Workspace admins can use **Admin → Plugins → Add → Import marketplace** with an empty `Path`.

ChatGPT Skills/Plugins availability depends on the plan, workspace settings, and client version. Importing this repository creates a custom marketplace; it does not automatically list the plugin in OpenAI's public directory.

### Standalone skill

```bash
npx skills add Huayudong/note-curator/plugins/note-curator/skills/note-curator
```

Or clone and copy the skill directory:

```bash
git clone https://github.com/Huayudong/note-curator.git
cp -r note-curator/plugins/note-curator/skills/note-curator ~/.agents/skills/note-curator
# ZCode:       ~/.zcode/skills/note-curator
# Claude Code: ~/.claude/skills/note-curator
```

Remove any manually installed copy before installing the plugin; a user-level skill can shadow the plugin version.

## Quick start

The first call runs a setup check. If the vault path or author is missing, the skill stops and asks for configuration instead of dumping a full note into the conversation.

```bash
python plugins/note-curator/skills/note-curator/scripts/check_setup.py --json
python plugins/note-curator/skills/note-curator/scripts/init_setup.py \
  --vault "D:/Obsidian/MyVault" --author "Your Name"
```

Configuration is written to `~/.note-curator/config.yaml`. If a legacy `config.yaml` exists in the skill directory, it is used instead. Plugin upgrades do not overwrite the user-level config.

Then ask:

```text
Organize this article into my notes: <URL>
```

```text
Archive this draft: ...
```

The skill shows a diff preview before writing; apply with `--apply`, then undo with `undo --run <run_id>` if needed.

## How it works

```text
input → fetch/read → deduplicate → merge or create → style check → preview → apply → undoable
```

The merge path appends new knowledge and edits only clear errors. The create path learns the target folder's formatting and, when enabled, the local voice profile before drafting.

## Style learning

Build a profile from recent notes in a folder. Chinese and English are measured separately: Chinese profiles count characters, English profiles count words. Language is auto-detected per corpus and can be forced with `--lang zh|en`; drafts are only compared against same-language profiles.

```bash
python plugins/note-curator/skills/note-curator/scripts/style_profile.py \
  --vault "D:/Obsidian/MyVault" --dir "04 AI" --sample 20
```

This writes `profile.json`, `profile.md`, and a `voice.md` template (in the profile's language) to `~/.note-curator/style-profiles/<name>/`. The agent reads the samples and fills `voice.md` with observations about tone, sentence rhythm, vocabulary, paragraph flow, and punctuation.

Check a draft:

```bash
python plugins/note-curator/skills/note-curator/scripts/style_check.py \
  _note.md --profile "~/.note-curator/style-profiles/04-AI/profile.json"
```

The result is consistent / minor deviation / major deviation. A language mismatch between draft and profile is reported instead of comparing. This is a statistical check, not a guarantee of identical voice. It works best with 10+ notes or 5,000+ units from the same folder.

Chinese profiles get extra depth: 把/被 construction density, four-character phrases, colloquialisms, 顿号 and 《》 punctuation, Latin-mixing density, and AI-tell blacklist hits (aligned with the writing guide) that are flagged directly when they appear in a draft but not in the profile.

The profile keeps learning: after you edit a note, ask the agent to "learn from this note" and `style_learn.py` folds your edited version back into the profile (sample-time rolling window, language-checked, with history). Only your edits are learned — never the plugin's own drafts.

## Configuration

See [`config.example.yaml`](plugins/note-curator/skills/note-curator/config.example.yaml). The main options are `vault_path`, `taxonomy.rules`, `dedup`, `backlinks`, and `style`.

## Compatibility

- The skill uses only Python's standard library and works in any client that supports Agent Skills.
- Plugin manifests target ZCode (`.zcode-plugin`), Claude Code (`.claude-plugin`), and Codex/ChatGPT (`.codex-plugin`); marketplaces live at `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`.
- Local file access and command execution are required to scan the vault, run the scripts, and write notes.
- Official marketplace listing is separate from adding a custom marketplace; this repository does not automatically appear in any vendor's official directory.

## Limitations

- Style learning is statistical plus a qualitative profile; it is not fine-tuning and does not clone an author.
- Profiles are per folder and depend on the samples; topic differences can cause false positives.
- The skill does not verify facts; it preserves the source's terms, data, and attribution.
- The first call is intentionally blocked until `vault_path` and `author` are configured.

## Releasing

Update the version in the three plugin manifests and `.claude-plugin/marketplace.json`, refresh the marketplace in each client, and publish the new tag or commit.

## Credits

- [write-like-me](https://github.com/Hiro-Inagawa/write-like-me) (MIT) — voice profile and deterministic checker structure; this implementation rewrites the features and rules for Chinese notes.
- [OpenAI Model guidance](https://developers.openai.com/api/docs/guides/latest-model) and [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) — writing-style guidance.
- [KKKKhazix/human-writing](https://github.com/KKKKhazix/human-writing).

## Evaluation discipline (B10)

The frozen eval set lives in `evals/` (physically separated from dev fixtures; source
hashes are locked and any change refuses to run). `run_eval.py` emits per-task
fact-retention/length/tail-list reports with pack and context-layer versions
(`--layers` for the public / +profile / +prefs ablation); `--sabotage` demonstrates
defect capture. Blind voting: `blind_compare.py` (directional preference rate with a
Wilson interval, ties reported separately, >60% is only an exploration threshold).
User feedback: `feedback.py` stays local by default and can convert into pending eval
tasks. No default strategy changed because of evaluation results.

## License## License

[MIT](LICENSE)
