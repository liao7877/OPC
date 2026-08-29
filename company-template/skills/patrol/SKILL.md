---
name: patrol
description: 公司例行巡检（总管每会话执行 / OPC 服务内置巡检自动执行）。触发词：巡检、巡查、公司体检、例行检查、心跳、服务巡检。定义"什么算异常"的唯一清单——人工巡检与机器巡检共享同一份定义，杜绝两套标准漂移。
summary: 公司例行巡检（总管每会话执行 / OPC 服务内置巡检自动执行）。
triggers: [巡检, 巡查, 公司体检, 例行检查, 心跳, 服务巡检]
---

# 公司巡检（patrol）

> **定位**：公司运转的例行体检清单。总管每次会话的"轻巡检"与 OPC 服务内置巡检
> （`opc_service.py` 进程内调用 `opc_patrol.py`）消费**同一份清单**——机器发现异常写入看板告警，
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
| 11 | 工单工期风险 | 活跃未完成单（`due` 已过 = 已逾期；剩余 ≤ 3 天 = 临期） | workbench/tasks/*/task.md | 催办或改期；已完成的直接关单（done/paused/failed/cancelled 不算逾期） |
| 12 | 工单停滞 | `in_progress` 超过 3 天无 updated | workbench/tasks/*/task.md | 问清卡点：真阻塞 → 改 `blocked` 并写升级信箱；否则催办 |

> 11/12 号（2026-08-29 决策 #18 新增）：用户拍板「要主动打扰」的两类事件——工单逾期/临期与长期无进展。阈值在 `opc_schema.PATROL`（`due_soon_days` / `stalled_days`，默认各 3 天）。

## 机器巡检（OPC 服务 · opc_patrol.py）

日常**不需要手动跑**：OPC 服务（`opc_service.py`，进程内调度）数据一变即巡检、另有周期兜底，异常实时弹系统通知。下面是排查/手动补跑的入口：

```
python opc_patrol.py --company <本司ID>            # 手动巡检一次 + 写日志/闭环态
python opc_patrol.py --company <本司ID> --dry-run  # 只检查打印，不写任何文件
python opc_patrol.py --selftest                # 内置自测
python opc_service.py                          # 前台起服务（bootstrap 已挂自启）
```

> ⚠️ 2026-08-29 修正：旧版文档写的 `--once-only` 参数**不存在**，实际是 `--dry-run`。

### 产出物三件套（机器写、人类读）

| 文件 | 性质 | 说明 |
|---|---|---|
| `workbench/patrol-log.md` | **审计流水**（只增不删） | 发现留痕，P2 主数据 |
| `workbench/patrol-state.json` | **闭环态**（可改） | `open → handled → 再犯 reopened`；派生态，删了可从 log 重建 |
| `workbench/patrol-pending.md` | **待办快照**（生成物） | 仅 open 项，critical 置顶；总管启动第 5 步读它 |

- 发现异常时另弹**系统通知**（A+ 报警通道，`opc.toml [patrol].notify=false` 可关；Windows/macOS/Linux 三端尽力而为，失败不影响巡检）。
- 巡检**不写** `dashboard-data.js`——那是生成器的投影，单向管道（P4）下投影永不写回。
- 用户不需要懂任何机制：**OPC 服务开着 = 公司自己体检**（数据一变就查）；服务没跑时，
  总管每会话的巡检（本清单）兜底。

## 自动化边界（PRINCIPLES P29）

巡检只做「发现」，**不做「处置决策」**：

| 段 | 谁做 | 状态 |
|---|---|---|
| 发现 | OPC 服务内置巡检（1~12 号检查项） | ✅ 已实现 |
| 留痕 / 闭环 | patrol-log + patrol-state + patrol-pending | ✅ 已实现 |
| 报警 | 系统通知（可关） | ✅ 已实现 |
| 处置（答复/转派/催办/补号） | **总管（人类在环）** | ✅ 已实现 |
| 自动派单 / 自动处置 | `opc.toml [patrol].actor` | ⏸ **预留扩展位，默认不启用**——启用需显式拍板 |

> **为什么到此为止**：用管人的抽象管 Agent，Agent 的失败模式与人根本不同（Multica issue #815 的教训）——人从"进行中"挪到"阻塞"只挪一次，Agent 卡在循环里 90 秒能刷五次状态迁移，自动处置会把看板淹掉。
> **判据**：机器可以提醒「该开工了」，不可以替人决定「这就算做完了」。

## 巡检结果留痕

- 机器：`workbench/patrol-log.md`（追加式，`[日期] 检查项: 结论` 一行一条，只增不删）。
- 人工：总管在处理完待办后，在对应工单 messages.md 留痕（照常），patrol-log 不记处置只记发现。
