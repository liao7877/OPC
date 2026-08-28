# 多 Agent 平台接入规范（AGENT_ECOSYSTEM）

> **定位**：OPC 组织层的多 AI Agent 平台接入规范。记录每个平台（WorkBuddy / Claude Code / Codex 等）的技能机制、目录约定、渐进式披露方式与接入配置方法。
> **为什么存在**：同一组织跑多个 Agent，各平台技能机制不同、目录路径不同、披露方式不同。本文件沉淀"每个平台怎么接入"，避免每次重新摸索、防止配置漂移。
> **维护**：每实测/配置一个平台，补全一节并标注日期；不确定的内容**明确标注「待核实」**，不写未经验证的细节。
>
> 配套：`PRINCIPLES.md`（组织级设计原则，P6-P10 技能体系）。

---

## 一、各平台速查对照表

| 维度 | WorkBuddy | Claude Code | Codex |
|---|---|---|---|
| 技能·用户级目录 | `~/.workbuddy/skills/` | `~/.claude/skills/` | 待核实 |
| 技能·工作区级目录 | `{工作区}/.workbuddy/skills/` | `{项目}/.claude/skills/` | 待核实 |
| 技能声明文件 | `SKILL.md`（frontmatter: name/description） | `SKILL.md`（同构） | 待核实 |
| 角色/指令文件 | `AGENTS.md` | `CLAUDE.md` | `AGENTS.md`（`.codex/AGENTS.md`） |
| 渐进式披露 | ✅ 自动（扫描 frontmatter→列表→命中加载全文） | ✅ 类似（description 触发） | 待核实 |
| 任意目录技能接入 | junction 到工作区级目录 | junction 到 `{项目}/.claude/skills/` | 待核实 |

---

## 二、WorkBuddy（已实测 ✅ 2026-08-27）

### 2.1 技能两级结构
- **用户级（通用型）**：`~/.workbuddy/skills/<name>/SKILL.md` —— 所有项目可用
- **工作区级（项目专用）**：`{工作区}/.workbuddy/skills/<name>/SKILL.md` —— 仅该工作区
- 两级都被平台**自动扫描 + 渐进式披露**，无需自建索引。

### 2.2 渐进式披露机制（平台实现）
1. **披露层**：平台扫描每个 `SKILL.md` 的 frontmatter（`name` + `description`，description 含触发词）→ 生成技能列表（名称+一句话+位置），正文**不加载**
2. **判断层**：任务与触发词匹配 → 决定使用
3. **加载层**：命中才注入 `SKILL.md` 全文

收益：100+ 技能也不爆 token，未命中不读正文。

### 2.3 三级接入结构（公司 / 团队 / 员工）

渐进式披露是**工作区级概念**——哪个层级目录作为工作区打开，平台就扫它下面的 `.workbuddy/skills`。因此三级目录统一采用「**实体 + 引用**」结构：

```
companies/C001/                 ← 公司级工作区（稳定锚 junction→真实公司目录）
├── skills/ticket-system/         ← 实体（唯一出处，文件系统即真相）
└── .workbuddy/skills → junction→ skills/     ← 引用（平台披露通道）

T001/                  ← 团队级工作区
├── skills/team-dev-standards/    ← 实体
└── .workbuddy/skills → junction→ skills/

E0001/               ← 员工级工作区
├── skills/data-analysis-template/ ← 实体（私有技能）
└── .workbuddy/skills → junction→ skills/
```

**每层通用接入步骤**（已实测 ✅ 2026-08-27）：
```powershell
# 1) {层级}/skills/ 放技能实体（唯一出处）
#    技能目录结构：skills/<name>/SKILL.md（frontmatter 必须含 name + description 触发词）

# 2) 建 junction 接入平台（零复制、单份文件）
New-Item -ItemType Junction -Path "{层级}\.workbuddy\skills" -Target "{层级}\skills"
# 验证：ls 两条路径 inode 相同（同一文件）；Get-Item 显示 LinkType=Junction

# 3) 角色文件（AGENTS.md）写一行引用（跨平台兜底：Codex/Claude Code 不认 WorkBuddy 平台技能时直读）
#    - 工单协作（公司级技能）：../skills/ticket-system/SKILL.md —— …触发时执行

# 4) 验证：新开会话 → 技能列表出现该技能；用触发词下指令 → 自动加载全文
```

当前落点（**截至 2026-08-27 快照，以实体目录为准**——新增技能只需放 `skills/`，无需更新本清单）：公司级（ticket-system）+ 团队级（team-dev-standards）+ 员工级（E0000 dispatch-sop/status-logging、E0001 data-analysis-template、E0002 material-archive/project-plan-template/status-report）四层 junction 已全部建立。

### 2.4 关键注意点
- **技能列表在会话启动时扫描**：junction 建好后需**新会话/重启**才生效，当前会话不刷新
- **INDEX.md 是生成物，不是手工索引**：由 `python opc_model.py --sync-index` 从各 SKILL.md frontmatter（triggers/summary）自动生成（勿手改、不入库，2026-08-28 Q2 拍板）；平台披露管「触发」，INDEX 管「跨目录派活的发现」，互补不冲突
- 平台扫描仅认 `SKILL.md`（frontmatter 规范）；目录下其他文件不会被当技能
- 公司根 `skills/` 本质是**规范文件层**（PRINCIPLES P10），junction 让它同时获得平台能力，两不冲突

### 2.5 工作区与子 Agent 的技能发现语义（重要）

**平台渐进式披露是"工作区级"**：平台只扫**当前会话工作区**的 `.workbuddy/skills`（+ 用户级 `~/.workbuddy/skills`），与"这个 Agent 逻辑上代表谁"无关。

**子 Agent（派活/调用）默认继承父会话工作区**：总管在 `E0000/` 工作区开子 Agent 派活给 E0001 → 子 Agent 扫的是 `E0000/.workbuddy/skills`（总管级），**不会自动切到 E0001 目录披露 E0001 私有技能**。

两条正确通道：

| 通道 | 机制 | 适用 | 状态 |
|---|---|---|---|
| **A · 工作区级** | 子 Agent **显式以目标员工目录为工作区**运行 → 平台扫该目录 `.workbuddy/skills` → 其私有技能渐进式披露 | 需要目标员工平台技能自动触发 | ❌ **实测不可行**（2026-08-27）：子 Agent `cd` 跨命令不持久（工作区无法切换）；技能清单为**会话启动时静态注入**（来源=用户级/插件/市场/连接器），**不按 cwd 重新扫描**；实测 `Skill("data-analysis-template")` → `Can not find skill`，员工级技能对子 Agent 不可见 |
| **B · 跨目录兜底（推荐，即渐进式披露标准做法）** | 派活时**注入目标员工 `AGENTS.md`（披露层入口：一行索引入口 + 公司级技能直引）**，**绝不注入技能全文**；员工私有技能清单走 `opc://company:<id>/skill/<名称>`（触发词摘要，命中再 Read SKILL.md 全文；原 INDEX.md 披露层已废弃），子 Agent 按触发词判断命中后，才**按需 Read 对应 `SKILL.md` 全文**（加载层） | 跨工作区、任何场景 | ✅ 实测有效，token 最省（AGENTS.md + INDEX 均小文件，技能全文按需读） |

**实测细节（2026-08-27，两个子 Agent 对照）**：
- 对照组（默认工作区）：cwd = 父会话工作区（继承）；可见技能=用户级 8 个 + 插件/市场/连接器；**不含**工作区 `.workbuddy/skills` 下的 ticket-system（本会话启动时 junction 未建，印证"技能列表会话启动时扫描、需新会话生效"）
- 实验组（尝试切 E0001）：`cd E0001 && pwd` 单命令内有效，下一条命令 pwd 重置回根；技能清单不含 data-analysis-template 也不含 ticket-system；`Skill("data-analysis-template")` 不可见
- **推论**：公司级技能（如 ticket-system）在**新开会话**后主会话技能列表应含它（junction 生效），子 Agent 继承父会话清单后也可用——待新会话实测确认；员工级私有技能对跨目录子 Agent **永远不自动披露**，只能走 B 通道

**结论**：平台披露（junction）= 本工作区加速（且限新会话）；**跨目录派活 = AGENTS.md 触发词摘要（披露层）→ 按需读 SKILL.md（加载层），这就是子 Agent 场景的渐进式披露**。三级 junction 是"该目录被独立打开时"的披露通道，跨目录派活走引用通道，两者互补、缺一不可。

---

## 三、Claude Code（初稿，待核实 ⏳）

- 技能位置：`~/.claude/skills/`（个人）/ `{项目}/.claude/skills/`（项目）
- 技能声明：`SKILL.md`（frontmatter `name`/`description`，机制与 WorkBuddy 同构）
- 角色文件：`CLAUDE.md`（对应 AGENTS.md，项目级/用户级）
- 接入方式推测：与 WorkBuddy 同理，任意目录技能用 junction 指向项目级 skills 目录
- **待核实**：渐进式披露的具体触发/列表机制、junction 兼容性

---

## 四、Codex（初稿，待核实 ⏳）

- 指令文件：`AGENTS.md`（项目 `.codex/AGENTS.md`、全局 `~/.codex/AGENTS.md`）
- 技能支持：**待核实**（是否支持 SKILL.md 目录式技能、目录位置、披露机制）
- 接入方式：**待核实**（确认技能目录后，可同样用 junction 接入公司 skills/）

---

## 四点五、平台能力边界与系统适配（实测沉淀 2026-08-28）

**workbuddy 子代理限制**（影响三条链路，系统已按"异步文件协作为主"适配）：
1. 子代理不能再开子代理；2. 会话间不能通信（员工无法"呼叫"总管）；3. 不能自动新开同级会话。

**系统适配结论**（各平台统一走异步文件协作，实时通信平台只是加速）：

| 链路 | 适配方式 |
|---|---|
| 总管→员工派发 | **dispatch-sop 双模式**：A 注入派发（支持子代理的平台）/ B 台账派发（建单填 owner + 用户为员工开会话，员工启动自领） |
| 员工→总管上报 | **升级信箱**：工单 messages.md 追加 `[escalate: 原因] (日期)` + status 改 paused；生成器告警、看板 ⏫ 标记，总管巡检必处理，处理完删标记行 |
| 同员工多单并行 | 用户手动开多个会话窗（一会话一工位卡，机制照常生效）；无法自动新开同级会话 |

**跨平台 junction/symlink 速查**（三级结构通用，`{层}/skills` 为实体、`{层}/.workbuddy/skills` 为引用）：
- **Windows**（PowerShell）：`New-Item -ItemType Junction -Path "{层}\.workbuddy\skills" -Target "{层}\skills"`（junction 无需管理员）
- **macOS / Linux**：`ln -s "../../skills" "{层}/.workbuddy/skills"`（相对链接，随目录整体搬迁不断链）
- **入口脚本**：Windows 用 `run_boards.bat`；macOS/Linux/Git-Bash 用 `./run_boards.sh`（once/watch 等价）
- 生成器均为纯 Python 标准库，三平台无需改动

---

## 五、通用原则（跨平台）

1. **单一真相**（P2）：技能实体只放一处（公司根 `skills/`），各平台用 junction 引用，不复制
2. **渐进式披露优先**（P9）：能靠平台自动披露就不自建索引；手动索引仅用于平台无法扫描的场景
3. **AGENTS.md 引用行是跨平台兜底**：平台技能触发失效时（其他 agent / 平台未扫到），路径引用保证技能可发现
4. **配置可逆**（P24）：junction 删除即还原（`Remove-Item` junction 链接本身），不破坏源目录

---
*创建：2026-08-27 · WorkBuddy 部分为实测沉淀；Claude Code / Codex 部分待实操后补全（逐节标注日期）*
