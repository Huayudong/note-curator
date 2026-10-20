# 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `E-VAULT-MISSING` | vault 路径不存在或拼写错误 | `check_setup.py --json` 核对；init_setup 重建配置 |
| `E-TARGET-EXISTS` | 目标笔记已存在且内容不同 | 改用 merge 模式，或换标题 |
| `E-CONFLICT-BASE`（退出码 3） | 预览后文件被外部修改 | 按提示重新预览；反向差异文件在 `writes/backup/` |
| `E-LOCK`（退出码 2） | 另一进程持锁写入同一 vault | 稍后重试；崩溃残留锁 5 分钟自动过期 |
| `E-SCHEMA-NEW` | 状态文件由更新版本的写入者创建 | 升级插件；不要手工改 schema 字段 |
| `E-PLAN-REVERTED` | 计划已撤销 | 重新整理生成新计划 |
| 语言包不可用 | pack.json 损坏 / 完整性不符 / 超限额 | `doctor.py` 查看详情；回退方法见下 |
| 检查结论「明显偏差」 | 草稿与画像统计差距大 | 按 findings 调整；最多修订两轮，不循环重写 |

## 语言包回退

当前包出问题时，从备份恢复：

```bash
ls plugins/note-curator/skills/note-curator/language-packs/.backup/
# 选择上一个版本目录，复制回 language-packs/zh-CN（或 en/）即可
```

内置兜底：包缺失/损坏时核心自动回退到代码内置词表（stderr 会有
`[PACK]` 提示），基础功能不受阻。

## 诊断与清理

```bash
python scripts/doctor.py --json        # 版本/占用/状态审计/锁
python scripts/doctor.py --clean       # 按保留期限清理计划/基线/备份
python scripts/write_note.py prune     # 同上（write_note 入口）
```

## 学习相关

- 「学习无差异」：与基线内容一致，属正常幂等；
- 「E-PLAN-REVERTED」：该计划已撤销，重新整理即可；
- 反馈与待办任务：`feedback.py list`。
