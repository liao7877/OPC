# OPC

> **Organization for AI-Agent Companies** —— 一套「用 AI Agent 跑公司」的组织级框架与规范库。
> 本仓库沉淀：跨 Agent 平台的接入规范、组织级设计原则、机制方案、系统说明，以及一个可复制的 AI 自动化公司示例（`C001`）与开箱模板（`company-template`）。

---

## 这是什么

OPC 不是某个具体产品，而是一套**方法论 + 目录规范 + 技能体系**，用来在同一组织内运行多个由 AI Agent 扮演「员工 / 团队」的公司。核心理念是：

- **文件系统即真相**：领域事实只存在于文件系统，看板 / 报表 / 界面只是它的投影（可重建、不污染真相）。
- **单一真相**：任何事实只有一个权威出处，用引用（路径 / 声明）代替复制。
- **技能分层隔离**：公司级 / 团队级 / 私有，谁需要就放哪层。
- **多 Agent 平台统一接入**：WorkBuddy / Claude Code / Codex 各自机制不同，本仓库统一记录「怎么接入」。

---

## 目录结构

```
OPC/
├── AGENT_ECOSYSTEM.md      # 多 Agent 平台接入规范（WorkBuddy/Claude Code/Codex 目录、披露机制、junction 接法）
├── PRINCIPLES.md           # 组织级设计原则（P1~P24：架构哲学/技能体系/工程实践/协作流程/红线）
├── MECHANISM_PLAN.md       # 机制方案（运行 / 协作 / 派活机制的设计与规划）
├── SYSTEM_GUIDE.html       # 系统说明（可视化总览，浏览器打开）
├── C001-AI自动化公司/       # 示例公司：完整跑通的 AI 自动化公司
│   ├── company.md          #   公司档案（定位 / 编制 / 边界）
│   ├── AGENTS.md / CLAUDE.md # 公司级角色与红线（跨平台兜底）
│   ├── E0000~E0002/        #   员工级工作区（总管 / 分析员 / 项目经理），各含 mydesk/worklog/skills
│   ├── T001-AI开发团队/     #   团队级工作区（含 teamboard / 团队技能）
│   ├── P0001~P0004/         #   项目目录（实体即目录，归属用字段声明）
│   ├── workbench/           #   工单看板系统（tasks/ 为唯一真相，看板 HTML 为投影）
│   ├── skills/              #   公司级技能实体（junction 接入平台披露）
│   ├── dashboard.html / generate_dashboard.py  # 公司看板生成器
│   └── page-templates/      #   dashboard / mydesk / teamboard 模板
├── company-template/        # 新公司脚手架：复制即可开一家新公司
│   ├── company.md / workflow.md / 目录结构说明书.md
│   ├── E0000-AI员工-总管/    #   总管岗模板
│   ├── skills/ / templates/ / workbench/ / page-templates/
│   └── verify_boards.js     #   看板自检脚本
└── create-company/
    └── SKILL.md             # 「开公司」技能：按模板 + 规范一键拉起新公司
```

---

## 核心文档

| 文件 | 作用 |
|---|---|
| [`PRINCIPLES.md`](PRINCIPLES.md) | 组织级通用原则（P1~P24）。搭任何新东西前先通读。 |
| [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md) | 多 Agent 平台接入规范：各平台技能目录、渐进式披露、junction 接法。 |
| [`MECHANISM_PLAN.md`](MECHANISM_PLAN.md) | 运行 / 协作 / 派活机制的设计方案。 |
| [`SYSTEM_GUIDE.html`](SYSTEM_GUIDE.html) | 系统总览说明（双击即用，零依赖）。 |

---

## 怎么用

**1. 开一家新公司（推荐走技能）**
- 加载 `create-company` 技能，按 `company-template/` 脚手架 + `PRINCIPLES.md` 规范拉起新公司目录。
- 或手动复制 `company-template/` 重命名为 `C00X-xxx`，再填 `company.md` / `AGENTS.md`。

**2. 接平台披露（以 WorkBuddy 为例）**
- 把技能实体放 `{层}/skills/<name>/SKILL.md`；
- 建 junction：`` New-Item -ItemType Junction -Path "{层}\.workbuddy\skills" -Target "{层}\skills" ``；
- **新开会话**后技能被平台渐进式披露（会话启动时扫描，当前会话不刷新）。

**3. 跑看板**
- `C001-AI自动化公司/` 下 `run_boards.bat`（Windows）/ `run_boards.sh`（Linux）生成 `dashboard.html` 等看板；`workbench/tasks/` 是唯一真相，看板是投影。

> 详细跨平台接入与子 Agent 派活机制见 [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md)；原则与红线见 [`PRINCIPLES.md`](PRINCIPLES.md)。

---

## 仓库约定

- **私有仓库**：本仓库为私有，含组织内部规范与示例数据，请勿外传。
- `.gitignore` 已排除 `.workbuddy/`、`node_modules`、`*.log`、`.env`、`.pem` 等，避免本地记忆 / 缓存 / 凭据误入库。
- 默认分支 `main`；提交信息用中文，聚焦「做了什么」。

---

*创建：2026-08-28 · 本仓库随 OPC 组织实践持续迭代*
