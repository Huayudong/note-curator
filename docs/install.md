# 安装

## Agent Skill（推荐入口）

- ZCode：插件市场 → 添加市场 → 粘贴 `https://github.com/Huayudong/note-curator` → 安装「笔记管家」。
- Claude Code：`/plugin marketplace add Huayudong/note-curator` 然后 `/plugin install note-curator@note-curator-market`。
- Codex CLI：`codex plugin marketplace add Huayudong/note-curator` → `codex plugin add note-curator@note-curator-market`。
- 独立技能：`npx skills add Huayudong/note-curator/plugins/note-curator/skills/note-curator`。

## Obsidian 原生插件（预览）

把 `apps/obsidian-plugin/` 复制到 `<vault>/.obsidian/plugins/note-curator/`，
在设置中启用，并填写核心脚本目录（`skills/note-curator/scripts` 绝对路径）。
详见 [apps/obsidian-plugin/README.md](../apps/obsidian-plugin/README.md)。

## 依赖与版本

- Python 3.8+（无第三方依赖；语法兼容，CI 实测 3.10/3.13 × Windows/Linux）。
- 状态 schema 兼容矩阵见 `scripts/nc_core.py` 的 `SCHEMA_MAX`：由更新版本
  写入者创建的状态文件，旧版本会拒绝并提示升级，不会猜测。

## 升级与回退

- 用户配置 `~/.note-curator/config.yaml` 与画像不会被升级覆盖。
- 语言包升级：替换 `language-packs/<lang>/` 目录；回退见 `docs/troubleshooting.md`。
- 遇到 `E-SCHEMA-NEW`：说明状态文件由更新版本写入，先升级插件。
