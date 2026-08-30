# 后端工程师工作流（员工级）

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> 并发/启动纪律以 AGENTS.md 与公司级技能为唯一权威，本文件不重复。

## Steps
- step: 1
  action: 读取任务需求
  role: E0009（后端工程师）
  input: 任务目录 task.md / 总管派发指令 / 用户直聊
  output: 理解任务目标；信息不全时向总管/用户澄清
  next: step 2
- step: 2
  action: 明确需求与契约 → 数据建模与接口定义 → 编码实现与自测 → 文档与交付
  role: E0009（后端工程师）
  input: 任务输入材料
  output: 服务代码/接口文档/部署说明
  next: step 3
- step: 3
  action: 交付与留痕：产出物写入任务目录 deliverables/，worklog 记条目
  role: E0009（后端工程师）
  input: 岗位产出物
  output: 交付物齐全、自检通过
  next: review（交总管待审，验收=用户）
