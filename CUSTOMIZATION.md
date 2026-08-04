# CUSTOMIZATION.md — 自有改造台账（hermes-agent）

> **强制要求**：凡进入 `dev` 的自有改动，必须在本文件逐条登记。
> 本台账是上游同步冲突解决、以及上游大重构导致自有 patch 失效后重建的**唯一依据**。漏登记 = 改动随时可能丢失。
> 规范详见 `.qoder/rules/hermes-rules.md` 第六节与本仓 `BRANCHING.md` 第八节。

## 台账记录

| 日期 | 改动位置 | 意图 | 热区标记 | 重建说明 |
| --- | --- | --- | --- | --- |
| 2026-08-04 | `BRANCHING.md`（新增） | 分支管理与上游同步规范文档 | 否（独立新文件，上游无同名文件） | 无需重建；内容与 `.qoder/rules/hermes-rules.md` 保持同步 |
| 2026-08-04 | `CUSTOMIZATION.md`（新增） | 改造台账模板初始化 | 否（独立新文件，上游无同名文件） | 无需重建 |

<!--
登记格式说明：
| YYYY-MM-DD | 文件/目录路径（新增/修改） | 为什么改、实现什么 | 是/否（是否触及上游高频变动文件） | 上游大重构导致失效时如何重建 |

热区文件参考（上游高频变动，改动需详录重建说明）：
- run_agent.py、cli.py、model_tools.py、toolsets.py
- gateway/run.py、gateway/session.py、gateway/config.py
- hermes_cli/main.py、hermes_cli/commands.py、hermes_cli/config.py
-->
