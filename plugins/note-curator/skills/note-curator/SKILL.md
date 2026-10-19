---
name: note-curator
description: 中文笔记自动整理与归档（通用 Agent skill，适用于任何支持工具调用的 Agent，如 Codex、Claude Code、Cursor 等）。当用户给出 URL 让你「整理/消化/总结这个链接」，或给出本地草稿/笔记内容让你「整理归档/归类/存进知识库」，或要求「整理笔记」「归档笔记」「存到我的知识库」「消化这篇文章」时使用。功能包括：抓取链接正文并按知识类/实验类提炼成结构化中文笔记；整理本地草稿并归类；对知识库做全库查重，命中同类旧笔记则合并补充（优先追加、有错才改），未命中则新建（新建前先学习已有笔记排版风格并模仿）；笔记中的概念对已有笔记自动建立双链（Obsidian 用 [[ ]]）。写作遵循人话守则：笔记面向人类阅读、去 AI 腔，上下文过渡与非术语句按中文语境改写；frontmatter 仅 author/created/tags 三字段，tags≤3 且概括本篇。生成内容均为中文，目录按知识领域归类。当前内置 Obsidian 适配，架构可扩展到其它笔记软件。
---

# 笔记管家（note-curator）

把零散内容（网页链接 / 本地草稿）整理成结构化中文或英文笔记，归档进知识库（默认 Obsidian）。核心特色：**写入前先全库查重，命中旧笔记就合并补充（优先追加、确有错误才改写），未命中才新建**；**新建前先学习已有笔记的排版风格并模仿**；笔记里的概念对已有笔记自动建双链；**一切落库文字遵守人话守则（中文 `references/writing-style.md` / 英文 `references/writing-style.en.md`）**。

## 第一原则

**整理笔记是为了给人看的，不是给计算机看的。** 提炼、结构化、双链、查重都只是手段，最后落库的文字必须是一篇人愿意从头读到尾的中文：上下文过渡要顺，非术语句要按中国人语境重写，AI 腔黑名单里的句式一律不产出。即使原文满是翻译腔和列表堆砌，也要转成正常人讲话的样子再入库。

## 通用性声明

本 skill 是**通用 Agent skill**，不绑定特定 Agent。所有操作通过本目录下的 Python 脚本（标准库，无第三方依赖）和文件读写完成，任何支持运行脚本/读写文件的 Agent（Codex、Claude Code、Cursor 等）都能使用。
- 抓取网页：优先用自带脚本 `fetch_url.py`；脚本失败时（JS 渲染页/超时），改用**你当前 Agent 可用的网页抓取工具**（如 WebFetch、web_reader、playwright 等，名称因 Agent 而异——用你手上有的那个即可）。
- 配置中不写死 Agent 专属工具名；遇到需要联网/渲染时，按当前环境选择等价工具。

## 前置：强制配置检查（每次任务先做）

**接到整理任务后，第一步必须运行：**

```bash
python scripts/check_setup.py --json
```

- `status == "ok"` → 进入主流程。
- **其他任何状态 → 拦截，不进入整理流程：**
  1. 不要抓正文、不要扫库、不要生成整篇笔记、不要写盘。
  2. 把 `message` 和 `next` 用一两句话告诉用户，说明具体缺什么。
  3. 一次性问齐必要信息（vault 路径、署名），给默认值；用户确认后运行：
     `python scripts/init_setup.py --vault "<路径>" --author "<署名>"`
     vault 不存在且用户同意新建时加 `--create-vault`。
  4. 重新运行 `check_setup.py`，只有 `ok` 才继续。
- **用户明确说「先看效果，不配置」**：只输出一小段预览（不超过约 300 字，或只给一个要点），标注「预览，未归档」；不要输出完整笔记。配置完成后才能完整整理和归档。
- `vault_path` 为空、路径不存在、指向文件、`author` 为空，都按未配置处理；不要绕过，也不要自动改用别的目录。
- 已经配置过但路径失效：先拦截，说明失效路径，让用户确认新路径；不要猜测新目录。

初始化与配置要点：`init_setup.py` 从 `config.example.yaml` 生成个人配置（保留全部注释），默认写到 `~/.note-curator/config.yaml`；如果 `<本skill目录>/config.yaml` 已存在则沿用旧文件。`check_setup.py` 也按「技能目录 `config.yaml` → 用户级 `~/.note-curator/config.yaml`」的顺序查找。`config.yaml` 含个人路径，属个人文件。关键配置：`vault_path`（知识库绝对路径）、`taxonomy`（目录归类规则）、`dedup`（查重阈值与合并流程）、`backlinks`（双链策略）、`style`（人话守则可调项）。

## 主流程（按输入自动分流）

```
            ┌─ 含 URL ──────────────→ 【链接模式】
识别输入 ──┤
            └─ 本地草稿/笔记文件 ──→ 【草稿模式】
                                          ↓
                            （两模式汇合到下面的共同步骤）
                                          ↓
              ① 全库查重（scan + find_duplicates + LLM 语义裁决）
                                          ↓
              ② 命中 → 合并补充（优先 append，有错才 edit）→ 预览 → 确认 → 写入旧笔记
                 未命中 → 学排版与文风 → 按模板生成（建双链）→ 定目录 → 新建写入
```

### 步骤 1：识别输入并取正文

- **链接模式**：先跑 `scripts/fetch_url.py "<URL>" --out _article.txt` 抓正文。
  - 若脚本失败（JS 渲染页/超时，会明确提示），改用**你当前 Agent 可用的网页抓取工具**（WebFetch / web_reader / playwright 等）抓取，把正文存成文件。
- **草稿模式**：读取用户给的草稿文件，或用户直接贴的文本。

### 步骤 2：全库查重（关键，先于任何写入）

1. 扫库：`python scripts/scan_vault.py --vault "<vault_path>" --out _index.json --max-body 400`（索引含每篇笔记的 `language`）
2. 初筛：`python scripts/find_duplicates.py --index _index.json --query "<新笔记主题+核心要点>" --top 5`
   - 把要整理的内容（或其主题句）当作 `--query`。默认只在**与查询同语言**的笔记中查重（中文查中文、英文查英文）；明确要跨语言时加 `--lang all`。英文查询自带轻量词形归一（caching/cache/caches 同根）。
3. **语义裁决（你来做）**：脚本只给关键词初筛分数，是否真重复由你结合两篇正文判断。脚本初筛可能漏（尤其中文术语分词），必要时在 `_index.json` 里按关键词人工核查相关笔记：
   - 主题相似度 ≥ `dedup.similarity_threshold`（默认 0.65）→ **命中**，走步骤 3a（合并）。
   - < 阈值 → **未命中**，走步骤 3b（新建）。

### 步骤 2.5：加载或建立文风画像（新建/合并前）

如果 `config.yaml` 的 `style.learn_from_vault` 为 false，跳过本步骤，只按写作守则和模板写。

1. **确定目录**：新建按 taxonomy 预判目标目录；合并用旧笔记所在目录。
2. **画像目录**：`<config.style.profile_dir>/<目录名>/`（默认 `~/.note-curator/style-profiles/<目录名>/`），包含：
   - `profile.json`：句长、标点、人称、语气词、连接词、高频片段、排版等统计
   - `profile.md`：人可读的统计摘要
   - `voice.md`：语气、用词、段落习惯等定性描述
3. **画像缺失时**：
   - 跑：`python scripts/style_profile.py --vault "<vault_path>" --dir "<目标目录>" --sample <config.style.profile_sample 或 20> --lang <config.style.language 或 auto> --profile-dir "<config.style.profile_dir 或 ~/.note-curator/style-profiles>"`
   - 语言按语料自动检测（中文按字、英文按词分别统计），也可以 `--lang zh|en` 强制指定；中文目录和英文目录各自建画像，不要混用。
   - 读 `profile.md` 和 `profile.json` 里的 `samples`，必要时打开 3–5 篇原始笔记，补全 `voice.md`：
     - 语气与态度、句长与节奏、用词习惯、段落与论证、标点习惯、要模仿、要避免、代表句。
   - 只写样本中能观察到的特征，不要编造；样本不足时直接说明。
4. **画像已存在**：直接读 `profile.md` 和 `voice.md`。用户说「更新文风 / 重新学习我的文风」时，重跑脚本并重新补全 `voice.md`。
5. **使用边界**：语气、句长、用词、连接词、标点、段落节奏向画像对齐；事实、术语、数据、观点归属仍以原文为准，不能为了像而改写事实。

### 步骤 3a：命中 → 合并补充（优先增、有错才改）

1. 按 `references/merge-rules.md` 生成 patch 文件 `_patch.md`，用操作块组织：
   - 旧笔记没有的新知识 → `## APPEND <小节>` 追加。
   - 旧笔记有但**写错了**（事实错误/笔误/过时）→ `## EDIT` 精确替换（OLD 必须逐字匹配原文）。
   - 一致的内容 → 不操作。
   - **追加的片段是你重新写的**：写作守则按旧笔记语言选——中文用 `references/writing-style.md`，英文用 `references/writing-style.en.md`——不是把原文剪一段贴进去。
   - **追加片段也向步骤 2.5 的画像对齐**：如果旧笔记和目录画像差异明显，以旧笔记本身为主。
2. 预览（不写盘）：`python scripts/write_note.py merge --vault "<vault_path>" --target "<旧笔记相对路径>" --patch _patch.md`
   - 脚本会自动做**重复检测**：已存在的 append 片段会标 `SKIP-DUP` 跳过，避免重复写入。
3. **把预览 diff 展示给用户**，等用户确认。
4. 确认后写入：同命令加 `--apply`。脚本不动 frontmatter，有实际变更且 patch 提供了来源时，自动在**正文文末**追加「来源补充」行留痕。

### 步骤 3b：未命中 → 学排版与文风 + 新建

1. **学习排版与文风（重要）**：
   - 排版：`python scripts/analyze_style.py --vault "<vault_path>" --dir "<目标目录>" --sample 8`，按摘要模仿 frontmatter 字段、标题层级、列表标记、强调用法、结构元素密度。
   - 文风：读取步骤 2.5 的 `profile.md` 和 `voice.md`；没有就按步骤 2.5 建立。写作时对齐语气、句长、用词、连接词、标点和段落节奏。
2. **判别类型 + 按语言选模板生成**：先按源文与目标目录的语言分流（以 `langdetect` 口径判断，与步骤 2.5 画像语言一致）：
   - 中文 → `references/templates.md` + `references/writing-style.md`
   - 英文 → `references/templates.en.md` + `references/writing-style.en.md`
   用对应模板判「知识类/实验类」并生成正文；语言表达遵守所选守则（段落优先、说人话、重点先行、去 AI 腔；过渡与非术语句必须按目标语言语境重写，不是复制搬运）。标题、正文、tags 用该语言；**术语、数据、结论、引语、代码保持原文，不翻译**。frontmatter 只写三字段：`author`（取 config）、`created`（当天日期）、`tags`（最多 3 个，每个都必须概括本篇内容）。
3. **建双链**：按 `references/obsidian-adapter.md` 第 3 节：
   - 用 `_index.json` 里的标题清单做词典，正文出现匹配的已有概念 → 写 `[[标题]]`（标题优先，置信度高）。
   - 标题未命中的核心概念，结合语义判断，置信度 ≥ `backlinks.min_confidence`（默认 0.6）才建链；否则放文末「待关联概念」。
4. **定目录**：按 `config.yaml.taxonomy.rules` 的领域关键词匹配；未命中用 `default_dir`。`confirm_dir: true` 时先问用户。
5. **生成草稿**：把正文写到 `_note.md`，先不要写盘。
6. **文风自查**：`python scripts/style_check.py _note.md --profile "<步骤 2.5 的 profile.json>"`
   - 草稿语言与画像语言不一致时会直接报「语言不一致」：换对应语言的画像重建，不要跨语言比较。
   - 中文画像会额外检查把/被句式、四字格、口语词、顿号书名号和中英混排度；**AI 腔黑名单命中**（与 `references/writing-style.md` B 节同步）在画像语料中没有、草稿中出现时直接报偏差，1 次 minor、2 次以上 major，命中必须改写后重跑。
   - 结论「明显偏差」：按提示调整句长、标点、连接词、排版，重跑一次。
   - 「基本一致」或「轻微偏差」：可以继续，并在预览里附一句检查结论。
7. **写入**：`python scripts/write_note.py new --vault "<vault_path>" --dir "<目录>" --title "<标题>" --file _note.md`
8. **写入后的学习提示**：写入完成后附一句：「这篇笔记如果你后续做了修改，说『学习这篇的写法』，我会把你的改稿并入文风画像。」不要主动把刚写的草稿当作用户文风学习——**信号来自用户的改稿，不来自插件自己的输出**。

## 参考文件（按需加载）

- `references/writing-style.md` — **中文人话写作守则（写中文正文前必读）**：六条写作守则、AI 腔黑名单、落库前自查清单、极客梗与延伸思考机制。融合自 OpenAI《Model guidance》（GPT-6 Astra）「Personality and writing style」与 lieflat-less-ai-tone 的 11 条去 AI 味规则。
- `references/obsidian-adapter.md` — Obsidian 双链 `[[ ]]` 规则、frontmatter 三字段铁律、目录约定、适配层扩展方式。
- `references/writing-style.en.md` — 英文版守则（写英文正文前必读）：英文母语视角的六条守则、英文 AI 腔黑名单（reframe/summary prelude/reveal dash/hollow booster 等）与自查清单，机制与中文版对应。
- `references/templates.md` — 知识类/实验类两套中文笔记模板 + 类型判别标准。
- `references/templates.en.md` — 英文版知识类/实验类模板 + 类型判别标准。
- `references/merge-rules.md` — 查重-合并规则（优先增有错才改、patch 的 APPEND/EDIT 格式、冲突处理、来源留痕）。
- `references/style-profiling.md` — 文风画像的统计口径、定性补全方法、限制与隐私说明。
- `config.example.yaml` — 全部可调配置（vault 路径、目录规则、查重阈值、双链策略、写作风格）。

## 脚本一览

| 脚本 | 作用 | 何时用 |
|------|------|--------|
| `scripts/check_setup.py` | 检查配置是否存在、vault 是否有效、署名是否已填；未就绪时阻止生成并给出下一步（`--lang zh/en` 切换提示语言） | 每次整理任务开始前 |
| `scripts/init_setup.py` | 首次初始化：从 config.example.yaml 生成个人配置（默认 `~/.note-curator/config.yaml`；兼容旧的技能目录 config.yaml），可顺带创建 vault 目录（`--lang en` 英文提示） | 首次使用或更换 vault 时 |
| `scripts/scan_vault.py` | 扫描 vault，输出笔记索引（标题/路径/语言/frontmatter/正文摘要） | 查重与建双链前，跑一次 |
| `scripts/find_duplicates.py` | 对新笔记在全库做关键词初筛（同语言过滤、英文词形归一、标题加权），返回 Top-N 候选 | 查重时，喂 `--index` 和 `--query` |
| `scripts/analyze_style.py` | 分析目录/笔记的排版风格，输出风格摘要供模仿 | 新建笔记前，对目标目录跑一次 |
| `scripts/style_metrics.py` | 文风统计与比较的共享实现（句长、标点、人称、语气词、连接词、排版） | 被下面两个脚本调用 |
| `scripts/style_profile.py` | 从本地笔记建立/更新文风画像（profile.json + profile.md + voice.md），中英文分别统计（zh 按字、en 按词） | 新建/合并前，或用户要求学习文风时 |
| `scripts/style_check.py` | 比较草稿与画像，报告明显的风格偏差 | 写入前 |
| `scripts/style_learn.py` | 把用户改过的笔记并入现有画像（滚动窗口、语言校验、历史留痕），实现持续学习 | 用户说「学习这篇的写法 / 更新我的文风」时 |
| `scripts/fetch_url.py` | 抓取 URL 正文，输出清洗纯文本 | 链接模式第一步；失败则改用 Agent 的网页工具 |
| `scripts/write_note.py` | 写入 vault：`new` 新建 / `merge` 合并（默认预览，`--apply` 写盘；merge 支持重复检测；合并不动 frontmatter，来源文末留痕） | 最后落库 |

所有脚本仅用 Python 标准库，无需额外安装。

## 重要守则

- **笔记给人看**：一切落库文字遵守 `references/writing-style.md`；这是第一原则，优先于模板的结构惯性。
- **首次使用先配置**：每次任务先跑 `check_setup.py`；未配置或路径失效时拦截并引导，不生成整篇笔记。用户明确要求预览时只给短预览。
- **查重先于新建**：每篇新笔记落库前都必须查重；命中旧笔记优先合并补充，不能另建重复笔记。
- **合并优先增、有错才改**：默认 `append` 追加；只有原内容确有错误/过时才用 `edit` 改写，且不要为「换个说法」而改写作者原有措辞——包括不因去 AI 味而改写旧笔记。
- **追加片段也是写作**：合并新增的内容按人话守则写成与旧笔记融为一体的中文，不是原文摘抄。
- **frontmatter 三字段铁律**：只有 `author`/`created`/`tags`，不多不少；`tags` 最多 3 个且每个都必须概括本篇内容（不放「知识」「笔记」这类零信息量标签）；合并时 frontmatter 一字不动，来源留痕写正文文末。
- **新建必学排版**：新建前用 `analyze_style.py` 看同目录风格并模仿，保持知识库排版一致。
- **文风画像只对齐表达**：语气、句长、用词、标点、段落节奏向画像靠拢；事实、术语、数据、观点归属仍以原文为准，不能为了像而改写事实。
- **画像不是微调**：它是统计 + 定性描述，不能保证完全复制作者；样本不足或主题差异大时，先说明局限，不要把检查结果当成硬性判决。
- **持续学习只认用户改稿**：用户说「学习这篇的写法」时跑 `scripts/style_learn.py --profile "<画像>" --note "<笔记>"`；语言不符或重复的笔记会被拒绝。不要把插件自己生成、未经用户修改的草稿并入画像。
- **改写不越界**：过渡、铺垫、非术语表达按中文语境重写；术语、数据、结论、引语忠实于原文，观点归属不混淆；延伸内容明确标注「整理者延伸」。
- **双链只对已有笔记建**，不对不存在的目标凭空建链；拿不准的进「待关联概念」。
- **语言跟随源文与目标目录**：正文、标题、tags 用笔记语言（中文或英文），写作守则与模板按语言选取；术语、数据、结论、引语、代码保持原文不翻译。中文语境下按中文守则下更多功夫（把/被句式、四字格、口语词、AI 腔命中都在检查范围）。
- **通用性**：笔记软件差异隔离在 `references/obsidian-adapter.md`；脚本通过配置的 `vault_path` 与 frontmatter 字段工作，不硬编码软件特性。网页抓取在脚本失败时回退到当前 Agent 的可用工具。
