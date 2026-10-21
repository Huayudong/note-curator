# 发布与渠道（B12-10）

## 版本与兼容矩阵

- 插件版本与核心写入者版本一致（`nc_core.WRITER_VERSION`）；
- 状态 schema 上限：`nc_core.SCHEMA_MAX`（plan/baseline/source_document/
  source_registry=1；index/profile=3；pack=1）；
- 语言包 manifest 声明 `compat.min_core`；渠道声明 `channel`。

## 发布流程

1. 版本号四处同步：三份 `plugin.json` + `.claude-plugin/marketplace.json`；
2. 语言包变更：更新 pack.json → 运行
   `python scripts/resource_pack.py --lang zh --write-manifest`（生成完整性
   清单）→ `resource_pack.py --lang zh --json` 校验通过；
3. 全部回归：`run_style_tests.py`、`run_write_tests.py`、
   `run_plugin_contract.py`、`run_b10_tests.py`、`run_b11_tests.py`、
   `run_b12_tests.py`、`run_b13_tests.py`（CI 同）；
4. 提交 tag；发布说明列出：新增规则（含出处）、行为变化、已知限制。

## 渠道

- **stable**（默认）：`language-packs/<lang>/`，candidate 规则不生效；
- **experimental**：`NC_PACK_CHANNEL=experimental` 时加载 candidate 规则
  用于试用；晋升 stable 需回归 + 盲评报告；
- 回退：`language-packs/.backup/<lang>-<版本>-<时间>/` 保留上一版本，
  复制回原位即回退（见 troubleshooting.md）。

## 已知限制（如实声明）

- Obsidian 图形端交互为代码审阅级预览，待人工验证；
- 评测集为 8 任务种子集，按方案 §9.2 的 140 任务矩阵扩容是后续工作；
- 用户试用与盲评尚无真实参与者数据；不对外宣称「像本人」类效果。
