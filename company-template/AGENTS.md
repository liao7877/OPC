# 公司级人设 · 平台自动加载入口

## 规范链
> 本层已含全部上层规范内容（沿链补读一次即可，按需渐进加载）；禁止在本文件内再直接引用上层规范——防重复（规范链铁律）。
- 上级规范：opc://org/agents


> **规范链实现口径**：平台原生只加载当前工作区的本文件；上级规范不是靠 agent 自觉手读，而由 OPC SessionStart 适配器按直属 `opc://` 声明自动注入（根→公司→团队→当前层之上的链，每层一次）。常驻 OPC 服务监听 roster/团队变动后被动重建声明；`--ensure-links` 只是初始化/手动兜底。
> 启动时：读取本入口 → 继续读取 `company.md`（公司总纲：实体/组织/任务区约定/工单系统入口）。
>
> 本体系人设/指令文件命名规范（2026-08-27 定稿）：
> - `AGENTS.md` = 人设唯一真相（平台自动加载：WorkBuddy ✅ / Codex ✅）
> - `CLAUDE.md` = Claude Code 导入适配（一行 `@AGENTS.md`）
> - 员工目录同理：`{员工}/AGENTS.md` + `{员工}/CLAUDE.md`

> **内容治理（P31，写/改文件前必读）**：新建或改动规范、原则、技能类文件 → 三问法归位 + 「精准高效、本质而非肤浅」（唯一真相 `opc://org/principles` P31）；记忆/日志/worklog/messages 等事实记录类不受此限，细节优先。

## 模板约定（建司前必读）
- 本模板所有 `<本司ID>` / `opc://company:<本司ID>` 为建司占位符：create-company 流程会统一替换为新公司 ID；漏改会被 OPC 根 `--check` 门禁拦下（公司 ID 全局唯一）。

## 启动门禁（init · 新建公司继承）
- 本模板新建的公司，其总管 `E0000/AGENTS.md` 启动流程**第 0 步为环境 init 自检**：在 OPC 根跑 `python opc_resolver.py --doctor`（Windows 用 `python`，macOS/Linux 用 `python3`），**全绿才开工**；不绿按 OPC 根 `README.md`「系统初始化」补齐（建稳定锚 `companies/C00x` / 装 pre-commit / 修失效引用）。
- 组织根治理与机制维护见 OPC 根 `AGENTS.md` 与 `opc-namespace-design.md`；命名空间/共享读取器铁律见 `PRINCIPLES.md`（P25/P26）。

## 推送与隐私剥离（新建公司继承 · 任何推送动作前必读）
- **红线 ⛔ 禁止 `git push origin`**：`origin` 是**公开**远程，而工作仓库 `main` **含私有内容**。pre-push 守卫（`opc.publicRemote=origin`）会拦下直推。
- **发布到公开仓库只走** `scripts/opc-publish.sh`（Windows PowerShell 用 `scripts/opc-publish.ps1`）：在临时克隆里按清单剥离后，force-push 干净 `main`。
- **备份走私有远程**：`main` 可直推私有远程（默认名 `backup`）做版本管理与异地备份——允许且应做。
- **清单维护**：私有路径点名写进仓库根 `.opc-private-paths.txt`（每行一相对路径，`*` 通配、`**` 跨目录，`#` 注释）。判据：**拿不准就加**。
- 唯一权威流程见 `opc://company:<本司ID>/skill/privacy-publish`（对外发布与隐私剥离）。
## 实践反馈留档（廖哥明令 2026-08-31）
- 凡用户实践反馈、问题上报及处置结论，处置前/后记入本公司 `knowledge/practice-log.md`（五段式：场景/问题/根因/解决/结果与价值；只增不删；同步其索引表）——复盘与对外展示取材于此，不许散失在会话里。员工/团队会话收到反馈转总管或机制维护者落档；跨公司普遍性结论按 P31 三问法上浮根层。
