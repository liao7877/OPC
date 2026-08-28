# C001 | AI自动化公司

> 公司级总纲文档。定义公司实体、组织规范与全局约定。
> **组织级设计原则**（通用，所有公司/项目适用）：`opc://org/principles` —— 搭建/改动前先读。
> **目录结构说明书**（结构契约：每个目录/文件的职责/维护者/红线）：`../companies/C001/目录结构说明书.md` —— 落位/改动前对照，改结构必须同步更新。
> **公司工作流**（三级协作协议：双入口/交接/升级/闭环）：`workflow.md`。

## 基本信息
- 公司 ID：C001
- 公司名：AI自动化公司
- 根目录：本目录
- 机制基线：company-template v2（2026-08-28；对照 `../company-template/CHANGELOG.md` 决定是否跟进机制升级）

## 组织架构
- 团队：T001-AI开发团队
- 员工：E0000-总管（调度中枢）、E0001-售前工程师（需求分析 × 售前解决方案）
- 项目：P0001-示例项目
- **新建员工**：总管按 `templates/employee-template/` 模板 + `dispatch-sop` 的「新建员工 SOP」执行（AGENTS.md / CLAUDE.md / skills INDEX / junction 四件套，禁止退回老结构）

## 全局规范（文件系统即领域模型）
- **命名规范**：前缀 + 序号 + `-` 分隔 + 名称；序号位数：C/T 三位（C001/T001）、E/P 四位（E0000/P0001）、TSK 五位（TSK00001）
  - 注：逻辑分隔符为 `|`（如 `E0000|AI员工|总管`），Windows 目录名用 `-` 替代
- **实体即目录**：公司/团队/员工/项目/任务均为独立目录
- **引用制（图）**：归属关系通过目录内声明表达，支持多对多，不依赖物理嵌套
- **员工位置无关（逻辑归属）**：员工与公司/团队为逻辑引用关系、无嵌套依赖，经 `E0000/roster.md` 发现；**物理约束**：参与看板体系的员工目录必须位于公司根目录下（扫描约定，见 P0004 需求文档）

## 目录结构
```
../companies/C001/
├── company.md              # 本文件（公司总纲）
├── workbench/tasks/        # 统一任务区：TSK00001-标题/（任务实体目录）
├── T001-AI开发团队/        # 团队实体（team.md）
├── E0000-AI员工-总管/       # 0 号员工：调度中枢
├── E0001-AI员工-售前工程师/  # 员工实体（需求分析 × 售前）
└── P0001-示例项目/          # 项目实体（project.md + workflow.md）
```

## 任务区约定
- 所有任务统一存放：`workbench/tasks/TSK00001-标题/`
- 任务目录结构：task.md（状态/负责人）+ messages.md（消息）+ deliverables/（交付物）+ logs/（日志）
- 任务编号 TSK 前缀全局唯一，由总管分配并登记

## 工单系统（看板 + 生成器 + 公司级技能）
- **看板**：`workbench/kanban.html`（双击即开；数据从 tasks/ 自动生成并 ≤3 秒同步；分组/筛选/详情/流转轨迹/逾期标记）
- **生成器**：机制代码上提 OPC 根——`opc_tickets.py`（工单）/ `opc_dashboards.py`（三级看板）；公司内统一入口 `run_boards.bat|.sh`（`--new` 建单 / `--watch` 自动重跑 / `--selftest` 内置自检 调根模块）
- **状态机**：backlog → in_progress → review → done；旁路 failed / paused / cancelled
- **公司级技能**：`skills/ticket-system/SKILL.md` —— 工单操作全流程自解释（建单/流转/完成/告警/红线），**员工 AGENTS.md 引用即生效，无需培训**
- **规范权威**：员工执行以 `skills/ticket-system/SKILL.md` 为准；参考手册 `workbench/tasks/README.md`；架构设计 `workbench/KANBAN_ARCHITECTURE.md`
