[English](README.md) | **简体中文**

# note-curator 笔记管家

把网页链接和本地草稿整理成结构化中文笔记，归档进你的 Obsidian 知识库，并向同目录已有笔记的排版与文风靠拢。

note-curator 是一个开源的中文笔记整理 Agent Skill：抓取文章或读取草稿，先在全库查重，命中旧笔记就合并补充、未命中才新建；随后按 Obsidian 约定建立双链，并学习目标目录的 frontmatter、标题层级、列表、强调和段落节奏。它只依赖 Python 标准库，同时提供 ZCode、Claude Code、Codex / ChatGPT 的薄插件清单。

## 功能点

### 输入与整理

- **链接 / 草稿 → 中文笔记**：抓取正文或读取本地草稿，整理成结构化中文笔记。
- **知识类 / 实验类模板**：知识类偏概念解释，实验类偏设置、方法、数据与结论。

### 查重与合并

- **落库前全库查重**：关键词初筛 + Agent 结合正文做语义裁决。
- **命中合并**：优先追加新知识，只有事实错误、笔误或过时才改写；先给 diff 预览。
- **未命中新建**：按模板生成，不另建重复笔记。

### 文风与排版

- **本地文风画像**：统计句长、标点、人称、语气词、连接词、句首习惯、修辞偏好和段落节奏；Agent 阅读样本后补全语气与用词描述。
- **写入前风格检查**：对比草稿与画像，提示句长、标点、用词和排版上的明显偏差。
- **排版自适应**：学习同目录的 frontmatter、标题层级、列表标记、强调用法和结构元素密度。
- **人话写作守则**：段落优先、说人话、去 AI 腔；过渡句按中文语境重写，延伸内容明确标注。

### 归档与双链

- **Obsidian 双链**：概念自动 `[[]]` 到已有笔记，标题优先 + 语义置信度兜底。
- **frontmatter 三字段**：只有 `author / created / tags`（tags ≤ 3 且概括本篇）。
- **来源留痕**：写在正文文末，不污染属性区。

### 工程与兼容

- **零第三方依赖**：全部脚本只用 Python 标准库，Python 3.8+。
- **一套源码，三种插件**：ZCode、Claude Code、Codex / ChatGPT 共用 `plugins/note-curator/skills/note-curator/`。
- **独立 skill 可用**：任何支持 Agent Skills 的客户端都能直接使用。

## 安装

插件根目录是 `plugins/note-curator/`，技能源码在 `plugins/note-curator/skills/note-curator/`。所有客户端共用同一份技能。

### ZCode

1. 打开「插件市场 → 添加 → 添加插件市场」。
2. 粘贴 `https://github.com/Huayudong/note-curator`。
3. 在「个人 → note-curator-market」安装「笔记管家」。

这是自定义市场源，不等同于 ZCode 官方市场收录。

### Claude Code

```bash
/plugin marketplace add Huayudong/note-curator
/plugin install note-curator@note-curator-market
```

### Codex / ChatGPT

Codex CLI：

```bash
codex plugin marketplace add Huayudong/note-curator
codex plugin add note-curator@note-curator-market
```

ChatGPT 桌面版：打开 Plugins / 插件目录，添加或导入该仓库作为市场，然后安装 `note-curator`。工作区管理员可走 **Admin → Plugins → Add → Import marketplace**，`Path` 留空。

ChatGPT 的 Skills / Plugins 可用性取决于套餐、工作区设置和客户端版本。导入本仓库创建的是自定义市场，不会自动进入 OpenAI 官方公共目录。

### 独立技能

```bash
npx skills add Huayudong/note-curator/plugins/note-curator/skills/note-curator
```

或克隆后复制技能目录：

```bash
git clone https://github.com/Huayudong/note-curator.git
cp -r note-curator/plugins/note-curator/skills/note-curator ~/.agents/skills/note-curator
# ZCode:       ~/.zcode/skills/note-curator
# Claude Code: ~/.claude/skills/note-curator
```

安装插件前先移除手动安装的同名技能副本；用户级技能可能遮蔽插件版本。

## 快速开始

首次调用会先运行配置检查。如果 vault 路径或署名缺失，插件会拦截并引导配置，不会把整篇笔记直接输出到会话。

```bash
python plugins/note-curator/skills/note-curator/scripts/check_setup.py --json
python plugins/note-curator/skills/note-curator/scripts/init_setup.py \
  --vault "D:/Obsidian/MyVault" --author "你的署名"
```

配置默认写入 `~/.note-curator/config.yaml`；如果技能目录里已有旧的 `config.yaml`，沿用旧文件。插件升级不会覆盖用户级配置。

然后直接说：

```text
帮我整理这篇文章：<URL>
```

```text
把这段草稿归档进知识库：……
```

写入前会先展示 diff 预览，确认后才落库。

## 工作原理

```text
输入 → 抓取/读取 → 查重 → 合并或新建 → 文风检查 → 预览 → 写入
```

合并路径优先追加新知识，只修正明确错误；新建路径先学习目标目录的排版和文风，再生成草稿。

## 文风学习

从某个目录最近的笔记建立画像。中文与英文分开统计：中文按字（密度每千字），英文按词（密度每千词）；语言按语料自动检测，也可 `--lang zh|en` 强制指定，草稿只与同语言画像比较。

```bash
python plugins/note-curator/skills/note-curator/scripts/style_profile.py \
  --vault "D:/Obsidian/MyVault" --dir "04 AI" --sample 20
```

输出到 `~/.note-curator/style-profiles/<目录名>/`：

- `profile.json`：统计指标（含 language 字段）
- `profile.md`：统计摘要（语言跟随画像）
- `voice.md`：定性画像模板（中文/英文各一套），Agent 阅读样本后补全

写入前检查草稿：

```bash
python plugins/note-curator/skills/note-curator/scripts/style_check.py \
  _note.md --profile "~/.note-curator/style-profiles/04-AI/profile.json"
```

结论分「基本一致 / 轻微偏差 / 明显偏差」；草稿与画像语言不一致时直接报「语言不一致」，不做跨语言比较。这是统计检查，不保证完全复制作者；建议同一目录至少 10 篇或 5000 单位。

中文画像有额外的深度特征：把/被句式密度、四字格、口语词、顿号与书名号、中英混排度，以及与写作守则黑名单同步的 AI 腔命中——画像语料里没有、草稿里出现时直接报偏差。

## 配置

见 [`config.example.yaml`](plugins/note-curator/skills/note-curator/config.example.yaml)。主要配置项是 `vault_path`、`taxonomy.rules`、`dedup`、`backlinks` 和 `style`。

## 兼容性

- 技能只用 Python 标准库，任何支持 Agent Skills 的客户端都可以使用。
- 插件清单分别面向 ZCode（`.zcode-plugin`）、Claude Code（`.claude-plugin`）和 Codex / ChatGPT（`.codex-plugin`）；市场文件在 `.claude-plugin/marketplace.json` 和 `.agents/plugins/marketplace.json`。
- 扫描 vault、运行脚本和写入笔记需要本地文件与命令执行权限。
- 官方市场收录和添加自定义市场是两件事；本仓库不会自动出现在任何厂商的官方目录中。

## 限制

- 文风学习是统计 + 定性描述，不是微调模型，不能保证完全复制作者。
- 画像按目录建立，依赖样本；主题差异大时可能出现误报。
- 插件不负责核实事实；术语、数据、观点归属仍以原文为准。
- 首次调用在 `vault_path` 和 `author` 配置完成前会被有意拦截。

## 发布版本

同步修改三份 `plugin.json` 和 `.claude-plugin/marketplace.json` 的版本号，刷新各客户端的市场，再发布新的 tag 或 commit。

## 致谢

- [write-like-me](https://github.com/Hiro-Inagawa/write-like-me)（MIT）—— 文风画像与确定性检查器的结构参考；本实现按中文笔记重写了特征与规则。
- [OpenAI《Model guidance》](https://developers.openai.com/api/docs/guides/latest-model) 与 [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) —— 写作风格指导。
- [KKKKhazix/human-writing](https://github.com/KKKKhazix/human-writing)。

## License

[MIT](LICENSE)
