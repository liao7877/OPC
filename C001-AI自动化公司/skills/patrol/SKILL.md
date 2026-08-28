---
name: patrol
description: 公司例行巡检（总管每会话执行 / opc_patrol.py 心跳自动执行）。触发词：巡检、巡查、公司体检、例行检查、心跳。定义"什么算异常"的唯一清单——人工巡检与机器心跳共享同一份定义，杜绝两套标准漂移。
summary: 公司例行巡检（总管每会话执行 / opc_patrol.py 心跳自动执行）。
triggers: [巡检, 巡查, 公司体检, 例行检查, 心跳]
---

# 公司巡检（patrol）

> **定位**：公司运转的例行体检清单。总管每次会话的"轻巡检"与本仓库 `opc_patrol.py`
> 心跳（可挂计划任务/cron 定时跑）消费**同一份清单**——机器发现异常写入看板告警，
> 总管（或用户）处理；谁先发现都能兜住。
> **执行器分工**：opc_patrol.py 负责"发现"（纯读 + 追加告警数据），总管负责"处置"
> （答复/转派/催办/补号）。机器不代做处置决策。

## 巡检清单（唯一权威，与 opc_schema.PATROL 阈值联动）

| # | 检查项 | 判定 | 数据源 | 处置 |
|---|---|---|---|---|
| 1 | 阻塞解锁 | blocked_by 上游已全部 done 而本单还在 backlog | tasks-data.json | 通知 owner 开工（机器自动写入看板告警） |
| 2 | 认领缺口 | owner 有主且未终态但 worklog 无对应条目 | tasks-data.json + worklog | 催 owner 认领 |
| 3 | 双账不一致 | worklog 状态与工单状态矛盾（A2 规则） | 同上 | 以 task.md 为准修 worklog |
| 4 | 脱期事务 | active 节奏事务超过 cadence 阈值未推进 / 从未推进 | dashboard-data.js affairs | 催 owner，连续 2 个周期脱期上报用户 |
| 5 | 升级信箱 | 工单 ⏫ 标记 / messages.md `[escalate: ...]` 行未处理 | tasks-data.json escalations | **优先处置**：答复/转派/解锁，处理完删标记行 |
| 6 | 号池水位 | 预留号池剩余 < `PATROL.ticket_pool_min` | workbench/task-index.md 预留号池段 | 补号段（登记补号日期） |
| 7 | worklog 归档 | 热文件存在上一年度条目 | E*/workspace/worklog.md | 提醒归档到 worklog-archive/ |
| 8 | 知识库增量 | 公司知识库 methods/ 有未评审新条目 | 公司知识库/methods/ | 评审提炼成技能/制度/背景资料 |
| 9 | 僵尸工位卡 | sessions/ 下 `status: 工作中` 但 mtime 超过 3 天 | E*/workspace/sessions/*.md | 核对会话是否真已结束：是 → 改"已收口"并收口其 inbox 分片；否 → 联系对应会话 |
| 10 | 生成器健康 | tasks-data.json 缺失/stale（生成时间 > 24h 且有 watcher 应在跑） | workbench/tasks-data.json | 跑 `run_boards once`；无 watcher 则补挂 |

## 心跳模式（opc_patrol.py）

```
python opc_patrol.py --company C001        # 单次巡检（计划任务/cron 每日调用）
python opc_patrol.py --company C001 --once-only   # 只检查不写告警（干跑）
```

- 心跳把 1/2/3/4 号检查项的异常**追加**进看板告警流（`dashboard-data.js` 的 risks.warnings，
  生成器重跑时由生成器口径重建，心跳告警存 `workbench/patrol-log.md`，幂等去重）。
- 5~10 号需要判断/联动处置的项，心跳只产出待办清单打印 + 追加到 patrol-log，由总管会话处理。
- 用户不需要懂任何机制：**开着计划任务 = 公司每天自己体检一次**；没挂计划任务时，
  总管每会话的巡检（本清单）兜底。

## 巡检结果留痕

- 机器：`workbench/patrol-log.md`（追加式，`[日期] 检查项: 结论` 一行一条，只增不删）。
- 人工：总管在处理完待办后，在对应工单 messages.md 留痕（照常），patrol-log 不记处置只记发现。
