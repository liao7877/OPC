#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_schema.py —— OPC 状态机与枚举唯一真相源（schema 层）

> 2026-08-28 下沉（架构评审）：此前工单状态机在 opc_tickets、worklog 状态在
> opc_dashboards、roster 状态枚举藏在解析正则里、affairs 节奏阈值硬编码——
> 同一份"状态语义"分散四处，改一个状态要动三处代码 + 一份 SKILL.md 人肉副本。
> 现在全部收敛到本模块：生成器 import 这里，SKILL.md / 台账等文档引用"见
> opc_schema"不复制（家规：文档描述状态时用文字，不维护第二份枚举表）。

被谁消费：
  - opc_tickets.py / opc_dashboards.py / opc_patrol.py（import）
  - 文档（SKILL.md / task-index 台账）只写自然语言描述，禁止复制枚举表

如需给状态加"中间态"（如 blocked），只改本文件 + 对应看板模板配色，生成器零改动。
"""

# ---- 工单状态机（7 态；task.md 的 status 字段唯一合法取值）----
TASK_STATUS = {
    "backlog": "待领",
    "in_progress": "进行中",
    "review": "待审",
    "done": "完成",
    "failed": "失败",
    "paused": "暂停",
    "cancelled": "取消",
}
TASK_STATUS_ORDER = ["backlog", "in_progress", "review", "done", "failed", "paused", "cancelled"]
# 终态：进入后不再出现在"在途/认领"口径里
TASK_TERMINAL = {"done", "failed", "cancelled"}
# 活跃在途（W4 口径；paused 显示不计数）
TASK_ACTIVE = {"backlog", "in_progress", "review"}

# ---- worklog 条目状态（worklog.md 条目的 status 字段）----
WORKLOG_STATUS = ("计划中", "进行中", "已完成")

# ---- roster 员工状态 ----
EMPLOYEE_STATUS = ("在职", "休假", "离职", "未登记")
# 员工状态列（含扩展"角色"列）中 lead 的识别词
LEAD_MARK = "lead"

# ---- 常设事务（affairs）----
AFF_STATUS = ("active", "paused", "closed")
# cadence -> 逾期天数阈值（距上次 worklog 推进；"按需"不判定）
AFF_CADENCE_DAYS = {"每日": 2, "每周": 9, "每两周": 17, "每月": 35}
AFF_CADENCE_ON_DEMAND = "按需"

# ---- 编号规范（与各公司 task-index 台账/公司.md 一致的组织级默认）----
ID_PATTERNS = {
    "company": r"^C\d{3}$",
    "team": r"^T\d{3}$",
    "project": r"^P\d{4}$",
    "employee": r"^E\d{4}$",
    "task": r"^TSK\d{5}$",
    "affair": r"^AFF\d{4}$",
}

# ---- 巡检阈值（opc_patrol / 总管巡检共用）----
PATROL = {
    "ticket_pool_min": 5,       # 号池剩余 < N 时告警补号
    "worklog_stale_days": 14,   # 进行中 N 天未动 → 风险提示
    "archive_warn_year": None,  # 上一年度热文件提醒归档（None=运行时按当年推导）
    "regen_stale_minutes": 30,  # 看板数据陈旧超过 N 分钟 → 服务自动重生成（数据刷新由 OPC 服务负责）
    "due_soon_days": 3,         # 截止日剩余 ≤ N 天 → 预警（#11）
    "stalled_days": 3,          # in_progress 超过 N 天无 updated → 无进展预警（#12）
}

# ---- 巡检检查项元数据（findings 结构化，2026-08-28 Q1 拍板 A 方案）----
# B 阶段（agent 自动处置）的地基：每项检查的 kind/severity/suggested_action 唯一真相在此。
# severity：info=处置后留痕即可 | warn=催办 | critical=必须打扰用户。
# 10 项里只有 #5（升级信箱）是 critical——用户只被它打扰，其余由总管/未来 agent actor 处置。
PATROL_SEVERITIES = ("info", "warn", "critical")
PATROL_CHECKS = {
    1:  {"kind": "unblock",        "severity": "info",     "action": "notify_owner"},
    2:  {"kind": "claim_gap",      "severity": "warn",     "action": "notify_owner"},
    3:  {"kind": "reconcile",      "severity": "warn",     "action": "reconcile_worklog"},   # 以 task.md 为准
    4:  {"kind": "affair_overdue", "severity": "warn",     "action": "notify_owner"},        # 连续 2 周期 → escalate_user
    5:  {"kind": "escalation",     "severity": "critical", "action": "escalate_user"},
    6:  {"kind": "pool_low",       "severity": "warn",     "action": "refill_pool"},
    7:  {"kind": "archive",        "severity": "info",     "action": "archive_worklog"},
    8:  {"kind": "knowledge",      "severity": "info",     "action": "review_knowledge"},    # ⚠️ 机器侧未实现（见评审 B6）
    9:  {"kind": "zombie_seat",    "severity": "info",     "action": "close_seat"},
    10: {"kind": "stale_data",     "severity": "warn",     "action": "regen_boards"},
    # 风险预警（2026-08-29 决策 #18：用户拍板要主动打扰的两类事件之一；windows 弹窗直达用户）
    11: {"kind": "due_risk",       "severity": "warn",     "action": "notify_owner"},        # 已逾期 / 截止日≤due_soon_days
    12: {"kind": "stalled",        "severity": "warn",     "action": "notify_owner"},        # in_progress 超 stalled_days 无更新
}


def validate():
    """schema 自洽性检查（--selftest 用）：枚举互斥、顺序完整。"""
    problems = []
    if set(TASK_STATUS_ORDER) != set(TASK_STATUS):
        problems.append("TASK_STATUS_ORDER 与 TASK_STATUS 不一致")
    if not TASK_TERMINAL < set(TASK_STATUS):
        problems.append("TASK_TERMINAL 含未知状态")
    if not TASK_ACTIVE < set(TASK_STATUS):
        problems.append("TASK_ACTIVE 含未知状态")
    if TASK_ACTIVE & TASK_TERMINAL:
        problems.append("TASK_ACTIVE 与 TASK_TERMINAL 交集非空")
    return problems


if __name__ == "__main__":
    import sys
    p = validate()
    if p:
        print("schema 不自洽：")
        for x in p:
            print("  -", x)
        sys.exit(1)
    print(f"[ok] opc_schema 自洽：task={len(TASK_STATUS)}态 worklog={len(WORKLOG_STATUS)}态 "
          f"employee={len(EMPLOYEE_STATUS)}态 aff={len(AFF_STATUS)}态 cadence={len(AFF_CADENCE_DAYS)}档 "
          f"patrol_checks={len(PATROL_CHECKS)}项")
