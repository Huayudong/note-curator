[简体中文](README.md) | **English**

# note-curator

Turn links and rough drafts into structured notes that fit your Obsidian vault and match the style of your existing notes. Chinese-first, with English support.

note-curator is an open-source Agent Skill for note curation: it fetches an article or reads a draft, checks the vault for duplicates, merges into an existing note or creates a new one, verifies facts and style before writing, and adds Obsidian backlinks where concepts appear. It uses only Python's standard library and ships as a standalone skill plus thin plugins for ZCode, Claude Code, and Codex / ChatGPT.

## Features and workflow

```text
input → fetch/read → vault-wide dedup → merge or create → fact & style checks → preview → apply / undo
```

- **Link or draft → structured note**: URLs and local files go through one source pipeline (tables and code kept in order). Seven incomplete states — truncation, login wall, dynamic page, short body, missing pagination, missing table, fetch failure — are reported honestly, and you are asked for more material instead of being given a half-read summary. Source content is data, never executed. Knowledge and experiment templates included.
- **Deduplication and merge**: keyword pre-filter plus semantic judgment, same-language by default (with light English stemming and title weighting). A hit appends new knowledge and fixes only clear errors after a diff preview; a miss creates one new note.
- **Search and backlinks**: large vaults get a chunked full-text index with incremental updates and evidence positions, so tail content is recallable. Links are verified by path, alias, heading anchor and block ID before writing; broken links block the write. Links live where the concept appears in the body — no "Related notes" dump at the end.
- **Fact fidelity**: numbers and units, dates, qualifiers, negations and attribution are checked before writing, along with a length budget (crossing the hard cap flags a split) and a tail link-list detector; at most two revision rounds.
- **Voice and formatting**: sentence length, punctuation, pronouns, particles, connectors, sentence openers and paragraph rhythm are measured, plus the target folder's frontmatter, heading levels, lists and emphasis; clear deviations are flagged before writing. Everything written follows the human-voice guide (paragraph first, no AI tells, transitions rewritten for the target language). By default, Chinese and English profiles live under `<folder>-<language>`, so bilingual samples never pollute each other.
- **Language packs**: `language-packs/zh-CN` and `en` ship AI-tell rules, terminology first-mention tables and sourced example sentences; user allow/deny phrases win, and a missing or corrupt pack falls back to built-in lists.
- **Learning from your edits**: only expression and formatting preferences are distilled from your edits — fact fixes never become style preferences. By default candidates take effect only after confirmation; auto mode activates a candidate once the same signal appears in 2+ independent notes. Four modes (off / explicit / assisted / auto) plus disable, forget, export and import.
- **Note conventions**: one note answers one question; independent side topics are deduplicated first and split into complete child notes when truly needed. Frontmatter holds only `author / created / tags` (at most three tags), and source traces go at the end of the body.
- **Write safety**: create and merge share one plan → apply → undo transaction with base-hash checks; atomic replacement, controlled backups and a write log, with paths contained inside the vault (no absolute paths, `..` traversal or symlink escapes).
- **Language and engineering**: output language = explicit request > target note > config > source language, preserving facts, figures and attribution across languages. Standard library only, Python 3.8+, one skill source for ZCode, Claude Code, Codex / ChatGPT and standalone use.

## Obsidian native plugin (preview)

`apps/obsidian-plugin/`: organize the current note (generate → preview → apply/undo),
learn this edit (candidates require explicit confirmation), preference management and
the write log — sharing the same core and state as the external Agent Skill. Save
events are discovery-only (never auto-learning); the API key goes through an env
var or the plugin's local data, never into notes or logs. See
[plugin README](apps/obsidian-plugin/README.md).

## Install

The agent plugin root is `plugins/note-curator/`; the skill itself is `plugins/note-curator/skills/note-curator/`. The same skill is used by every target.

### ZCode

1. Open **Plugin Marketplace → Add → Add Plugin Marketplace**.
2. Paste `https://github.com/Huayudong/note-curator`.
3. Install **Note Curator (笔记管家)** from `note-curator`.

This is a custom marketplace source, not an official ZCode marketplace listing.

### Claude Code

```bash
/plugin marketplace add Huayudong/note-curator
/plugin install note-curator@note-curator
```

### Codex / ChatGPT

Codex CLI:

```bash
codex plugin marketplace add Huayudong/note-curator
codex plugin add note-curator@note-curator
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

Configuration is written to `~/.note-curator/config.yaml`. If a legacy `config.yaml` exists in the skill directory, it is used instead. Upgrades do not overwrite the user-level config.

Then ask:

```text
Organize this article into my notes: <URL>
```

```text
Archive this draft: ...
```

The skill shows a diff preview before writing; apply with `--apply`, then undo with `undo --run <run_id>` if needed.

## Style learning

Build a profile from recent notes in a folder. Chinese profiles count characters and English profiles count words; language is auto-detected per corpus and can be forced with `--lang zh|en`. Drafts are only compared against same-language profiles.

```bash
python plugins/note-curator/skills/note-curator/scripts/style_profile.py \
  --vault "D:/Obsidian/MyVault" --dir "04 AI" --sample 20
```

This writes `profile.json`, `profile.md`, and a `voice.md` template (in the profile's language) to `~/.note-curator/style-profiles/<folder>-<language>/`. The agent reads the samples and fills `voice.md` with observations about tone, sentence rhythm, vocabulary, paragraph flow, and punctuation.

Check a draft:

```bash
python plugins/note-curator/skills/note-curator/scripts/style_check.py \
  _note.md --profile "~/.note-curator/style-profiles/04-AI-zh/profile.json"
```

The result is consistent / minor deviation / major deviation. A language mismatch between draft and profile is reported instead of comparing. This is a statistical check, not a guarantee of identical voice. It works best with 10+ notes or 5,000+ units from the same folder.

Chinese profiles get extra depth: 把/被 construction density, four-character phrases, colloquialisms, 顿号 and 《》 punctuation, Latin-mixing density, and AI-tell hits that are flagged directly when they appear in a draft but not in the profile.

The profile keeps learning: after you edit a note, ask the agent to "learn from this note" and `style_learn.py` folds your edited version back into the profile (sample-time rolling window, language-checked, with history). Only your edits are learned — never the plugin's own drafts.

## Configuration

See [`config.example.yaml`](plugins/note-curator/skills/note-curator/config.example.yaml). The main options are `vault_path`, `taxonomy.rules`, `dedup`, `backlinks`, and `style`.

More docs: [install](docs/install.md) · [learning](docs/learning.md) · [migration](docs/migration.md) · [privacy](docs/privacy.md) · [troubleshooting](docs/troubleshooting.md) · [release](docs/release.md).

## Quality and reliability

- **Evaluation**: the frozen eval set in `evals/` is locked by source hash — any change refuses to run. `run_eval.py` reports per-task fact retention, length and tail-list issues, with runs layered by public rules / +profile / +prefs and a `--sabotage` defect demo; `blind_compare.py` reports a directional preference rate with a Wilson interval, and `feedback.py` stays local by default.
- **Stability**: a cross-process lock rejects concurrent writes to the same vault (stale locks are taken over after 5 minutes); plans, baselines, source documents, index, profiles and packs each carry a schema ceiling, so older versions refuse newer state with an upgrade hint; `doctor.py` shows versions, packs, active locks and recent writes (sanitized), and `--clean` prunes by retention; `perf_bench.py` reproduces index and search benchmarks.
- **Language packs**: a per-file sha256 manifest is verified at load and tampered packs are refused; stable / experimental channels with a candidate → stable → deprecated lifecycle; `resource_pack.py --install/--rollback` swaps packs reversibly, and `pack_compare.py` compares old and new packs.
- **Configuration hard gate**: in ZCode / Claude Code plugin form, every skill call is checked first; a missing config, dead vault path or empty author denies the call with a guided flow. Gate failures fail open so the plugin never wedges; other forms keep the SKILL.md check.

## Compatibility

- The skill uses only Python's standard library and works in any client that supports Agent Skills.
- Plugin manifests target ZCode (`.zcode-plugin`), Claude Code (`.claude-plugin`), and Codex/ChatGPT (`.codex-plugin`); marketplaces live at `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json`.
- Local file access and command execution are required to scan the vault, run the scripts, and write notes.
- Official marketplace listing is separate from adding a custom marketplace; this repository does not automatically appear in any vendor's official directory.

## Limitations

- Style learning is statistical plus a qualitative profile; it is not fine-tuning and does not clone an author.
- Profiles are per folder and depend on the samples; topic differences can cause false positives.
- It does not verify whether the source itself is true; before writing it only checks that key facts are preserved. Terms, data, and attribution still follow the source.
- The first call is intentionally blocked until `vault_path` and `author` are configured.

## Releasing

Update the version in the three plugin manifests and `.claude-plugin/marketplace.json`; the Obsidian plugin version in `apps/obsidian-plugin/manifest.json` is independent. Refresh the marketplace in each client, and publish the new tag or commit.

## Credits

- [write-like-me](https://github.com/Hiro-Inagawa/write-like-me) (MIT) — voice profile and deterministic checker structure; this implementation rewrites the features and rules for Chinese notes.
- [OpenAI Model guidance](https://developers.openai.com/api/docs/guides/latest-model) and [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) — writing-style guidance.
- [KKKKhazix/human-writing](https://github.com/KKKKhazix/human-writing).

## License

[MIT](LICENSE)
