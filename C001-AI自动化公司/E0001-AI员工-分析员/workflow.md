# 分析员工作流（员工级）

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> **并发约定**：多工单并行时一会话一单（工位卡隔离）；memory 沉淀写 inbox 分片、收口合并；交接/阻塞字段规则见公司级技能 ticket-system。启动三动作（工位卡/漏接自查/保活）见 AGENTS.md。
> 技能引用一律在 `AGENTS.md` 中声明；本文件仅描述需要多技能编排/复杂任务的流程。

## Steps
- step: 1
  action: 读取任务需求
  role: E0001-分析员
  input: 任务目录 task.md
  output: 理解任务目标
  next: step 2
- step: 2
  action: 执行分析（调用技能/工具）
  role: E0001-分析员
  input: 任务输入材料
  output: 分析结论
  next: step 3
- step: 3
  action: 产出交付物
  role: E0001-分析员
  input: 分析结论
  output: 任务目录 deliverables/
  next: review（交总管待审）
