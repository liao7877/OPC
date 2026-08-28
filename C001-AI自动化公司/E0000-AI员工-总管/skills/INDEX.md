<!-- 本文件由 `python opc_model.py --sync-index` 生成，勿手改。
     技能元数据的唯一真相在各 SKILL.md frontmatter（triggers/summary）。
     重新生成：python opc_model.py --sync-index --company C001 -->

# 技能披露索引（E0000-AI员工-总管）

| 技能 | 触发词（命中即加载） | 摘要 | 路径 |
|---|---|---|---|
| **demand-clarify** | 需求、想法、构想、我想要、帮我理、澄清、PRD、需求分析、立项 | 需求澄清与 PRD 存档流程（总管兼任需求分析师）。 | `skills/demand-clarify/SKILL.md` |
| **dispatch-sop** | 派任务、派发、分配、接需求、调度、建工单、创建任务 | 总管接到用户需求后，按标准流程拆解、建工单、选人派发的操作手册。 | `skills/dispatch-sop/SKILL.md` |
| **mechanism-sop** | 机制、制度、新想法怎么落地、放哪里、建目录、落位、扩展、怎么改、设计、搭建、升级机制 | 机制落位 SOP（总管核心能力：把用户构想变成正确的文件/目录/机制安排）。 | `skills/mechanism-sop/SKILL.md` |
| **status-logging** | 更新状态、记一下、留痕、看板、状态变更 | 任务状态留痕规范，确保状态可追溯。 | `skills/status-logging/SKILL.md` |
| **ticket-split** | 拆单、拆分、拆需求、分解任务、怎么拆、派活、工单拆分、需求闭环 | 需求拆分工单 SOP（总管专用）。 | `skills/ticket-split/SKILL.md` |
| **concurrent-work** | 并发、多开、多个会话、工位、seat、收口、同时干活、抢活、共干 | 并发会话协作机制（工位卡）。 | `opc://company:C001/skill/concurrent-work` |
| **patrol** | 巡检、巡查、公司体检、例行检查、心跳 | 公司例行巡检（总管每会话执行 / opc_patrol.py 心跳自动执行）。 | `opc://company:C001/skill/patrol` |
| **ticket-system** | 建工单、创建任务、派任务、新建工单、改状态、流转、交接、转交、完成工单、取消工单、task.md、handoffs、inputs、completed_at、TSK、认领、接单、漏接、阻塞、blocked_by、前置、父单、子单、需求闭环、取号、号池 | 公司工单系统自解释技能。 | `opc://company:C001/skill/ticket-system` |
| **worklog-discipline** | 记工作、worklog、开工、干完了、任务完成、交付物归档、接到任务、归档、切档 | 员工工作自记录机制（三段式+归档）。 | `opc://company:C001/skill/worklog-discipline` |
