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
├── PRINCIPLES.md           # 组织级设计原则（P1~P31：架构哲学/技能体系/工程实践/协作流程/红线/跨平台/内容治理）
├── MECHANISM_PLAN.md       # 机制方案（运行 / 协作 / 派活机制的设计与规划）
├── opc_resolver.py / opc_model.py / opc_tickets.py / opc_dashboards.py  # 命名空间运行时 + 机制层生成器（公司目录零机制代码）
├── companies/C001/          # 示例公司稳定锚（junction→真实公司目录）：完整跑通的 AI 自动化公司
│   ├── company.md          #   公司档案（定位 / 编制 / 边界）
│   ├── AGENTS.md / CLAUDE.md # 公司级角色与红线（跨平台兜底）
│   ├── E0000-AI员工-总管/ 等 E0000~E0002/  #   员工级工作区（决策 #17：ID-说明后缀命名，显示名登记于 roster 岗位列，各含 mydesk/worklog/skills）
│   ├── T001/     #   团队级工作区（含 teamboard / 团队技能）
│   ├── P0004-…/             #   项目目录（实体即目录，归属用字段声明；决策 #17 ID-说明后缀）
│   ├── workbench/           #   工单看板系统（tasks/ 为唯一真相，看板 HTML 为投影）
│   ├── skills/              #   公司级技能实体（junction 接入平台披露）
│   ├── dashboard.html                      # 公司看板（数据由 OPC 根生成器产出）
│   └── page-templates/      #   dashboard / mydesk / teamboard 模板
├── company-template/        # 新公司脚手架：复制即可开一家新公司
│   ├── company.md / workflow.md / 目录结构说明书.md
│   ├── E0000-AI员工-总管/    #   总管岗模板
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
| [`PRINCIPLES.md`](PRINCIPLES.md) | 组织级通用原则（P1~P31）。搭任何新东西前先通读。 |
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
   - **注册 OPC 服务自启**（决策 #18：常驻后台中枢——看板实时化/巡检/风险预警通知全由一个 headless 进程承载，`http://127.0.0.1:8765`）
     - 自启项写启动文件夹 `OPC-Service.vbs`（唯一的机器级副作用）：`--no-heartbeat` 跳过、删该文件即撤销。通知自带去重：只报新发现，已在待办里的不再弹。
3. **验证**：`python opc_resolver.py --doctor` 输出 `[ok] 初始化自检通过` 即可正常使用（doctor 自带自愈，会先打印 `[fix]` 行告诉你自动补了什么，再检查五项：Python 版本 / 稳定锚 / 钩子 / 命名空间 / 技能披露链接）。

```bash
# —— 新电脑全流程（三条）——
python3 opc_resolver.py --bootstrap     # 一键自举（含 OPC 服务自动注册+拉起；Windows 把 python3 换成 python）
python3 opc_resolver.py --doctor        # 终检，全绿才开工（含「OPC 服务在跑」探活）
run_boards.bat once                     # 可选：手动重建看板数据（bootstrap 已做过；macOS/Linux: ./run_boards.sh once）

# —— 各模块内置自测（不碰真实数据，排查问题时用）——
python3 opc_resolver.py --selftest && python3 opc_model.py --selftest
python3 opc_tickets.py --selftest && python3 opc_dashboards.py --selftest && python3 opc_patrol.py --selftest
python3 opc_sync.py --selftest && python3 integrations/feishu.py --selftest  # 在线协作内核 + 飞书 fake HTTP

# —— 看板不同步时（新电脑 / 目录搬家 / 多份 clone）——
python3 opc_resolver.py --doctor   # 服务探活含「根身份校验」：端口上是别的根的服务会点名 + 给处置命令；自启项指向旧目录则自动重写

# —— 公司目录改名/迁移后（引用自愈）——
python3 opc_resolver.py --ensure-links  # 零参数，按 company.md 的「公司 ID」扫描发现，幂等
```

**跨平台说明**
- 稳定锚：Windows 用 junction（`mklink /J`，普通用户可建）；macOS/Linux 用 symlink（`os.symlink`）。二者对浏览器/OS 透明，运行时层 HTML 双击即用。
- `.ps1` 脚本必须以 UTF-8 **带 BOM** 落盘（Windows PowerShell 5.1 对无 BOM 的 UTF-8 中文按 GBK 误读会语法错）。
- 巡检/通知/看板实时化的调度唯一来源在 `opc_service.py`（OPC 服务进程内线程，决策 #18）；开机自启走启动文件夹 `OPC-Service.vbs`，免管理员，删文件即卸载。
- ✅ Windows 已实跑全流程；macOS/Linux 分支逻辑正确，且已纳入 GitHub Actions 三平台矩阵持续验证（每次 push 自动跑 bootstrap 等价流程）。

---

## 怎么用

**0. 想派活（日常使用入口，小白从这开始）**：把 `companies/C001/E0000/`（每家公司各自的 E0000 总管目录）当工作区打开一个 agent 会话——总管的身份、职责、技能会自动加载，用自然语言说需求即可；系统的命名/看板/巡检/门禁维护由机制层与总管兜底，你不需要了解实现，也不需要手动维护任何文件。完整使用手册（怎么对话/机制地图/FAQ）：浏览器打开 [`USER_GUIDE.html`](USER_GUIDE.html)。

**1. 开一家新公司（推荐走技能）**
- 加载 `create-company` 技能，按 `company-template/` 脚手架 + `PRINCIPLES.md` 规范拉起新公司目录。
- 或手动复制 `company-template/` 重命名为 `C00X-xxx`，再填 `company.md` / `AGENTS.md`。
- 纪律类技能（ticket-system 等 7 项）真相源在实例：改完实例侧跑 `python opc_resolver.py --sync-skills` 单向刷进模板（C 方案），`--diff-template` 复核归一。

**2. 接平台披露（以 WorkBuddy 为例）**
- 把技能实体放 `{层}/skills/<name>/SKILL.md`；
- 建 junction：`` New-Item -ItemType Junction -Path "{层}\.workbuddy\skills" -Target "{层}\skills" ``（macOS/Linux 用 `ln -sfn`，或直接 `python opc_resolver.py --ensure-links` 全层幂等重建，`--doctor` 会校验）；
- 技能触发词索引：`python opc_model.py --sync-index` 一键重生成各层 `skills/INDEX.md`（生成物，勿手改；`--list-skills` 实时查看）；
- **新开会话**后技能被平台渐进式披露（会话启动时扫描，当前会话不刷新）。

**3. OPC 服务（bootstrap 自动搞定，你不需要知道这个进程）**——`--bootstrap` 第 ⑤ 步会**自动注册开机自启并当场拉起**，新 clone 跑完第 2 步即全部生效（决策 #18）。它是 OPC 的常驻后台中枢，承载一切「必须有进程才能实现」的机制：

| 能力 | 说明 |
|---|---|
| 看板实时化 | 看板从 `http://127.0.0.1:8765/{公司ID}/dashboard.html` 打开，「同步」按钮=即时重算数据，自动刷新秒级生效 |
| 巡检实时化 | 数据变动即巡检 + 周期兜底（阻塞解锁/认领缺口/脱期事务/升级信箱/号池水位/**工单逾期与停滞预警**…），异常写入 `workbench/patrol-log.md` |
| 主动通知 | 新发现实时弹系统通知（Windows/macOS/Linux 各自原生弹窗；`opc.toml [patrol].notify` 可关），每天 `09:00` 汇总重提未处理项 |
| 只读 API + 唯一写边界 | GET `/api/{公司ID}/tickets、/dashboard、/patrol、/ping` 供 agent 与外部服务查询；唯一带副作用的动作是 POST `/api/{公司ID}/sync`（重算看板数据，同站校验）——文件仍是唯一真相 |

- 进程=宿主、公司=租户：扫描 `opc.toml` 全部公司逐家装配，新公司自动纳管；`opc.toml [service]` 可配端口/巡检周期/每日摘要时间/通知通道。
- 跨平台自启：Windows=启动文件夹 `OPC-Service.vbs`（headless 无窗口）；macOS/Linux=crontab `@reboot` 标记块。删自启项即卸载；`python opc_service.py` 可前台手动跑（`--open` 顺带开浏览器）。

**3.1 在线协作 Level 3（飞书第一版）**
- 员工先加载公司级 `feishu-bitable` / `feishu-knowledge` Skill；执行通道优先采用已核验 CLI 或官方 HTTP API，MCP 仅作可选 fallback。
- 平台中立契约在 `opc_integrations.py`，reconcile/冲突/墓碑/事件账本在 `opc_sync.py`，飞书 HTTP 边界在 `integrations/feishu.py`；运行态写入公司根 `.opc-sync/`（已忽略，不入库）。
- 使用 `integrations/feishu.example.json` 复制出**仓库外的本机私有配置**后替换测试资源 ID，再运行 `python opc_sync.py --root <公司根> --config <私有配置.json> --reconcile`。示例文件不含凭据；真实 `FEISHU_APP_ID` / `FEISHU_APP_SECRET` 只放环境变量或系统凭据库。
- `python opc_sync.py --root <公司根> --status` 查看连接/绑定/shadow/冲突数量；`--project` 重建给看板和巡检读取的标准 projection。
- 第一版开放多维表格读取与字段白名单的单条有限更新、Wiki/DOCX 只读；批量、删除、表结构、权限和知识自动晋升默认关闭。

**4. 跑看板**
- 日常**无需手动**：OPC 服务已在 `http://127.0.0.1:8765/{公司ID}/dashboard.html` 托管看板并实时刷新。
- 离线应急可在公司根执行 `run_boards.bat`（Windows）/ `./run_boards.sh`（macOS/Linux/Git-Bash）：薄壳自动反查本公司 ID 并调 OPC 根 `opc_tickets.py` / `opc_dashboards.py` 一次性重算（已降级为手动应急工具，决策 #18）；`workbench/tasks/` 是唯一真相，看板是投影（数据文件不入库，删了重跑即重建）。

> 详细跨平台接入与子 Agent 派活机制见 [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md)；原则与红线见 [`PRINCIPLES.md`](PRINCIPLES.md)。

---

## 仓库约定

- **双远程模型**：`origin`（github.com/liao7877/OPC）是**公开**远程，供他人 fork，只收「剥离私有路径后」的干净 `main`；另设私有远程（默认名 `backup`，建议 Private）承载**含私有的全量** `main` = 版本管理 + 异地备份。详见下方「对外发布」。
- `.gitignore` 已排除 `.workbuddy/`、`node_modules`、`*.log`、`.env`、`.pem` 等；发布时再按 `.opc-private-paths.txt` 二次剥离，双重保险。
- 默认分支 `main`；提交信息用中文，聚焦「做了什么」。

---

## 对外发布（机制公开 / 私有备份）

本仓库采用「单仓双远程」模型：机制改进对外公开供 fork，私有内容只留在 `main` 与私有远程做版本管理与备份，绝不进公开分支。

- **公开远程 `origin`**（github.com/liao7877/OPC，Public）：只接收「按 `.opc-private-paths.txt` 剥离私有后」的干净 `main`。**禁止从工作仓库直推**——pre-push 守卫已启用（`opc.publicRemote=origin`）。
- **私有远程 `backup`**（已配置：本机另一块盘的裸仓库，与工作仓不同卷）：直推 `main` 全量（机制 + 私有）= 完整版本管理 + 备份。**允许且应当做**。具体路径只存本机 `.git/config`（不入库、不进公开仓），查地址 `git remote get-url backup`。

日常开发一切照旧：在 `main` 随便提交。备份与发布各一条命令：

```bash
# 备份：推私有远程（含私有，做版本管理）——允许直推
git push backup main

# 发布：自动剥离私有路径后推公开远程 origin —— 唯一合法途径
./scripts/opc-publish.sh        # Git Bash / macOS / Linux
.\scripts\opc-publish.ps1       # Windows PowerShell
```

- **私有清单**：`.opc-private-paths.txt` 控制「公开分支剥离什么」；引入隐私文件往里加一行即可，公开分支自动不含它，且不影响 `main` 的备份。完整操作（怎么加 / 怎么剥 / 怎么发）见 `opc://company:C001/skill/privacy-publish`。
- **红线**：pre-push 钩子禁止从工作仓库直接推公开远程，只允许经发布脚本（在临时克隆里剥离后推送）。
- ⚠️ 公开分支历史每次发布会重写，forkers 需偶尔 `git pull --rebase`（或重新 fork）。
- 一旦私有文件误推公开远程，立即用 `git filter-repo` scrub 历史并轮换任何泄露凭据。

---

*创建：2026-08-28 · 本仓库随 OPC 组织实践持续迭代*
