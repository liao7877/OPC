# 协作看板系统 · 架构设计规范（设计语言 v1.0）

> 定位：本文件是整套"文件系统即工单系统"的**根本设计规范**，回答三个问题——
> 系统如何自包含、边界如何切分（Agent 对接面在哪）、机制如何演进。
> 相关文档：`workbench/KANBAN_PRD.md`（需求规格）、`workbench/tasks/README.md`（工单使用手册/Agent 培训规范）。

---

## 0. 一句话

**文件系统即真相，看板只是投影；工单规范是唯一接口，Agent 只认文件。**

---

## 1. 自包含（Self-contained）

- **唯一数据源**：`workbench/tasks/` 目录。看板的所有机制（分组/筛选/详情/流转/输入物/逾期/标记）全部由该目录下的工单文件驱动，无任何第二数据源。
- **零外部依赖**：数据生成器仅用 Python 标准库；看板是单文件 vanilla JS；`file://` 双击即开（含 `tasks-data.js` 兼容方案）。
- **整体可移植**：`workbench/` 整目录复制到任何机器即可运行，无安装、无服务、无数据库。

## 2. 数据流（单向管道）

```
tasks/（真相，Agent 在此维护文件）
   │  修改
   ▼
generate_tasks.py（解析 + 校验 + 告警，可 --watch 自动重跑）
   │  产出
   ▼
tasks-data.json / tasks-data.js（投影数据，内联 messages/deliverables/logs/handoffs/inputs）
   │  加载
   ▼
kanban.html（只读渲染，3 秒轮询自动同步，不写回任何文件）
```

**方向铁律：管道是单向的。** 数据只从 `tasks/` 流向看板，**看板永不写回 `tasks/`**（写回属 C 方案，需后端，见 §7）。

## 3. 系统边界（插件化 / 解耦）

系统分三层，边界即"谁对接谁"：

| 层 | 组成 | 对接对象 | 谁维护 |
|---|---|---|---|
| **A 数据层** | `workbench/tasks/` 下的工单文件 | **Agent 的唯一对接面**：创建/修改/管理工单 = 改文件 | 员工 Agent（E0001/E0002/…）+ 总管派单 |
| **B 生成层** | `generate_tasks.py` | 读 A 层文件，产出投影数据；负责校验与告警 | 廖哥 + 后端 Agent |
| **C 展示层** | `kanban.html`（看板） | 只读 B 层数据渲染，**不感知 Agent、不对接 Agent** | 廖哥 + 前端 Agent |

**边界铁律：**
1. **Agent 对接 A 层即可**：员工 Agent 只需要会"按规范创建/修改 `task.md` 等文件"，**不需要知道看板怎么用、不需要理解前端实现**。
2. **看板不对接 Agent**：C 层只是投影，Agent 改文件后看板自动变化，两者无任何直接交互。
3. **改看板 ≠ 改工单规范**：要改看板 UI/逻辑（配色、布局、加功能），由廖哥在 `workbench/` 目录与前端/后端 Agent 协作修改 `kanban.html` / `generate_tasks.py`，**与数据层 Agent 无关**。
4. **新增机制按管道演进**：先在 A 层加字段/目录约定 → B 层解析 → C 层展示。任何功能都从数据层长出来，不从看板硬编码出来。

## 4. 数据模型（权威 Schema）

### 4.1 目录结构
```
workbench/tasks/TSKxxx-标题/        # 一个工单 = 一个目录；TSK 编号全局唯一（总管 E0000 分配登记）
├── task.md           # 静态事实：frontmatter（状态/负责人/项目/…）+ 正文描述
├── messages.md       # 消息日志：追加式异步消息（交接/备注），只追加不覆盖
├── deliverables/     # 交付物：中间产物 + 最终产物（输出）
├── logs/             # 执行日志：审计/回溯
└── （inputs 无目录）  # 输入物用引用，不复制文件
```

### 4.2 task.md frontmatter 字段（权威定义）
格式：`---` 包裹 + 单行 `key: value`，禁止多行/嵌套 YAML（生成器为轻量解析）。

| 字段 | 类型 | 必填 | 用途 |
|---|---|---|---|
| id | string | 是 | 全局唯一编号（TSKxxx） |
| title | string | 是 | 卡片标题 |
| status | enum | 是 | backlog / in_progress / review / done / failed / paused |
| owner | string | 否 | 当前负责人 ID（空则「未分配」） |
| owner_name | string | 否 | 负责人可读名（目录未建时的兜底，工单自包含） |
| project | string | 否 | 所属项目 ID |
| project_name | string | 否 | 项目可读名（兜底） |
| priority | enum | 否 | 高 / 中 / 低 |
| type | enum | 否 | 需求 / bug / 任务 |
| due | date | 否 | 预估截止日 |
| completed_at | date | 否 | 实际完成时间（status=done 时填，否则生成器告警） |
| tags | list | 否 | 标签筛选 |
| created / updated | date | 否 | 创建 / 更新时间 |
| handoffs | list | 否 | 流转链 `[{from,to,at,reason}]`，与状态解耦 |
| inputs | list | 否 | 输入物引用 `[{name,path}]`，不复制 |
| parent / children / links | - | 否 | **预留字段**：未来并行协作/子任务拆分（扩展 C） |
| description | text | 否 | 正文描述 |

### 4.3 状态机
`backlog → in_progress → review → done`；旁路 `failed` / `paused` / `cancelled`（取消——不背「逾期」的锅）。
- 状态只允许枚举值，非法/缺失 → 生成器**跳过该工单并告警**（不降级上板）。

## 5. 核心机制（机制清单）

| 机制 | 规则 |
|---|---|
| **代号→名称注册表** | 双来源：① 公司根目录扫描 `E###-*`/`P###-*`（权威，新建目录自动收录）；② 工单 `owner_name`/`project_name` 兜底。目录优先。动态非写死。 |
| **流转（handoffs）** | 单当前负责人；换人 = 改 owner + 追加一条 `{from,to,at,reason}`；**最后一条 to 必须等于当前 owner**（生成器校验告警）；换人不改状态。 |
| **输入物（inputs）** | 引用外部路径（相对 `workbench/`），不复制不漂移；生成器校验存在性，失效告警 + 详情标 ⚠️；可指向项目目录或上游工单 deliverables（上一手交付物 = 下一手输入物）。 |
| **逾期语义** | 「逾期中」仅对活跃未完成（backlog/in_progress/review）且 due<今天 生效；done/paused/failed 不标；done 且 completed_at>due → 「逾期完成」（橙黄 + 逾期天数）。 |
| **容错** | 坏 frontmatter / 非法 status / **重复 id**（跳过+告警，避免点开错单）；失效路径 / owner 不一致 / done 缺 completed_at（告警不跳过）。 |
| **原子写** | `.tmp` + `os.replace`，避免数据文件写一半被读。 |
| **自动同步** | `--watch` 监听 tasks/ 自动重跑；前端每 3 秒轮询 `tasks-data.js`（方案 X，`file://` 兼容）比对 `generated_at` 自动重渲染。 |

## 6. 看板能力（C 层，只读投影）

- 分组：状态 / 项目 / 负责人 / **参与者**（含历史经手人，一单可归多列）
- 筛选：优先级 / 类型 / 标签（多选）/ 搜索（含名称与参与者）
- 卡片：标题 + **ID 标签** + 状态色条 + 负责人（名称+代号）+ 优先级（**圆点+文字**）+ 项目 + 截止日（**逾期标红 / 逾期完成橙黄**）+ 流转标记 + 输入标记
- 详情：字段网格 + **流转轨迹时间轴** + 描述 + 交接备注 + **输入物（可点击，失效标红）** + 交付物 + 执行日志
- 主题：暗 / 亮（localStorage 记忆，默认暗）

## 7. 扩展路径（按管道演进，不推倒重来）

| 需求 | 路径 |
|---|---|
| 看板写回（拖拽改状态/转发） | C 方案，需后端；当前架构刻意不做，保持 A 静态 |
| 并行协作 / 子任务 | `parent`/`children`/`links` 字段已预留，填字段 + 生成层解析 + 展示层视图即可 |
| 统计（按期率 / 平均时长） | 数据已含 `completed_at`/`created`/`due`，加统计视图即可 |
| 多角色视图 / 快捷 URL | 前端 `?owner=E0002` 等参数化，不动数据层 |

## 8. 文件清单（workbench/）

| 文件 | 职责 |
|---|---|
| `kanban.html` | 看板（C 层，只读渲染，双击即开） |
| `generate_tasks.py` | 生成器（B 层，解析+校验+告警；`--watch` 自动重跑；`--new` 一键建单模板；`--selftest` 内置自检） |
| `tasks-data.json` / `tasks-data.js` | 投影数据（js 为 file:// 兼容入口） |
| `tasks/` | **唯一真相**（A 层，Agent 对接面） |
| `tasks/README.md` | **工单使用手册（Agent 培训规范）** |
| `KANBAN_PRD.md` | 需求规格（已澄清决策存档） |
| `KANBAN_ARCHITECTURE.md` | 本文件（设计规范） |
| `KANBAN_REVIEW.md` | 历轮审核记录（问题与修复轨迹） |

## 9. 维护职责（谁负责哪块）

| 内容 | 负责人 |
|---|---|
| 工单数据（创建/修改/流转/完成） | 员工 Agent + 总管，按公司级技能 `skills/ticket-system/SKILL.md` 操作 |
| 工单规范（公司级技能 + tasks/README.md） | 廖哥（或授权总管）维护；**规范自解释，改动无需逐人培训** |
| 生成器 / 看板 / 架构文档 | 廖哥 + 后端/前端 Agent，在 workbench/ 协作 |
| 员工接入 | **不人肉培训**：员工 `AGENTS.md` 引用公司级技能一行即可（已对 E0001/E0002 生效） |

### 9.1 技能分层（公司级 / 团队级 / 私有）

| 层级 | 位置 | 可用范围 |
|---|---|---|
| **公司级** | `公司根目录/skills/<name>/`（如 `skills/ticket-system/`） | 全公司所有员工 + 总管 |
| **团队级** | 团队目录（T001-…）/skills/ | 该团队内员工 |
| **私有** | 员工目录/skills/ | 仅该员工 |

**每层结构（实体 + 平台接入）**：技能实体只放 `{层}/skills/` 一处（唯一出处）。**WorkBuddy 平台接入方式**：`{层}/.workbuddy/skills` junction 引用（2026-08-27 公司/团队/员工四层已全部建立）——该目录作为工作区打开时，平台自动扫其 `.workbuddy/skills`、享受渐进式披露。Codex/Claude Code 等平台**无需 junction 结构**，接入方法见 `AGENT_ECOSYSTEM.md`。

员工 `AGENTS.md` 只需写一行引用，指向公司级技能 `opc://company:C001/skill/ticket-system`；技能内容自解释、自包含，无需人肉培训。

> **定位说明**：公司根 `skills/` 是**规范文件层**——存放自解释的规范技能（如 `ticket-system/`）。**已用 junction 接入平台自动披露**（`{工作区}/.workbuddy/skills` → 公司根 `skills/`，零复制单份文件）：ticket-system 会出现在平台技能列表、触发词命中自动加载全文（平台级渐进式披露，与用户级技能一致）。AGENTS.md 引用行是跨平台兜底（Codex/Claude Code 等不识别 WorkBuddy 平台技能时直读本文件）。具体平台接入方法见 `opc://org/agent-ecosystem`。
