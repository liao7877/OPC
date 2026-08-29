# template-diff-allowlist —— 实例 ↔ company-template 已知差异登记清单
#
# 机制（2026-08-29）：`opc_resolver.py --diff-template` 机器发现实例与模板的差异，
# 未登记的差异会在本清单之外被标出 [未登记]，并在 doctor 出 warning（不阻断）。
# 人工决策二选一：属实例专属内容 → 在此登记一行；属机制漂移 → 回改两侧对齐
# （四处同步铁律：C001 实例 + 总管 + company-template + 根文档）。
# 格式：一行一个相对实例根的路径（目录/文件均可）；# 开头为注释。

# —— 实例档案与公司专属内容（本就该不同）——
AGENTS.md                     # 模板侧多「建司指引」段；实例侧是已落地的公司红线
company.md                    # 公司档案本身：定位/编制/边界各公司必然不同
公司规章制度/工单操作规范.md     # 公司级操作细则，实例自定义
目录结构说明书.md               # 结构契约说明（实例含实际目录举例）
CHANGELOG.md                  # 模板独有：模板自身的演进记录，实例不跟随

# —— 技能与流程文档（实例先行，模板滞后属已知债，回改收敛前登记；ticket-system 已打样归一移出）——
skills/worklog-discipline/SKILL.md
templates/employee-template/workflow.md

# —— workbench 机制文档（实例侧多历史决策段）——
workbench/KANBAN_ARCHITECTURE.md
workbench/tasks/README.md     # 实例侧含完整使用手册（162 行差异，模板侧为骨架）
