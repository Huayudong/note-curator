# 发布与渠道

## 版本与兼容矩阵

- 核心写入者版本 `nc_core.WRITER_VERSION` 独立维护，状态格式或写入语义变化时递增；插件版本按发布节奏单独管理；
- 状态 schema 上限：`nc_core.SCHEMA_MAX`（plan/baseline/source_document/
  source_registry=1；index/profile=3；pack=1）；
- 语言包 `pack.json` 声明 `pack_version` 与 `compat.min_core`；`manifest.json`
  记录 `pack_version`、`channel` 与逐文件 sha256；
- Obsidian 插件 `apps/obsidian-plugin/manifest.json` 的版本独立维护。

## 发布流程

1. 版本号四处同步：三份 `plugin.json` + `.claude-plugin/marketplace.json`；
2. 语言包变更：更新 pack.json → 运行
   `python scripts/resource_pack.py --lang zh --write-manifest`（生成完整性
   清单）→ `resource_pack.py --lang zh --json` 校验通过；
3. 全部回归：按 `.github/workflows/tests.yml` 运行 `tests/run_*.py` 全部测试
   脚本（CI 同）；
4. 提交 tag；发布说明列出：新增规则（含出处）、行为变化、已知限制。

## 渠道

- **stable**（默认）：`language-packs/<lang>/`，candidate 规则不生效；
- **experimental**：`NC_PACK_CHANNEL=experimental` 时加载 candidate 规则
  用于试用；晋升 stable 需回归 + 盲评报告；
- 回退：`language-packs/.backup/<语言目录>-prev-<时间戳>/` 保留上一版本，
  复制回原位即回退（见 troubleshooting.md）。

## 已知限制（如实声明）

- Obsidian 图形端交互为代码审阅级预览，待人工验证；
- 评测集目前为 8 任务种子集，扩到 140 任务矩阵是后续工作；
- 用户试用与盲评尚无真实参与者数据；不对外宣称「像本人」类效果。
