# 项目工作流（流水线）

> 项目级流水线：定义任务从开始到完成的流转步骤（三级工作流中的"项目/团队级"）。
> 统一 Markdown 格式：Steps 列表。

## Steps
- step: 1
  action: 需求确认与拆解
  role: E0000（总管）
  input: 用户需求
  output: 拆解后的 TSK 任务
  next: step 2
- step: 2
  action: 任务执行
  role: 按任务类型匹配员工（如 E0001 售前工程师）
  input: 任务目录 task.md
  output: 任务目录 deliverables/
  next: step 3
- step: 3
  action: 审核与汇报
  role: E0000（总管）
  input: 交付物
  output: 汇报用户，任务状态改完成
  next: done
