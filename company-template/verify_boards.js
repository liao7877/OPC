const fs = require("fs");
const path = require("path");
const WB = __dirname;

function load(p, vn) {
  const raw = fs.readFileSync(path.join(WB, p), "utf-8");
  const m = raw.match(new RegExp("^window\\." + vn + " = ([\\s\\S]*);\\s*$"));
  if (!m) throw new Error("bad js payload: " + p);
  return JSON.parse(m[1]);
}

const dash = load("dashboard-data.js", "DASHBOARD_DATA");
const team = load("T001-AI开发团队/teamboard-data.js", "TEAMBOARD_DATA");
const desks = [
  load("E0000-AI员工-总管/mydesk-data.js", "MYDESK_DATA"),
  load("E0001-AI员工-分析员/mydesk-data.js", "MYDESK_DATA"),
  load("E0002-AI员工-项目经理/mydesk-data.js", "MYDESK_DATA"),
];

// 同批生成
const gens = new Set([dash, team, ...desks].map((x) => x.generated_at));
if (gens.size !== 1) throw new Error("generated_at mismatch: " + [...gens]);
console.log("PASS 五份数据同批生成:", dash.generated_at);

// 深链目标存在
const kd = JSON.parse(fs.readFileSync(path.join(WB, "workbench", "tasks-data.json"), "utf-8"));
const ids = new Set(kd.tasks.map((t) => t.id));
desks.forEach((d) =>
  d.tickets.forEach((t) => {
    if (!ids.has(t.id)) throw new Error("死链: " + t.id);
  })
);
dash.activity.forEach((a) => {
  if (a.ticket && !ids.has(a.ticket)) throw new Error("动态流死链: " + a.ticket);
});
console.log("PASS 深链目标全部存在（mydesk 工单 + 动态流 ticket）");

// 三级数据自洽抽查
if (!dash.employees.length || !dash.teams.length || !dash.projects.length) throw new Error("公司级数据不完整");
if (team.members.length !== 2) throw new Error("T001 成员应为 E0001+E0002");
const t001 = dash.projects.find((p) => p.pid === "P0004");
if (!t001 || t001.teams[0] !== "T001") throw new Error("P0004 应归 T001");
["P0001", "P0002", "P0003"].forEach((pid) => {
  const p = dash.projects.find((x) => x.pid === pid);
  if (p && p.teams.length) throw new Error(pid + " 存量应公司直属，实为 " + p.teams);
});
if (team.projects.some((p) => p.pid !== "P0004")) throw new Error("T001 项目切片应为 P0004");
console.log("PASS 归属正确：存量项目公司直属，仅 P0004 属 T001");

// 交叉核验告警渲染源存在且只在风险模块
if (!Array.isArray(dash.risks.warnings) || dash.risks.warnings.length < 2)
  throw new Error("预期存在 ≥2 条核验告警（种子演示数据）");
console.log("PASS 交叉核验告警生效:", dash.risks.warnings.length, "条（种子演示：忘关单场景）");

// 陈旧告警字段
[dash, team, ...desks].forEach((d) => {
  if (!d.generated_at || !d.config || d.config.stale_days == null) throw new Error("缺 generated_at/config");
});
console.log("PASS 全部数据带 generated_at + config.stale_days");
console.log("\nALL PASS ✓");
