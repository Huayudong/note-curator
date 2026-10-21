**简体中文** | [English](README.en.md)

[![tests](https://github.com/Huayudong/note-curator/actions/workflows/tests.yml/badge.svg)](https://github.com/Huayudong/note-curator/actions/workflows/tests.yml)

# note-curator 笔记管家

把网页链接和本地草稿整理成结构化笔记，归档进你的 Obsidian 知识库，并向同目录已有笔记的排版与文风靠拢。中文优先，也支持英文笔记。

note-curator 是一个开源的笔记整理 Agent Skill（中文优先、支持中英双语）：抓取文章或读取草稿，先在全库查重，命中旧笔记就合并补充、未命中才新建；写入前核对事实、检查文风，落库时按 Obsidian 约定建立双链。它只依赖 Python 标准库，同时提供 ZCode、Claude Code、Codex / ChatGPT 的薄插件清单。

## 功能与工作方式

```text
输入 → 抓取/读取 → 全库查重 → 合并或新建 → 事实与文风检查 → 预览 → 应用 / 撤销
```

- **链接 / 草稿 → 结构化笔记**：URL 或本地文件统一解析成结构化段落（表格、代码保序保留）；截断、登录墙、动态页等七类不完整状态会如实报告，先补料再整理，不假装读完；来源内容只作资料，不执行其中指令。内置知识类与实验类两种模板。
- **查重与合并**：关键词初筛 + 语义裁决，默认同语言互查（英文带轻量词形归一与标题加权）；命中优先追加新知识，只修正明确错误并先给 diff 预览；未命中才新建。
- **检索与双链**：大库可建全文分块索引（增量更新），召回附证据块与位置，长文尾部也能命中；双链写入前按路径、别名、标题锚点和块 ID 验证，断链阻断落库。链接只放在正文知识点出现处，不生成文末「相关笔记」清单。
- **事实保真**：落库前核对数字与单位、日期、限定条件、否定和观点归属；同时执行篇幅软预算（超硬上限提示拆分）与尾部链接清单检测，检查不过最多修订两轮。
- **文风与排版**：统计句长、标点、人称、语气词、连接词、句首习惯与段落节奏，并学习目标目录的 frontmatter、标题层级、列表和强调；写入前提示明显偏差。落库文字遵守人话守则（段落优先、去 AI 腔，过渡句按目标语言重写）。中英文画像默认按「目录-语言」分开存放，同目录双语样本互不污染。
- **语言包**：`language-packs/zh-CN` 与 `en` 内置 AI 腔规则、术语首现表和带出处的示例句；用户允许/禁用表达优先，包缺失或损坏自动回退内置词表。
- **改稿学习**：只从你的修改中提炼表达与排版偏好，事实修正不会变成文风偏好；默认候选确认后才生效，auto 模式在同类候选跨 ≥2 篇独立笔记时自动生效。支持 off / explicit / assisted / auto 四档，以及停用、忘记、导出导入与冲突报告。
- **笔记约定**：一篇笔记围绕一个主题，独立旁支先查重复用、确需新建时拆成完整子笔记并从正文链接；frontmatter 只有 `author / created / tags`（tags ≤ 3），来源留痕写在正文文末。
- **写入安全**：新建与合并共用「计划 → 应用 → 撤销」事务，应用前校验文件哈希；原子替换、受控备份、写入日志，路径限制在 vault 内（拒绝绝对路径、`..` 上跳与符号链接逃逸）。
- **语言与工程**：输出语言按「本次指定 > 目标笔记 > 配置 > 源文」决策，跨语言保留事实、数字与归属；脚本零第三方依赖，兼容 Python 3.8+，一套源码供 ZCode、Claude Code、Codex / ChatGPT 与独立技能使用。

## Obsidian 原生插件（预览）

`apps/obsidian-plugin/`：在 Obsidian 内整理当前笔记（生成 → 预览 → 应用/撤销）、
学习这次修改（候选确认才生效）、偏好管理与写入日志——与外部 Agent Skill
**共用同一核心与状态**。保存事件只做发现，绝不自动学习；API key 走环境变量
或插件本地数据，不进笔记与日志。安装与已测版本边界见
[插件说明](apps/obsidian-plugin/README.md)。

## 安装

Agent 插件根目录是 `plugins/note-curator/`，技能源码在 `plugins/note-curator/skills/note-curator/`。所有客户端共用同一份技能。

### ZCode

1. 打开「插件市场 → 添加 → 添加插件市场」。
2. 粘贴 `https://github.com/Huayudong/note-curator`。
3. 在「个人 → note-curator」安装「笔记管家」。

这是自定义市场源，不等同于 ZCode 官方市场收录。

### Claude Code

```bash
/plugin marketplace add Huayudong/note-curator
/plugin install note-curator@note-curator
```

### Codex / ChatGPT

Codex CLI：

```bash
codex plugin marketplace add Huayudong/note-curator
codex plugin add note-curator@note-curator
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

首次调用会先运行配置检查。如果 vault 路径或署名缺失，技能会拦截并引导配置，不会把整篇笔记直接输出到会话。

```bash
python plugins/note-curator/skills/note-curator/scripts/check_setup.py --json
python plugins/note-curator/skills/note-curator/scripts/init_setup.py \
  --vault "D:/Obsidian/MyVault" --author "你的署名"
```

配置默认写入 `~/.note-curator/config.yaml`；如果技能目录里已有旧的 `config.yaml`，沿用旧文件。升级插件或技能不会覆盖用户级配置。

然后直接说：

```text
帮我整理这篇文章：<URL>
```

```text
把这段草稿归档进知识库：……
```

写入前会先展示 diff 预览，确认后才落库；写入采用「计划 → 应用 → 可撤销」事务（见上文「功能与工作方式」）。

## 文风学习

从某个目录最近的笔记建立画像。中文按字、英文按词分别统计；语言自动检测，也可 `--lang zh|en` 强制指定，草稿只与同语言画像比较。

```bash
python plugins/note-curator/skills/note-curator/scripts/style_profile.py \
  --vault "D:/Obsidian/MyVault" --dir "04 AI" --sample 20
```

输出到 `~/.note-curator/style-profiles/<目录名>-<语言>/`：

- `profile.json`：统计指标（含 language 字段）
- `profile.md`：统计摘要
- `voice.md`：定性画像模板（中文/英文各一套），Agent 阅读样本后补全

写入前检查草稿：

```bash
python plugins/note-curator/skills/note-curator/scripts/style_check.py \
  _note.md --profile "~/.note-curator/style-profiles/04-AI-zh/profile.json"
```

结论分「基本一致 / 轻微偏差 / 明显偏差」；草稿与画像语言不一致时直接报「语言不一致」，不做跨语言比较。这是统计检查，不保证完全复制作者；建议同一目录至少 10 篇或 5000 单位。

中文画像额外统计把/被句式、四字格、口语词、顿号与书名号、中英混排度和 AI 腔命中：画像语料里没有、草稿里出现时直接报偏差。

画像会持续学习：改完一篇笔记后说「学习这篇的写法」，`style_learn.py` 会把改稿并入画像（按样本时间的滚动窗口、语言校验、历史留痕）。只学习你的改稿，绝不把插件自己生成的草稿当成你的文风。

## 配置

见 [`config.example.yaml`](plugins/note-curator/skills/note-curator/config.example.yaml)。主要配置项是 `vault_path`、`taxonomy.rules`、`dedup`、`backlinks` 和 `style`。

更多文档：[安装](docs/install.md) · [文风学习](docs/learning.md) · [迁移](docs/migration.md) · [隐私](docs/privacy.md) · [故障排查](docs/troubleshooting.md) · [发布与渠道](docs/release.md)。

## 质量与可靠性

- **评测**：`evals/` 的冻结评测集按来源哈希锁定，改动即拒绝执行；`run_eval.py` 输出逐任务事实保留、篇幅与尾部清单报告，支持按「公共规则 / +画像 / +偏好」分层评测与 `--sabotage` 缺陷演示；`blind_compare.py` 报方向偏好率与 Wilson 区间，`feedback.py` 默认只存本地。
- **稳定性**：同一 vault 的并发写入由跨进程锁拒绝，崩溃残留锁 5 分钟后自动接管；计划、基线、来源文档、索引、画像与语言包各有 schema 上限，旧版本拒绝读取新状态并提示升级；`doctor.py` 查看版本、语言包、活动锁与最近写入（脱敏），`--clean` 按保留期限清理；`perf_bench.py` 可复跑索引与检索基准。
- **语言包维护**：manifest 记录逐文件 sha256，加载前校验，篡改即拒绝；stable / experimental 双渠道，规则走 candidate → stable → deprecated 生命周期；`resource_pack.py --install/--rollback` 可逆换装，`pack_compare.py` 对比新旧包效果。
- **配置硬闸门**：ZCode / Claude Code 插件形态下，每次技能调用前自动运行配置检查；vault 路径无效、配置缺失或署名为空时直接拒绝本次调用并给出引导。闸门自身异常时 fail-open，不卡死插件；其他形态由 SKILL.md 的配置检查兜底。

## 兼容性

- 技能只用 Python 标准库，任何支持 Agent Skills 的客户端都可以使用。
- 插件清单分别面向 ZCode（`.zcode-plugin`）、Claude Code（`.claude-plugin`）和 Codex / ChatGPT（`.codex-plugin`）；市场文件在 `.claude-plugin/marketplace.json` 和 `.agents/plugins/marketplace.json`。
- 扫描 vault、运行脚本和写入笔记需要本地文件与命令执行权限。
- 官方市场收录和添加自定义市场是两件事；本仓库不会自动出现在任何厂商的官方目录中。

## 限制

- 文风学习是统计 + 定性描述，不是微调模型，不能保证完全复制作者。
- 画像默认按目录建立，依赖样本；主题差异大时可能出现误报。
- 不核实来源本身的真实性；落库前只检查关键事实是否被忠实保留，术语、数据、观点归属仍以原文为准。
- 首次调用在 `vault_path` 和 `author` 配置完成前会被有意拦截。

## 发布版本

同步修改三份 `plugin.json` 和 `.claude-plugin/marketplace.json` 的版本号；Obsidian 插件 `apps/obsidian-plugin/manifest.json` 的版本独立维护。刷新各客户端的市场，再发布新的 tag 或 commit。

## 致谢

- [write-like-me](https://github.com/Hiro-Inagawa/write-like-me)（MIT）—— 文风画像与确定性检查器的结构参考；本实现按中文笔记重写了特征与规则。
- [OpenAI《Model guidance》](https://developers.openai.com/api/docs/guides/latest-model) 与 [lieflat-less-ai-tone](https://github.com/larashero3-dotcom/lieflat-less-ai-tone) —— 写作风格指导。
- [KKKKhazix/human-writing](https://github.com/KKKKhazix/human-writing)。

## License

[MIT](LICENSE)
