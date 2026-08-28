# OPC 组织级治理入口（AGENTS）

> **本文件是 OPC 组织根（仓库根）的 agent 行为入口**，面向在 OPC 根做机制 / 基础设施 / 跨公司治理工作的 agent（总管、机制维护者等）。
> 公司级 agent 入口在各公司 `AGENTS.md`（如 `C001-AI自动化公司/AGENTS.md`）；本文件管「组织根这一层」。

## 启动门禁（init · 任何 agent 开工前必过）
- 在 OPC 根跑 `python opc_resolver.py --doctor`：**全绿（输出「初始化自检通过」）才允许开工**；不绿按 [`README.md`「系统初始化」](README.md) 补齐——典型是稳定锚缺失（跑 `scripts/link-company.{ps1,sh}` 重建 `companies/<cid>`）或 pre-commit 未装（`cp scripts/pre-commit .git/hooks/`）。
- 这相当于函数 `init()`：命名空间符号化 + 稳定锚物理入口 + 提交门禁是系统正常跑的硬前置，未达标不许进入业务。
- 改名公司目录后，重跑 `scripts/link-company.{ps1,sh}` 即可自动重指向，无需改任何其他文件。

## 组织级铁律（与 PRINCIPLES 一致，速记）
- **命名空间**：物理路径唯一真相源在 `opc.toml`；跨文件引用统一 `opc://company:<cid>/...`（文档层，resolver 校验）或 `companies/<cid>/` 稳定锚（运行时层）。禁止裸写 `../` 或绝对路径（PRINCIPLES P26）。
- **机制改动波及面**：C001 实例 + 其总管(E0000) + company-template 新建模板 + 根文档，四处须同步。
- **共享读取器**：实体卡 frontmatter 读取统一走 OPC 根 `opc_model.py::parse_frontmatter`（PRINCIPLES P25）。
- **提交门禁**：提交前 `opc --check` 由 pre-commit 自动跑，拦截失效引用 / 锚点漂移。

## 关键文件
| 文件 | 作用 |
|---|---|
| [`README.md`](README.md) | 系统初始化 / 使用说明（开工前先读「系统初始化」） |
| [`opc-namespace-design.md`](opc-namespace-design.md) | 命名空间机制设计规范（动机 / URI / resolver / 跨平台 / 落地） |
| [`PRINCIPLES.md`](PRINCIPLES.md) | 组织级设计原则 P1~P26 |
| [`AGENT_ECOSYSTEM.md`](AGENT_ECOSYSTEM.md) | 多 Agent 平台接入规范 |
| `opc_resolver.py` / `opc_model.py` / `opc.toml` | 命名空间运行时（DI 容器 / 共享读取器 / 配置） |
