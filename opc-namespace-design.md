# OPC 命名空间设计规范（opc-namespace-design.md）

> **定位**：PRINCIPLES 的补充约定，是 P2（单一真相）/ P3（高内聚低耦合）在**「架构常量层」**的具体落地。
> **创建**：2026-08-28 · **依据**：架构评审（依赖倒置视角）+ PoC 验证。
> **关联文件**：`opc.toml`（全局 manifest）、`opc_resolver.py`（解析器/DI 容器）、`generate_dashboard.py`（首个接入的 consumer）。

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
home = "C001-AI自动化公司"
```

**铁律**
- `opc.toml` 是**物理路径首选真相源（人类可读 + 加速）**，但非唯一必需：公司层改名**连本文件都不用改**——resolver 靠 `company.md` 的「公司 ID」扫描发现真实目录（自愈）。team / employee / project 本就按目录名前缀扫描发现，改名天然自愈。
- 手动改目录名后**无需任何操作**：所有 consumer 经 resolver 自动解析到新位置。仍建议把 `home` 同步成新名，保持 manifest 作为人类可读的布局速查。
- 公司段只写「偏离」字段，未写字段回退 DEFAULT（约定优于配置）。

---

## 3. URI 方案

**语法**
```
opc://<scope>/<type>/<id>/<sub>
```
- `scope`：`org`（组织层，OPC 根）| `company:<id>`（如 `company:C001`）
- `type`：`company / team / employee / project / skill / workbench / task / doc`

**别名**
- 单公司语境内可省略 scope：`@skill/ticket-system` 或 `opc:skill/ticket-system` 默认解析到当前公司。
- 跨公司 / 组织层**必须带 scope**，避免歧义。

**已注册 name（resolver 当前可解析）**
| name | 含义 | 例 |
|---|---|---|
| `workbench` | 工单系统目录 | `opc://company:C001/workbench` |
| `tasks_data` | 工单产物文件 | `opc://company:C001/tasks_data` |
| `roster` | 总管花名册（相对公司根） | `opc://company:C001/roster` |
| `affairs` | 常设事务目录 | `opc://company:C001/affairs` |
| `page_templates` | 看板模板目录 | `opc://company:C001/page_templates` |

**技能命名约定（resolver 待扩展）**：`opc://company:C001/skill/<名称>`。

---

## 4. resolver（`opc_resolver.py`，OPC 根，零第三方依赖）

仅用标准库 `tomllib`。API：
- `load_company(cid)` → 合并 `DEFAULT` + `[company.<cid>]` 覆盖，返回 `CompanyConfig`（含 `home_abs` / `tasks_data_abs` / `roster_rel` 等派生路径）。**自愈兜底**：若 manifest 的 `home` 目录不存在，自动扫 OPC 根下 `company.md`、按「公司 ID」定位真实目录——手动改名目录忘了改 manifest 也能工作。
- `resolve(uri)` → `opc://...` 解析为绝对路径；无 name 则返回公司根。
- `check_links(cid)` → 扫描所有 name 是否解析到真实存在的路径；失效即报「失效引用：opc://... -> 路径（不存在）」，返回 issue 列表。

`CompanyConfig` 即**依赖倒置容器**：高层只依赖 `opc://` 符号，物理路径细节在此注入。

---

## 5. 链接器自检（check-links）

```bash
cd OPC根 && python opc_resolver.py --check          # 全绿=自洽
python opc_resolver.py --resolve opc://company:C001/workbench   # 打印绝对路径
```
**用途**：改名 / 重构后跑一次，立即知道哪些引用漏改。拟接入 **pre-commit** 钩子，提交前阻断失效引用。

---

## 6. 落地状态（PoC 2026-08-28，已验证）

- 新增 `opc.toml` + `opc_resolver.py`。
- `C001-AI自动化公司/generate_dashboard.py` 顶部加注入块：路径常量从 `opc_resolver.load_company("C001")` 注入，保留 `__file__` fallback。
- **验证三步全过**：
  1. 生成器从 manifest 注入公司根，三级看板数据正常生成（exit 0）；
  2. `opc check-links` → 「命名空间自洽」；
  3. 模拟把 `home` 改成不存在名（manifest 未同步改名）→ resolver 靠 `company.md` 的「公司 ID」**自愈定位**真实目录，`check-links` 全绿、生成器照常生成、**配置与脚本零改动**；改回真名后一致。
  4. （后续增强）公司层自愈落地：即便 `opc.toml` 的 `home` 永久写错 / 过时，所有 consumer 仍经 `_discover_company_home` 按 ID 现场发现，改名零配置。

---

## 7. 推广路线（后续「开工搞」）

| 阶段 | 内容 | 状态 |
|---|---|---|
| A | `create-company` 接入：新建公司自动写 `opc.toml` 段 + 用 `opc://` + 首跑 `check-links` | ✅ 已做 |
| B | 总管治理：总管 AGENTS 加命名空间治理职责，定期 `check-links` 巡检 | ✅ 已做（C001 实例） |
| C | consumer 铺开：绝对路径 / 已废弃 INDEX.md / 写死公司名等高危裸引用全改 `opc://`（`company-template` 同步） | ✅ 已做 |
| D | pre-commit：接入 `check-links`，提交前阻断失效引用（本仓库已装 `.git/hooks/pre-commit`，其他 clone 需重装） | ✅ 已做 |
| E | resolver 扩展：补 `skill/team/employee/project` 实体解析 + `org` 范围 + 全文扫描 `check-links` | ✅ 已做 |
| F | 公司层自愈：`load_company` 加 `_discover_company_home` 扫描发现兜底，手动改公司目录名忘了改 manifest 也能自动定位 | ✅ 已做（2026-08-28） |

---

## 8. 反模式禁忌

- ❌ 在文档 / skill / 代码里裸写 `../` 上跳或绝对路径 `E:\OPC\...` 引用实体。
- ❌ 把脚本位置（`__file__`）当作布局约定硬编码（原 `COMPANY_DIR = SCRIPT_DIR` 即此反模式）。
- ❌ 改名时逐个改引用点（裸路径反模式）；改名后无需改任何引用——resolver 按 `opc://` 符号 + 实体 ID 自动重定位。manifest `home` 同步改是「建议」非「必须」。

---

## 9. 与 PRINCIPLES 关系

- 补充 **P2 单一真相**：延伸到「架构常量层」——路径/布局约定也有唯一出处（`opc.toml`）。
- 补充 **P3 高内聚低耦合**：`opc_resolver.py` 单一职责（解析/注入/自检），consumer 不碰路径细节。
- 强化 **P4 单向管道**：`opc.toml` 是真相，consumer 只读符号、永不写回路径约定。
