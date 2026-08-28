# 售前工程师工作流（员工级）

> 本岗位的标准工作流程（三级工作流中的"员工级"）。
> 统一 Markdown 格式：Steps 列表，含动作/角色/输入/产出/下一步。
> **并发约定**：多工单并行时一会话一单（工位卡隔离）；memory 沉淀写 inbox 分片、收口合并；交接/阻塞字段规则见公司级技能 ticket-system。启动三动作（工位卡/漏接自查/保活）见 AGENTS.md。
> 技能引用一律在 `AGENTS.md` 中声明；本文件只做**编排与纪律**（分流/交付/待审），方法论步骤与产出物细节的唯一权威在私有技能 `presales-requirement-analysis`，本文件不重复。

## Steps
- step: 1
  action: 读取任务需求
  role: E0001-售前工程师
  input: 任务目录 task.md
  output: 理解任务目标；信息不全时按 presales skill §4.1 访谈提纲向总管/用户澄清
  next: step 2
- step: 2
  action: 判定任务类型：需求分析/文档类 → 分支 A；方案设计/售前类 → 分支 B
  role: E0001-售前工程师
  input: 任务目标 + 输入材料
  output: 分支路由
  next: step A 或 B
- step: 3
  action: 交付与自检：产出物写入任务目录 deliverables/，按 presales skill §6 自检清单过一遍
  role: E0001-售前工程师
  input: 阶段产出
  output: 交付物齐全、自检通过
  next: review（交总管待审，验收=用户）

## 分支 A：需求分析类
- step: A
  action: 按 presales skill §2.1「需求分析五步法」逐步执行（需求定义 → 捕获 → 分析建模 → 规约 → 验证跟踪）；每步产出物以技能内清单为准
  role: E0001-售前工程师
  input: 任务输入材料
  output: BRD/MRD/PRD/SRS 及配套流程图/用例图 → 任务目录 deliverables/
  next: step 3

## 分支 B：售前方案类
- step: B
  action: 按 presales skill §2.2「售前方案设计六步法」逐步执行（客户画像 → 差距分析 → 架构设计 → ROI 论证 → 落地规划 → 风险保障）；每步产出物以技能内清单为准
  role: E0001-售前工程师
  input: 任务输入材料
  output: 方案蓝图/架构图/ROI 报告/实施路线图/风险评估表 → 任务目录 deliverables/
  next: step 3
