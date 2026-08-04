# 分支管理与上游同步规范（Fork 改造项目）

> **适用对象**：所有参与本仓库（`qingfengJava/hermes-agent`，fork 自 [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)）改造开发的人员与 AI 助手。
> **执行级别**：标注"禁止 / 必须"的条目为强制项，其余为推荐实践。

---

## 一、分支模型

本仓库是**长期改造的 downstream fork**。上游更新频繁，为保证"持续吸收上游更新"与"自有改造互不干扰"，采用三层分支模型：

```
upstream（NousResearch/hermes-agent，只读 remote，仅 fetch）
   │  git merge --ff-only（仅快进）
   ▼
main ──────────── 上游镜像分支：永远与上游 main 一致
   │  定期 git merge（每周一次，或跟随上游版本节奏）
   ▼
dev ───────────── 自有主分支：全部自有改造的最终归宿（GitHub 默认分支）
   │  PR 合入
   ▼
feature/xxx ───── 功能分支：从 dev 切出，完成后 PR 合回 dev，随即删除
```

## 二、各分支职责与铁律

| 分支 | 职责 | 规则 |
| --- | --- | --- |
| `main` | 上游镜像，仅用于跟踪/对比上游 | **禁止直接提交任何自有改动**；只接受 `upstream/main` 的 `--ff-only` 合并 |
| `dev` | 自有改造主分支 | **GitHub 默认分支**；只接受 feature 分支的 PR 合入；同步上游用 `git merge main`，**禁止 rebase** |
| `feature/*` | 单个功能/修复的开发分支 | 从最新 `dev` 切出；保持短小（天级）；合并后即删 |
| `custom`、`custom-legacy` | 历史废弃分支 | **已废弃，不再使用**；归档 tag 后可删除，禁止在其上继续开发 |

**三条铁律（违反即返工）：**

1. **main 只进不出**——任何自有代码不得进入 main。`git log dev..main` 必须永远精确反映"上游有、我们还没有"的提交。
2. **dev 禁止 rebase**——dev 是已推送的共享分支，rebase 改写历史会摧毁所有基于它的工作。同步上游一律 `git merge main`。
3. **两仓同节奏**——本仓库与 `hermes-web-ui` 存在运行时耦合（web-ui 的 agent-bridge 直接 import 本仓库 `run_agent`），同步上游时两个仓库必须在同一轮内完成，禁止单仓长期超前。

## 三、Remote 配置

```bash
origin    https://github.com/qingfengJava/hermes-agent.git      # 自己的 fork（读写）
upstream  https://github.com/NousResearch/hermes-agent.git      # 上游（只读）
```

新环境一次性配置：

```bash
git remote add upstream https://github.com/NousResearch/hermes-agent.git
git fetch upstream
```

## 四、日常开发 SOP

```bash
git checkout dev
git pull origin dev
git checkout -b feature/<英文业务名_YYYYMMDD>   # 例：feature/kanban_custom_columns_20260804

# …开发、提交…
# 提交信息遵循 Conventional Commits：feat/fix/docs/refactor/test/chore(可选 scope)

git push -u origin feature/<英文业务名_日期>
# 在 GitHub 开 PR：feature/<英文业务名_日期> → dev（默认分支已是 dev，不会开错目标）
# PR 合并后删除 feature 分支（本地 + 远程）
```

**分支命名规范（强制）**：`feature/英文业务名_YYYYMMDD`——业务名用英文 snake_case，日期为切分支当天（8 位数字）。禁止中文、禁止无日期后缀。

**开发前自检**：

- [ ] 当前在 feature 分支，而不是 dev/main 上直接改
- [ ] 改动落点符合第七节"改造落点优先级"
- [ ] 若为自有改动，同步登记 `CUSTOMIZATION.md` 改造台账（见第八节）

## 五、上游同步 SOP（每周一次，或跟随上游版本 tag）

### 5.1 同步 main 镜像

```bash
git fetch upstream
git checkout main
git merge --ff-only upstream/main     # 仅允许快进
git push origin main
```

> 若 `--ff-only` 失败，说明 main 被污染（有人直接提交了 main）。**禁止强行合并**，先排查污染提交并修复镜像纯度。

### 5.2 合并进 dev

```bash
git checkout dev
git merge main
# 有冲突时：自有改动对照 CUSTOMIZATION.md 台账决策；上游结构性改动优先保留上游结构
```

### 5.3 同步后验证（必做）

最小验证（改动集中时）：

```bash
scripts/run_tests.sh tests/agent/ -q          # 或冲突涉及的测试目录
```

全量验证（大合并 / 跨版本时）：

```bash
scripts/run_tests.sh                          # 禁止直接调 pytest，必须用该脚本
```

验证通过后：

```bash
git push origin dev
```

### 5.4 双仓联动检查（与 hermes-web-ui 同步时）

本仓库以下文件的改动会直接影响 web-ui 的 agent-bridge，同步时必须在 web-ui 侧确认兼容：

- `run_agent.py`（`AIAgent.__init__` 签名、`platform="cli"` 行为）
- `hermes_state*.py`（session DB schema）
- `tui_gateway/server.py`（JSON-RPC 方法/事件目录）

## 六、查看与挑选上游更新

```bash
git log dev..main --oneline                    # 上游有、dev 还没有的全部提交
git log dev..main --oneline -- <路径>          # 按目录过滤，例：-- gateway/platforms/
```

- **默认动作是全量 `git merge main`**——上游提交之间常有依赖链，选择性挑选容易漏。
- 仅当明确"只要某个修复、不要整个版本"时才 `git cherry-pick <sha>`。

## 七、冲突控制：改造落点优先级

降低合并冲突率的根本手段是**控制自有改动的落点**。按优先级从高到低：

1. `plugins/` 新增插件目录（首选；上游约定插件不改核心文件）
2. `skills/`、`optional-skills/` 新增技能
3. `hermes_cli/subcommands/` 新增 CLI 子命令
4. 配置文件 / 文档 / `CUSTOMIZATION.md`
5. 核心文件（`run_agent.py`、`cli.py`、`gateway/run.py` 等）——**尽量不动**；非动不可时保持最小 patch 并在台账中详录意图

该优先级与上游 AGENTS.md 的 Footprint Ladder 一致：上游社区最少触碰的面，就是我们冲突最少的面。

## 八、改造台账 `CUSTOMIZATION.md`

凡进入 `dev` 的自有改动，必须在仓库根目录 `CUSTOMIZATION.md` 逐条登记：

| 字段 | 说明 |
| --- | --- |
| 改动位置 | 文件/目录路径 |
| 意图 | 为什么改、实现什么 |
| 热区标记 | 是否触及上游高频变动文件 |
| 重建说明 | 上游大重构导致该 patch 失效时，如何重建 |

台账是同步冲突解决和上游大重构后重建自有改动的唯一地图，**漏登记等于改动随时可能丢失**。

## 九、版本号策略

- `pyproject.toml` 的 `version` **跟随上游**，同步合并时让上游值自然覆盖，不争抢该行（避免每次同步都在版本行冲突）。
- 需要标识自有构建时，使用 build metadata 后缀，如 `0.20.0+custom.1`。

## 十、常见问题

**Q：main 被误提交了怎么办？**
A：立即将误提交 cherry-pick 到 dev，然后 `git reset --hard upstream/main` 恢复 main 镜像纯度并强推（强推前确认无其他人基于该污染状态工作）。

**Q：想撤回 dev 上已推送的某个合并？**
A：用 `git revert -m 1 <merge-commit>` 生成反向提交，**禁止 reset + 强推**。

**Q：上游更新太多，冲突解不动？**
A：说明同步间隔太长了。冲突解完后立即缩短同步周期；历史教训：废弃的 `custom` 分支曾落后上游 10000+ 提交，完全失去合并可能。

**Q：协议上有什么约束？**
A：本仓库为 MIT，改造与分发基本无约束，保留原始 LICENSE 即可。
