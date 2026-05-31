# hermes-agent 定制改造与上游同步日志

> 仓库：`hermes-agent`（上游：NousResearch/hermes-agent）
> 维护规范：参见根目录 `DEVELOPMENT.md` 第六章
> 记录类型：`[Custom]` 定制改造 / `[Sync]` 上游同步 / `[Reset]` 分支重置

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
- 新增文件 / 修改文件 / 删除文件
- 冲突处理：策略与原因
- 不可合并模块：原因 + 后续策略
- 合并建议：短期 / 长期
- 提交：`chore(sync): merge upstream main into custom @ YYYY-MM-DD`
```

---

## 历史记录（最新在上）

<!-- 在此处自上向下追加记录 -->

## [Reset] 2026-05-31 ─ 废弃旧 custom，基于最新 upstream/main 重建

- **背景**：旧 custom 分支采用侵入式重写策略（直接把上游的 `readConfigYaml/saveEnvValue` 替换为 `callConfigApi`），导致每次上游同步冲突 1000+ 行，且偏离上游"多 profile / 用户视角"演进方向，长期不可维护
- **决策**：本次同步上游时（2026-05-31），评估冲突规模与架构错位后，废弃旧 custom 分支，从 `main`（已重置到 `upstream/main` 最新 `02d1da49d`）重新拉出干净的 `custom`
- **旧分支归档**：旧 custom 已推送为 `custom-legacy`（顶点 `558d621ce`），保留所有历史定制提交（含数据库抽象层 `d8364a4c4`、CUSTOM_CHANGELOG 制度建立、上次同步合并）作历史档案
- **后续计划**：按"扩展式 + StorageAdapter"架构重新实现企业级数据库与多模型配置能力
  - 上游 controller 文件几乎不改 → 上游同步零冲突
  - 在 `services/storage/` 新建 `StorageAdapter` 抽象层 + `Yaml/MySql/PgSql` 三种实现
  - 多 profile（上游方向）+ DB 多配置（企业方向）正交叠加
  - 通过环境变量 `STORAGE_BACKEND=yaml|mysql|postgres` 切换运行模式
- **本仓库新 custom 起点**：等同于 `upstream/main @ 02d1da49d`，无任何定制改动
