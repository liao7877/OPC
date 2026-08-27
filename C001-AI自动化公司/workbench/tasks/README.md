# 统一任务区（tasks）· 工单使用手册

> 本目录是公司唯一工单区。文件即工单：对工单的一切操作 = 对文件的操作。
> 对接方式：你（Agent）只需按本手册创建/修改/管理工单文件，**无需了解看板如何实现**。
> 数据自动上板：本目录任何文件变动 → 数据生成器自动重跑 → 看板 ≤3 秒自动更新，无需人工干预。
>
> ⚠️ **权威版本**：Agent 执行规范以**公司级技能 `../skills/ticket-system/SKILL.md`** 为准（员工 AGENTS.md 已引用）；本文件为参考手册（人类查阅 / 培训索引）。**修改规范时两处需同步**。

---

## 1. 工单是什么

- 一个工单 = `workbench/tasks/` 下的一个目录：`TSKxxx-标题/`
- 工单编号 **TSK 前缀全局唯一**，由总管 E0000 分配并登记（**不要自造编号**）
- **编号台账**：总管应在自己的 `task-index.md`（或同等台账）维护「已分配编号」列表，派单时先查重再分配，避免重号（生成器也会查重告警，但台账是源头防线）
- 工单归属（项目/团队）写在 `task.md` 里声明，不依赖物理位置

```
workbench/tasks/TSK00001-标题/
├── task.md           # 必建：状态/负责人/项目/描述 等全部事实
├── messages.md       # 可选：追加式交接/备注（只追加，不覆盖）
├── deliverables/     # 可选：交付物（中间 + 最终产物）
└── logs/             # 可选：执行日志（审计/回溯）
```

## 2. 生命周期与状态机

```
待领(backlog) → 进行中(in_progress) → 待审(review) → 完成(done)
旁路：失败(failed) / 暂停(paused) / 取消(cancelled)
```

- 状态写在 `task.md` 的 `status` 字段，**只允许上面 7 个枚举值**
- 非法/缺失状态 → 该工单会被生成器**跳过并告警**，不会上板（别踩）
- 被否决/不需要做的工单 → 置 `cancelled`（取消），**不背「逾期」的锅**

## 3. 新建工单（模板）

1. 在 `workbench/tasks/` 下建目录：`TSKxxx-标题/`（编号找总管 E0000 要）
2. 写 `task.md`，frontmatter 必须用 `---` 包裹、单行 `key: value`：

```markdown
---
id: TSK00001
title: 协作看板需求澄清
status: backlog
owner: E0002
project: P0001
priority: 高
type: 需求
due: 2026-08-30
tags: [前端, 工具链]
created: 2026-08-26
updated: 2026-08-26
---

正文：工单描述（可选，写清楚要干什么、目标是什么）
```

> ⚠️ frontmatter 每行只能是 `key: value`，**不要写行尾注释**（`due: 2026-08-30 # 备注` 会把 `# 备注` 当成值的一部分，导致日期解析失败）。要写说明请放正文描述或 `messages.md`。

## 4. 字段速查

| 字段 | 必填 | 说明 |
|---|---|---|
| id | 是 | TSKxxx，总管分配 |
| title | 是 | 标题 |
| status | 是 | 见状态机 |
| owner | 否 | 当前负责人 ID（E0000/E0001/E0002/…） |
| owner_name / project_name | 否 | 可读名（目录未建时的兜底，通常由生成器按目录自动补） |
| project | 否 | 所属项目 ID（P0001/P0002/…） |
| priority | 否 | 高 / 中 / 低 |
| type | 否 | 需求 / bug / 任务 |
| due | 否 | 预估截止日 `YYYY-MM-DD` |
| completed_at | 否 | **实际完成时间**，status=done 时必须填（否则生成器告警） |
| tags | 否 | `[标签1, 标签2]` |
| created / updated | 否 | 日期 |
| handoffs | 否 | 流转链，见 §6 |
| status_history | 否 | 状态变更时间线 `[{to, at}]`（可选，审计补充） |
| inputs | 否 | 输入物引用，见 §7 |
| parent / children / links | 否 | 预留字段（未来用，先留空） |

## 5. 推进工单

- **状态变了** → 改 `status`
- **有交接/备注** → 追加到 `messages.md`（**只追加，不覆盖历史**）
- **产出物** → 放进 `deliverables/`（交付物）或 `logs/`（过程记录）
- **每次改动顺手更新 `updated`**

## 6. 流转（换负责人）—— 工单还是同一个，不新建

```yaml
owner: E0003              # 改成新负责人
handoffs: [{"from":"E0002","to":"E0003","at":"2026-08-27","reason":"开发完成，转测试验收"}]
```

> ⚠️ **重要**：`handoffs` / `inputs` 必须写成**单行 JSON**（一行写完，不要换行/缩进）。解析器是极简单行 `key: value`，多行写法会把 JSON 内容当新字段，污染 frontmatter（生成器会告警跳过）。

**铁律：**
- 最后一条 `handoffs` 的 `to` **必须等于当前 `owner`**（生成器会校验，不一致告警）
- **换人不改状态**（状态由当前负责人自行推进，两件事解耦）
- 交接原因写清楚，这是审计轨迹，将来详情页按此渲染「流转轨迹」时间轴

## 7. 输入物（inputs）—— 开工需要的外部材料

- 用**引用**，不复制文件（避免两份真相漂移）
- 路径相对 `workbench/`：项目文件写 `../P0001-示例项目/xxx.md`；上游工单交付物写 `tasks/TSK00001-xxx/deliverables/xxx.md`
- **上一手的交付物就是下一手的输入物**——流转时把上游交付物列为你的输入

```yaml
inputs: [{"name":"PRD 需求规格","path":"tasks/TSK00001-xxx/deliverables/PRD.md"}]
```

- 引用路径失效（文件被移走/改名）→ 生成器告警 + 看板详情标「⚠️ 路径失效」，及时修复

## 8. 完成（done）

```yaml
status: done
completed_at: 2026-08-27   # 实际完成时间，必须填
```

- `completed_at ≤ due` → 按期完成；`> due` → 看板标「逾期完成」
- **status=done 不填 completed_at → 生成器告警**（保证统计完整）

## 9. 生成器告警对照表（遇到告警怎么修）

| 告警 | 含义 | 处理 |
|---|---|---|
| `缺少 frontmatter…跳过` | task.md 没 `---` 包裹 | 补全格式 |
| `status=… 非法，跳过` | 状态值不在枚举 | 改成 7 个合法值之一 |
| `id=… 重复，跳过` | 两个目录同名 TSK | 改编号（找总管） |
| `handoffs 最后交接给 X，但 owner=Y` | 漏改 owner 或漏记交接 | 对齐两者 |
| `inputs[…] 路径不存在` | 输入物引用失效 | 修路径 / 把文件移回 |
| `status=done 但未填 completed_at` | 缺实际完成时间 | 补填 `completed_at` |
| `…日期格式无法识别` | 日期写错 | 改成 `YYYY-MM-DD`（可带 `HH:MM`） |
| `frontmatter id=… 与目录名前缀不一致` | 两处编号对不上 | 统一编号 |
| `目录名不是规范格式` / `id 不是规范编号格式` | 非 TSKxxx | 改目录名/编号 |
| `handoffs 时间倒序` | 流转链时间顺序错 | 按时间重排 |
| `due/completed_at 早于 created` | 截止/完成早于创建 | 修正日期 |
| `读取失败（疑似非 UTF-8 编码）` | 文件是 GBK 等编码 | 另存为 UTF-8 |

## 10. 红线（不要做）

1. **不要改看板文件**：`workbench/kanban.html`、`generate_tasks.py`、`KANBAN_*.md` 是廖哥与前端/后端 Agent 的领地，你只维护 `tasks/` 下的工单文件
2. **不要复制输入物进工单**：保持引用（§7）
3. **不要自造编号 / 非规范目录**：`TSKxxx-` 前缀 + 模板字段，不自由发挥
4. **不要删 messages.md 历史**：追加式，历史即审计

## 11. 一句话总结（给 Agent 的对接契约）

> 我只认 `workbench/tasks/TSKxxx-标题/` 下的文件；按本手册维护 `task.md`（+messages/deliverables/logs）；改完文件看板自动更新，我不用管看板怎么实现。

## 12. 快捷命令（generate_tasks.py）

| 命令 | 作用 |
|---|---|
| `python generate_tasks.py` | 手动生成看板数据 |
| `python generate_tasks.py --watch` | 监听 tasks/ 变动自动重跑（日常建议挂着） |
| `python generate_tasks.py --new TSKxxx 标题 [--owner E0001] [--project P0001]` | **一键生成规范工单模板目录**（推荐建单方式，避免手抄出错） |
| `python generate_tasks.py --selftest` | **内置自测**（解析/校验/容错 9 项用例），全过退出码 0 |

> 注意：`--watch` 保持**单个实例**即可（双开会互相覆盖写）；文件轮询为 1 秒级感知，极端同秒并发改动可能延迟 1 秒才上板，属正常。
