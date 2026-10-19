# note-curator 笔记管家

note-curator（笔记管家）是一个开源的通用 Agent skill：把网页链接和本地草稿自动整理成「给人看的」结构化中文笔记——提炼成知识类或实验类笔记，先对整个知识库查重，命中旧笔记就合并补充、未命中才新建归档，并把文中概念自动链接到已有笔记（Obsidian 双链）。它只依赖 SKILL.md 和 Python 标准库脚本，Codex、Claude Code、Cursor 等任何支持工具调用的 Agent 都能直接安装使用。

**整理笔记是为了给人看的，不是给计算机看的。** 这是本 skill 的第一原则：所有落库文字遵守一套「人话写作守则」，拒绝翻译腔和 AI 八股。

## 功能特性

- **链接 / 草稿 → 中文笔记**：知识类、实验类两套模板，按内容自动分流
- **落库前全库查重**：命中旧笔记就合并补充（优先追加、有错才改），绝不另建重复笔记
- **Obsidian 双链**：概念自动 `[[]]` 到已有笔记，标题优先匹配 + 语义置信度兜底
- **人话写作守则**：段落优先、说人话、去 AI 腔（融合 OpenAI《Model guidance》与 lieflat-less-ai-tone 的 11 条实测规则）；过渡句按中文语境重写，可选极客梗，延伸思考明确标注
- **frontmatter 三字段铁律**：只有 `author / created / tags`（tags ≤ 3 且必须概括本篇）；来源留痕写正文文末，属性区永远干净
- **排版自适应**：新建前学习同目录已有笔记的排版风格，不画风突变
- **零依赖**：所有脚本只用 Python 标准库，Python 3.8+ 即可

## 快速开始

### 1. 安装到你的 Agent

**方式一 · ZCode 插件市场（推荐 ZCode 用户）**：仓库根目录带有 `.zcode-plugin/plugin.json` 和 `marketplace.json`，可以直接作为插件市场添加。

1. 打开 ZCode 的「插件市场 → 添加 → 添加插件市场」。
2. 粘贴仓库地址：`https://github.com/Huayudong/note-curator`。
3. 在「个人 → note-curator-market」里安装「笔记管家」。

> 如果之前手动把技能放进了 `~/.zcode/skills/note-curator`，请先删除那份再安装插件。用户级技能优先级高于插件技能，两者同时存在时插件版不会生效。

插件更新：在插件市场里刷新 `note-curator-market`，再打开插件详情点「更新」。

**方式二 · npx 一键安装（推荐非 ZCode 用户）**：SKILL.md 是跨 Agent 的开放标准（Claude Code、Codex、Cursor、Copilot CLI 等 27+ Agent 支持），skills CLI 会自动检测你机器上装了哪些 Agent，把技能放进正确的目录：

```bash
npx skills add Huayudong/note-curator
```

**方式三 · git clone / 手动复制**：技能源码在 `skills/note-curator/`，把它复制到 Agent 的 skills 目录，目录名保持 `note-curator`：

```bash
git clone https://github.com/Huayudong/note-curator.git
cp -r note-curator/skills/note-curator ~/.zcode/skills/note-curator   # ZCode / Codex
# Claude Code: cp -r note-curator/skills/note-curator ~/.claude/skills/note-curator
# 其他 Agent：放进它加载 skills 的目录即可
```

### 2. 初始化（约 30 秒）

**方式 A · 对话式**：直接丢一个链接给 Agent（「帮我整理这篇文章：<URL>」）。首次使用会引导你完成配置；未配置 vault 时也会先直接生成笔记内容给你看效果，不会卡在配置上。

**方式 B · 命令式**：

```bash
python skills/note-curator/scripts/init_setup.py --vault "D:/Obsidian/MyVault" --author "你的署名"
# vault 目录还不存在？加 --create-vault
# 想逐项询问？不带参数直接运行 python skills/note-curator/scripts/init_setup.py
# 已经安装到 Agent 的话，在技能目录里运行 scripts/init_setup.py
```

默认写入 `~/.note-curator/config.yaml`，插件升级/重装不会覆盖它。旧版手动安装留下的 `<技能目录>/config.yaml` 仍会被沿用。

### 3. 开用

- 「帮我整理这篇文章：<URL>」→ 抓取、查重、生成 / 合并
- 「把这段草稿归档进知识库：……」→ 草稿模式
- 写入前会展示 diff 预览，你确认后才落库

## 工作原理

```
            ┌─ 含 URL ──────────────→ 【链接模式】
识别输入 ──┤
            └─ 本地草稿/笔记文件 ──→ 【草稿模式】
                                          ↓
              ① 全库查重（scan + find_duplicates + LLM 语义裁决）
                                          ↓
              ② 命中 → 合并补充（优先 append，有错才 edit）→ 预览 → 确认 → 写入旧笔记
                 未命中 → 学排版风格 → 按模板生成（建双链）→ 定目录 → 新建写入
```

## 目录结构

```
note-curator/
├── .zcode-plugin/
│   └── plugin.json           # ZCode 插件清单
├── marketplace.json          # ZCode 插件市场目录
├── skills/
│   └── note-curator/
│       ├── SKILL.md          # skill 主流程（Agent 读这份）
│       ├── config.example.yaml
│       ├── references/       # 写作守则、模板、合并规则、Obsidian 适配
│       ├── scripts/          # 初始化 / 扫库 / 查重 / 学排版 / 抓网页 / 落库
│       ├── examples/         # 两篇示例笔记
│       └── agents/openai.yaml
├── README.md
└── LICENSE
```

> 本仓库同时是独立 skill 和 ZCode 插件。非 ZCode 用户只需要 `skills/note-curator/` 这一层，插件相关文件可以忽略。

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

> `config.yaml` 默认生成在 `~/.note-curator/config.yaml`（插件升级/重装不会覆盖；如果技能目录里已有旧的 `config.yaml` 则沿用旧文件）。它含本机路径与署名，已列入 `.gitignore`，请勿提交。

## 示例

见 [examples/](skills/note-curator/examples/)：一篇知识类（缓存穿透、击穿与雪崩），一篇实验类（RAG vs 长上下文），展示模板结构、人话文风、极客梗的浓度上限，以及延伸思考的标注方式。

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

## License

[MIT](LICENSE)
