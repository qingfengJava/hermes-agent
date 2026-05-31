# hermes-agent 定制改造与上游同步日志

> 仓库：`hermes-agent`（上游：NousResearch/hermes-agent）
> 维护规范：参见根目录 `DEVELOPMENT.md` 第六章
> 记录类型：`[Custom]` 定制改造 / `[Sync]` 上游同步

---

## 模板（复制使用）

### 定制改造模板

```markdown
## [Custom] YYYY-MM-DD ─ 简短标题

- 类型：feat / fix / refactor / chore
- 范围：彻底改造 | 增量优化 | 新增独立模块
- 影响文件：
  - `path/to/file_a.py`（新增）
  - `path/to/file_b.py`（修改 12-45 行，做了 xxx）
- 与上游关系：
  - [独立] 新增文件，无合并风险
  - [叠加] 修改了上游文件，未来同步需关注此处
  - [改造] 彻底重写，上游对应改动不再合并
- 测试：本地冒烟通过 / 单测通过 / 接口联调通过
- 提交：`feat(custom): xxx`（commit hash）
```

### 上游同步模板

```markdown
## [Sync] YYYY-MM-DD ─ 同步上游 NousResearch/main

- 上游版本：commit `<short-sha>`（或 release tag）
- 新增文件：
  - `path/...`（无冲突）
- 修改文件：
  - `path/...`：自动合并 | 手动合并（保留 xxx）
- 删除文件：
  - `path/...`（我们未引用 / 我们已替换）
- 冲突处理：
  - 文件 A：策略与原因
- 不可合并模块：（若有）
  - 模块 X：原因 + 后续策略
- 合并建议：
  - 短期：xxx
  - 长期：xxx
- 提交：`chore(sync): merge upstream main into custom @ YYYY-MM-DD`
```

---

# 历史记录（最新在上）

<!-- 在此处自上向下追加记录 -->

## [Sync] 2026-05-31 ─ 同步上游 NousResearch/main → custom

- 上游版本：`02d1da49d Block Hermes root config in media delivery`
- 网络：HTTPS 拉取失败（Connection was reset），按规范启用 SSH 兜底（`git remote set-url upstream git@github.com:NousResearch/hermes-agent.git`），同步完已保留 SSH 形态
- 上游变化：上游 main 较远程 origin/custom 上次同步点（`0ce0c449b`，2026-05 之前）领先约 1000+ commit，覆盖 v0.15.0 / v0.15.1 发版、大量 fix/feat、website i18n 全量重建、ko 语言包重整等
- 冲突处理：本次 merge 自动完成，仅有 `hermes_cli/config.py` 走 recursive 合并策略，无人工冲突
- 与定制改造的影响：本仓库现有定制为 `d8364a4c4 feat(custom): 添加数据库抽象层，支持 MySQL/PostgreSQL 共享数据库`（已在上次同步中并入 `0ce0c449b`），本次未触碰该模块文件，理论无回归
- 合并建议：
  - 短期：建议运行 hermes-agent 的冒烟测试和 db adapter 相关单测，验证数据库抽象层未被上游改动间接破坏
  - 长期：上游已大幅重构 plugins/model-providers、web、tools 等目录，建议下次接入新业务前评估是否需要将"数据库抽象层"重构为标准 plugin，降低后续合并成本
- 提交：`6f77f0823 chore(sync): merge upstream main into custom @ 2026-05-31`

## [Init] 2026-05-31 ─ 建立 CUSTOM_CHANGELOG 制度

- 创建本日志文件，作为 hermes-agent 仓库定制改造与上游同步的统一账本
- 后续所有定制开发与上游同步**必须**在此追加条目，详见根目录 `DEVELOPMENT.md` §6
