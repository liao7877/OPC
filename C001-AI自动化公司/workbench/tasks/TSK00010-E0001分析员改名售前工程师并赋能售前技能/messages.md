# messages

## 2026-08-29 E0000
- 建单并领单（owner=E0000，in_progress）。依据：AGENTS.md 自营例外（公司机制/员工设定类总管可自营，工位卡 identity=执行，验收=用户）。
- 改名方案已摸底：E0001 实体 ID 不变，历史工单/台账不动；看板数据为生成物，改 roster + 重跑生成器自愈。

## 2026-08-29 E0000（完工待审）
- 完成事项：
  1. 目录改名 `E0001-AI员工-分析员/` → `E0001-AI员工-售前工程师/`；重建断掉的 `.workbuddy/skills` junction
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
