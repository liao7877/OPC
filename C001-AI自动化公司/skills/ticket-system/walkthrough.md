# ticket-system 新手全流程示例（walkthrough）

> 场景：总管派给你「搭建日志系统」任务，编号 TSK00010，项目 P0001。照做一遍即掌握全流程。

1. **建单**（编号找总管确认后执行）：
   ```
   python ../../../opc_tickets.py --company C001 --new TSK00010 搭建日志系统 --owner E0001 --project P0001
   ```
2. **开工**：打开本单 `task.md`，把 `status` 改成 `in_progress`、`priority: 高`、填 `due`，顺手更新 `updated`。
3. **干完**：交付物放 `deliverables/`，在 `messages.md` **追加**完成备注，`status: review`（交下一手审核）。
4. **流转**（转给 E0002 实现）：改 `owner: E0002` + 追加 handoffs（**单行 JSON**）：
   ```yaml
   handoffs: [{"from":"E0001","to":"E0002","at":"2026-08-28","reason":"方案设计完成，转开发实现"}]
   ```
5. **完成**（E0002 做完）：`status: done` + `completed_at`（必填）+ worklog 条目同步「已完成」（双账联动）。
6. **自检**：`python ../../../opc_tickets.py --selftest` 全过即收工。

> 每步改完文件，看板 ≤3 秒自动更新；全程只动本工单目录下的文件，不碰看板/生成器（SKILL.md §8 红线）。
