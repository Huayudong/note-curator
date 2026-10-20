# note-curator Obsidian 插件（B09 预览版）

在 Obsidian 内完成：整理当前笔记（生成 → 预览 → 应用）、学习这次修改
（差异 → 候选确认）、偏好管理、写入日志、配置检查。与外部 Agent Skill
**共用同一核心脚本与状态**（WritePlan 事务、画像、语言包、偏好），
两个入口同时打开时的写入由同一套 base_hash 校验与文件锁保护。

## 安装（手动）

1. 把 `apps/obsidian-plugin/` 整个目录复制到
   `<你的vault>/.obsidian/plugins/note-curator/`。
2. Obsidian → 设置 → 第三方插件 → 启用 **Note Curator 笔记管家**。
3. 设置页填写「核心脚本目录」：本仓库
   `plugins/note-curator/skills/note-curator/scripts` 的绝对路径，
   以及 Python 命令（默认 `python`）。

依赖：本机 Python 3.8+（与核心一致，无第三方依赖）。

## 命令

| 命令 | 行为 |
|---|---|
| 整理当前笔记 | SourceDocument → 生成草稿 → write_note 预览 → 弹窗应用/取消（base_hash 冲突会拒绝并保留双方内容） |
| 学习这次修改 | learn_edit diff → 候选弹窗，逐条确认才生效 |
| 偏好管理 | 列出 active/停用状态 |
| 写入日志 | 最近 WritePlan 记录 |
| 检查配置 | check_setup 结果 |

侧栏视图显示「待学习清单」——保存事件只做**发现**（B09-08）：
插件自身写入会被过滤，其余修改仅记录路径，绝不自动学习。

## 模型连接（插件内独立生成路径）

设置页填写 OpenAI 兼容 Base URL 与模型名。API key 两种给法：

1. **推荐**：环境变量 `NC_LLM_API_KEY`（不落盘）。
2. 填在设置页：存储于本插件数据文件（`.obsidian/plugins/note-curator/data.json`），
   不会写入 vault 笔记或日志；请勿把该目录纳入同步。

核心调用时 key 仅通过 `NC_LLM_API_KEY` 环境变量传递。

## 已测试版本（诚实边界）

- 插件逻辑（核心桥 JSON 契约、生成/预览/学习/偏好命令链）在
  Windows 10+ / Python 3.8+ 上由自动化契约测试覆盖（`tests/run_plugin_contract.py`）。
- Obsidian 图形端内的人类操作路径（弹窗交互、Ribbon 点击）当前为
  **代码审阅级预览**：核心契约与脚本闭环已测，GUI 交互待在 Obsidian
  1.5+（Windows）上人工验证后升级为正式支持。已知限制：移动端不支持
  （桌面子进程方案）。

## 卸载

移除插件目录即可；`~/.note-curator/` 下的计划/日志/画像与 vault 笔记
不受影响，可按需手动清理。
