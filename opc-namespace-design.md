# OPC 命名空间设计规范（opc-namespace-design.md）

> **定位**：PRINCIPLES 的补充约定，是 P2（单一真相）/ P3（高内聚低耦合）在**「架构常量层」**的具体落地。
> **创建**：2026-08-28 · **依据**：架构评审（依赖倒置视角）+ PoC 验证。
> **关联文件**：`opc.toml`（全局 manifest）、`opc_resolver.py`（解析器/DI 容器）、`scripts/link-company.*`（稳定锚同步）、`scripts/watch-companies.py`（可选监听守护）、`opc_tickets.py` / `opc_dashboards.py`（机制层生成器，2026-08-28 上提 OPC 根）。

---

## 0. 动机（本质问题）

把 OPC 当作一门**语言**来看：约定文档 + 目录树 + skill 是它的「源码」，agent 是人肉「运行时」。
散落的具体路径名、目录名 = **裸写内存地址**（最低层细节），所有 consumer 直接 import，违反**依赖倒置 DIP**。

**本质毛病（设计模式语言）**
1. **无符号引用层** → 违反 DIP：高层（生成器/AGENTS/skill）直接依赖物理路径这个低层细节。
2. **布局约定无单一配置源** → 违反「配置外部化 / 单一真相在架构常量层」。
3. **文件系统当 DB 却缺 Repository 层** → 业务 consumer 直接 `ls`/`Read`+ 拼路径 = 业务层裸写 SQL。
4. **无链接器** → 改名 = 所有裸引用悬空，无「符号重定位」能力。
5. **约定内联散文且规范互冲突** → PRINCIPLES 推 `INDEX.md`，MECHANISM_PLAN 批#1 已废，定规则的文档自己不单一真相。

---

## 1. 决策（已与廖哥确认）

- **Q1 命名空间 scheme** = `opc://` URI 逻辑符号（稳定契约，几乎不变）。
- **Q2 Registry 组织** = **全局单例（`opc.toml`）+ 公司级覆盖**（约定优于配置：公司段仅写偏离 DEFAULT 的字段）。
- **Z 稳定锚方案** = 公司 `home` 指向 OS 级稳定锚 `companies/<cid>`（junction/symlink），真实目录可任意改名/挪动，只更新该链接（手动跑脚本或未来加 watcher），所有 consumer 零改动、跨平台。
- **跨平台硬约束** = 所有机制（resolver / 脚本 / watcher）必须同时兼容 Windows / macOS / Linux：Windows 用 `mklink /J`（junction），*nix 用 `ln -s`（symlink）；发现/重指逻辑全在 `opc_resolver.py`（仅标准库、无平台分支业务），平台差异只在 `_create_link` 一处；`companies/` 锚目录 gitignore（Windows 默认不跟踪 symlink，提交了会退化成文本文件）。

---

## 2. manifest 规范（`opc.toml`，位于 OPC 根）

```toml
[workspace]
root = "."                       # 相对本 manifest 所在目录（= OPC 根）

[company.DEFAULT]                # 骨架默认值，所有公司继承
workbench = "workbench"
tasks_data = "workbench/tasks-data.json"
roster = "E0000-AI员工-总管/roster.md"
affairs = "workbench/affairs"
page_templates = "page-templates"

[company.C001]                   # 仅覆盖偏离字段；其余继承 DEFAULT
home = "companies/C001"          # Z 方案：指向 OS 级稳定锚（junction/symlink），不直写真实目录名
```

**铁律**
- `opc.toml` 的 `home` 指向**稳定锚** `companies/<cid>`，不直写易变的真实目录名（`C001-AI自动化公司`）。真实目录改名后，**只更新锚、不碰本文件、不碰 consumer**。
- **更新锚 = 跑 `scripts/link-company`（零参数）**：脚本不靠你告诉它改了哪个目录，而是扫 OPC 根下各 `company.md`、按「公司 ID」扫描发现真实位置，重指 `companies/<cid>`。发现逻辑复用 resolver 的 `_discover_company_home`，零手动输入。
- **终极兜底（C 自愈）**：即便锚也断了（没跑脚本），resolver 仍按 `company.md` 的「公司 ID」扫描发现真实目录——所有 consumer 经 resolver 自动定位，改名零配置。锚只是「人类可读 + 加速」层。
- 公司段只写「偏离」字段，未写字段回退 DEFAULT（约定优于配置）。
- **company.md 锚点的维护边界（回答「总得有人维护吗」）**：仅公司根目录一份 `company.md`，其「公司 ID」由 `create-company` 技能在**建公司时写一次**；ID 是位置无关的，**目录改名不需要改它**。子实体（员工/团队/项目）靠目录名前缀（`E0000-`/`T001-`/`P0001-`）扫描发现，**无 md、零维护**。锚点漂移由 `audit_structure`（被 `--check` / pre-commit 自动跑）兜底报警——你无需记着维护，工具替你盯。

---

## 3. URI 方案

**语法**
```
opc://<scope>/<type>/<id>/<sub>
```
- `scope`：`org`（组织层，OPC 根）| `company:<id>`（如 `company:C001`）
- `type`：`company / team / employee / project / skill / workbench / task / doc`

**scope 规则**
- 引用必须显式带 scope（`opc://company:<cid>/...` 或 `opc://org/...`）；单文件内省略 scope 的简写（`opc:skill/...`、`@skill/...`）**未实现，禁止使用**——resolver 对不带 `//` 的形态直接报错（宁可失败不给歧义解析）。

**已注册 name（resolver 当前可解析）**
| name | 含义 | 例 |
|---|---|---|
| `workbench` | 工单系统目录 | `opc://company:C001/workbench` |
| `tasks_data` | 工单产物文件 | `opc://company:C001/tasks_data` |
| `roster` | 总管花名册（相对公司根） | `opc://company:C001/roster` |
| `affairs` | 常设事务目录 | `opc://company:C001/affairs` |
| `page_templates` | 看板模板目录 | `opc://company:C001/page_templates` |

**技能命名约定**：`opc://company:C001/skill/<名称>`（约定式：`{home}/{skills}/<名称>`）。

### 3.1 路径解析约定（agent 实操：opc:// 如何变成能打开的文件）
文档里的 `opc://company:C001/...` 是**逻辑符号，不是文件路径**。agent 要读 / 写对应文件时，必须先把符号落到真实路径，两种等价方式任选：

- **方式 A（推荐，零 resolver）：稳定锚直开**。`opc://company:C001` 在公司根有 OS 级稳定锚 `companies/C001/`（junction / symlink），是真实可开目录。把前缀 `opc://company:C001` 直接换成 `companies/C001` 即可，例如技能文件 → 直接打开 `companies/C001/skills/ticket-system/SKILL.md`（OS 内核透明解析，任何 agent / 编辑器 / 工具都行，无需跑脚本）。
- **方式 B（精确绝对路径）：resolver 翻译**。`cd OPC根 && python opc_resolver.py --resolve opc://company:C001/skill/ticket-system` → 打印绝对路径（如 `E:\OPC\companies\C001\skills\ticket-system`）。
- **技能通常以名调用**：平台经 `.workbuddy/skills` junction 披露技能，agent 命中触发词直接调技能名即可，不必手动解析 opc:// 去 Read SKILL.md；仅当需手动检视某技能文件时才用上面 A / B。

> ❗红线：agent **绝不要把 `opc://...` 当裸文件路径直接 Read / Open**（必找不到）；先按 A 或 B 落到真实路径。详见各员工 AGENTS.md「命名空间治理」段。

---

## 4. resolver（`opc_resolver.py`，OPC 根，零第三方依赖）

仅用标准库 `tomllib`。API：
- `load_company(cid)` → 合并 `DEFAULT` + `[company.<cid>]` 覆盖，返回 `CompanyConfig`（含 `home_abs` / `tasks_data_abs` / `roster_rel` 等派生路径）。**自愈兜底**：若 `home` 目录不存在，自动扫 OPC 根下 `company.md`、按「公司 ID」定位真实目录——改名目录忘了更新锚也能工作。**严格性**：未知公司（manifest 无段且扫描发现无果）直接抛错，绝不返回假路径。
- `resolve(uri)` → `opc://...` 解析为绝对路径；实体与子路径逐级校验存在性（`opc://company:C001/skill/<名>/SKILL.md` 直达文件）；实体类型与编号前缀强校验（team↔T、project↔P、employee↔E）；解析失败一律抛错。
- `check_links(cid)` → ① manifest key 物理存在 + ② 全文 opc:// 引用可解析 + ③ 结构审计（company.md 锚点缺失/ID 无效/与 opc.toml 不符）；任一失效报 issue 列表。
- `audit_structure()` → 结构审计（见上 ③）；可单独调用，亦被 `check_links` 内含。
- `ensure_links()` → **OS 级链接同步中枢**（2026-08-28 Q3 拍板，`sync_links` 收敛为其别名）：①按 `home`（优先）或 `company.md` 的「公司 ID」扫描发现真实位置，把 `companies/<cid>` 重指过去；②按 manifest `[platform.*]` 配置重建各层技能披露链接（层自动发现，新员工/团队自动覆盖）。零参数、零手动输入、幂等。**手动脚本与未来 watcher 都只调它**（DIP：业务智能单一来源）。

`CompanyConfig` 即**依赖倒置容器**：高层只依赖 `opc://` 符号，物理路径细节在此注入。

---

## 5. 链接器自检 + 稳定锚同步

```bash
cd OPC根
python opc_resolver.py --doctor           # 🚦 init 自检门禁：开工前先跑，全绿才进业务（5 项：Python/锚/钩子/命名空间/技能披露链接）
python opc_resolver.py --check            # 全文扫描 opc:// 引用，全绿=自洽
python opc_resolver.py --selftest         # resolver 内置回归测试
python opc_resolver.py --resolve opc://company:C001/workbench   # 打印绝对路径
python opc_resolver.py --ensure-links      # 同步全部 OS 级链接（稳定锚 + 各层技能披露；幂等，clone/改名/换机后跑一次）
python opc_resolver.py --diff-template     # 实例公司 ↔ company-template 双向 diff（忽略换行符与 <CID> 占位符）
python opc_model.py --sync-index           # 重生成各层 skills/INDEX.md（生成物；--list-skills 实时查看）
python opc_tickets.py --company C001       # 生成工单看板数据（--dir <公司根> 亦可）
python opc_dashboards.py --company C001    # 生成三级看板数据（--watch 监听 / --verify 校验）
```

**🚦 init 自检门禁（`--doctor`，2026-08-28 新增）**：任何 agent 开工前必须跑 `python opc_resolver.py --doctor`，检查五项——①Python ≥3.11（`tomllib` 依赖）②稳定锚 `companies/<cid>` 存在且指向真实目录 ③pre-commit 门禁已装 ④`--check` 命名空间扫描自洽 ⑤技能披露链接完整（`check_disclosure_links`，缺失/断链 error 阻断，根治「门禁假绿」）。全绿（输出「初始化自检通过」）才允许进入业务；不绿按 README「系统初始化」补齐（建锚 / 装钩子 / 修失效引用）。此步相当于函数 `init()`：前置条件不满足不许开工。详见 README「系统初始化」。

**跨平台**：`opc_resolver.py` 仅标准库（`os/re/sys/tomllib/subprocess`），无 Windows 专属 import；Windows 跑 `scripts/link-company.ps1`、macOS/Linux 跑 `scripts/link-company.sh`，二者都只是调 `opc_resolver.py --sync-links`。`companies/` 锚目录已 gitignore，clone 后首次跑 link-company 即重建。⚠️ 稳定锚 Windows 用 junction（`mklink /J`）、macOS/Linux 用 symlink（`os.symlink`），二者对浏览器/OS 透明；Windows 侧已实跑，macOS/Linux 的 `os.symlink` 分支逻辑正确但**未在真机实测**。

**手动同步（改名后跑一次）**：`scripts/link-company.ps1`（Windows）/ `scripts/link-company.sh`（*nix），内部即调 `opc_resolver.py --sync-links`。

**可选监听守护（未来启用）**：`scripts/watch-companies.py` —— watchdog 监听 OPC 根 rename/move/create/delete → 防抖 2s → 调 `--sync-links`。它只是「触发器外壳」，不含任何发现逻辑（全在 resolver），故「加监听 = 写个 20 行包装」。依赖 `pip install watchdog`。

**pre-commit 分发**：钩子源文件已入库 `scripts/pre-commit`（/bin/sh + `python3` 兜底，Windows/macOS/Linux 原生可跑）。git 不追踪 `.git/`，clone 后重装：`cp scripts/pre-commit .git/hooks/`（或 `git config core.hooksPath scripts/`）。

---

## 6. 落地状态（2026-08-28，已验证）

- 新增 `opc.toml` + `opc_resolver.py`。
- `C001-AI自动化公司/generate_dashboard.py` 顶部加注入块：路径常量从 `opc_resolver.load_company("C001")` 注入，保留 `__file__` fallback。
- **验证三步全过（PoC）**：
  1. 生成器从 manifest 注入公司根，三级看板数据正常生成（exit 0）；
  2. `opc check-links` → 「命名空间自洽」；
  3. 模拟把 `home` 改成不存在名 → resolver 靠 `company.md` 的「公司 ID」**自愈定位**真实目录，`check-links` 全绿、生成器照常生成、配置与脚本零改动；改回真名后一致。
- **Z 稳定锚（本轮新增）**：
  - `companies/C001` junction 已建，指向真实公司目录；`opc.toml` 的 `home` 改为 `companies/C001`。
  - `sync_links()` + `scripts/link-company.{ps1,sh}` + `scripts/watch-companies.py` 已实现：靠 `company.md` 的「公司 ID」扫描发现，**零参数**重指锚。`--sync-links` 实跑验证待 shell 恢复后补（逻辑已审阅）。

### 6.1 全净化完成（2026-08-28，强制全符号化/稳定锚化）

用户硬性要求：**所有内部引用一律符号化/稳定锚化，不留任何写死物理路径**——路径一旦变动全量失效，违背符号化初心。已完成两层净化：

- **文档层（`.md`）**：内部引用统一为 `opc://company:C001/...`（resolver 可校验，`--check` 门禁）。残留的 `C001根/`、`C001-AI自动化公司/` 字面量已全部改写为稳定锚 `companies/C001/`。
- **运行时层（`.html/.js/.py` + shell）**：浏览器/shell 不认 `opc://`，统一改用稳定锚真实路径 `companies/C001/`。C001 与 `company-template` 两处 `generate_dashboard.py` 改用 `anchor_prefix(base_dir, subdir)` 助手，**按输出目录深度自动补 `../`**，杜绝硬编码深度写错。

⚠️ **关键坑（全净化核心教训）**：稳定锚 `companies/C001` 位于 **OPC 根**，比公司根**高一级**。因此子目录里的相对链接必须是 `../../companies/C001/`（两级上跳到 OPC 根），而非 `../companies/C001/`（那会错指到 `C001-AI自动化公司/companies/C001/`，不存在）。`anchor_prefix` 的算法：

```python
def anchor_prefix(base_dir, subdir):
    out_dir = os.path.realpath(os.path.join(base_dir, subdir))  # base=公司根
    base = os.path.realpath(base_dir)
    rel = os.path.relpath(out_dir, base)          # 'E0001' / '.' / 'T001'
    depth = 0 if rel == "." else len(rel.split(os.sep))
    return ("../" * (depth + 1)) + "companies/C001/"   # 公司根→1跳，子目录→N+1跳
```

- 公司根输出（depth 0）：`../companies/C001/`
- 一级子目录（depth 1，如 `E0001-*/`、`workbench/`）：`../../companies/C001/`
- **验证**：`opc_resolver.py --check` → 全绿；C001 + 模板共 4 个生成器 `--selftest` 全过；`anchor_prefix` 单测 4 场景全对；全项目 `companies/C001` 引用 177 处深度核对 0 偏差。

> 数据层（看板 JSON 等运行时产物）仍走物理路径，属预期（产物不进版本库、随生成而变），不纳入符号化范围。

### 6.2 机制上提 + 严格化（2026-08-28 第二轮，架构评审落地）

**机制上提（推翻「工具随看板走」，廖哥拍板）**：`generate_tasks.py` / `generate_dashboard.py`
（此前每个公司目录各一份复制、已实际分叉）收敛为 OPC 根单例 `opc_tickets.py` / `opc_dashboards.py`。
公司目录只留数据 + `run_boards.{bat,sh}` 薄壳（自动反查公司 ID）。修 bug 一处生效、开新公司零代码复制。

**resolver 严格化**：
- URI 子路径直达（`.../skill/<名>/SKILL.md`），不再静默截断；
- 未知公司 / 不存在实体与子路径 / 类型前缀错配（team 配 E 号）一律抛错，悬空引用不再漏网；
- `--check` 默认遍历全部公司（原单查 C001）；扫描器兼容 GBK 文件（latin-1 兜底）+ 中文标点不吸入 URI；
- `--sync-links` 对无法安全重建的锚位给可读报错（不再裸栈）；doctor 认 `core.hooksPath`；
- 三个根模块均带 `--selftest`（resolver 11 / tickets 22 / dashboards 23 项断言）。

**产物出库**：`*-data.js` / `tasks-data.json` 进 `.gitignore`（`generated_at` 每次生成必变，
入库=永久噪音 diff）；HTML 是模板的确定性拷贝，留库。clone 后跑一次 `run_boards once` 重建数据。

**跨平台**：`run_boards.sh` python3/python 双探测（Windows Git Bash 常无 python3、macOS 常无 python）；
`link-company.ps1` 不再写死机器专属 Python 路径，并以 UTF-8 BOM 落盘（Windows PowerShell 5.1 硬要求）。

### 6.2 init 自检门禁（`--doctor`，2026-08-28 新增）

用户要求：系统要正常跑的前置工作必须固化成「开工前必过的门禁」，相当于函数 `init()`——前置不满足不许进入业务。落地：

- `opc_resolver.py` 新增 `--doctor`：检查 Python≥3.11 / 稳定锚 / pre-commit 钩子 / 命名空间扫描 / 技能披露链接五项，全绿才放行（exit 0），有缺失 exit 1 并打印补齐指引。
- **治理文件全部写入该门禁**（波及面四处同步）：
  - 总管 `E0000-AI员工-总管/AGENTS.md` 启动流程**第 0 步** = 环境 init 自检（C001 实例 + company-template 模板均改）。
  - 新建 **OPC 根 `AGENTS.md`**（组织级治理入口）：规定任何在 OPC 根工作的 agent 开工前必跑 `--doctor`。
  - `company-template/AGENTS.md` 加「启动门禁（init · 新建公司继承）」段，新公司自动遵循。
  - `README.md` 新增「系统初始化（首次运行必做）」章节：clone 后必做清单（Python≥3.11 / 建锚 / 装钩子 / 验证）。
- **验证**：Windows 侧 `--doctor` 实跑通过（OK 场景全绿 + 缺失场景正确报 2 项错误并 exit 1）；macOS/Linux 未真机实测。

## 7. 推广路线（后续「开工搞」）

| 阶段 | 内容 | 状态 |
|---|---|---|
| A | `create-company` 接入：新建公司自动写 `opc.toml` 段 + 用 `opc://` + 首跑 `check-links` | ✅ 已做 |
| B | 总管治理：总管 AGENTS 加命名空间治理职责，定期 `check-links` 巡检 | ✅ 已做（C001 实例） |
| C | consumer 铺开：绝对路径 / 已废弃 INDEX.md / 写死公司名等高危裸引用全改 `opc://`（`company-template` 同步） | ✅ 已做 |
| D | pre-commit：接入 `check-links`，提交前阻断失效引用（本仓库已装 `.git/hooks/pre-commit`，其他 clone 需重装） | ✅ 已做 |
| E | resolver 扩展：补 `skill/team/employee/project` 实体解析 + `org` 范围 + 全文扫描 `check-links` | ✅ 已做 |
| F | 公司层自愈：`load_company` 加 `_discover_company_home` 扫描发现兜底，手动改公司目录名忘了改 manifest 也能自动定位 | ✅ 已做 |
| G | Z 稳定锚：`companies/<cid>` junction + `sync_links()` + `scripts/link-company.*` + `watch-companies.py`（按 ID 扫描发现，零参数重指） | ✅ 已实现（待 shell 恢复实跑验证） |
| H | 锚点审计：`audit_structure` 把 company.md 维护职责下沉到工具门禁（`--check` / pre-commit 自动覆盖漂移）；`.gitignore` 排除 `companies/` | ✅ 已做 |
| I | init 门禁：`opc_resolver.py --doctor` 开工前自检（Python/锚/钩子/命名空间/披露链接五项）；README「系统初始化」+ 总管/OPC根/模板 AGENTS 写入启动门禁，clone 后必做清单固化 | ✅ 已做 |
| J | ensure_links：技能披露 junction 纳入 resolver 托管 + doctor 第 5 项（`[platform.*]` 配置化，负例实测阻断/重建） | ✅ 已做（2026-08-28） |
| K | `--diff-template` 实例↔模板双向 diff（忽略换行/占位符）+ `opc_model --list-skills/--sync-index`（INDEX.md 转生成物） | ✅ 已做（2026-08-28） |

---

## 8. 反模式禁忌

- ❌ 在文档 / skill / 代码里裸写 `../` 上跳或绝对路径 `E:\OPC\...` 引用实体。
- ❌ 把脚本位置（`__file__`）当作布局约定硬编码（原 `COMPANY_DIR = SCRIPT_DIR` 即此反模式）。
- ❌ 改名时逐个改引用点（裸路径反模式）；改名后**不要手动改 opc.toml 的 home**，而是跑 `scripts/link-company` 重指锚——引用点零改动。resolver 也会按 `company.md` 的 ID 自愈兜底。
- ❌ 在 `companies/` 锚命名空间下放真实公司目录（该目录仅供本机制管理链接）。
- ❌ 在机制代码里写 Windows 专属路径/命令却不提供 *nix 分支——所有机制必须 Windows + macOS + Linux 三端可用（平台差异只允许集中在 `_create_link` 一处）。

---

## 9. 与 PRINCIPLES 关系

- 补充 **P2 单一真相**：延伸到「架构常量层」——路径/布局约定也有唯一出处（`opc.toml` + `companies/` 锚）。
- 补充 **P3 高内聚低耦合**：`opc_resolver.py` 单一职责（解析/注入/自检/同步锚），consumer 不碰路径细节。
- 强化 **P4 单向管道**：`opc.toml` 是真相，consumer 只读符号、永不写回路径约定。
- 落地 **DIP**：高层依赖 `opc://` 抽象符号；物理路径细节注入进 manifest + `companies/` 锚 + resolver 扫描发现，consumer 零感知。
