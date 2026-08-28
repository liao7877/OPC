<!-- 本文件由 `python opc_model.py --sync-index` 生成，勿手改。
     技能元数据的唯一真相在各 SKILL.md frontmatter（triggers/summary）。
     重新生成：python opc_model.py --sync-index --company C001 -->

# 技能披露索引（E0001-AI员工-分析员）

| 技能 | 触发词（命中即加载） | 摘要 | 路径 |
|---|---|---|---|
| **data-analysis-template** | 分析一下、做个研究、数据报告、对比、整理情报 | 分析员接到分析/研究类任务时，产出结构化分析报告的标准模板。 | `skills/data-analysis-template/SKILL.md` |
| **concurrent-work** | 并发、多开、多个会话、工位、seat、收口、同时干活、抢活、共干 | 并发会话协作机制（工位卡）。 | `opc://company:C001/skill/concurrent-work` |
| **patrol** | 巡检、巡查、公司体检、例行检查、心跳 | 公司例行巡检（总管每会话执行 / opc_patrol.py 心跳自动执行）。 | `opc://company:C001/skill/patrol` |
| **ticket-system** | 建工单、创建任务、派任务、新建工单、改状态、流转、交接、转交、完成工单、取消工单、task.md、handoffs、inputs、completed_at、TSK、认领、接单、漏接、阻塞、blocked_by、前置、父单、子单、需求闭环、取号、号池 | 公司工单系统自解释技能。 | `opc://company:C001/skill/ticket-system` |
| **worklog-discipline** | 记工作、worklog、开工、干完了、任务完成、交付物归档、接到任务、归档、切档 | 员工工作自记录机制（三段式+归档）。 | `opc://company:C001/skill/worklog-discipline` |
