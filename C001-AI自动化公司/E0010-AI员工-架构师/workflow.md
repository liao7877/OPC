# 架构师工作流（员工级）

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> 并发/启动纪律以 AGENTS.md 与公司级技能为唯一权威，本文件不重复。

## Steps
- step: 1
  action: 读取任务需求
  role: E0010（架构师）
  input: 任务目录 task.md / 总管派发指令 / 用户直聊
  output: 理解任务目标；信息不全时向总管/用户澄清
  next: step 2
- step: 2
  action: 理解业务目标与约束 → 架构方案（分层/模块/数据流/技术选型）→ 权衡取舍并留档 → 评审与迭代
  role: E0010（架构师）
  input: 任务输入材料
  output: 架构设计文档/技术选型报告/ADR
  next: step 3
- step: 3
  action: 交付与留痕：产出物写入任务目录 deliverables/，worklog 记条目
  role: E0010（架构师）
  input: 岗位产出物
  output: 交付物齐全、自检通过
  next: review（交总管待审，验收=用户）
