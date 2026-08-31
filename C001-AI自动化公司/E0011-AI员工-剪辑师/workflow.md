# 岗位工作流（员工级）剪辑师

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> 技能引用走 `opc://company:C001/skill/<名称>`（见 opc-namespace-design.md）或在 `AGENTS.md` 中声明；本文件仅在需要**多技能编排/复杂任务**时描述流程；agent 要打开技能文件时把 `opc://company:C001/...` 当稳定锚 `companies/C001` 用（真实目录），或 `python opc_resolver.py --resolve <uri>` 取绝对路径（见 opc-namespace-design.md §3.1）。

## Steps
- step: 1
  action: 接收剪辑任务，确认脚本/分镜/参考风格与交付规格（时长/画幅/平台/字幕语言）
  role: E0011（剪辑师）
  input: 任务目录 task.md / 总管派发指令 / 素材清单
  output: 理解任务目标；规格不齐时向总管/用户一次性问清
  next: step 2
- step: 2
  action: 整理素材并粗剪（搭结构、定节奏），产出粗剪版供确认
  role: E0011（剪辑师）
  input: 原始素材（只读副本）、脚本/分镜
  output: 粗剪版（任务目录 deliverables/，标注待定项）
  next: step 3
- step: 3
  action: 精剪 + 字幕/包装 + 配乐音效，按平台规格导出成片并留痕
  role: E0011（剪辑师）
  input: 粗剪反馈、素材副本
  output: 成片 + 工程文件归档（任务目录 deliverables/）+ messages.md 备注
  next: review（交总管/用户验收）
