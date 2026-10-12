import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

import {
  isIndependentTask,
  patchTaskCollection,
  rootsForView,
  tasksForRoot,
} from "../src/taskState.js"

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8")

const member = { id: 7 }
const owner = { id: 8 }
const root = {
  id: 1, kind: "item", parent_id: null, owner: owner, owner_claimable: false,
  status: "doing", collaborators: [], deadline: null,
}
const claimOne = {
  id: 2, parent_id: 1, owner: null, owner_claimable: true,
  status: "todo", collaborators: [], deadline: null,
}
const claimTwo = { ...claimOne, id: 3 }
const assignedChild = {
  ...claimOne, id: 4, owner: member, owner_claimable: false,
}
const rows = [root, claimOne, claimTwo, assignedChild]
const independent = {
  id: 5, kind: "task", parent_id: null, owner: null, owner_claimable: true,
  status: "todo", collaborators: [], deadline: null,
}
assert.equal(isIndependentTask(independent), true)
assert.equal(isIndependentTask(root), false)
assert.deepEqual(rootsForView([...rows, independent], "claimable", member.id).map((task) => task.id), [root.id, independent.id])

assert.deepEqual(rootsForView(rows, "claimable", member.id).map((task) => task.id), [root.id])
assert.deepEqual(tasksForRoot(rows, root.id, "claimable", member.id).map((task) => task.id), [claimOne.id, claimTwo.id])
assert.deepEqual(rootsForView(rows, "mine", member.id).map((task) => task.id), [root.id])
assert.deepEqual(tasksForRoot(rows, root.id, "mine", member.id).map((task) => task.id), [assignedChild.id])

const afterFirstClaim = patchTaskCollection(rows.slice(0, 3), { ...claimOne, owner: member }, "claimable", member.id)
assert.deepEqual(rootsForView(afterFirstClaim, "claimable", member.id).map((task) => task.id), [root.id])
assert.deepEqual(tasksForRoot(afterFirstClaim, root.id, "claimable", member.id).map((task) => task.id), [claimTwo.id])
assert.equal(tasksForRoot(afterFirstClaim, root.id, "claimable", member.id).length, 1)

const afterLastClaim = patchTaskCollection(afterFirstClaim, { ...claimTwo, owner: member }, "claimable", member.id)
assert.deepEqual(afterLastClaim, [])
assert.deepEqual(rootsForView(afterLastClaim, "claimable", member.id), [])

const claimableRoot = { ...root, owner: null, owner_claimable: true }
const claimedRootWithOpenChild = patchTaskCollection(
  [claimableRoot, claimOne],
  { ...claimableRoot, owner: member },
  "claimable",
  member.id,
)
assert.equal(claimedRootWithOpenChild.find((task) => task.id === root.id).owner.id, member.id)
assert.deepEqual(tasksForRoot(claimedRootWithOpenChild, root.id, "claimable", member.id).map((task) => task.id), [claimOne.id])
assert.deepEqual(
  patchTaskCollection(claimedRootWithOpenChild, { ...claimOne, owner: member }, "claimable", member.id),
  [],
)

assert.match(app, /const rootTasks = computed\(\(\) => rootsForView\(tasks\.value, taskView\.value, user\.value\?\.id \?\? 0\)\)/)
assert.match(app, /function claimableChildren\(parentId: number\)/)
assert.match(app, /:class="\{ 'claimable-root-card': taskView === 'claimable' \}"/)
assert.match(app, /"总负责人 " \+ task\.owner\.name : "总负责人待认领"/)
assert.match(app, /\{\{ claimableChildren\(task\.id\)\.length \}\} 项待认领/)
assert.match(app, /认领事项负责人/)
assert.match(app, /展开待认领分工 ▾/)
assert.match(app, /收起待认领分工 ▴/)
assert.match(app, /:aria-expanded="isRootExpanded\(task\.id\)"/)
assert.match(app, /v-for="child in \(taskView === 'claimable' \? claimableChildren\(task\.id\) : taskViewChildren\(task\.id\)\)"/)
assert.doesNotMatch(app, /orphanTasks|orphan-task/)

const replace = app.match(/function replaceTaskInState\(updated: Task\)[\s\S]*?\n}/)?.[0]
assert.ok(replace)
assert.match(replace, /patchTaskCollection\(tasks\.value, updated, currentView/)
assert.match(replace, /knownParentContext/)
const claimHandler = app.match(/async function claimTask\(task: Task\)[\s\S]*?\n}/)?.[0]
assert.match(claimHandler, /runTaskAction\(task, "claim", \(\) => api\.claimTask\(task\.id\)\)/)
assert.doesNotMatch(claimHandler, /loadRoute/)

assert.match(css, /\.claimable-root-summary\s*\{[^}]*min-width:\s*0/s)
assert.match(css, /@media \(max-width: 860px\)[\s\S]*?\.claimable-root-summary\s*\{[^}]*flex-direction:\s*column/s)
assert.match(css, /@media \(max-width: 560px\)[\s\S]*?\.child-task-footer\s*\{[^}]*flex-direction:\s*column/s)

console.log("Claimable and mine task views preserve root context and patch groups locally")
