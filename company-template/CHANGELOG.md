# company-template 变更日志（机制版本）

> 红线 4：模板升级不自动跟进已建公司（各公司独立演进）。本日志是唯一的模板演进记录——
> 各公司总管入职/巡检时对照本日志与自家 `公司.md` 的「机制基线」字段，决定是否手动跟进。

## [v2] 2026-08-28 · 机制上提 + 自转机制
- 生成器机制代码上提 OPC 根（opc_tickets.py / opc_dashboards.py），公司目录只留 run_boards 薄壳；
- 新增 opc_patrol.py 心跳巡检（公司自转：不依赖用户注意力）+ skills/patrol 清单；
- 新增 opc_schema.py（状态机唯一真相源）；opc_tickets/dashboards/patrol 均带 --selftest；
- workflow.md 新增：返工协议（5.5）/ 入口 B 护栏（5.6）/ 双总管仲裁（5.7）/ 超时升级（5）；
- ticket-system 新增：§1.55 自助取号并发安全 / §1.66 超时升级 / §3.5 离职转移；
- roster 按表头解析（插列/换列序安全）；记忆归一规则（memory/ 权威）；总管重启卡。

## [v1] 2026-08-28 · 初版（命名空间 + 稳定锚 + 工单系统 + 三级看板）
