# 文风画像（style profiling）

支持中文与英文两种语言，按语言分别统计、分别建画像：**中文以「字」为单位**（句长按字符、密度按每千字），**英文以「词」为单位**（句长按词数、密度按每千词）。语言由 `scripts/langdetect.py` 按 CJK 与拉丁字母占比自动检测，也可用 `--lang zh|en` 强制指定；`style_check.py` 只在同语言画像之间比较，跨语言直接报「语言不一致」。

## 它解决什么

只模仿排版，能让新笔记“看起来”像旧笔记；但语气、句长、用词习惯仍然可能不像同一个人。文风画像在排版之外，再对齐四件事：

1. **句长与节奏**：平均句长、长短句分布、段落长度。
2. **用词与语气**：人称、语气词、模糊限定词、强调词、连接词、高频片段。
3. **行文习惯**：句首写法、举例/类比/枚举/个人经验等修辞偏好。
4. **标点与排版**：逗号、破折号、括号、引号的使用密度，标题/列表/加粗/双链密度。

实现分两层：

- **统计层（确定性）**：`scripts/style_profile.py` 扫描本地笔记，按语言调用 `style_lang_zh.py` / `style_lang_en.py` 语言包计算指标，写出 `profile.json` 和 `profile.md`。
- **定性层（Agent 阅读后写）**：Agent 阅读统计摘要和样本片段，把“语气是克制还是松弛、爱不爱用短句、有没有口头禅、段落怎么推进”写进 `voice.md`（英文画像用英文模板）。

写入前再用 `scripts/style_check.py` 比较草稿和画像，报告明显偏差（报告语言跟随画像语言）。

### 英文语言包的特征

英文方法论参考 [write-like-me](https://github.com/Hiro-Inagawa/write-like-me)（lexical / syntactic / hedging & stance / structural 四类），按本项目重写：

- 句切分：缩写（Mr. / e.g. / U.S.）与小数点保护后按 `.!?` 切句；句长按词数。
- 标点：comma / period / question / exclamation / colon / semicolon / dash / ellipsis / parens / quotes，每千词。
- 人称：I / me / my / we / us / our / you / he / him / she / her / it / they / them / their（词边界匹配）。
- hedges：maybe / perhaps / probably / seems / might / somewhat / tend to…
- boosters：clearly / certainly / obviously / really / very / always / never…
- connectors：however / but / therefore / because / although / in other words / on the other hand…
- 修辞：example / analogy / enumeration / personal / transition。
- 高频片段：词 1–3 gram（过滤停用词）；句首取前 3 个词。
- 词汇丰富度：词级 TTR 与 hapax 比例。

中文语言包见本文件其余部分；两种语言的特征键一一对应，但**阈值和单位不跨语言可比**。

## 能学什么，不能学什么

**能学：**

- 句长、段落长度的分布和波动
- 标点使用密度
- 人称、语气词、模糊限定、强调词、连接词
- 句首习惯和高频字词片段
- 举例、类比、枚举、个人经验、转折等修辞偏好
- 标题、列表、加粗、引用块、双链等排版密度

**不能学：**

- 它不是微调模型，不会复制作者的完整语言能力或知识结构。
- 它不判断内容是否正确，也不判断观点归属；这些仍以原文为准。
- 主题差异大时，统计检查可能误报。比如写 API 文档和写读书笔记，标点与句长本来就会不同。
- 样本太少时（低于 5 篇或几千字），画像只适合当参考，不适合当硬性规则。

## 语料建议

- 优先用**同一目录、同一 register** 的笔记。技术笔记、日记、邮件不要混在一起建一个画像。
- 建议至少 10 篇或 5000 字；默认取最近 20 篇（`--sample 20`）。
- 样本会取最近修改的笔记；如果最近写的都是同一主题，画像会偏向那个主题。可以手动用 `--files` 指定更有代表性的篇目。
- 画像里的 `samples` 会保存几段原文片段，便于 Agent 做定性判断。这些片段属于个人内容，不要提交到公开仓库。

## 建立画像

```bash
# 分析某个目录最近 20 篇（语言自动检测）
python scripts/style_profile.py --vault "D:/Obsidian/MyVault" --dir "04 人工智能"

# 英文目录：强制英文统计（句长按词、密度按每千词）
python scripts/style_profile.py --vault "D:/Obsidian/MyVault" --dir "04 AI" --lang en

# 指定文件、指定画像名
python scripts/style_profile.py --vault "D:/Obsidian/MyVault" \
  --files "04 人工智能/RAG 笔记.md,04 人工智能/向量检索.md" \
  --name ai-notes

# 整个 vault
python scripts/style_profile.py --vault "D:/Obsidian/MyVault" --all --name vault
```

默认输出到 `~/.note-curator/style-profiles/<name>/`：

```text
profile.json   # 机器可读统计（含 language 字段），style_check.py 使用
profile.md     # 人可读摘要（语言跟随画像），Agent 先读这份
voice.md       # 定性画像模板（中文/英文各一套），Agent 阅读样本后补全
```

`--sample 0` 表示使用全部文件；`--no-recursive` 只扫描目标目录第一层。

## Agent 如何补全 voice.md

脚本只负责统计，不能替作者判断“语气像不像”。Agent 需要：

1. 读 `profile.md` 的统计摘要。
2. 读 `profile.json` 里的 `samples`，必要时打开 3–5 篇原始笔记。
3. 在 `voice.md` 中填写：
   - **语气与态度**：克制/热情、直接/委婉、严肃/松弛，是否有幽默或自嘲。
   - **句长与节奏**：偏短句还是长句，长短如何交替，段落通常多长。
   - **用词习惯**：偏口语还是书面，常用动词/形容词/连接词，有没有重复的口头禅。
   - **段落与论证**：先给结论还是先铺垫，爱不爱举例/类比/反问，转折怎么处理。
   - **标点习惯**：逗号密度、破折号/括号/引号的偏好。
   - **要模仿 / 要避免**：写成可执行的短句，不要写“自然流畅”这种空话。
   - **代表句**：从样本里摘 2–3 句，作为语气锚点。

只写样本中能观察到的特征。样本不足时，直接说“样本不足，以下只是初步判断”，不要编造。

## 写入前检查

```bash
python scripts/style_check.py _note.md --profile "~/.note-curator/style-profiles/ai-notes/profile.json"
```

输出结论分三档：

- **基本一致**：没有明显统计偏差。
- **轻微偏差**：有 1 个 major 或少量 minor；可以写入，建议顺手调整。
- **明显偏差**：3 个以上 major；建议先按提示改句长、标点、连接词或排版，再重跑。

`--json` 输出机器可读结果；`--strict` 在有 major 时退出码为 1，可用于脚本或 CI。

统计检查只覆盖可量化特征。它说“句长偏短”，不代表内容不好；它说“基本一致”，也不代表语气一定像本人。最终仍要结合 `voice.md` 和实际阅读判断。

## 配置

在 `config.yaml` 的 `style` 下：

```yaml
style:
  learn_from_vault: true       # 是否启用文风画像
  profile_sample: 20           # 建立画像时取最近 N 篇
  profile_dir: "~/.note-curator/style-profiles"
  check_before_write: true     # 写入前是否跑 style_check.py
```

## 隐私

- 画像、样本片段和 `voice.md` 默认保存在 `~/.note-curator/style-profiles/`，不在知识库或代码仓库里。
- 如果你把 `profile_dir` 改到 vault 内，注意不要把 `voice.md` 和 `samples` 提交到公开仓库。
- Agent 读取的是本地文件；是否把内容发送给模型，取决于你使用的客户端和会话权限。

## 方法参考

画像的“统计画像 + 定性描述 + 确定性检查器”结构参考了开源项目
[write-like-me](https://github.com/Hiro-Inagawa/write-like-me)（MIT）。
本实现针对中文笔记重写了特征、标点、语气词和检查逻辑，没有复制其代码。
