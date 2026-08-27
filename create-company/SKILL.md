---
name: create-company
description: 在 OPC 组织根下快速创建新 AI 公司实例。触发词：建公司、新建公司、创建公司、再建一家、公司实例化。用户要建立新公司时，加载本技能按交互式问卷 → 模板复制 → 000 号总管入职流程执行。
---

# 建司技能（create-company）

> **定位**：公司 = `company-template/` 母版 + 本技能流程 的实例化产物（组织可实例化原则）。
> **母版位置**：`company-template/`（与本技能同在 OPC 根）。母版自带：000 号总管（含 dispatch-sop/demand-clarify/ticket-split/mechanism-sop/status-logging 全套技能）、工单系统（生成器+看板）、公司级技能四件、规章制度/知识库/目录结构说明书骨架、员工模板。
> **原则**：每公司内 E/T/P/TSK 编号空间独立；公司 ID 全局唯一（C001、C002…递增，建司前扫 OPC 根查重）。

## 一、交互式问卷（建司前逐项确认，P18）

1. **公司 ID 与名称**：ID 自动取下一个 C 序号（扫 `C*/` 确认）；名称用户定 → 目录名 `C00x-<名称>`；
2. **业务域**：一句话公司定位（写进 company.md「基本信息」）；
3. **预装技能**：默认四件套（ticket-system / worklog-discipline / concurrent-work + 总管五私有技能）；要不要按业务域预建额外公司级技能（通常**不要**，运行中按 mechanism-sop 增量建）；
4. **初始团队与岗位**：默认**不预建**（000 号总管运转起来后按需搭，避免空壳实体）；用户明确要初始团队才建；
5. **确认改动清单**：将创建的目录树一览，给用户过目。

## 二、建司流程

1. **复制母本**：整个 `company-template/` 复制为 `C00x-<名称>/`（含 .workbuddy 结构；junction 复制后会退化为实体目录，下一步重建）；
2. **重建 junction**（关键，母版里是绝对路径指向模板自身）：
   ```powershell
   New-Item -ItemType Junction -Path "C00x-<名称>\.workbuddy\skills" -Target "<绝对路径>\C00x-<名称>\skills"
   New-Item -ItemType Junction -Path "C00x-<名称>\E0000-AI员工-总管\.workbuddy\skills" -Target "<绝对路径>\C00x-<名称>\E0000-AI员工-总管\skills"
   ```
3. **改名落位**：总管目录若带【替换】占位符则按模板规范替换；company.md 填公司 ID/名称/业务域；
4. **首跑验证**：
   ```
   cd C00x-<名称>/workbench && python generate_tasks.py --selftest
   python generate_tasks.py --check-structure
   cd .. && python generate_dashboard.py
   ```
   三项全过 = 骨架可用；
5. **000 号总管入职**（见 §三）。

## 三、000 号总管入职动作（首次会话）

1. 读 `AGENTS.md`（我是总管）→ 读 `roster.md`（此刻只有我自己）→ 读 `目录结构说明书.md`（认清领地）；
2. 确认 junction 四件套有效（公司级 + 总管级）；
3. 跑一次 `run_boards.bat once`（数据链路打通）；
4. 向用户报到：汇报公司骨架就绪 + 请用户给第一个需求/或先搭团队；
5. 后续团队/员工/项目全部按 `skills/dispatch-sop/SKILL.md`（新建员工 SOP、规章制度落实 SOP）+ `skills/mechanism-sop/SKILL.md`（落位决策树）推进，把公司运转起来。

## 四、红线

1. 不在模板里堆业务数据：company-template/ 永远保持"空骨架"（无实例工单/无实例员工/空 worklog）；模板升级 = 改模板，已建公司不自动跟进（各公司独立演进，重大升级由用户决定是否迁移）；
2. 建司问卷不跳步：未确认清单不动手；
3. 公司 ID 全局唯一，创建前必查重；
4. 老公司不受影响：本技能只管新公司；C001 等存量公司由其 000 号总管管理。

---
*创建：2026-08-28 · 依据 MECHANISM_PLAN 决策 #10 · 模板母本：../company-template/*
