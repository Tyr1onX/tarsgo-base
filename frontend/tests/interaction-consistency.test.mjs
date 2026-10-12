import assert from "node:assert/strict"
import { readFileSync } from "node:fs"

const app = readFileSync(new URL("../src/App.vue", import.meta.url), "utf8")
const actionMenu = readFileSync(new URL("../src/components/ActionMenu.vue", import.meta.url), "utf8")
const taskMenu = readFileSync(new URL("../src/TaskActionMenu.vue", import.meta.url), "utf8")
const leave = readFileSync(new URL("../src/pages/SchoolLeavePage.vue", import.meta.url), "utf8")
const dailyLeave = readFileSync(new URL("../src/pages/DailyLeavePage.vue", import.meta.url), "utf8")
const campLeave = readFileSync(new URL("../src/pages/CampLeavePage.vue", import.meta.url), "utf8")
const knowledge = readFileSync(new URL("../src/pages/KnowledgePage.vue", import.meta.url), "utf8")
const team = readFileSync(new URL("../src/pages/TeamPage.vue", import.meta.url), "utf8")
const dropzone = readFileSync(new URL("../src/components/FileDropzone.vue", import.meta.url), "utf8")
const css = readFileSync(new URL("../src/style.css", import.meta.url), "utf8")

// One generic overflow menu owns interaction behavior.
assert.match(actionMenu, /@click="toggle"/)
assert.match(actionMenu, /v-if="open"/)
assert.match(actionMenu, /document\.addEventListener\("pointerdown", onPointerDown\)/)
assert.match(actionMenu, /!root\.value\?\.contains\(event\.target\)/)
assert.match(actionMenu, /event\.key === "Escape"/)
assert.match(actionMenu, /close\(true\)/)
assert.match(actionMenu, /event\.key === "ArrowDown" \|\| event\.key === "ArrowUp"/)
assert.match(actionMenu, /event\.key === "Home" \|\| event\.key === "End"/)
assert.match(actionMenu, /enabledButtons\(\)/)
assert.match(actionMenu, /:disabled="disabled \|\| action\.disabled"/)
assert.match(actionMenu, /:class="\{ danger: action\.danger \}"/)
assert.match(actionMenu, /window\.innerWidth/)
assert.match(actionMenu, /window\.innerHeight/)
assert.match(actionMenu, /openAbove\.value/)
assert.doesNotMatch(taskMenu, /document\.addEventListener|window\.innerWidth|onMenuKeydown/)
assert.match(taskMenu, /<ActionMenu/)

// Task rows keep the core claim CTA visible and put low-frequency actions in one menu.
const normalRootStart = app.indexOf('<div v-else class="operation-card-top">')
const normalRootEnd = app.indexOf('<div v-if="taskView !== \'claimable\'" class="root-breakdown-control">', normalRootStart)
const normalRoot = app.slice(normalRootStart, normalRootEnd)
assert.ok(normalRootStart >= 0 && normalRootEnd > normalRootStart)
assert.equal((normalRoot.match(/class="primary small-action"/g) ?? []).length, 1)
assert.match(normalRoot, /认领事项负责人/)
assert.match(normalRoot, /<TaskActionMenu/)
assert.doesNotMatch(normalRoot, />\s*(?:取消认领|加入协作|退出协作|编辑|删除)\s*<\/button>/)
assert.match(app, /label: isIndependentTask\(task\) \? "删除任务" : "删除事项"[\s\S]*?danger: true/)
assert.match(app, /function handleRootTaskMenuAction/)

// Daily and camp leave use the shared menu for low-frequency document actions.
assert.match(dailyLeave, /<ActionMenu[\s\S]*?aria-label="其他下载选项"/)
assert.match(dailyLeave, /aria-label="共享活动操作"/)
assert.match(dailyLeave, /开启临时公开链接/)
assert.match(campLeave, /<ActionMenu[\s\S]*?aria-label="更多文档下载选项"/)
assert.doesNotMatch(leave, /class="leave-more"/)
assert.match(dailyLeave, /<ConfirmDialog/)

// Knowledge shares FileDropzone and matches backend-established constraints.
assert.match(knowledge, /import FileDropzone/)
assert.match(knowledge, /<FileDropzone/)
assert.match(knowledge, /KNOWLEDGE_UPLOAD_ACCEPT = "\.md,\.txt,\.docx,\.pdf"/)
assert.match(knowledge, /KNOWLEDGE_UPLOAD_MAX_SIZE = 10 \* 1024 \* 1024/)
assert.doesNotMatch(knowledge, /type="file"/)

// Team is browse-first: the row itself opens detail, with no exposed edit action.
assert.match(team, /class="team-member-link"/)
assert.match(team, /emit\('navigate', `\/team\/\$\{member\.id\}`\)/)
assert.match(team, /class="team-member-chevron"/)
assert.doesNotMatch(team, />\s*编辑\s*<\/button>/)
assert.match(team, /:focus-visible/)

// Responsive surfaces stay bounded rather than requiring a wide viewport.
assert.match(css, /\.action-menu\s*\{[^}]*max-width:\s*min\(240px, calc\(100vw - 24px\)\)/s)
assert.match(css, /@media \(max-width: 560px\)[\s\S]*?\.action-menu\s*\{[^}]*max-width:\s*calc\(100vw - 24px\)/s)
assert.match(dropzone, /width:\s*100%/)
assert.match(dropzone, /min-width:\s*0/)
assert.match(knowledge, /class="knowledge-dropzone"/)
assert.doesNotMatch(team + knowledge + leave + dailyLeave + campLeave, /min-width:\s*(?:4\d\d|[5-9]\d\d|\d{4,})px/)

// Root items use a list surface instead of separate floating cards.
assert.match(css, /\.operation-list\s*\{[^}]*border-top:\s*1px solid var\(--line\)/s)
assert.match(css, /\.operation-card\s*\{[^}]*border:\s*0[^}]*border-bottom:\s*1px solid var\(--line\)[^}]*background:\s*transparent/s)

// Existing task status interaction remains in place.
assert.match(app, /<TaskStatusIndicator/)
assert.match(app, /@update-status="updateOwnTaskStatus\(/)

console.log("Interaction consistency, shared menu, upload, browse-first list, and responsive rules passed")
