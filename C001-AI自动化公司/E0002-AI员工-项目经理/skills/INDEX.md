<!-- 本文件由 `python opc_model.py --sync-index` 生成，勿手改。
     技能元数据的唯一真相在各 SKILL.md frontmatter（triggers/summary）。
     重新生成：python opc_model.py --sync-index --company C001 -->

# 技能披露索引（E0002-AI员工-项目经理）

| 技能 | 触发词（命中即加载） | 摘要 | 路径 |
|---|---|---|---|
| **material-archive** | 资料归档、收资料、整理文件、存一下 | 项目经理接收并归档用户投喂的项目管理资料（需求/会议纪要/进度表/合同等）到工作区的规范。 | `skills/material-archive/SKILL.md` |
| **project-plan-template** | 项目规划、做计划、WBS、排期、拆解任务、立项 | 项目经理接到项目资料或需求后，生成 WBS 拆解、排期与风险登记册的标准模板。 | `skills/project-plan-template/SKILL.md` |
| **status-report** | 周报、状态报告、汇报进度、项目进展、给我汇报一下 | 项目经理基于项目当前状态生成周报/状态报告，向总管或用户汇报。 | `skills/status-report/SKILL.md` |
| **concurrent-work** | 并发、多开、多个会话、工位、seat、收口、同时干活、抢活、共干 | 并发会话协作机制（工位卡）。 | `opc://company:C001/skill/concurrent-work` |
| **patrol** | 巡检、巡查、公司体检、例行检查、心跳 | 公司例行巡检（总管每会话执行 / opc_patrol.py 心跳自动执行）。 | `opc://company:C001/skill/patrol` |
| **ticket-system** | 建工单、创建任务、派任务、新建工单、改状态、流转、交接、转交、完成工单、取消工单、task.md、handoffs、inputs、completed_at、TSK、认领、接单、漏接、阻塞、blocked_by、前置、父单、子单、需求闭环、取号、号池 | 公司工单系统自解释技能。 | `opc://company:C001/skill/ticket-system` |
| **worklog-discipline** | 记工作、worklog、开工、干完了、任务完成、交付物归档、接到任务、归档、切档 | 员工工作自记录机制（三段式+归档）。 | `opc://company:C001/skill/worklog-discipline` |
