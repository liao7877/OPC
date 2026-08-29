---
name: dispatch-sop
description: 总管接到用户需求后，按标准流程拆解、建工单、选人派发的操作手册。触发词：派任务、派发、分配、接需求、调度、建工单、创建任务。
summary: 总管接到用户需求后，按标准流程拆解、建工单、选人派发的操作手册。
triggers: [派任务, 派发, 分配, 接需求, 调度, 建工单, 创建任务]
---

# 派发工单 SOP（dispatch-sop）

> 用途：总管把用户需求变成可执行、可追踪的工单并派给对的员工。
> 级别：E0000 私有技能。

## 流程
1. **接需求**：听清总目标，不明确就走需求澄清（`skills/demand-clarify/SKILL.md`，一问一答 + PRD 存档，不瞎猜）
2. **拆任务**：多工单需求按 `skills/ticket-split/SKILL.md` 拆分（三原则 + 四项自检 + 父单闭环）；**编号先查 `workbench/task-index.md` 台账**（避免重号）
3. **建工单**：`python ../../../../../opc_tickets.py --company C001 --new TSKxxx 标题 [--owner E0001] [--project P0001]`（自动生成 `workbench/tasks/TSKxxx-标题/task.md` 模板；拆分子单补 `parent`/`blocked_by`/`inputs` 字段）
4. **登记**：在 `workbench/task-index.md` 台账追加一行（ID / 标题 / 承接 / 创建时间 / 父单）
5. **选人**：查 roster.md，按岗位匹配 + 负荷均衡（mydesk 统计）选员工；无命中则人工判断
6. **派发（双模式，按平台能力选择）**：
   - **模式 A · 注入派发**（平台支持开子代理时：zcode/claude 等）：向员工子代理注入 AGENTS.md + workflow.md + memory/（均小文件），交代任务。
     - **⚠️ 禁止注入员工技能全文**：员工 AGENTS.md 里的技能引用行即"披露层"（触发词摘要+路径），**子 Agent 按触发词判断命中后，才按需 Read 对应 `SKILL.md` 全文**——这是跨目录派活的渐进式披露，绝不把员工 `skills/` 下所有技能文件塞进上下文（浪费 token）
   - **模式 B · 台账派发**（平台不支持子代理/多会话时：workbuddy 等）：只做①建单时填好 owner（工单出生即有主）→ ②登记台账 → ③**告知用户"已派给 E00xx，请为其开会话（或等其下次启动自领）"**。员工会话启动时按 ticket-system §1.5 拉通道自动认领，**不需要注入**。
   - 两模式产物完全一致（tasks/ 文件），员工侧无感知差异。
7. **监控**：看 `workbench/kanban.html`（数据从 tasks/ 自动同步 ≤3 秒）；**升级信箱（⏫ 标记）优先处理**：员工 [escalate: …] 请求 = 在该工单处理（答复/转派/解锁），处理完删除标记行；异常与中转由总管处理
8. **团队公告维护**：新项目立项、工单体系变更、重要节点时，总管在对应团队目录 `notices.md` 追加一条公告（--- 块式：title/date/author+正文），团队看板自动呈现
9. **开工保活（兜底）**：每次会话开工先跑一次 `run_boards.bat once`（Windows）或 `./run_boards.sh once`（macOS/Linux/Git-Bash；在公司根执行；顺序刷新工单+三级看板数据，约2秒）；页面出现"数据已陈旧"黄条 = 生成器没在跑，同样跑它即可

## 派单预取（分支预测）
- 痛点：员工开工先反问总管要上下文，一来一回浪费一轮会话
- 药方：派单指令里**预写下游大概率要读的引用**——工单号、相关项目、参考文档的 `opc://` 链接，员工接单免一次来回问询，直接开工

## 编号纪律与预留号池（2026-08-28，双入口决策 #12）
- TSK 编号**只由总管主会话分配**；多子代理并发时子代理只领已建好的单、不建单
- **号池**：task-index.md 尾部维护「预留号池」段（约 20 个连续号，标记 reserved-for-claim）——供**用户直派员工**（入口 B）时员工自助取号（先占台账后建单，防撞号）
- **号池水位**：每次会话启动查一次，剩余 <5 个立即补号段（在台账登记"补号至 TSKxxxxx"）
- 巡检时核对：号池取用的号是否都已建成工单（取号未建 = 员工领号未动工，跟进）；台账占用与实际工单目录对齐

## 铁律
- 只调度不代劳：具体活派给对应员工（**自营例外**：公司运转/机制/制度/运维类可自营——工位卡标 identity: 执行、照常上板、验收=用户或指定员工，不自审自批）
- 派发必注入：人设 + 工作流 + 记忆，缺一不可
- 编号必查台账：分配前查重，避免重号
- 状态必留痕：员工改 `task.md` 即留痕（看板自动呈现），总管不重复维护状态
- **机制落位走 mechanism-sop**：涉及改目录/技能/制度/字段的构想，一律先加载 `skills/mechanism-sop/SKILL.md` 按决策树落位（清单→过目→备份→执行→验证），不拍脑袋改文件

## 员工培训（不人肉）
- 工单系统使用规范 = 公司级技能 `opc://company:C001/skill/ticket-system`（自解释、自包含）
- 新员工入职：确认其 AGENTS.md 已引用该技能即可，无需逐人培训

## 规章制度落实 SOP（2026-08-27 定稿）
> 触发：用户说"把 XX 规章制度落实一下 / 按规章管理员工 / 改规范"。
> **规章原文件统一放 `../../../../companies/C001/公司规章制度/`**（公司级/团队级/个体级内容都在这，**不复制到团队/员工目录**，单一真相）；**格式多样（word/excel/pdf/md 等），不做预处理，由总管自行解析**。

1. **接指令**：确认要落实的规章（文件名或主题；不明确就问）
2. **读规章**：到 `../../../../companies/C001/公司规章制度/` 定位文件，解析内容（任意格式，总管负责转换理解）
3. **按条款判范围**：**逐条判定**（一份混合规章可拆多条分别落实）——
   - 公司条款（"所有员工/全员"）→ 改**所有员工** AGENTS.md 及相关 skills
   - 团队条款（点名"T001 团队"）→ 改 **team.md + 团队 skills + 该团队所有成员**
   - 个体条款（点名 E0xx）→ 仅改该员工
   - 条款要求建/改 skill → 按员工模板 `skills/_template/SKILL.md` 规范执行（frontmatter 写全 name/description/triggers/summary，INDEX 由 --sync-index 生成）
   - **⚠️ 先核对"已实现"**：条款要求的机制若已由现有目录结构/技能/文档实现（如工单规范已由 ticket-system 技能 + tasks/ 结构覆盖）→ **不改文件，仅确认引用行存在**（员工 AGENTS.md / team.md 是否已引用对应技能或规章）——避免重复落地、制造双份真相（P2）
4. **出改动清单**：列出"将改哪些文件、每处怎么改（新增/修改/删除）"，**先给用户过目确认**（P24 零风险可逆）
5. **备份**：确认后，被改文件先复制 `.bak`（同名备份，可回滚）
6. **执行**：按清单改文件（AGENTS.md / team.md / skills 等；INDEX.md 属生成物，由 --sync-index 重生成）；**落实后在被改的 team.md / 员工 AGENTS.md 留「适用规章」引用行**（只引用不复制）：`适用规章：../../../../companies/C001/公司规章制度/XX.md`
7. **汇报**：改了哪些文件、备份位置、如何回滚

## 缓存失效纪律
- 痛点：改了技能「没人生效」，排查半天发现是会话缓存——运行中的会话用的是**启动时的快照**（平台渐进式披露的已知行为）
- 药方：SKILL.md / INDEX.md / AGENTS.md 变更后，必须提醒「相关角色**重开会话**生效」；此条列入收尾检查

## 新建员工 SOP（2026-08-27 定稿，必须按新标准，禁止老结构）
> 模板：`opc://company:C001/templates/employee-template/`（标准骨架，含全部机制文件与占位符）。

1. **编号**：查 roster.md，取下一个编号（如 E0003），岗位名按职责定 → 目录 `../E000x-AI员工-<岗位名>/`（目录自解释：{编号}-{岗位}）
2. **复制模板**：把 `opc://company:C001/templates/employee-template/` 整体复制为 `../E000x-AI员工-<岗位名>/`（含 AGENTS.md / CLAUDE.md / workflow.md / memory/ / workspace/ / skills/ / .workbuddy/）
3. **改人设**：编辑 AGENTS.md —— 替换全部【替换】占位符（编号/岗位名/职责/红线）；CLAUDE.md 保持一行 `@AGENTS.md`
4. **建私有技能**：按需复制 `skills/_template/SKILL.md` 为 `<技能>/SKILL.md`，填 frontmatter（name + description + **triggers** + **summary**，技能元数据唯一真相在此）；建好即自动可被 `opc://company:<id>/skill/<名称>` 解析；跑 `python opc_model.py --sync-index` 重生成该员工 `skills/INDEX.md`（生成物，「登记」动作消失）
5. **建 junction（关键，模板复制不会带过来）**：
   ```powershell
   New-Item -ItemType Junction -Path "E000x-AI员工-<岗位名>/.workbuddy/skills" -Target "E000x-AI员工-<岗位名>/skills"
   ```
   macOS/Linux：`ln -sfn "$(pwd)/E000x-AI员工-<岗位名>/skills" "E000x-AI员工-<岗位名>/.workbuddy/skills"`
   或（推荐，全层幂等重建）：回 OPC 根跑 `python opc_resolver.py --ensure-links`
   验证：`ls -i .workbuddy/skills/<技能>/SKILL.md skills/<技能>/SKILL.md` inode 相同
6. **登记 roster.md**：追加一行（ID / 岗位 / 目录路径）
7. **验证三件套**：AGENTS.md（WorkBuddy/Codex 自动加载，技能引用走 `opc://company:<id>/skill/<名称>`）、CLAUDE.md（Claude Code 一行导入）、.workbuddy/skills junction（平台披露通道）— 原"公司级 skills/INDEX.md"披露层已废弃（公司级技能走平台披露），员工私有技能的 skills/INDEX.md **保留**为披露索引（生成物，--sync-index 重生成），四件套 = 三件套 + 员工私有索引

> ⚠️ 新建员工**一律按本 SOP 新标准**（AGENTS.md/CLAUDE.md/INDEX(生成物)/junction）；老结构（单数 AGENT.md、无索引、无 junction）**已废弃**，不得沿用。

## 员工改名 SOP（2026-08-29 决策 #17：改名零改动，一条命令）
> 目录名保留自解释（`E0001-AI员工-售前工程师`），改名的一切机械动作由命令包办——引用层（opc:// / 实体 ID）本就免疫改名（ID 前缀扫描发现）。

1. **一条命令**（OPC 根）：`python opc_resolver.py --rename-entity E0001 新岗位说明`
   自动完成：git mv 改目录名 → 重建稳定锚/技能披露链接 → 同步 roster「路径」列与「岗位」列口径 → 重跑看板数据 → 全文旧目录名按 ID 映射自动改写 → 门禁终检
   预演加 `--dry-run`。手动在资源管理器里改了目录名？跑 `python opc_resolver.py --heal-entity-refs` 同样一键自愈（OPC 服务巡检周期兜底时也会自动重建断链）
2. **改人设**（命令管不到的内容）：该员工 AGENTS.md（标题/岗位字段/职责描述）+ workflow.md 标题；按需落新私有技能
3. **留痕**：worklog 记一条 + task messages 留痕（机制/结构类工作不可免记）

> 历史留痕区（worklog/memory/archive）里的旧目录名**不被改写**——旧名是历史事实（只增不删）。
> 反模式（已废弃）：删旧目录新建目录、逐文件搜替换全名（2026-08-29 E0001 改名实际发生的全量手术）。
