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

1. **复制母本**：整个 `company-template/` 复制为 `C00x-<名称>/`（含 .workbuddy 结构；junction 复制后会退化为实体目录，下一步重建）。**CHANGELOG.md 留在模板目录不复制**（它是模板自身的演进记录，各公司在 `company.md` 记「机制基线」版本号对照即可）；
2. **重建 junction**（关键，母版里是绝对路径指向模板自身；跨平台二选一）：
   ```powershell
   # Windows（junction，普通用户可建）：
   New-Item -ItemType Junction -Path "C00x-<名称>\.workbuddy\skills" -Target "<绝对路径>\C00x-<名称>\skills"
   New-Item -ItemType Junction -Path "C00x-<名称>\E0000\.workbuddy\skills" -Target "<绝对路径>\C00x-<名称>\E0000\skills"
   ```
   ```bash
   # macOS / Linux（symlink，注意用绝对路径）：
   ln -sfn "<绝对路径>/C00x-<名称>/skills" "C00x-<名称>/.workbuddy/skills"
   ln -sfn "<绝对路径>/C00x-<名称>/E0000/skills" "C00x-<名称>/E0000/.workbuddy/skills"
   ```
3. **改名落位**：总管目录若带【替换】占位符则按模板规范替换；company.md 的三处 `<本司ID>` 占位符（公司 ID / 目录结构说明书路径 / 目录树）全部替换为新 ID，并填公司名/业务域——**漏改会导致与新公司并列出现重复 ID**（`--check` 门禁会拦）；
4. **首跑验证**（机制代码在 OPC 根，公司目录无生成器）：
   ```
   python opc_resolver.py --sync-links     # 建稳定锚 companies/C00x（先建锚再自检）
   python opc_resolver.py --doctor         # init 自检门禁，全绿才进业务
   python opc_tickets.py --company C00x --selftest
   python opc_tickets.py --company C00x --check-structure
   python opc_tickets.py --company C00x && python opc_dashboards.py --company C00x
   ```
   （在 OPC 根执行；Windows 用 `python`，macOS/Linux 用 `python3`）全过 = 骨架可用；
5. **000 号总管入职**（见 §三）。

## 三、000 号总管入职动作（首次会话）

1. 读 `AGENTS.md`（我是总管）→ 读 `roster.md`（此刻只有我自己）→ 读 `目录结构说明书.md`（认清领地）；
2. 确认 junction 四件套有效（公司级 + 总管级）；
3. 跑一次 `run_boards once`（Windows 用 `run_boards.bat once`，macOS/Linux/Git-Bash 用 `./run_boards.sh once`，数据链路打通）；
4. 向用户报到：汇报公司骨架就绪 + 请用户给第一个需求/或先搭团队；
5. 后续团队/员工/项目全部按 `skills/dispatch-sop/SKILL.md`（新建员工 SOP、规章制度落实 SOP）+ `skills/mechanism-sop/SKILL.md`（落位决策树）推进，把公司运转起来。

## 二·五、命名空间接入（2026-08-28 新增，依据 opc-namespace-design.md）

> 机制：物理路径唯一真相源下沉到 `opc.toml`（OPC 根）。新建公司必须落地，否则后续改名 / 巡检无据可依。

1. **写公司段**：在 `opc.toml` 追加（继承 DEFAULT 骨架，仅写偏离字段）。**home 必须指向稳定锚，禁止直写真实目录名**（`opc-namespace-design.md` §2 铁律——直写目录名会让公司失去改名自愈保护）：
   ```toml
   [company.C00x]
   home = "companies/C00x"
   ```
   写完回 OPC 根跑一次 `scripts/link-company.ps1`（Windows）或 `scripts/link-company.sh`（macOS/Linux）建稳定锚（零参数，按 company.md 的公司 ID 自动发现真实目录）。
2. **引用用符号**：公司内 `AGENTS.md` / `SKILL.md` / 看板模板一律用 `opc://company:C00x/...` 逻辑符号，禁止裸写 `../` 或绝对路径 `E:\OPC\...`；
3. **首跑验证补一项**（接 §二.4）：建司三步跑完后，回到 OPC 根跑 `python opc_resolver.py --check`（链接器自检），全绿 = 命名空间自洽；
4. **总管入职补一项**（接 §三.1）：读 `opc-namespace-design.md` 认清机制——改名只动 `opc.toml` 一行、引用走 `opc://`、定期 `opc check-links` 巡检失效引用。

## 三·七、C002 时刻备忘（纪律技能换轨与配置预埋，2026-08-30 拍板）

> 现状（双份收口方案 C）：纪律类技能真相源在 C001 实例，经 `--sync-skills` 单向刷进模板；C002 开司仍是模板快照复制。**开第二家公司的那一刻**，执行以下换轨与预埋：

1. **纪律技能换轨为根层 junction（方案 B 落地）**：根层建 `org-skills/` 真相源 → C002 的 `skills/` 纪律技能改 junction 指向根层；C001 建议同轨（纪律跨公司成立，C001 无理由特殊——试新东西后同步回根层）；
2. **预授权清单首填**：`[delegation]` 第一次真实填写；schema 带「根层默认 + 每公司 override」（新公司授权应比存量公司更紧）；
3. **副署人分公司路由**：critical 通知通道设计带租户维度（各公司可不同副署人）；
4. **机械项**（机制已就绪，照做即可）：opc.toml 加公司段 → `--sync-links` 建锚 → 重启服务自动纳管 → 巡检/摘要自动带上新租户。

届时本技能问卷增加对应确认项：换轨确认 / 授权清单 / 通知路由。

## 四、红线

1. 不在模板里堆业务数据：company-template/ 永远保持"空骨架"（无实例工单/无实例员工/空 worklog）；模板升级 = 改模板，已建公司不自动跟进（各公司独立演进，重大升级由用户决定是否迁移）；
2. 建司问卷不跳步：未确认清单不动手；
3. 公司 ID 全局唯一，创建前必查重；
4. 老公司不受影响：本技能只管新公司；C001 等存量公司由其 000 号总管管理。

---
*创建：2026-08-28 · 依据 MECHANISM_PLAN 决策 #10 · 模板母本：../company-template/*
