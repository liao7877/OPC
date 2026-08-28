# 项目经理工作流（员工级）

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> **并发约定**：多工单并行时一会话一单（工位卡隔离）；memory 沉淀写 inbox 分片、收口合并；交接/阻塞字段规则见公司级技能 ticket-system。启动三动作（工位卡/漏接自查/保活）见 AGENTS.md。

## Steps
- step: 1
  action: 接收项目资料与需求
  role: E0002（项目经理）
  input: 用户投喂的资料 + 对话需求
  output: 归档到 workspace/，建立项目上下文
  next: step 2
- step: 2
  action: 项目规划（WBS 拆解、排期、风险识别）
  role: E0002（项目经理）
  input: 项目上下文
  output: 项目计划 / 任务清单
  next: step 3
- step: 3
  action: 执行与监控（进度跟踪、阻塞处理、变更管理）
  role: E0002（项目经理）
  input: 项目计划
  output: 状态更新、风险预警、待决策项
  next: step 4
- step: 4
  action: 归档与汇报
  role: E0002（项目经理）
  input: 阶段/终版交付物
  output: 资料沉淀 memory/ + 向总管汇报
  next: review（交总管待审）
