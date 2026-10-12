import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { isExpandedRoot, removeRootAndChildren, toggleExpandedRoot } from "../src/rootItemList.js"

const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8")
const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8")
const confirmDialog = readFileSync(new URL("../src/components/ConfirmDialog.vue", import.meta.url), "utf8")

assert.match(api, /deleteRootTask: \(rootTaskId: number\) =>\s*request<void>\(`\/api\/tasks\/\$\{rootTaskId\}`, \{ method: "DELETE" \}\)/)
assert.match(app, /function openDeleteRootItemModal\(root = detailRoot\.value, origin: "detail" \| "list" = "detail"\)/)
assert.doesNotMatch(app, /危险操作|danger-zone/)
assert.match(app, /requestAppConfirmation\(\{[\s\S]*?title: independent \? "删除独立任务？" : "删除事项？"[\s\S]*?confirmLabel: independent \? "删除任务" : "删除事项"[\s\S]*?danger: true[\s\S]*?action: confirmDeleteRootItem/)
assert.match(confirmDialog, /role="dialog"[\s\S]*?aria-modal="true"/)
assert.match(confirmDialog, /confirmLabel: "删除事项"|confirmLabel\?: string/)
assert.match(confirmDialog, /:class="\{ danger \}"/)
assert.match(app, /if \(origin === "detail"\) \{[\s\S]*?navigateTasks\("all"\)[\s\S]*?\} else \{[\s\S]*?api\.tasks\(taskView\.value\)/)
assert.match(app, /openDeleteRootItemModal\(task, "list"\)/)
assert.match(app, /function handleDetailRootTaskMenuAction\(task: Task, action: string\)[\s\S]*?openDeleteRootItemModal\(task, "detail"\)/)
assert.match(app, /:actions="detailRootTaskMenuActions\(detailTask\)"[\s\S]*?@select="handleDetailRootTaskMenuAction\(detailTask, \$event\)"/)
assert.match(app, /showFeedback\("success", isIndependentTask\(root\) \? "独立任务已删除" : "事项已删除"\)/)
assert.match(app, /itemActivities\.value = \[\][\s\S]*?clearFactSuggestions\(\)[\s\S]*?clearItemReview\(\)/)
assert.doesNotMatch(css, /danger-modal-backdrop|danger-zone/)
assert.match(confirmDialog, /\.confirm-dialog-confirm\.danger\s*\{[^}]*color:\s*var\(--danger\)/s)

const initiallyExpanded = new Set()
assert.equal(isExpandedRoot(initiallyExpanded, 11), false)
const withFirstExpanded = toggleExpandedRoot(initiallyExpanded, 11)
const withBothExpanded = toggleExpandedRoot(withFirstExpanded, 22)
assert.equal(isExpandedRoot(withBothExpanded, 11), true)
assert.equal(isExpandedRoot(withBothExpanded, 22), true)
assert.equal(isExpandedRoot(toggleExpandedRoot(withBothExpanded, 11), 11), false)
assert.equal(isExpandedRoot(toggleExpandedRoot(withBothExpanded, 11), 22), true)

const listStart = app.indexOf('<article v-for="task in rootTasks"')
const rootList = app.slice(listStart, app.indexOf('<div v-else class="empty empty-action empty-state">', listStart))
assert.match(rootList, /<button class="task-title-link" type="button" @click="openTaskDetail\(task\)">/)
assert.match(rootList, /:aria-expanded="isRootExpanded\(task\.id\)"/)
assert.match(rootList, /展开分工 ▾/)
assert.match(rootList, /收起分工 ▴/)
assert.match(rootList, /<span v-else-if="taskView === 'all' && !childTasks\(task\.id\)\.length" class="no-child-tasks">暂无分工<\/span>/)
assert.match(rootList, /<TaskActionMenu[\s\S]*?:actions="rootTaskMenuActions\(task\)"[\s\S]*?@select="handleRootTaskMenuAction\(task, \$event\)"/)
assert.doesNotMatch(rootList, />\s*编辑\s*<\/button>/)
assert.doesNotMatch(rootList, />\s*删除\s*<\/button>/)
assert.match(app, /label: isIndependentTask\(task\) \? "编辑任务" : "编辑事项"/)
assert.match(app, /label: isIndependentTask\(task\) \? "删除任务" : "删除事项"[\s\S]*?danger: true/)
assert.match(rootList, /v-if="\(taskView === 'claimable' \? claimableChildren\(task\.id\)\.length : taskViewChildren\(task\.id\)\.length\) && isRootExpanded\(task\.id\)"[\s\S]*?class="work-breakdown"/)
assert.match(rootList, /root-progress-summary[\s\S]*?executionSummary\(childTasks\(task\.id\)\)\.blocked/)
assert.match(rootList, /<TaskStatusIndicator :status="task\.status"[\s\S]*?:editable="isAdmin && taskView === 'all' && childTasks\(task\.id\)\.length === 0"/)
assert.doesNotMatch(rootList, /status-actions/)
assert.equal((rootList.match(/class="danger-text"/g) ?? []).length, 0)
assert.doesNotMatch(app, /orphanTasks|orphan-task/, "scoped views never render child tasks without their item context")
assert.match(css, /@media \(max-width: 860px\)[\s\S]*?\.operation-card-top\s*\{\s*grid-template-columns: minmax\(0, 1fr\)/)

const tasks = [
  { id: 1, parent_id: null },
  { id: 2, parent_id: 1 },
  { id: 3, parent_id: 1 },
  { id: 4, parent_id: null },
  { id: 5, parent_id: 4 },
]
assert.deepEqual(removeRootAndChildren(tasks, 1).map((task) => task.id), [4, 5])

console.log("Root item list expand/collapse, shared delete confirmation, and API wiring passed")
