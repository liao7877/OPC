---
name: ticket-system
description: 公司工单系统使用规则（新建/取号/认领/推进/流转/完成/升级）。任何员工要创建、认领、修改、流转、完成公司工单（workbench/tasks/TSKxxx）时加载执行；task.md 模板、字段细则、告警对照按正文链接按需读，正文只写主干。
summary: 公司工单系统自解释技能。
triggers: [建工单, 创建任务, 派任务, 新建工单, 改状态, 流转, 交接, 转交, 完成工单, 取消工单, task.md, handoffs, inputs, completed_at, TSK, 认领, 接单, 漏接, 阻塞, blocked_by, 前置, 父单, 子单, 需求闭环, 取号, 号池]
---

# 公司工单系统（ticket-system）

> **文件即工单**：一切工单 = `workbench/tasks/TSKxxx-标题/` 目录下的文件。你只改文件，看板自动更新（≤3 秒），不需要懂看板。
> 本文件只写规则主干；**task.md 模板/字段细则/告警对照 → [reference.md](reference.md)，新手全流程示例 → [walkthrough.md](walkthrough.md)**。

> **🚦 车道判定**：需要验收、可能交接、跨会话的活 → 走工单；干完就完的（问答/查资料/随手小改）→ 不建单，worklog 记 `type: 直聊`（见 worklog-discipline）。拿不准就建单——多一单成本极低，漏跟踪的活没人管。
>
> **⚠️ 路径基准**：工单命令统一经稳定锚 `../../../companies/C001/workbench/`（从员工目录起算）；已 `cd` 到公司根则直接用 `workbench/` 前缀。**不要从员工目录裸用 `workbench/`**。

## 0. 三件事

1. **唯一工单区**：`workbench/tasks/`；一个工单 = 一个目录 `TSKxxx-标题/`。
2. **核心文件**：`task.md`（必建，全部事实）+ 可选 `messages.md`（**只追加不覆盖**）/ `deliverables/`（交付物）/ `logs/`（过程记录）。
3. **状态机**：`backlog(待领) → in_progress(进行中) → review(待审) → done(完成)`；旁路 `failed / paused / cancelled`。只填这 7 个合法值（唯一真相 `opc_schema`；非法值上板标红不丢数据，改对即恢复）。
4. **扩展字段**（全部单行）：`blocked_by: [TSKxxx,…]`（前置全 done 才能开工）；`parent: TSKxxx`（子单，父单须子单全 done 才能 done）；`handoffs: [{…}]`（单行 JSON，见 §4）；`inputs: [{name,path}]`（引用不复制，细则见 reference.md）。

## 1. 新建与取号

- **常态（总管派发）**：总管分配编号并建单（台账 `workbench/task-index.md` 他维护），员工不建单只干活。
- **用户直派自助取号**（先占台账后建单，防并发撞号）：
  1. 读台账「预留号池」段 → 取最靠前的未占用号 → **立即勾选该行**（原子替换写、改前重读最新版，号被抢就换下一个）；
  2. 建单：`python ../../../opc_tickets.py --company C001 --new <号> "<标题>" --owner <你的E号>`，task.md 备注 `来源: 用户直派`；
  3. 台账「工单登记」表补一行 → 按 §2 认领 → 向总管留一行备案（`入口B建单 TSKxxxxx`，巡检会核对取号与工单对齐）。
- **不自造编号**：号池空 → 请总管补号段。台账写权 = 唯一在岗会话（见 concurrent-work）。`--auto-id` 可让生成器取「最大号+1」并自动登记台账。

## 2. 认领（≠开工）

认领 = 接单登记（worklog 建「计划中」条目 + 回执），status 保持 backlog；动工才改 in_progress——看板靠它区分「已接未动」和「没人接」。

| 通道 | 动作 |
|---|---|
| 推（总管派发） | 收到即认领 |
| 拉（会话启动自扫） | 扫 `owner=自己 且 backlog 且 worklog 无对应条目` → 补认领 |
| 用户直派 | 自填 `owner: 自己` + 追加 handoffs（`reason: "用户直派"`）+ messages 来源备注 |

分级自主权：`priority: 高` → 认领后自动开工；中/低 → 只补认领，等总管或用户指令。

## 3. 推进

状态变了改 `task.md` 的 `status`；备注/交接**追加**到 `messages.md`；产出进 `deliverables/`、过程进 `logs/`；每次改动顺手更新 `updated`（YYYY-MM-DD）。

## 4. 流转（换人不换单）

```yaml
owner: E0003
handoffs: [{"from":"E0002","to":"E0003","at":"2026-08-27","reason":"一句话说清交接"}]
```

铁律：`handoffs` 必须单行 JSON；最后一条 `handoffs.to` 必须等于当前 `owner`；**换人不改状态**（状态由新负责人推进）。
**离职/长休**：名下非终态工单不得悬空——休假挂 `paused` + messages 注明预计返回日期；离职由总管 1 个工作日内按本节流转（`reason: "离职转移"`），下游依赖逐个知会（巡检 #2 兜底漏转移）。

## 5. 完成

`status: done` + `completed_at: YYYY-MM-DD`（**必填**，缺了告警；≤ due 按期，> due 标逾期完成）；被否决 → `cancelled`（不背逾期的锅）。
**双账联动**：关单同一时刻把 worklog 里 ticket=本单 的条目改「已完成」（`opc://company:C001/skill/worklog-discipline`）——只关一边会被交叉核验告警。
**复盘标记（知识飞轮入口）**：关单前在 messages.md 追加一行 `[lesson: 一句话教训/有效做法] (日期)`——有标记 = 已复盘，教训由总管归位知识库（二次命中晋升技能素材，见 P31）。

## 6. 阻塞与父子单

- 开工前自查 `blocked_by` 所列工单全部 done；未清 → 留 backlog（看板标 🔒）。上游 cancelled / 编号无效 → 找总管确认本单是否还做。
- 需求拆多单：总管建父单（`type: 需求`，owner=总管），子单 frontmatter 加 `parent: TSKxxx`；子单只管自己的生命周期，父单由总管在子单全 done 后收口。

## 7. 升级（员工 → 总管，全平台统一通道）

需要总管决策、需要换人、被阻塞自己解不了（三选一）→ 在工单 `messages.md` **追加一行**（格式严格，生成器靠它识别）：

```
[escalate: 一句话说清要总管干什么] (YYYY-MM-DD)
```

并把 status 改 `paused`（挂起不算你的逾期）；总管处理后删标记、回结论、恢复状态机。**超时自动升层**：等 lead 超 2 个工作日 → 越级报总管；等总管超 3 个工作日 → escalate 注明「等待用户拍板」；**等用户是唯一合法的无限等待**（总管每会话汇报必提）。纪律：能自查的不升；升级前把上下文写全——总管不在你的会话里，messages 就是他的眼睛。

## 8. 红线

1. **不碰看板/生成器**（`workbench/kanban.html`、OPC 根 `opc_tickets.py`/`opc_dashboards.py` 等）——你只维护 `workbench/tasks/` 下的工单文件。
2. **不复制输入物**（保持引用）、**不自造编号**/**非规范目录**、**不删 messages.md 历史**。

## 9. 自检

收工前 `python ../../../opc_tickets.py --selftest` 全过（退出码 0）；上板确认开 `workbench/kanban.html`（或地址栏 `?selftest=1` 跑前端自测）。
