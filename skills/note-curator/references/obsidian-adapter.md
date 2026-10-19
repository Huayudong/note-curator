# Obsidian 适配层

本文件隔离所有 Obsidian 专属约定。脚本通过 `config.yaml` 的 `vault_path` 与 frontmatter 字段工作，不硬编码下文规则；这里只是写给 LLM 的「生成笔记时必须遵守的规范」。
将来若换笔记软件（Logseq/Notion 等），新增 `references/<软件>-adapter.md` 并在 SKILL.md 的「适配层选择」加一个分支即可，脚本主体不动。

## 1. 文件与目录

- 所有笔记是 vault 内的 `.md` 文件，相对路径用正斜杠（`04 人工智能/LLM 大模型.md`）。
- 目录按知识领域归类，复用 vault 已有目录（见 `config.yaml` 的 `taxonomy.rules`），不要新建无关目录。
- 文件名由笔记标题生成；标题中的 `<>:"/\|?*` 已由 `write_note.py` 转成空格。

## 2. frontmatter 约定（三字段铁律）

```yaml
---
author: Macro_Ray
created: 2026-07-16
tags: [AI, RAG, 检索增强]
---
```

- frontmatter **只允许 `author` / `created` / `tags` 三个字段，不多不少**。需要溯源、更新时间等信息时写进正文文末，不进属性区——属性区是给 Obsidian 检索用的最小集合，不是仓库。
- `tags` **最多 3 个，每个都必须概括本篇文章内容**（领域词或主题词）；「知识」「实验」「笔记」这类对本篇零信息量的万能标签不许用来凑数，3 个以内宁缺毋滥。领域词可按 `config.yaml.taxonomy.rules` 的 domain 取。
- **新建笔记**：写 `author`（取 `config.yaml.frontmatter.author`）+ `created`（当天日期）+ `tags`（≤3，概括本篇）。
- **合并旧笔记**：frontmatter **一字不动**——不追加任何字段；来源留痕由 `write_note.py` 追加到**正文文末**的「来源补充」行（见 `merge-rules.md` 第 5 节）。旧笔记 frontmatter 里若留有历史字段（旧版 skill 追加过的 `updated`/`sources` 等），保持原样，不主动清理，除非用户要求。
- 旧版「合并时向 frontmatter 追加 `updated`/`sources`」的约定**已废弃**。

## 3. 双链 `[[ ]]` 规则（核心）

笔记中出现的概念，对知识库里**已有笔记**要形成双链。建链策略 `title_first_then_concept`（见 `config.yaml.backlinks`）：

1. **标题精确/包含匹配（高置信，直接建链）**：
   把 scan 出的笔记标题清单当作词典。笔记正文里出现的概念若与某已有笔记标题**完全相同**或**包含**该标题，写成 `[[标题]]`。
   - 例：库里有 `LLM 大模型.md`，正文出现「LLM 大模型」→ 写成 `[[LLM 大模型]]`。
   - 显示文字与标题不同时用别名：`[[LLM 大模型|大语言模型]]`。

2. **概念语义兜底（需置信度）**：
   标题未命中的核心概念，结合已有笔记正文判断是否同义/从属。置信度 ≥ `min_confidence`（默认 0.6）才建链；低于阈值**不要硬建**，改为在文末「待关联概念」列出，供人工复核。

3. **不要做的事**：
   - 不要对不存在目标笔记的概念凭空建 `[[ ]]`（会产生断链）。
   - 不要把整句话包进双链，双链只包**概念词**（通常 2~8 字）。
   - 不要为同一个概念在一句话里重复建多次链。

## 4. 适配层选择（将来扩展用）

当前只实现 Obsidian。新增软件时在此加分支：

```
if adapter == "obsidian":   → 遵守本文件（双链 [[ ]]、上述 frontmatter）
elif adapter == "logseq":   → 新建 references/logseq-adapter.md
elif adapter == "notion":   → 新建 references/notion-adapter.md（用 API 导出 markdown）
```

脚本 `scan_vault.py` / `write_note.py` 只认「一个存 .md 的根目录 + frontmatter」，与具体软件解耦；真正软件相关的差异（如 Notion 的 block 结构、Logseq的 outline）在此层吸收。
