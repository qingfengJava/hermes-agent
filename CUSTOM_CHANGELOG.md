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

## 历史记录（最新在上）

<!-- 在此处自上向下追加记录 -->

## [Init] 2026-05-31 ─ 建立 CUSTOM_CHANGELOG 制度

- 创建本日志文件，作为 hermes-agent 仓库定制改造与上游同步的统一账本
- 后续所有定制开发与上游同步**必须**在此追加条目，详见根目录 `DEVELOPMENT.md` §6
