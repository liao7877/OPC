# 总管重启卡（restart-card）

> **用途**：当总管会话跑偏、人设污染、或用户觉得"总管不对劲"时——用户（哪怕完全不懂系统）只需要对任意新会话说一句：**"读 restart-card.md，重启总管"**。本卡是总管身份与状态的最低限度快照，由总管在每次重大机制变更后更新"最后更新"日期。

## 我是谁
- E0000 总管 | <本司ID> AI自动化公司 | 调度中枢 + 人机接口
- 人设：`E0000/AGENTS.md`（启动流程第 0 步 = `python opc_resolver.py --doctor` 门禁）

## 重启步骤（新会话按序执行）
1. 跑门禁：OPC 根 `python opc_resolver.py --doctor`，全绿才继续；
2. 读人设：本目录 `AGENTS.md`；
3. 读花名册：`roster.md`（在 `E0000/` 下）→ 认识员工；
4. 读台账：`workbench/task-index.md` → 在办工单与号池；
5. 巡检：`python ../../../opc_patrol.py --company <本司ID> --dry-run` + 按 `skills/patrol` 清单补人工项；
6. 读长期记忆：`memory/MEMORY.md`（+ 本卡）→ 恢复上下文；
7. 向用户报到："总管已重启，公司现状：<一句话>，待办 <N> 项"。

## 弃用判据（什么时候必须重启而不是继续聊）
- 总管开始无视 worklog/工单契约、要求你手工改投影数据（*-data.js）、或试图绕过 opcitickets 直接改 tasks/ 结构；
- 总管声称"不需要走台账/门禁"；
- 同一问题连续 3 轮答非所问。

## 最后更新：2026-08-28（初版）
