import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

import { itemReviewChanges, removeItemReviewSuggestion } from "../src/itemReview.js"

const appSource = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
assert.match(appSource, /v-if="plannerDraft\.suggestions\.length"/)
assert.match(appSource, /@click="dismissPlannerSuggestion\(index\)"/)
assert.doesNotMatch(appSource, /addPlannerSuggestion|refineAIPlan|planner-global-refine/)
assert.doesNotMatch(appSource, /v-model="plannerDraft\.item\.deliverable"/)
assert.match(appSource, /做到什么算完成/)
assert.match(appSource, /<h3>执行提示<\/h3>/)
assert.match(appSource, /＋ 添加注意/)
assert.match(appSource, /开始前需要/)
assert.match(appSource, /＋ 添加开始条件/)
assert.match(appSource, /taskDetailSections\(task: Task\)[\s\S]*?title: "执行提示"[\s\S]*?title: "开始前需要"/)
assert.ok(appSource.includes('<summary>{{ taskEditorShowsExecutionFields ? "执行说明与协作设置" : "协作设置" }}</summary>'))

const reviewChanges = itemReviewChanges(
  {
    title: "现场布展",
    deliverable: "设备完成布置。",
    execution_points: ["按活动流程布置"],
    cautions: [],
    prerequisites: [],
  },
  {
    title: "现场布展",
    deliverable: "设备完成布置。",
    execution_points: ["按主办方要求提前 20 分钟完成布展"],
    cautions: [],
    prerequisites: [],
  },
)
assert.deepEqual(reviewChanges.map((change) => change.field), ["execution_points"])
assert.equal(reviewChanges[0].label, "执行提示")
assert.deepEqual(
  removeItemReviewSuggestion([{ key: "one" }, { key: "two" }], "one").map((item) => item.key),
  ["two"],
)
assert.match(appSource, /label: "检查当前方案"/)
assert.match(appSource, /itemReviewLoading\.value/)
assert.match(appSource, /方案检查完成，暂未发现调整建议/)
assert.match(appSource, /reviewItemPlan\(root\.id\)/)
assert.match(appSource, /applyItemReview\(root\.id, entry\.suggestion\)/)
assert.match(appSource, /removeItemReviewSuggestion\(itemReviewSuggestions\.value, entry\.key\)/)
assert.match(appSource, /clearItemReview\(\)/)
assert.match(appSource, /itemReviewChanges\(current, suggestion\.proposed_task\)/)
assert.match(appSource, /detailTask\.parent_id === null/)
assert.match(appSource, /entry\.suggestion\.kind === "add_task" \? "新增任务" : "调整现有任务"/)
assert.match(appSource, /entry\.suggestion\.kind === 'update_task'/)
assert.match(appSource, /entry\.suggestion\.proposed_task\.title/)
assert.match(readFileSync(new URL("../src/style.css", import.meta.url), "utf8"), /@media \(max-width: 560px\)[\s\S]*?\.ai-review-values \{[\s\S]*?grid-template-columns: minmax\(0, 1fr\)/)
const functionSource = (name) => {
  const match = appSource.match(new RegExp(`(?:async )?function ${name}\\b[\\s\\S]*?\\n}`))
  assert.ok(match, `missing ${name}`)
  return match[0]
}
for (const mutation of [
  "saveTaskResult",
  "removeCurrentFact",
  "recordItemActivity",
  "addResultToContext",
  "submitTask",
]) {
  assert.match(functionSource(mutation), /clearItemReview\(\)/, `${mutation} should clear stale review results`)
}
assert.match(functionSource("runTaskAction"), /clearItemReview\(\)/, "task actions should clear stale review results after successful patch")
assert.doesNotMatch(functionSource("dismissItemReviewSuggestion"), /api\./)
assert.match(functionSource("applyItemReviewSuggestion"), /api\.applyItemReview/)
assert.doesNotMatch(functionSource("applyItemReviewSuggestion"), /generateAIPlan|reviewItemPlan/)
assert.equal([...functionSource("applyItemReviewSuggestion").matchAll(/api\./g)].length, 1)

console.log("Published item review frontend tests passed")
