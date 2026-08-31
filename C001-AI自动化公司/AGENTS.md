# 公司级人设 · 平台自动加载入口

> **本文件是平台（WorkBuddy / Codex）自动加载的入口**，公司级总纲与全局规范见 `company.md`。
> 启动时：读取本入口 → 继续读取 `company.md`（公司总纲：实体/组织/任务区约定/工单系统入口）。
>
> 本体系人设/指令文件命名规范（2026-08-27 定稿）：
> - `AGENTS.md` = 人设唯一真相（平台自动加载：WorkBuddy ✅ / Codex ✅）
> - `CLAUDE.md` = Claude Code 导入适配（一行 `@AGENTS.md`）
> - 员工目录同理：`{员工}/AGENTS.md` + `{员工}/CLAUDE.md`

> **内容治理（P31，写/改文件前必读）**：新建或改动规范、原则、技能类文件 → 三问法归位 + 「精准高效、本质而非肤浅」（唯一真相 `opc://org/principles` P31）；记忆/日志/worklog/messages 等事实记录类不受此限，细节优先。

## 推送与隐私剥离（命中即读技能）
- 任何**推送 / 发布 / 上传 GitHub / fork / 剥离隐私 / 私有清单**动作，先读 `opc://company:C001/skill/privacy-publish`（唯一权威）。
- 红线速记：`origin` 是**公开**远程，**禁止 `git push origin`**（pre-push 守卫会拦）；发布走 `scripts/opc-publish.sh`（Windows 用 `.ps1`），备份走私有远程（如 `backup`）可直推。
- 私有路径点名加进仓库根 `.opc-private-paths.txt`，判据：**拿不准就加**（多剥无害，漏剥是事故）。
## 实践反馈留档（廖哥明令 2026-08-31）
- 凡用户实践反馈、问题上报及处置结论，处置前/后记入本公司 `knowledge/practice-log.md`（五段式：场景/问题/根因/解决/结果与价值；只增不删；同步其索引表）——复盘与对外展示取材于此，不许散失在会话里。员工/团队会话收到反馈转总管或机制维护者落档；跨公司普遍性结论按 P31 三问法上浮根层。
