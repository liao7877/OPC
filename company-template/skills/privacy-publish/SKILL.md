---
name: privacy-publish
description: 公开发布、推送和私有备份的唯一执行标准；工作 main 含私有内容，禁止直推公开远程。
summary: 公开发布过滤、历史校验与私有备份。
triggers: [发布, 推送, push, 上传github, fork, 剥离隐私, 私有清单, 备份]
---

# 对外发布与隐私剥离

## 边界
- 工作仓库 main 含私有内容。pre-push 同时检查远程名称和 URL，拒绝公开远程、其 URL 别名及未登记目标。
- 私有远程只有登记 opc.privateRemote 并与实际推送 URL 一致才放行；不得假定名为 backup 就是私有，登记前确认目标性质。
- 没有已确认的私有远程时，使用仓库外、当前用户独占的版本化文件备份，包含 .git 和未提交资料并核验 SHA256。本机备份不是异地备份；不在此技能写机器路径或声称已配置。

## 发布流程
在 OPC 根调用 scripts/opc-publish.sh（Windows 用 scripts/opc-publish.ps1）：
1. 默认只构建：临时克隆放 _AI工作区/发布构建/，不上传。依赖 Python 3.11+ 与 git-filter-repo；OPC_PYTHON 可指定隔离环境。
2. opc_publish.py 在临时克隆中调用共享 opc_privacy.py 策略，过滤 main 全部历史中的私有路径；提交消息和作者标识替换为中性值，避免元数据带出私密描述。
3. 遍历每个历史树复查私有路径，重建命名空间锚并执行 --check。克隆、过滤、校验任一失败立即停止，绝不继续推送。
4. 审核构建产物后，需要发布时显式加 --push；仅允许已提交且干净的 main，目标取 opc.publicRemote 配置的单一推送 URL；构建前读取远端 main 版本，推送使用该版本的 force-with-lease，远端并发变更则拒绝覆盖。公开历史被重写，协作者需按新历史同步。
5. --preview-working 可把未提交修复加入离线预览；与 --push 互斥。预览通过不代表工作变更已提交。

## 私有策略
- opc_privacy.py 自动剥离任意公司、任意层级的 private、私密、个人、memory、workspace、_AI工作区、.workbuddy、.zcode、.claude、.codex、.agents、.opc-sync、.opc-data，不依赖公司目录显示名。
- 唯一例外是版本化的合成回归代码 _AI工作区/回归测试/test_runtime.py；它不含用户数据，公开 CI 需要运行。其他过程材料仍剥离。
- opc.toml 的 private_entities 按实体 ID 剥离声明的私有实体，覆盖历史改名路径。availability=optional 且提供原因后，原始目录缺席可通过链接门禁，但必须显示“私有资料未挂载”；已挂载实体内部的断链仍然失败。
- .opc-private-paths.txt 补充每行一个仓库相对路径模式。未公开客户、合同、财务、个人或凭据资料均应登记；拿不准就加。路径策略不能识别普通公开文件中的敏感段落，发布前仍需内容审核。
- 只在临时克隆过滤；工作仓库历史、原始资料及私有备份保持可恢复。已发生泄露时，清理历史不能替代凭据轮换。

## 验证
python _AI工作区/回归测试/test_runtime.py 覆盖远程别名、过滤失败闭锁、公司改名、私有实体缺席等边界；离线发布预览额外核验实际历史。不要把本地模拟结果描述成真实外部服务写入验收。
