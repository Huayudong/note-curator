# 语言包贡献指南

感谢为 note-curator 的中英文语言库贡献表达规则。语言包是「受限数据 +
写作指导」，**不允许夹带任何可执行内容**。

## 规则字段

一条规则（pack.json 的 rules 数组项）必须包含：

| 字段 | 说明 |
|---|---|
| id | 全局唯一，格式 `<语言>.<类别>.<短名>`，如 `zh.ai-tell.hollow-booster` |
| category | 类别（ai_tell / transition / modifier / subject / terminology / register…） |
| severity | major / minor / suggestion / info |
| kind | deterministic（正则可查）/ contextual（需上下文判断）/ guidance（纯写作指导） |
| guidance | 为什么提示、怎么改（写给用户看） |
| pattern | 仅 deterministic 规则：正则，≤500 字符 |
| bad_example / better_example | 正反例；改写不得引入来源没有的事实 |
| exceptions | 合理例外（引语、用户允许项等） |
| status | stable / candidate / deprecated（默认 stable；新规则建议从 candidate 起） |

## 硬性限制（超出会被拒绝加载）

- rules ≤ 200 条；单条 pattern ≤ 500 字符且必须可编译
- terms 各列表 ≤ 500 项；pack.json ≤ 2MB

## 提交流程

1. 从 `rule-template.json` 复制并填写。
2. 自测：把规则放进一个临时包目录，跑
   `python scripts/resource_pack.py --lang zh --pack-root <临时目录> --json`，
   再用 `style_check.py --json` 在正反例上验证命中/例外行为。
3. 提交 PR：说明来源依据（语法书/语料/自查清单）、许可，以及至少一组
   正反例。无来源依据或纯个人偏好的规则请放 `candidate` 状态。
4. 合入前由维护者运行
   `python scripts/resource_pack.py --lang zh --write-manifest`（英文包用 `--lang en`）
   生成完整性清单。

## 渠道

- `stable`：默认渠道，candidate 规则不生效。
- `experimental`：环境变量 `NC_PACK_CHANNEL=experimental`，加载 candidate
  规则用于试用；晋升 stable 需通过回归与盲评报告。
- `deprecated` 规则保留在包内但不再加载，需注明替代规则 id。
