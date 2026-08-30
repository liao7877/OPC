# 测试工程师工作流（员工级）

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> 并发/启动纪律以 AGENTS.md 与公司级技能为唯一权威，本文件不重复。

## Steps
- step: 1
  action: 读取任务需求
  role: E0008（测试工程师）
  input: 任务目录 task.md / 总管派发指令 / 用户直聊
  output: 理解任务目标；信息不全时向总管/用户澄清
  next: step 2
- step: 2
  action: 分析需求 → 设计测试用例（正常/边界/异常）→ 搭建执行（手工/自动化）→ 报告缺陷并跟踪回归
  role: E0008（测试工程师）
  input: 任务输入材料
  output: 用例集/测试报告/缺陷清单
  next: step 3
- step: 3
  action: 交付与留痕：产出物写入任务目录 deliverables/，worklog 记条目
  role: E0008（测试工程师）
  input: 岗位产出物
  output: 交付物齐全、自检通过
  next: review（交总管待审，验收=用户）
