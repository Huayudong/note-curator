# note-curator 笔记管家

note-curator（笔记管家）是一个开源的中文笔记整理 Agent skill：把网页链接和本地草稿整理成「给人看的」结构化中文笔记——提炼成知识类或实验类笔记，先对整个知识库查重，命中旧笔记就合并补充、未命中才新建归档，并把文中概念自动链接到已有笔记（Obsidian 双链）。它只依赖 SKILL.md 和 Python 标准库脚本，任何支持 Agent Skills 的客户端都可以直接使用。

本仓库同时提供 ZCode、Claude Code、Codex / ChatGPT 的插件清单。技能逻辑只有一份，位于 `plugins/note-curator/skills/note-curator/`，三份清单都指向它。

**整理笔记是为了给人看的，不是给计算机看的。** 这是本 skill 的第一原则：所有落库文字遵守一套「人话写作守则」，拒绝翻译腔和 AI 八股。

## 功能点

### 输入与整理

- **链接 / 草稿 → 中文笔记**：抓取正文或读取本地草稿，整理成结构化中文笔记
- **知识类 / 实验类模板**：知识类偏概念解释，实验类偏设置、方法、数据与结论，按内容自动分流

### 查重与合并

- **落库前全库查重**：扫描知识库，先做关键词初筛，再由 Agent 结合正文做语义裁决
- **命中合并**：优先追加新知识，只有事实错误、笔误或过时才改写；先预览 diff，确认后写入
- **未命中新建**：按模板生成，不另建重复笔记

### 文风与排版

- **本地文风画像**：统计句长、标点、人称、语气词、连接词、句首习惯、修辞偏好和段落节奏；Agent 阅读样本后补全语气与用词描述
- **写入前风格检查**：用 `style_check.py` 对比草稿与画像，提示句长、标点、用词和排版上的明显偏差
- **排版自适应**：新建前学习同目录的 frontmatter、标题层级、列表标记、强调用法和结构元素密度
- **人话写作守则**：段落优先、说人话、去 AI 腔；过渡句按中文语境重写，可选极客梗，延伸内容明确标注

### 归档与双链

- **Obsidian 双链**：概念自动 `[[]]` 到已有笔记，标题优先匹配 + 语义置信度兜底
- **frontmatter 三字段**：只有 `author / created / tags`（tags ≤ 3 且概括本篇）
- **来源留痕**：写在正文文末，不污染属性区

### 工程与兼容

- **零第三方依赖**：全部脚本只用 Python 标准库，Python 3.8+
- **一套源码，三种插件**：ZCode、Claude Code、Codex / ChatGPT 共用 `plugins/note-curator/skills/note-curator/`
- **独立 skill 可用**：任何支持 Agent Skills 的客户端都能直接使用

## 仓库结构

```text
note-curator/
├── .agents/
│   └── plugins/
│       └── marketplace.json          # Codex / ChatGPT 插件市场
├── .claude-plugin/
│   └── marketplace.json              # Claude Code 插件市场（ZCode 也读取）
├── plugins/
│   └── note-curator/                 # 唯一的插件根目录
│       ├── .zcode-plugin/
│       │   └── plugin.json           # ZCode 插件清单
│       ├── .claude-plugin/
│       │   └── plugin.json           # Claude Code 插件清单
│       ├── .codex-plugin/
│       │   └── plugin.json           # Codex / ChatGPT 插件清单
│       └── skills/
│           └── note-curator/
│               ├── SKILL.md          # 技能主流程
│               ├── config.example.yaml
│               ├── references/       # 写作守则、模板、合并规则、文风画像、Obsidian 适配
│               ├── scripts/          # 初始化 / 扫库 / 查重 / 学排版与文风 / 抓网页 / 落库
│               ├── examples/         # 两篇示例笔记
│               └── agents/openai.yaml
├── README.md
└── LICENSE
```

三份 `plugin.json` 只描述安装和展示信息；技能行为由 `plugins/note-curator/skills/note-curator/SKILL.md` 及其脚本决定。

## 安装

> 同一个客户端里，手动安装的技能副本优先级高于插件提供的技能。安装插件前，请先移除对应目录下的手动副本，例如 `~/.zcode/skills/note-curator`、`~/.claude/skills/note-curator`、`~/.agents/skills/note-curator`。

### ZCode

1. 打开「插件市场 → 添加 → 添加插件市场」。
2. 粘贴仓库地址：`https://github.com/Huayudong/note-curator`。
3. 在「个人 → note-curator-market」中安装「笔记管家」。

这是自定义市场源，不等同于 ZCode 官方市场的收录。

### Claude Code

```bash
/plugin marketplace add Huayudong/note-curator
/plugin install note-curator@note-curator-market
```

Claude Code 读取仓库根目录的 `.claude-plugin/marketplace.json`，以及插件根目录的 `.claude-plugin/plugin.json`。具体命令和入口以你的 Claude Code 版本为准。

### Codex / ChatGPT

Codex CLI：

```bash
codex plugin marketplace add Huayudong/note-curator
codex plugin add note-curator@note-curator-market
```

也可以打开 `/plugins`，在 `note-curator-market` 中浏览并安装。

ChatGPT 桌面版：

1. 打开 Plugins / 插件目录。
2. 添加或导入市场，粘贴仓库地址。
3. 安装「笔记管家」。

ChatGPT 工作区管理员：

```text
Admin → Plugins → Add → Import marketplace
```

填写仓库地址，`Path` 留空（市场文件在仓库根目录的 `.agents/plugins/marketplace.json`）。

ChatGPT 的 Skills / Plugins 入口和可用性取决于套餐与工作区设置；官方公共插件目录的收录需要单独提交和审核，GitHub 仓库本身不会自动出现在官方目录中。

### 独立技能（任意 Agent）

如果客户端支持 Agent Skills，但不想使用插件市场，可以直接安装技能目录：

```bash
npx skills add Huayudong/note-curator/plugins/note-curator/skills/note-curator
```

或手动复制：

```bash
git clone https://github.com/Huayudong/note-curator.git
cp -r note-curator/plugins/note-curator/skills/note-curator ~/.agents/skills/note-curator
# ZCode:       ~/.zcode/skills/note-curator
# Claude Code: ~/.claude/skills/note-curator
# 其他 Agent： 放进它加载 skills 的目录
```

插件根目录是 `plugins/note-curator`，所以 `npx skills add` 需要写到技能子目录。这是为了兼容 Codex 的插件市场布局。

## 首次初始化

**方式 A · 对话式**：直接把链接或草稿交给 Agent。首次调用会先运行 `check_setup.py`；未配置 vault、路径失效或署名为空时，插件会先拦截并引导配置，不会把整篇笔记直接输出到会话。配置完成后才会抓正文、查重和归档。

> 如果只想先看效果，明确说「只预览，不归档」；插件只给一小段预览，不会输出完整笔记。

**方式 B · 命令式**：

```bash
python plugins/note-curator/skills/note-curator/scripts/init_setup.py --vault "D:/Obsidian/MyVault" --author "你的署名"
# vault 目录还不存在？加 --create-vault
# 想逐项询问？不带参数直接运行脚本
# 已经安装到 Agent 的话，在技能目录里运行 scripts/init_setup.py
```

随时检查配置是否就绪：

```bash
python plugins/note-curator/skills/note-curator/scripts/check_setup.py --json
```

配置默认写入 `~/.note-curator/config.yaml`；如果技能目录里已有旧的 `config.yaml`，沿用旧文件；也可以用 `--config <路径>` 显式指定。插件升级或重装不会覆盖用户级配置。

## 使用

- 「帮我整理这篇文章：<URL>」→ 抓取、查重、生成或合并
- 「把这段草稿归档进知识库：……」→ 草稿模式
- 「先查重，再决定是合并还是新建：……」→ 合并流程
- 写入前会展示 diff 预览，确认后才落库

## 文风学习（可选）

插件不只模仿排版，也可以从同目录已有笔记学习文风：句长、标点、人称、语气词、连接词、句首习惯、修辞偏好和段落节奏。统计由脚本完成，语气、用词偏好等定性部分由 Agent 阅读样本后写入 `voice.md`。

建立画像：

```bash
python plugins/note-curator/skills/note-curator/scripts/style_profile.py \
  --vault "D:/Obsidian/MyVault" --dir "04 人工智能" --sample 20
```

默认写到 `~/.note-curator/style-profiles/<目录名>/`：

- `profile.json`：机器可读的统计指标
- `profile.md`：人可读的统计摘要
- `voice.md`：定性画像，Agent 阅读样本后补全

写入前检查：

```bash
python plugins/note-curator/skills/note-curator/scripts/style_check.py \
  _note.md --profile "~/.note-curator/style-profiles/04-人工智能/profile.json"
```

结论分「基本一致 / 轻微偏差 / 明显偏差」。统计检查只覆盖可量化特征，不判断内容正确性，也不保证完全复制作者。

注意：

- 建议至少 10 篇或 5000 字同目录样本；默认取最近 20 篇。
- 主题差异大时可能出现误报；以 `voice.md` 和实际阅读为准。
- 画像和 samples 含个人内容，默认存放在 `~/.note-curator/`，不要提交到公开仓库。

## 配置速览

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `vault_path` | 知识库根目录（Obsidian vault） | 空 = 引导初始化 |
| `taxonomy.rules` | 领域关键词 → 目录的归类规则 | 编程 / AI / 人文 / 杂学示例 |
| `frontmatter.author` | 笔记署名 | 空 = 初始化时询问 |
| `dedup.similarity_threshold` | 主题相似度命中阈值 | 0.65 |
| `backlinks.min_confidence` | 语义双链置信度下限 | 0.6 |
| `style.geek_joke_probability` | 极客梗触发频率（0 为关闭） | 0.33 |
| `style.allow_extension` | 允许延伸回答源文未解问题 | true |
| `style.learn_from_vault` | 是否启用本地文风画像 | true |
| `style.profile_sample` | 建立画像时取最近 N 篇 | 20 |
| `style.profile_dir` | 画像保存目录 | `~/.note-curator/style-profiles` |
| `style.check_before_write` | 写入前是否做风格偏差检查 | true |

> `config.yaml` 默认生成在 `~/.note-curator/config.yaml`，包含本机路径与署名，已列入 `.gitignore`，请勿提交。

## 示例

见 [`plugins/note-curator/skills/note-curator/examples/`](plugins/note-curator/skills/note-curator/examples/)：一篇知识类（缓存穿透、击穿与雪崩），一篇实验类（RAG vs 长上下文），展示模板结构、人话文风、极客梗的浓度上限，以及延伸思考的标注方式。

## 兼容性说明

- 插件清单只负责安装、展示和更新；技能是否可用，仍取决于客户端是否支持 Agent Skills、是否具备本地文件/命令执行能力。
- 各客户端的插件市场是独立机制。本仓库提供的是自定义市场源，发布到 GitHub 不会自动进入任何官方公共目录；官方目录的收录按各平台流程另行提交和审核。
- ChatGPT 与 Codex 的 Skills / Plugins 可用性受套餐、工作区设置和客户端版本影响；企业或教育工作区可能还需要管理员启用相关权限。
- 需要读写本地 Obsidian vault 和运行 Python 脚本时，请在具备本地文件与命令执行能力的会话中使用。

## 维护者：发布新版本

1. 同步修改三份 `plugin.json` 的 `version`：`plugins/note-curator/.zcode-plugin/plugin.json`、`.claude-plugin/plugin.json`、`.codex-plugin/plugin.json`。
2. 同步修改 `.claude-plugin/marketplace.json` 中对应条目的 `version`。
3. 在目标客户端刷新市场并更新插件；如果已在官方目录上架，按对应平台流程重新提交。
4. 提交新版本前运行一次技能脚本的语法检查，并确认 `plugins/note-curator/skills/note-curator/SKILL.md` 的 frontmatter 仍包含有效的 `name` 和 `description`。

## 设计原则

1. **查重先于新建**——知识库最怕重复，先找旧笔记
2. **优先增、有错才改**——尊重作者原有措辞，包括不为「去 AI 味」改写旧笔记
3. **三字段铁律**——属性区是给检索的最小集，溯源信息写正文文末
4. **改写不越界**——术语、数据、结论、引语忠实原文；延伸内容必须标注「整理者延伸」
5. **预览后才写盘**——所有合并操作先出 diff，用户确认才落库

## 致谢

- [OpenAI《Model guidance》（GPT-6 Astra）「Personality and writing style」](https://developers.openai.com/api/docs/guides/latest-model) —— 段落优先、说人话、去 slop 的生成侧指导
- [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) —— 11 条基于人类 / AI 语料实测的去 AI 味规则
- [KKKKhazix/human-writing](https://github.com/KKKKhazix/human-writing)（经 lieflat 间接参考）
- [write-like-me](https://github.com/Hiro-Inagawa/write-like-me)（MIT）—— 文风画像与确定性检查器的结构参考；本实现按中文笔记重写了特征与规则

## License

[MIT](LICENSE)
