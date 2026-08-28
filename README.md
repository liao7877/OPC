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
├── PRINCIPLES.md           # 组织级设计原则（P1~P26：架构哲学/技能体系/工程实践/协作流程/红线）
├── MECHANISM_PLAN.md       # 机制方案（运行 / 协作 / 派活机制的设计与规划）
├── opc_resolver.py / opc_model.py / opc_tickets.py / opc_dashboards.py  # 命名空间运行时 + 机制层生成器（公司目录零机制代码）
├── companies/C001/          # 示例公司稳定锚（junction→真实公司目录）：完整跑通的 AI 自动化公司
│   ├── company.md          #   公司档案（定位 / 编制 / 边界）
│   ├── AGENTS.md / CLAUDE.md # 公司级角色与红线（跨平台兜底）
│   ├── E0000~E0002/        #   员工级工作区（总管 / 售前工程师 / 项目经理）；目录名 ID-only，显示名登记于 roster 岗位列，各含 mydesk/worklog/skills
│   ├── T001/     #   团队级工作区（含 teamboard / 团队技能）
│   ├── P0001~P0004/         #   项目目录（实体即目录，归属用字段声明）
│   ├── workbench/           #   工单看板系统（tasks/ 为唯一真相，看板 HTML 为投影）
│   ├── skills/              #   公司级技能实体（junction 接入平台披露）
│   ├── dashboard.html                      # 公司看板（数据由 OPC 根生成器产出）
│   └── page-templates/      #   dashboard / mydesk / teamboard 模板
├── company-template/        # 新公司脚手架：复制即可开一家新公司
│   ├── company.md / workflow.md / 目录结构说明书.md
│   ├── E0000/    #   总管岗模板
│   └── skills/ / templates/ / workbench/ / page-templates/
└── create-company/
    └── SKILL.md             # 「开公司」技能：按模板 + 规范一键拉起新公司
```

---

## 核心文档

| 文件 | 作用 |
|---|---|
| [`USER_GUIDE.html`](USER_GUIDE.html) | **用户手册**（浏览器打开）：怎么派活、怎么和员工对话、机制地图、命令速查、常见情况处置。 |
| [`SYSTEM_GUIDE.html`](SYSTEM_GUIDE.html) | 系统总览（浏览器打开）：对外讲解 OPC 的理念、架构与机制亮点。 |
| [`PRINCIPLES.md`](PRINCIPLES.md) | 组织级通用原则（P1~P26）。搭任何新东西前先通读。 |
| [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md) | 多 Agent 平台接入规范：各平台技能目录、渐进式披露、junction 接法。 |
| [`MECHANISM_PLAN.md`](MECHANISM_PLAN.md) | 运行 / 协作 / 派活机制的设计方案与评审拍板记录。 |

---

## 系统初始化（新电脑三步，约 2 分钟）

> **这条流水线已高度自举**：第 2 步一条命令自动完成全部「事先准备」，不依赖你懂机制。任何 AI agent 开工前必须先跑 `--doctor`（自带自愈，见下），全绿才进业务。机制详情见 [`opc-namespace-design.md`](opc-namespace-design.md) §5 跨平台。

1. **装 Python ≥ 3.11**（唯一硬前提，resolver 依赖标准库 `tomllib`）：Windows 用 `python --version` 验证，macOS/Linux 用 `python3 --version`（下文按你的平台替换 `python3`/`python`）。
2. **一键自举**：在 OPC 根执行 `python opc_resolver.py --bootstrap`，它会自动完成——
   - 重建稳定锚 `companies/<cid>` 与各层技能披露链接（OS 级链接不入库，clone 后必缺）；
   - 安装 pre-commit 门禁钩子（提交前拦截失效引用）；
   - 重建看板数据与技能索引（产物不入库，clone 后必缺）；
   - **注册公司心跳**（每 30 分钟自动巡检 + 数据自愈 + 异常系统通知；Windows 写计划任务、macOS/Linux 写 crontab，任务名 `OPC-Patrol-<公司ID>`，间隔可改：`--heartbeat-every 15`）
     - 心跳是唯一的机器级副作用：`--no-heartbeat` 跳过、`--heartbeat-every 60` 改间隔、`python opc_patrol.py --unregister-heartbeat --company C001` 撤销。通知自带去重：只报新发现，已在待办里的不再弹。
3. **验证**：`python opc_resolver.py --doctor` 输出 `[ok] 初始化自检通过` 即可正常使用（doctor 自带自愈，会先打印 `[fix]` 行告诉你自动补了什么，再检查五项：Python 版本 / 稳定锚 / 钩子 / 命名空间 / 技能披露链接）。

```bash
# —— 新电脑全流程（三条）——
python3 opc_resolver.py --bootstrap     # 一键自举（含心跳；Windows 把 python3 换成 python）
python3 opc_resolver.py --doctor        # 终检，全绿才开工
run_boards.bat once                     # 可选：手动重建看板数据（bootstrap 已做过；macOS/Linux: ./run_boards.sh once）

# —— 各模块内置自测（不碰真实数据，排查问题时用）——
python3 opc_resolver.py --selftest && python3 opc_model.py --selftest
python3 opc_tickets.py --selftest && python3 opc_dashboards.py --selftest && python3 opc_patrol.py --selftest

# —— 公司目录改名/迁移后（引用自愈）——
python3 opc_resolver.py --ensure-links  # 零参数，按 company.md 的「公司 ID」扫描发现，幂等
```

**跨平台说明**
- 稳定锚：Windows 用 junction（`mklink /J`，普通用户可建）；macOS/Linux 用 symlink（`os.symlink`）。二者对浏览器/OS 透明，运行时层 HTML 双击即用。
- `.ps1` 脚本必须以 UTF-8 **带 BOM** 落盘（Windows PowerShell 5.1 对无 BOM 的 UTF-8 中文按 GBK 误读会语法错）。
- 心跳定时逻辑唯一来源在 `opc_patrol.py`（`register-patrol.ps1/.sh` 只是薄壳）；Windows 计划任务为当前用户级，无需管理员。
- ✅ Windows 已实跑全流程；macOS/Linux 分支逻辑正确，且已纳入 GitHub Actions 三平台矩阵持续验证（每次 push 自动跑 bootstrap 等价流程）。

---

## 怎么用

**0. 想派活（日常使用入口，小白从这开始）**：把 `companies/C001/E0000/`（每家公司各自的 E0000 总管目录）当工作区打开一个 agent 会话——总管的身份、职责、技能会自动加载，用自然语言说需求即可；系统的命名/看板/巡检/门禁维护由机制层与总管兜底，你不需要了解实现，也不需要手动维护任何文件。完整使用手册（怎么对话/机制地图/FAQ）：浏览器打开 [`USER_GUIDE.html`](USER_GUIDE.html)。

**1. 开一家新公司（推荐走技能）**
- 加载 `create-company` 技能，按 `company-template/` 脚手架 + `PRINCIPLES.md` 规范拉起新公司目录。
- 或手动复制 `company-template/` 重命名为 `C00X-xxx`，再填 `company.md` / `AGENTS.md`。

**2. 接平台披露（以 WorkBuddy 为例）**
- 把技能实体放 `{层}/skills/<name>/SKILL.md`；
- 建 junction：`` New-Item -ItemType Junction -Path "{层}\.workbuddy\skills" -Target "{层}\skills" ``（macOS/Linux 用 `ln -sfn`，或直接 `python opc_resolver.py --ensure-links` 全层幂等重建，`--doctor` 会校验）；
- 技能触发词索引：`python opc_model.py --sync-index` 一键重生成各层 `skills/INDEX.md`（生成物，勿手改；`--list-skills` 实时查看）；
- **新开会话**后技能被平台渐进式披露（会话启动时扫描，当前会话不刷新）。

**3. 挂公司心跳（推荐，一次性）**——让公司不依赖你的注意力自己转：每天自动巡检（阻塞解锁/认领缺口/脱期事务/升级信箱/号池水位/僵尸工位卡…），异常写入 `workbench/patrol-log.md` 并**弹系统通知**（A+ 报警通道，`opc.toml [patrol].notify` 可关），总管每会话按同一份清单处置：
```bash
# 公司根执行（自动反查公司 ID）：
powershell -ExecutionPolicy Bypass -File register-patrol.ps1   # Windows 计划任务
# 或 macOS/Linux crontab：
0 9 * * * cd /path/to/OPC && python3 opc_patrol.py --company C001 --quiet
```

**4. 跑看板**
- 在公司根执行 `run_boards.bat`（Windows）/ `./run_boards.sh`（macOS/Linux/Git-Bash）：薄壳自动反查本公司 ID 并调 OPC 根 `opc_tickets.py` / `opc_dashboards.py` 生成数据；`workbench/tasks/` 是唯一真相，看板是投影（数据文件不入库，删了重跑即重建）。

> 详细跨平台接入与子 Agent 派活机制见 [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md)；原则与红线见 [`PRINCIPLES.md`](PRINCIPLES.md)。

---

## 仓库约定

- **私有仓库**：本仓库为私有，含组织内部规范与示例数据，请勿外传。
- `.gitignore` 已排除 `.workbuddy/`、`node_modules`、`*.log`、`.env`、`.pem` 等，避免本地记忆 / 缓存 / 凭据误入库。
- 默认分支 `main`；提交信息用中文，聚焦「做了什么」。

---

*创建：2026-08-28 · 本仓库随 OPC 组织实践持续迭代*
