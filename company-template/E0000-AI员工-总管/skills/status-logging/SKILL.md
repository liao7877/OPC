---
name: status-logging
description: 任务状态留痕规范，确保状态可追溯。触发词：更新状态、记一下、留痕、看板、状态变更。
---

# 状态留痕规范（status-logging）

> 用途：任务状态变化必须可追溯，避免"黑箱推进"。
> 级别：E0000 私有技能。

## 状态机（与工单系统一致）
待领(backlog) → 进行中(in_progress) → 待审(review) → 完成(done)
旁路：失败(failed) / 暂停(paused) / 取消(cancelled)

## 留痕动作（新体系：文件即留痕）
- **状态变更的真相在工单文件**：员工改 `workbench/tasks/TSKxxx-标题/task.md` 的 `status`（+可选 `status_history`），生成器自动读取 → 看板 `kanban.html` ≤3 秒呈现，**无需人工同步看板**。
- 新工单：`--new` 建单 + task-index.md 台账登记编号（见 dispatch-sop）。
- 异常 / 完成：写入该工单 `messages.md` / `logs/`；关键决策沉淀 memory/MEMORY.md（五要素）。
- 审计：看板详情里的「流转轨迹（handoffs）」与「状态轨迹（status_history）」即完整留痕。

## 检查清单
- [ ] 工单 `task.md` 状态与实际情况一致（生成器校验，不一致会告警）
- [ ] 任务编号已在 task-index.md 台账登记
- [ ] 关键决策已沉淀（messages.md / memory）
