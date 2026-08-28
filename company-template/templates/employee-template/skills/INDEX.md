<!-- 本文件由 `python opc_model.py --sync-index` 生成，勿手改。
     技能元数据的唯一真相在各 SKILL.md frontmatter（triggers/summary）。
     重新生成：python opc_model.py --sync-index -->

# 技能披露索引（employee-template）

| 技能 | 触发词（命中即加载） | 摘要 | 路径 |
|---|---|---|---|
| **技能名-kebab-case** | 触发词1、触发词2 | 一句话说明本技能做什么 + 触发词（用户提到这些场景时加载）。 | `skills/技能名-kebab-case/SKILL.md` |
| **concurrent-work** | 并发、多开、多个会话、工位、seat、收口、同时干活、抢活、共干 | 并发会话协作机制（工位卡）。 | `skills/concurrent-work/SKILL.md` |
| **patrol** | 巡检、巡查、公司体检、例行检查、心跳 | 公司例行巡检（总管每会话执行 / opc_patrol.py 心跳自动执行）。 | `skills/patrol/SKILL.md` |
| **ticket-system** | 建工单、创建任务、派任务、新建工单、改状态、流转、交接、转交、完成工单、取消工单、task.md、handoffs、inputs、completed_at、TSK、认领、接单、漏接、阻塞、blocked_by、前置、父单、子单、需求闭环、取号、号池 | 公司工单系统自解释技能。 | `skills/ticket-system/SKILL.md` |
| **worklog-discipline** | 记工作、worklog、开工、干完了、任务完成、交付物归档、接到任务、归档、切档 | 员工工作自记录机制（三段式+归档）。 | `skills/worklog-discipline/SKILL.md` |
