---
name: privacy-publish
description: 对外发布与隐私剥离（单仓双远程）。触发词：发布、推送、push、上传github、公开仓库、fork、剥离隐私、私有清单、隐私文件、opc-publish、备份。「怎么推送 / 怎么剥离 / 怎么把隐私加进清单」的唯一权威——工作仓库 main 含私有内容，禁止直推公开远程 origin。
summary: 对外发布与隐私剥离（单仓双远程剥离法）。
triggers: [发布, 推送, push, 上传github, 公开仓库, fork, 剥离隐私, 私有清单, 隐私文件, opc-publish, 备份]
---

# 对外发布与隐私剥离（privacy-publish）

> **要解决的问题**：本仓库既要对外开放让人 fork，又要装自己的私有资料。
> 方案是**单仓双远程剥离法**——`main` 照常提交私有内容（版本管理 + 备份），
> 公开分支由 `scripts/opc-publish.*` 按清单剥离后生成并推送。
> 本文件是「怎么推送 / 怎么剥离 / 怎么把隐私加进清单」的**唯一权威**，与 `scripts/opc-publish.*`、
> `.opc-private-paths.txt`、pre-push 守卫三处联动，改任一方须同步其余。

## 三条红线（违反即事故）

| # | 红线 | 为什么 |
|---|---|---|
| 1 | ⛔ **禁止** `git push origin` | `origin`（github.com/liao7877/OPC）是**公开**远程，而工作仓库 `main` **含私有内容**。pre-push 守卫已启用（`opc.publicRemote=origin`），直推会被拦下 |
| 2 | ✅ 发布到公开仓库**只走** `scripts/opc-publish.sh`（Windows PowerShell 用 `.ps1`） | 它在**临时克隆** `.opc-publish-build/` 里剥离后推送；临时克隆不带钩子，故可直推 |
| 3 | ✅ `main` 推**私有远程**做备份 —— 允许且应做 | 私有远程（默认名 `backup`）承载含私有的全量，这才是版本管理与异地备份 |

## 远程拓扑

| 远程 | 性质 | 承载 | 谁推 |
|---|---|---|---|
| `origin` | **公开**（别人 fork） | 剥离后的干净 `main` | **只由 opc-publish 推** |
| `backup`（已配置） | **私有**（本机另一块盘的裸仓库，与工作仓不同卷） | 含私有的完整 `main` | 可直推 `git push backup main` |

> `backup` 的具体路径只存在本机 `.git/config`（**不入库、不进公开仓**，避免把盘符布局写进公开内容）；
> 需要时查地址：`git remote get-url backup`。换机器/换盘时重新 `git remote set-url backup <新路径>` 即可。

## 一、怎么推送

```bash
# 备份：推私有远程（含私有，做版本管理）——允许直推
git push backup main

# 发布：剥离私有后推公开远程 —— 唯一合法途径
cd <OPC 仓库根>
./scripts/opc-publish.sh          # Git Bash / macOS / Linux
.\scripts\opc-publish.ps1         # Windows PowerShell
```

发布脚本做三件事：克隆到 `.opc-publish-build/` → 按清单 `git filter-repo --invert-paths` 剥离 →
`git push --force` 到公开远程的 `main`。

- 依赖 `git-filter-repo`：脚本默认用 `python3`；本机已装在受控 venv，用环境变量指定：
  `OPC_PYTHON=/path/to/python`（该解释器需已 `pip install git-filter-repo`）
- **历史会被重写**，forkers 需 `git pull --rebase` 或重新 fork —— 这是 filter-repo 的固有行为，正常。
- 发布后公开远程的 `main` 与本地 `main` **不同名同内容**：本地含私有，公开已剥离。

## 二、怎么把隐私数据加进清单

清单文件：仓库根 **`.opc-private-paths.txt`**（每行一条**相对仓库根**的路径；`#` 开头为注释；
支持 `*` 通配——fnmatch，`**` 可跨目录）。

```bash
# 例：把某个真实私有目录点名加进去（加完当天发布即自动不含它）
echo 'C001-AI自动化公司/E0002-AI员工-项目经理/客户资料/**' >> .opc-private-paths.txt
```

已有规则（目录不存在时自动忽略；建了即自动剥离）：

| 规则 | 覆盖 |
|---|---|
| `C001-AI自动化公司/**/private/**`、`/**/私密/**`、`/**/个人/**` | 私有 / 私密 / 个人 目录 |
| `*.pem`、`*.key`、`.env`、`.env.*` | 凭据密钥（防御性，正常不入库） |
| `.workbuddy/**` | 本地记忆（已全局忽略，兜底） |
| `*-data.js`、`tasks-data.json` | 看板数据产物（已忽略，兜底） |

**什么该加清单**：账号密码 / 密钥令牌 / 客户与个人信息 / 财务与合同 / 未公开商业资料 /
任何「推到公开仓库会后悔」的内容。

> **判据：拿不准就加。** 多剥离无害（公开分支少一个文件而已），漏剥离是事故（隐私外泄）。

## 三、怎么剥离（手工核验 / 排障）

发布脚本会自动剥离。要手工确认剥离结果，**必须在临时克隆里做**（见下方事故）：

```bash
git clone . .opc-check && cd .opc-check
git filter-repo --force --invert-paths --path-glob '...'
git ls-files | grep -E "private|私密|个人"     # 剥离后应无命中（清单文件自身除外）
```

⚠️ **filter-repo 误伤事故（2026-08-30 实踩，务必吸取）**：`git filter-repo` 必须在**临时克隆**内执行。
若 `cd` 进临时目录失败而命令继续，filter-repo 会跑在**真实工作仓库**上——
**重写全部提交 SHA** 并**删除 `origin` 远程**（filter-repo 默认剥离 remote）。

- **现象**：提交 SHA 全变；`git remote get-url origin` 报 `No such remote 'origin'`。
- **修复**：`git remote add origin https://github.com/liao7877/OPC.git` + `git fetch origin`。
- **预防**：任何 filter-repo 调用前先 `pwd` 校验 CWD 确实在临时目录；`cd` 失败立即中止，**不接续**。

## 发布 / 推送前自检

- [ ] `git status` 已处理（该提交的都提交了）
- [ ] 新增的私有内容已点名进 `.opc-private-paths.txt`
- [ ] 剥离后扫描无私有残留
- [ ] 用 `opc-publish` 推公开远程，**不用** `git push origin`

## 误推的补救

一旦私有文件进了公开远程：立即 `git filter-repo` scrub 历史 + force-push，
并**轮换任何可能泄露的凭据**（改密码 / 吊销 token）——历史重写不等于凭据安全。
