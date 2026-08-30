# 岗位工作流（员工级）【岗位名】

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> 技能引用走 `opc://company:C001/skill/<名称>`（见 opc-namespace-design.md）或在 `AGENTS.md` 中声明；本文件仅在需要**多技能编排/复杂任务**时描述流程；agent 要打开技能文件时把 `opc://company:C001/...` 当稳定锚 `companies/C001` 用（真实目录），或 `python opc_resolver.py --resolve <uri>` 取绝对路径（见 opc-namespace-design.md §3.1）。

## Steps
- step: 1
  action: 读取任务需求【替换为岗位实际第一步】
  role: E00x-【岗位名】
  input: 任务目录 task.md / 总管派发指令
  output: 理解任务目标
  next: step 2
- step: 2
  action: 执行【岗位核心动作】【替换】
  role: E00x-【岗位名】
  input: 任务输入材料
  output: 【岗位产出物】
  next: step 3
- step: 3
  action: 产出交付物并留痕
  role: E00x-【岗位名】
  input: 岗位产出物
  output: 任务目录 deliverables/ + messages.md 备注
  next: review（交总管/下一手审核）
