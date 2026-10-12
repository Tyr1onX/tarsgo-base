import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
const styles = readFileSync(new URL("../src/style.css", import.meta.url), "utf8")
const taskMenu = readFileSync(new URL("../src/TaskActionMenu.vue", import.meta.url), "utf8")
const confirmDialog = readFileSync(new URL("../src/components/ConfirmDialog.vue", import.meta.url), "utf8")

function functionSource(name) {
  const match = app.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}`))
  assert.ok(match, `missing ${name}`)
  return match[0]
}

// Current information is display-only; progress still has a single publishing form.
assert.doesNotMatch(app, /新增一条当前信息|scoped-fact-form|function addCurrentFact/)
assert.match(app, /<h2>当前信息<\/h2>/)
assert.match(app, /<form v-if="canWriteDetailItem" class="activity-entry" @submit\.prevent="recordItemActivity">[\s\S]*?placeholder="记录新动态"[\s\S]*?>发布更新<\/button>/)

// Root activity scope is global. Related AI suggestions without a picked task default to the current child.
assert.match(functionSource("recordItemActivity"), /api\.addItemActivity\(root\.id, content, false, "global", \[\]\)/)
assert.match(app, /const currentTaskId = detailTask\.value\.parent_id === null \? null : detailTask\.value\.id[\s\S]*?return currentTaskId \? \[currentTaskId\]/)
assert.match(functionSource("publishTaskProgress"), /api\.publishTaskProgress\(task\.id, content\)[\s\S]*?extractProgressFacts\(task\.id, published\.task\.parent_id as number, published\.activity, epoch\)/)

// Current facts, work assignments, and activity history each start compact and have one expand/collapse control.
assert.match(app, /detailFactsExpanded\.value \? facts : facts\.slice\(0, 3\)/)
assert.match(app, /visibleDetailFacts[\s\S]*?detailRoot\.item_facts\.length > 3[\s\S]*?展开全部 \$\{detailRoot\.item_facts\.length\} 条/)
assert.match(app, /detailChildrenExpanded\.value \? detailChildren\.value : detailChildren\.value\.slice\(0, 3\)/)
assert.match(app, /v-for="task in visibleDetailChildren"[\s\S]*?detailChildren\.length > 3[\s\S]*?展开全部 \$\{detailChildren\.length\} 项/)
assert.match(app, /detailActivitiesExpanded\.value \? detailTaskActivities\.value : detailTaskActivities\.value\.slice\(0, 3\)/)
assert.match(app, /查看全部进展[\s\S]*?detailActivitiesExpanded && detailActivitiesHasMore[\s\S]*?查看更早进展/)
assert.equal((app.match(/查看全部进展/g) ?? []).length, 2, "root and child detail each have one activity toggle")

// AI review is an item menu action and its result area exists only while checking or when suggestions remain.
assert.match(taskMenu, /ariaLabel\?: string/)
assert.match(app, /:aria-label="isIndependentTask\(detailTask\) \? '独立任务更多操作' : '事项更多操作'"[\s\S]*?:actions="detailRootTaskMenuActions\(detailTask\)"/)
assert.match(app, /key: "review",\s*label: "检查当前方案"/)
assert.match(app, /v-if="itemReviewLoading \|\| itemReviewSuggestions\.length" class="execution-section ai-review-section"/)
assert.doesNotMatch(app, /让 AI 检查方案|class="review-trigger"/)
assert.match(functionSource("reviewCurrentItemPlan"), /else notice\.value = "方案检查完成，暂未发现调整建议"/)
assert.match(functionSource("dismissItemReviewSuggestion"), /if \(!itemReviewSuggestions\.value\.length\) itemReviewSummary\.value = ""/)

// Delete is absent from the detail body and opens the shared dangerous confirmation from its action menu.
assert.doesNotMatch(app, /危险操作|danger-zone/)
assert.match(app, /key: "delete",\s*label: isIndependentTask\(task\) \? "删除任务" : "删除事项"[\s\S]*?danger: true/)
assert.match(functionSource("handleDetailRootTaskMenuAction"), /openDeleteRootItemModal\(task, "detail"\)/)
assert.match(functionSource("openDeleteRootItemModal"), /requestAppConfirmation\([\s\S]*?danger: true[\s\S]*?action: confirmDeleteRootItem/)
assert.match(app, /<ConfirmDialog[\s\S]*?@confirm="confirmAppConfirmation"/)
assert.match(confirmDialog, /role="dialog"[\s\S]*?aria-modal="true"/)

// Detail controls stay bounded at 400px, including long titles, action menus, and wrapped activity text.
assert.match(styles, /\.execution-detail-heading\s*\{[^}]*min-width:\s*0/s)
assert.match(styles, /\.execution-detail-heading h1\s*\{[^}]*overflow-wrap:\s*anywhere/s)
assert.match(styles, /\.action-menu\s*\{[^}]*max-width:\s*min\(240px, calc\(100vw - 24px\)\)/s)
assert.match(styles, /\.activity-row p\s*\{[^}]*overflow-wrap:\s*anywhere/s)
assert.match(styles, /@media \(max-width: 560px\)[\s\S]*?\.execution-detail-heading\s*\{[^}]*align-items:\s*flex-start/s)
assert.doesNotMatch(styles, /min-width:\s*(?:4\d\d|[5-9]\d\d|\d{4,})px\s*;/)

// Existing task detail workflows remain wired: status, owner, deadline, result, progress, extraction, and pagination.
assert.match(app, /<TaskStatusIndicator[\s\S]*?detailTask\.owner[\s\S]*?detailTask\.deadline/)
assert.match(app, /detailProgress\.done \/ detailProgress\.total/)
assert.match(app, /@click="openTaskDetail\(task\)"/)
assert.match(app, /api\.publishTaskProgress\(task\.id, content\)/)
assert.match(app, /api\.extractActivityFacts\(rootTaskId, activity\.id\)/)
assert.match(app, /api\.completeTask\(task\.id, result, syncToItem\)/)
assert.match(app, /api\.updateTask\(task\.id, \{ result: taskResultDraft\.value \}\)/)
assert.match(app, /api\.itemActivityPage\(root\.id, selected\.parent_id === null \? undefined : selected\.id, 20, beforeId\)/)
assert.match(app, /api\.deleteRootTask\(root\.id\)/)

console.log("Task detail simplification, defaults, compact lists, review menu, shared delete confirmation, and mobile rules passed")
