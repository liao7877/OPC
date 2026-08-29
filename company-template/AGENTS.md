# 公司级人设 · 平台自动加载入口

> **本文件是平台（WorkBuddy / Codex）自动加载的入口**，公司级总纲与全局规范见 `company.md`。
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
