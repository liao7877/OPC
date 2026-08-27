# OPC 领域类型系统设计（opc-schema）

> **定位**：OPC 组织层的「领域模型 / 类型系统」设计规范。与 `opc-namespace-design.md`（引用层 / DIP）互补——命名空间解决了**文件→文件**的指针，本文件解决**实体→实体**的指针与**实体自身的字段契约**。
> **本质动机**：OPC 是一门「语言」。一门语言要有词法（实体）、语法（实体间如何引用）、**类型（每个实体长什么样、字段可取什么值）**、**编译器（整棵树是否 well-formed 的检查器）**。当前缺后两者，导致：①每个 consumer 各自用正则 re-parse 同一套 frontmatter（DRY 违反，P3）；②`owner: E0001` 这类实体指针仍是裸 ID = 与当年 `E:\OPC\...` 同款的「裸写内存地址」（DIP 只切了一半）；③实体间引用零校验，改名员工目录即悬空（问题 2）。
> **决策**：单一 schema 文件声明类型 + 单一 `opc_model.py` 解析/校验（Repository 模式）+ `opc validate` 编译器（schema 校验 + FK 校验）。
> **配套**：`PRINCIPLES.md`（P2 单一真相 / P3 高内聚 / P11 容错 / P14 契约先行 / P21 根治根因）、`MECHANISM_PLAN.md`（字段来源）。

---

## 〇、决策总览

| # | 议题 | 决策 |
|---|---|---|
| 1 | 类型声明放哪 | 单一文件 `opc_schema.toml`（OPC 根），是所有实体字段/枚举/引用的**唯一真相**；PRINCIPLES / MECHANISM_PLAN / SKILL 只引用它，不再各写各的 |
| 2 | 谁来做解析 | 单一模块 `opc_model.py`（Repository）：读实体卡 → 按 schema 校验 → 返回 typed 对象。consumer 一律调它，**禁止私有正则** |
| 3 | 实体间引用怎么不悬空 | schema 把 `owner`/`project`/`blocked_by`/`parent`/`handoffs` 声明为**类型化引用（FK）**；`opc validate` 遍历全树做参照完整性校验 |
| 4 | 反规范化副本怎么办 | `owner_name`/`project_name` 等是 P2 禁止的「复制而非引用」；改为**派生字段**（generator 实时算），schema 标记 `derived`，validator 存了就告警 |
| 5 | 与现有 `--check` 关系 | `opc_resolver --check` 管**文件级** `opc://` 引用；`opc validate` 管**实体级** schema + FK。互补，未来 pre-commit 两者都跑 |
| 6 | 范围边界 | **不涉并发（问题 3）**——锁/事务/版本号是运行时事，与类型系统两码事，不在本文件治理 |

---

## 一、本质重构：DIP 那刀只切了一半

命名空间解决的是**文件→文件**的裸路径（`E:\OPC\C001\...` → `opc://`）。但还有一类引用没动——**实体→实体**的指针，藏在 frontmatter 里：

```yaml
owner: E0001          # 指向「员工」实体，但只是裸 ID
project: P0001        # 指向「项目」实体，裸 ID
blocked_by: [TSK0007] # 指向「工单」实体，裸 ID
parent: TSK0042       # 同上
```

`owner: E0001` 与当年 `E:\OPC\C001\...` **是同一个反模式**——裸写内存地址。命名空间只把引用层抬到符号级，字段里的实体指针还是裸 ID。所以：

- **问题 1（无类型）与问题 2（无外键）是连体婴**：没有「类型」就谈不上「外键」；有了类型化的引用，FK 校验自然长出来。
- 命名空间迁移本身也**没做完**：实测 `E0001/AGENTS.md` 至今仍含 `../skills/ticket-system/SKILL.md` 裸相对路径（违反 P7 / opc://）；`AGENT_ECOSYSTEM.md` 2.3 第 3 步同理。规范层自己都没守规矩（问题 4）。本文件的 `derived` 治理 + 单一 schema 能顺带收口这类漂移。

---

## 二、三层架构

| 层 | 是什么 | 对标模式 | 落点文件 |
|---|---|---|---|
| **Schema（类型声明）** | 单文件声明每个实体的发现方式、字段、类型、枚举、必填/可选、引用(FK)、派生 | DTO / Value Object / JSON Schema | `opc_schema.toml`（OPC 根） |
| **Model（唯一解析器）** | `opc_model.py`：发现实体 → 读卡 → 按 schema 校验 → 返回 typed 对象；FK 索引构建 | **Repository 模式**（实体读取逻辑单一收敛点） | `opc_model.py` |
| **Validator（编译器）** | `opc validate`：遍历全树 → schema 校验（枚举/必填/格式）→ FK 校验（引用指向的实体存在吗） | Linter / 编译期检查 | `opc_model.py --validate` |

**为什么是三层而不是加更多脚本**：当前 `generate_dashboard.py` 与 `workbench/generate_tasks.py` **两个脚本各自用正则 re-parse 同一套 frontmatter**（已 grep 证实两者都解析 `owner:`/`project:`/`blocked_by:`/`parent:`）。加字段要改 N 处。Repository 把「什么是工单」的知识收敛到一处，consumer 只调 `opc_model.load_task(...)`。

---

## 三、Schema 声明格式（`opc_schema.toml`）

```toml
# opc_schema.toml — OPC 领域类型系统（单一真相）
[meta]
version = "1"

# ---- 实体发现：每个实体如何被找到 ----
[entity.company]
discover = "company.md"        # 公司根 company.md，解析「公司 ID」
id_field = "公司 ID"

[entity.employee]
discover = "roster"            # 经 E0000/roster.md 表发现（员工 ID 列）
id_field = "员工 ID"

[entity.team]
discover = "team.md"
id_field = "团队 ID"

[entity.project]
discover = "project.md"
id_field = "项目 ID"

[entity.task]
discover = "task.md"           # workbench/tasks/<TSKxxxxx-标题>/task.md
id_field = "id"

# ---- 字段契约（类型 / 枚举 / 必填）----
[entity.task.fields]
id         = { type = "string", required = true, pattern = "^TSK\\d{5}$" }
title      = { type = "string", required = true }
status     = { type = "enum", required = true, enum = ["backlog","in_progress","review","done","paused"] }
owner      = { type = "ref", ref = "employee", required = true }   # FK → employee
project    = { type = "ref", ref = "project", required = false }   # FK → project
priority   = { type = "enum", enum = ["高","中","低"] }
type       = { type = "string" }      # 待核实枚举（已知：任务/需求）
due        = { type = "date" }
created    = { type = "date" }
updated    = { type = "date" }
completed_at = { type = "date" }
tags       = { type = "list" }
handoffs   = { type = "list" }        # 元素含 from/to → employee（FK）
blocked_by = { type = "ref_list", ref = "task" }   # FK[] → task
parent     = { type = "ref", ref = "task" }        # FK → task

# 反规范化字段（P2 禁止复制）：以下为派生字段，不应存储，
# 应由 generator 从 FK 实时派生；validator 检测到存储即告警。
[entity.task.derived]
owner_name   = "owner → employee.岗位"
project_name = "project → project.名称"
```

---

## 四、实体与真实字段（已核实，非臆造）

来源：实测 `C001-AI自动化公司` 真实文件抽取。

| 实体 | 发现方式 | 真实 ID 字段 | 真实引用字段（FK） |
|---|---|---|---|
| company | `company.md` | `公司 ID: C001` | — |
| employee | `E0000/roster.md` 表（员工 ID / 路径 / 岗位 / 状态 / 团队 / 角色） | `员工 ID: E000x` | `团队` → team；`角色=lead` → 团队负责人 |
| team | `team.md` | `团队 ID: T001` | `lead`（roster 角色列）→ employee |
| project | `project.md` | `项目 ID: P0001` | `归属团队` → team；`负责人(owner)` → employee |
| task | `task.md` frontmatter | `id: TSK00001` | `owner`→employee；`project`→project；`blocked_by[]`→task；`parent`→task；`handoffs[].from/to`→employee |

**实锤证据（已读真实文件）**：
- `TSK00001/task.md` frontmatter 含 `owner: E0002`、`project: P0001`、`handoffs: [{from:E0001,to:E0002,...}]`、`owner_name: 项目经理`、`project_name: 示例项目`。`owner_name`/`project_name` 是**反规范化冗余副本**（P2 禁止），本文件 §五治理。
- `E0001/AGENTS.md` 仍含 `../skills/ticket-system/SKILL.md` 裸相对路径（违反 P7 / opc://）——命名空间迁移漏网，待收口（见 §七）。

---

## 五、反规范化治理（呼应 P2）

`task.md` 的 `owner_name` / `project_name` 是「复制而非引用」：员工改名 → 这里脏数据。治法：
1. schema 标记 `derived`（§三），声明其来源表达式；
2. validator 在 `opc validate` 中**检测存储即告警**（P11 跳过+告警，不静默）；
3. generator（看板）改为从 FK 实时派生显示，不再读存储副本。
长期目标：从 task.md frontmatter 删除这两个字段（零风险可逆，P24）。

---

## 六、Validator 行为（`opc validate`）

遍历 OPC 根 → 构建实体索引（task / project / employee / team）→ 逐实体：

1. **schema 校验**：必填缺失？枚举越界（`status: foo`）？格式不符（`id` 不匹配 `^TSK\d{5}$`）？→ 报错（P11 不降级）。
2. **FK 校验**：`owner` 指向的员工在 roster 吗？`project` 指向的项目存在吗？`blocked_by[]` / `parent` 指向的工单存在吗？`handoffs[].from/to` 指向的员工存在吗？→ 悬空即报错。
3. **派生告警**：检测到 `owner_name` / `project_name` 被存储 → 告警（非错误）。

输出分级：`[ERR]`（阻断，pre-commit 应 fail）/ `[WARN]`（告警，不阻断）。退出码：有 ERR 则 1。

**与 `opc_resolver --check` 关系**：`--check` 管 `opc://` 文件级引用；`opc validate` 管实体级 schema+FK。互补。未来 pre-commit 同时跑两者，构成「OPC 编译器」完整检查。

---

## 七、规范漂移收口（顺带治问题 4）

本文件落地后，字段定义从「多份散文」收口到 `opc_schema.toml` 一份真相；PRINCIPLES / MECHANISM_PLAN / SKILL 只引用它。同时：
- `AGENT_ECOSYSTEM.md` 2.3 第 3 步、`E0001/AGENTS.md` 等处的 `../skills/<name>/SKILL.md` 裸路径 → 统一改 `opc://company:<id>/skill/<名称>`（一行级治理，单列待办）。
- 规范文档间冲突时，以 `opc_schema.toml` + `opc.toml` 为机器可读的权威，散文规范不得与之矛盾。

---

## 八、迁移路径

| 批次 | 动作 | 涉及 |
|---|---|---|
| 1 | 建 `opc_schema.toml`（实体发现 + task 字段契约 + FK + derived） | OPC 根 |
| 2 | 建 `opc_model.py`（Repository：发现 / 解析 frontmatter / schema 校验 / FK 索引 / `validate_all`） | OPC 根 |
| 3 | `opc_model.py --validate` 跑通真实 C001 树，确认零误报、能抓真漂移 | 验证 |
| 4 | `generate_dashboard.py` + `generate_tasks.py` 改调 `opc_model.load_task`（去重正则，根治 DRY） | 两脚本 |
| 5 | 反规范化字段治理：generator 改实时派生；task.md 删 `owner_name`/`project_name`（P24 可逆） | 生成器 + 数据 |
| 6 | pre-commit 增 `opc validate`（与 `--check` 并列） | `.git/hooks/pre-commit` |

---

## 九、反模式禁忌（呼应已解决问题）

- ❌ 在 consumer 里再写正则解析 frontmatter → 一律走 `opc_model`。
- ❌ 裸 ID 当实体引用（`owner: E0001` 不校验）→ 必须类型化 FK，由 validator 查。
- ❌ 存储反规范化副本（`owner_name`）→ 改为派生。
- ❌ 字段定义在多份散文各写一遍 → 单一 `opc_schema.toml`。

---

## 十、落地状态表

| 阶段 | 内容 | 状态 |
|---|---|---|
| 设计 | 本文件（三层架构 / schema 格式 / FK 图 / 迁移路径） | ✅ 已定稿（2026-08-28） |
| 方案 3 实施 | `opc_schema.toml` + `opc_model.py` + `opc validate`（schema + FK） | ✅ 已完成（commit 273561c，实测抓出真实漂移） |
| 批次 4 | 两生成器改调 `opc_model` | 待定（DRY 根治） |
| 批次 5 | 反规范化字段治理 | 待定（generator 实时派生 + 删 owner_name/project_name） |
| 批次 6 | pre-commit 增 `opc validate` | 待定（与 `--check` 并列，构成 OPC 编译器） |

### 实测抓出 → 根因已修（validator 首跑，2026-08-28）
初跑报 4 ERR + 16 WARN，根因复盘（均修在工具层，未动业务数据）：
- `[ERR]` TSK00006 `status=failed` 越枚举 → **根因：opc_schema.toml 枚举漏写 failed/cancelled**。系统权威 7 值为 `backlog/in_progress/review/done/failed/paused/cancelled`（见 KANBAN_PRD.md:46 / generate_tasks.py:33 / ticket-system SKILL.md:20）。已补 7 值。
- `[ERR]` TSK00007/8/9 `project=P0002/P0003` FK 悬空 → **根因：校验器只认散文「项目 ID：P000x」，但 P0002/P0003 用 frontmatter `id: P000x` 注册（与 task.md 同款写法）**，属校验器单格式解析 bug，非数据漏注册。已修 `extract_id` 同时支持 frontmatter+散文（根治，不补冗余 prose 行，避打补丁）。
- `[WARN]`×16：8 个 task 存储 `owner_name`/`project_name` 反规范化副本（P2 禁止）→ 留作批次 5 派生化治理（非阻断）。
修正后重跑：0 ERR，仅剩 16 WARN（反规范化债务）。

---

*定稿：2026-08-28 · 承接 opc-namespace-design.md（引用层 DIP），补全领域模型类型系统（schema + Repository + validator），一并治问题 1（无类型）与问题 2（无 FK），范围不涉并发（问题 3）。*
