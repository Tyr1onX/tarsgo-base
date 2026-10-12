import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

import { recentBaseChanges } from "../src/baseHome.js"

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8")
const home = app.slice(app.indexOf("<template v-else-if=\"path === '/'\">"), app.indexOf("<template v-else-if=\"path === '/planner-draft' && plannerDraft\">"))
const now = Date.parse("2026-10-05T12:00:00Z")

const root = {
  id: 1,
  parent_id: null,
  title: "校友参观",
  owner: null,
  item_facts: [
    { id: 1, content: "参观时间已确认：10 月 9 日 15:00", scope: "global", related_tasks: [], source_activity_id: 101, created_at: "2026-10-04T10:00:00Z" },
    { id: 2, content: "接待资料已准备", scope: "related", related_tasks: [{ id: 11, title: "接待" }], source_activity_id: null, created_at: "2026-10-03T10:00:00Z" },
    { id: 3, content: "其他分工的内部安排", scope: "related", related_tasks: [{ id: 12, title: "摄影" }], source_activity_id: null, created_at: "2026-10-03T09:00:00Z" },
    { id: 4, content: "很久以前的信息", scope: "global", related_tasks: [], source_activity_id: null, created_at: "2026-08-01T09:00:00Z" },
  ],
}
const relatedTasks = [
  { id: 11, parent_id: 1, title: "接待", owner: { id: 7 }, collaborators: [] },
]
const allTasks = [root, ...relatedTasks, { id: 12, parent_id: 1, title: "摄影", owner: { id: 8 }, collaborators: [] }]
const activities = [
  { id: 101, root_task_id: 1, task_id: 11, content: "参观时间已确认：10 月 9 日 15:00", created_at: "2026-10-04T10:00:00Z" },
  { id: 102, root_task_id: 1, task_id: 11, content: "接待联系已完成", created_at: "2026-10-03T14:00:00Z" },
  { id: 103, root_task_id: 1, task_id: 12, content: "摄影分工内部进展", created_at: "2026-10-03T13:00:00Z" },
]

const changes = recentBaseChanges(allTasks, relatedTasks, activities, 7, now)
assert.equal(changes.length, 3)
assert.deepEqual(changes.map((change) => change.content), [
  "参观时间已确认：10 月 9 日 15:00",
  "接待联系已完成",
  "接待资料已准备",
])
assert.equal(recentBaseChanges(allTasks, [], activities, 7, now).length, 0)
assert.equal(recentBaseChanges(allTasks, relatedTasks, [], 7, now).length, 2)
const unchangedTasks = allTasks.map((task) => task.parent_id === null ? { ...task, item_facts: [] } : task)
assert.equal(recentBaseChanges(unchangedTasks, relatedTasks, [], 7, now).length, 0)
const standalone = { id: 20, kind: "task", parent_id: null, title: "独立任务", owner: { id: 8 }, item_facts: [] }
const standaloneChange = recentBaseChanges(
  [standalone],
  [standalone],
  [{ id: 120, root_task_id: 20, task_id: 20, content: "独立任务进展", created_at: "2026-10-05T11:00:00Z" }],
  7,
  now,
)
assert.equal(standaloneChange[0].context, "独立任务")

const manyChanges = recentBaseChanges(allTasks, relatedTasks, [
  ...activities,
  { id: 104, root_task_id: 1, task_id: 11, content: "后续材料已发送", created_at: "2026-10-05T11:00:00Z" },
  { id: 105, root_task_id: 1, task_id: 11, content: "接待路线已确认", created_at: "2026-10-05T10:00:00Z" },
], 7, now)
assert.equal(manyChanges.length, 3)
assert.deepEqual(manyChanges.map((change) => change.content), [
  "后续材料已发送",
  "接待路线已确认",
  "参观时间已确认：10 月 9 日 15:00",
])

assert.match(home, /v-if="isAdmin"[\s\S]*?class="planner-composer base-composer"/)
assert.match(home, /复制 AI 提示词[\s\S]*?导入 AI 方案/)
assert.doesNotMatch(home, /aiPlannerAvailable|planFromBase|或手动创建任务/)
assert.match(home, /homeRecentChanges.length[\s\S]*?最近与你有关/)
assert.match(home, /v-if="homeTaskCards.length"[\s\S]*?现在要处理/)
assert.match(home, /v-for="task in visibleHomeTaskCards"/)
assert.match(home, /快速创建独立任务/)
assert.match(home, /isIndependentTask\(task\) \? "独立任务" : "事项"/)
assert.doesNotMatch(home, /task\.deliverable/)
assert.match(home, /homeTaskCards.length > 3[\s\S]*?查看全部任务 →/)
assert.match(home, /v-if="claimableCount"[\s\S]*?还有 \{\{ claimableCount \}\} 项可以认领 →/)
assert.doesNotMatch(home, /homeTaskCards.length }} 项|当前没有待处理任务|dashboard|完成率|排行榜|统计：0/)
assert.ok(app.includes("api.itemActivityPage(rootId, undefined, 5)"))
assert.ok(app.includes("const visibleHomeTaskCards = computed(() => homeTaskCards.value.slice(0, 3)"))
assert.match(css, /@media \(max-width: 560px\)[\s\S]*?\.page \{[\s\S]*?width: min\(calc\(100% - 28px\), 560px\)/)
assert.match(css, /\.home-task-card strong \{[\s\S]*?overflow-wrap: anywhere/)
assert.match(css, /\.base-change-row p \{[\s\S]*?overflow-wrap: anywhere/)
assert.match(css, /\.home-task-card \{[\s\S]*?min-width: 0/)

console.log("Base home role, density, relevant changes, claimable entry and narrow layout passed")
