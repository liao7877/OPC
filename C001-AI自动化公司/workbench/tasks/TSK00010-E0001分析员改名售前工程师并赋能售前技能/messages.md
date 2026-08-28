# messages

## 2026-08-29 E0000
- 建单并领单（owner=E0000，in_progress）。依据：AGENTS.md 自营例外（公司机制/员工设定类总管可自营，工位卡 identity=执行，验收=用户）。
- 改名方案已摸底：E0001 实体 ID 不变，历史工单/台账不动；看板数据为生成物，改 roster + 重跑生成器自愈。

## 2026-08-29 E0000（完工待审）
- 完成事项：
  1. 目录改名 `E0001/` → `E0001/`；重建断掉的 `.workbuddy/skills` junction
  2. roster.md：路径/岗位/备注更新；预留岗位「需求分析师」注记同步（分析能力已由 E0001 承接，澄清入口仍在总管）
  3. E0001 人设重写：AGENTS.md（角色定位=售前工程师，补素养基线七条；公司级技能引用行原样保留）+ workflow.md（主流程 + 需求分析五步法分支 A + 售前方案六步法分支 B）
  4. 新增私有技能 `skills/presales-requirement-analysis/SKILL.md`（用户提供蓝本全文落地，补 frontmatter）；`data-analysis-template` 与 skills/README.md 措辞同步
  5. 引用清理：company.md、T001/team.md、P0001/workflow.md、公司级技能 ticket-system 描述、总管文档目录.html、总管 workbench/auto-rules.md（R1 更名分析/售前线并扩充触发词）
  6. `opc_model.py --sync-index` 重生成技能索引（新技能已收录）；`run_boards.bat once` 重生成三级看板数据（dashboard 已显示「售前工程师」）
  7. `opc_resolver.py --doctor` 全绿（命名空间全文扫描自洽 ✓）
- 历史留痕未动：task-index-archive、worklog-archive、各工单 messages.md、.workbuddy 平台记忆中的「分析员」字样属历史事实，不改。
- 工单置 review，待用户验收；验收通过后关单。

## 2026-08-29 E0000（用户反馈去重）
- 反馈：AGENTS/workflow/skill 间内容重复，重复内容随加载浪费 token。
- 处置（单一真相源原则，按加载时机归属）：
  1. 素养基线：唯一权威留在 AGENTS.md（每会话必载）；skill 删除原 §一（20 行），头部留指针；补回压缩时遗漏的「持续进化」条目，信息零损失
  2. 方法论步骤：唯一权威在 skill §2（2.1 五步法 / 2.2 六步法）；workflow.md 从 70 行压到 42 行，A/B 分支只留编排与产出物指向
  3. skill 章节重编号（§一~§七），workflow 交叉引用同步（§2.1/§2.2/§4.1/§6 已验证有效）
- 效果：skill 286→266 行、workflow 70→42 行；同一内容不再存在两份需同时加载的副本。

## 2026-08-29 E0000（并发迁移协同 + 收尾）
- 用户推动全公司实体目录裸 ID 化（E0001/E0002/T001/P0001~P0004），检测到另一会话并行施工（roster/company.md/说明书/opc.toml 05:54 批量更新）。本会话立即停改权威文件防踩踏，只做只读侦察 + 补缺：
  1. dispatch-sop 新建员工 SOP 4 处改裸 ID 口径（对方漏的唯一一处）
  2. 散文引用统一 `ID（名称）` 格式（auto-rules/E0002 workflow×4/P0001 workflow×2）
  3. doctor [fix] 自愈披露 junction ×3（新目标为相对路径，抗改名）
  4. 清除 E0001/E0002 内空 workbench 残留目录
  5. 审计去重收尾：E0001 workflow 头部并发约定摘要改指针；skills/README 技能清单改指向 INDEX.md
  6. 经验已沉淀总管 memory/MEMORY.md（四条五要素）；总管 AGENTS.md 启动流程补"读自己的 MEMORY.md"（原来只有员工有此要求）
- 待办：E0000-AI员工-总管 → E0000 物理改名（opc.toml/roster 已由对方备好，目录被运行中会话占用）。

## 2026-08-29 机制维护者
- 决策 #17（实体显示名与物理路径解耦）已落地：E/T/P 实体目录 ID-only 迁移（E0001/E0002/T001/P0001~P0004），显示名唯一真相=roster 岗位列；--check 新增裸路径散文门禁；dispatch-sop 增「员工改名 SOP」；MECHANISM_PLAN §十五 记档。
- **待办（E0000 目录改名顺延）**：3 个 ZCode 会话进程 cwd 占用 `E0000-AI员工-总管/`，无法改名。用户关闭这些会话后执行：① `git mv "C001-AI自动化公司/E0000-AI员工-总管" "C001-AI自动化公司/E0000"`；② opc.toml roster 键改 `"E0000/roster.md"`；③ OPC 根跑 `python opc_resolver.py --doctor`。机制对遗留名完全兼容，不改名也不影响运行。
