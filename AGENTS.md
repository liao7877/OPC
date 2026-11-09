# OPC 组织级治理入口（AGENTS）

> **本文件是 OPC 组织根（仓库根）的 agent 行为入口**，面向在 OPC 根做机制 / 基础设施 / 跨公司治理工作的 agent（总管、机制维护者等）。
> 公司级 agent 入口在各公司 `AGENTS.md`（如 `C001-AI自动化公司/AGENTS.md`）；本文件管「组织根这一层」。

## 启动门禁（init · 任何 agent 开工前必过）
- 在 OPC 根跑 `python opc_resolver.py --doctor`（Windows 用 `python`，macOS/Linux 用 `python3`）：**全绿（输出「初始化自检通过」）才允许开工**。doctor **自带自愈**：缺锚/缺技能披露链接/缺钩子/缺看板数据会在检查前自动补齐（打印 `[fix]` 行）——新 clone 后跑一次 doctor 即完成自举。
- 仍不绿时跑 `python opc_resolver.py --bootstrap`（一键自举：链接+钩子+看板数据+技能索引+**OPC 服务自启项**），再跑 doctor 终检；人工补齐仅用于 bootstrap 也修不了的场景（如权限）。
- 这相当于函数 `init()`：命名空间符号化 + 稳定锚物理入口 + 提交门禁是系统正常跑的硬前置，未达标不许进入业务。
- 改名公司目录后，重跑 `python opc_resolver.py --ensure-links`（或 scripts/link-company.{ps1,sh}）即可自动重指向，无需改任何其他文件。

## 组织级铁律（与 PRINCIPLES 一致，速记）
- **命名空间**：物理路径唯一真相源在 `opc.toml`；跨文件引用统一 `opc://company:<cid>/...`（文档层，resolver 校验）或 `companies/<cid>/` 稳定锚（运行时层）。禁止裸写 `../` 或绝对路径（PRINCIPLES P26）。
- **机制改动波及面**：C001 实例 + 其总管(E0000) + company-template 新建模板 + 根文档，四处须同步。
- **共享读取器**：实体卡 frontmatter 读取统一走 OPC 根 `opc_model.py::parse_frontmatter`（PRINCIPLES P25）。
- **提交门禁**：提交前 `opc --check` 由 pre-commit 自动跑，拦截失效引用 / 锚点漂移。
- **跨平台三系统（P30，廖哥明令）**：一切修改与机制设计必须 Windows/macOS/Linux 三系统可运行；平台差异收口在机制层 `sys.platform` 分支，新增行为必须进 selftest 过 CI 三平台矩阵。
- **内容治理（P31，廖哥明令）**：总管/员工/会话新建或改动规范、原则、技能类文件，一律遵守三问法归位（普遍→根层 / 公司政策→公司层正文+他层引用 / 单角色→员工技能）与「精准高效、本质而非肤浅」表达总纲——每句话要么改变行为要么帮助定位；**例外**：记忆/日志/worklog/messages 等事实记录类内容以保证信息细节不丢失为先，不受精简约束。
- **对外讲解同步（P32，廖哥明令）**：机制更新/改动/新增与好设计，同一提交内同步 SYSTEM_GUIDE.html 机制亮点章节——外人看得懂亮点，好想法留档不遗忘。
- **规范链**：根 AGENTS 是所有公司的上级规范；公司/团队/员工 AGENTS 只声明**直属**上级 `opc://`，不重复直挂更上层。唯一真相是 roster「团队」列；常驻 OPC 服务监听组织数据变动后被动重建链，`--ensure-links` 是手动/初始化兜底；会话钩子自动注入当前层以上的链，当前层由平台原生加载。
- **代码路径依赖（廖哥明令 2026-08-31）**：脚本/代码禁止硬编码组织路径，统一运行时走 resolver（`--resolve` 或 import `opc_resolver`），改名即免疫；文档引用遵守 P26 散文口径。

## 对外发布与隐私剥离（单仓双远程 · 任何推送动作前必读）
- **红线 ⛔ 禁止 `git push origin`**：`origin`（github.com/liao7877/OPC）是**公开**远程，而工作仓库 `main` **含私有内容**。pre-push 守卫已启用（`opc.publicRemote=origin`），直推会被拦下。
- **发布到公开仓库只走** `scripts/opc-publish.sh`（Windows PowerShell 用 `scripts/opc-publish.ps1`）：默认在临时克隆过滤并校验全部历史；显式 --push 才发布已提交的干净 `main` 到 `origin`。
- **备份边界**：已确认私有的远程须登记 opc.privateRemote 才可推全量；未配置时使用仓库外的本地版本化备份并校验恢复，不得声称已有异地备份。
- **清单维护**：私有路径点名写进仓库根 `.opc-private-paths.txt`（每行一相对路径，`*` 通配、`**` 跨目录，`#` 注释）。判据：**拿不准就加**——多剥无害，漏剥是事故。
- 唯一权威流程见 `opc://company:C001/skill/privacy-publish`（对外发布与隐私剥离）。机制改动波及面四处须同步：C001 实例 + E0000 总管 + company-template + 本文件。

## 关键文件
| 文件 | 作用 |
|---|---|
| [`README.md`](README.md) | 系统初始化 / 使用说明（开工前先读「系统初始化」） |
| [`opc-namespace-design.md`](opc-namespace-design.md) | 命名空间机制设计规范（动机 / URI / resolver / 跨平台 / 落地） |
| [`PRINCIPLES.md`](PRINCIPLES.md) | 组织级设计原则 P1~P31 |
| [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md) | 多 Agent 平台接入规范 |
| `opc_resolver.py` / `opc_model.py` / `opc.toml` | 命名空间运行时（DI 容器 / 共享读取器 / 配置） |
| `opc_tickets.py` / `opc_dashboards.py` | 看板机制层生成器（公司目录零机制代码，run_boards 薄壳调用） |
| `opc_service.py` | **OPC 服务**（决策 #18：组织级常驻后台中枢，升级自 opc_board_server.py）：进程=宿主、公司=租户（扫描 opc.toml 全公司自动装载）；承载看板实时化（`同步`按钮直算 + 秒级监听）、巡检（含工单逾期/停滞预警）、实时通知与每日摘要、只读 API（`/api/{CID}/tickets|dashboard|patrol`，唯一写边界=POST `/sync` 同站校验）；`--register` 挂开机自启；看板从 `http://127.0.0.1:8765/{CID}/dashboard.html` 打开 |

## 运行边界与验收
- 缺席私有实体须在 opc.toml 的 private_entities 显式声明和说明；保留历史，显示未挂载，不生成虚假交付物，不放过普通断链。
- 手动、监听、周期重算共用公司生成锁；哈希快照捕获删除及快速修改。源数据在生成中变化时保留待重试状态，不发布不一致批次。
- 同步接口分别报告本地生成与外部集成：partial / integration_ok 不可被解释为全量成功。
- HTTP 只服务看板白名单与只读 API，校验 loopback Host；原始文件从本地路径访问。macOS 用 launchd、Windows 用启动文件夹、Linux 用有超时的 crontab。

初始化验收：bootstrap 保留生成器、自启注册与服务启动的真实失败并返回非零；自启失败仍独立尝试即时启动。公开发布使用远端 main 的已观测版本作为 force-with-lease 条件，远端变动则拒绝覆盖。

- CI 环境的 doctor/bootstrap 不改机器自启项、不拉起服务；离线 bootstrap 使用 --no-heartbeat，终检同样保持此边界。模板比较排除 .opc-*.lock 运行锁，依赖锁文件仍参与比较。

- 核心 CLI 输出编码统一交给 opc_runtime.configure_output；跨平台回归须覆盖 ANSI 管道下的真实子进程。
