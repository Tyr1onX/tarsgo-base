<script setup lang="ts">
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue"

import { ApiError, api } from "./api"
import { clearAsyncRouteRecovery, handleAsyncRouteResourceError } from "./asyncRouteRecovery.js"
import { recentBaseChanges } from "./baseHome.js"
import { buildExternalAIPlannerPrompt, parseExternalAIPlannerDraft } from "./externalAIPlanner.js"
import { revealInvalidField } from "./formFeedback.js"
import { itemReviewChanges, removeItemReviewSuggestion } from "./itemReview.js"
import { isExpandedRoot, removeRootAndChildren, toggleExpandedRoot } from "./rootItemList.js"
import { parseTaskEditorRoute, taskEditorCancelPath, taskEditorSuccessPath, taskEditorTitle } from "./taskRoutes.js"
import TaskStatusIndicator from "./TaskStatusIndicator.vue"
import TaskActionMenu, { type TaskActionMenuItem } from "./TaskActionMenu.vue"
import ConfirmDialog from "./components/ConfirmDialog.vue"
import CollegeSelect from "./components/CollegeSelect.vue"
import MemberSearchFilters from "./components/MemberSearchFilters.vue"
import AsyncRouteLoadError from "./pages/AsyncRouteLoadError.vue"
import LocalPageLoading from "./pages/LocalPageLoading.vue"
import { filterMembers } from "./memberSearch.js"
import {
  claimableTask,
  compareTaskDeadlines,
  isIndependentTask,
  mergeRecentActivities,
  patchTaskCollection,
  prependUniqueActivity,
  rootsForView,
  setPendingTaskAction,
  tasksForRoot,
} from "./taskState.js"
import {
  defaultFactSelection,
  executionSummary,
  isCurrentFactSuggestionRequest,
  preserveEditableDraft,
  sourceTaskTitle,
} from "./execution.js"
import type {
  AIPlannerDraft,
  AIPlannerExtractedFile,
  AIPlannerSuggestionDraft,
  AIPlannerTaskDraft,
  AIReviewAccess,
  AIItemReviewSuggestion,
  AIItemFactSuggestion,
  CollegeOption,
  InvitationInfo,
  InviteResult,
  ItemActivity,
  ItemFact,
  ItemFactInput,
  ItemFactScope,
  KnowledgeDocument,
  KnowledgeSyncSummary,
  Member,
  MemberProfilePayload,
  MemberSummary,
  TaskAssigneeOption,
  Role,
  TeamGroup,
  TeamMembership,
  TeamRegistrationInfo,
  TeamRegistrationWindow,
  Task,
  TaskStatus,
  TaskView,
} from "./types"

const path = ref(window.location.pathname)
const taskEditor = computed(() => parseTaskEditorRoute(path.value))
const isTaskEditorRoute = computed(() => taskEditor.value !== null)
const taskEditorLoading = ref(false)
let initializedTaskEditorPath = ""
function defineLazyPage(loader: () => Promise<{ default: import("vue").Component }>) {
  return defineAsyncComponent({
    loader: async () => {
      const page = await loader()
      clearAsyncRouteRecovery()
      return page
    },
    loadingComponent: LocalPageLoading,
    errorComponent: AsyncRouteLoadError,
    delay: 120,
    onError(error, _retry, fail) {
      if (handleAsyncRouteResourceError(error) !== "reloading") fail()
    },
  })
}

const TeamPage = defineLazyPage(() => import("./pages/TeamPage.vue"))
const MemberDetailPage = defineLazyPage(() => import("./pages/MemberDetailPage.vue"))
const KnowledgePage = defineLazyPage(() => import("./pages/KnowledgePage.vue"))
const SchoolLeavePage = defineLazyPage(() => import("./pages/SchoolLeavePage.vue"))
const CampLeavePublicPage = defineLazyPage(() => import("./pages/CampLeavePublicPage.vue"))
const DailyLeavePublicPage = defineLazyPage(() => import("./pages/DailyLeavePublicPage.vue"))
const campLeavePublicToken = computed(() => path.value.match(/^\/leave\/camp\/([A-Za-z0-9_-]+)$/)?.[1] ?? "")
const isCampLeavePublicRoute = computed(() => path.value.startsWith("/leave/camp/"))
const dailyLeavePublicToken = computed(() => path.value.match(/^\/leave\/daily\/([A-Za-z0-9_-]+)$/)?.[1] ?? "")
const isDailyLeavePublicRoute = computed(() => path.value.startsWith("/leave/daily/"))
const user = ref<Member | null>(null)
const loading = ref(true)
const initialRouteResolved = ref(false)
const routeNotFound = ref(false)
const error = ref("")
const notice = ref("")
const fieldErrors = ref<Record<string, string>>({})
const feedback = ref<{ kind: "success" | "error" | "info"; message: string } | null>(null)
let feedbackTimer: number | undefined

interface ConfirmRequest {
  title: string
  description: string
  confirmLabel: string
  danger?: boolean
  action: () => Promise<void> | void
}

const appConfirm = ref<ConfirmRequest | null>(null)
const appConfirmPending = ref(false)

const loginEmail = ref("")
const loginPassword = ref("")
const studentIdDraft = ref("")
const teamGroupDraft = ref<TeamGroup | "">("")
const collegeDraft = ref("")
const collegeOptions = ref<CollegeOption[]>([])
const profileFieldErrors = ref<Record<string, string>>({})
const memberProfileFieldErrors = ref<Record<number, Record<string, string>>>({})
const profileSaving = ref(false)

const invitation = ref<InvitationInfo | null>(null)
const invitePassword = ref("")
const invitePasswordConfirm = ref("")

const registrationInfo = ref<TeamRegistrationInfo | null>(null)
const registrationChecking = ref(false)
const registrationEnded = ref(false)
const registrationLoadError = ref("")
const registrationName = ref("")
const registrationStudentId = ref("")
const registrationCollege = ref("")
const registrationEmail = ref("")
const registrationTeamGroup = ref<TeamGroup | "">("")
const registrationFieldErrors = ref<Record<string, string>>({})
const registrationPassword = ref("")
const registrationPasswordConfirm = ref("")
const registrationSubmitting = ref(false)
const registrationWindow = ref<TeamRegistrationWindow | null>(null)
const registrationPath = ref("")
const openingRegistration = ref(false)
const closingRegistration = ref(false)
const schoolLeaveTodoCount = ref(0)

const tasks = ref<Task[]>([])
const homeMineTasks = ref<Task[]>([])
const homeAllTasks = ref<Task[]>([])
const baseRecentActivities = ref<ItemActivity[]>([])
const itemActivities = ref<ItemActivity[]>([])
const detailActivitiesHasMore = ref(false)
const detailActivitiesNextBeforeId = ref<number | null>(null)
const loadingEarlierActivities = ref(false)
const detailActivitiesExpanded = ref(false)
const detailFactsExpanded = ref(false)
const detailChildrenExpanded = ref(false)
const detailContextLoading = ref(false)
const members = ref<Member[]>([])
const taskMembers = ref<TaskAssigneeOption[]>([])
const taskMembersLoaded = ref(false)
const pendingTaskActions = ref<Map<number, string>>(new Map())
const latestInvite = ref<InviteResult | null>(null)
const memberProfileSavingId = ref<number | null>(null)
const taskView = ref<TaskView>("mine")
const tasksLoadedScope = ref<TaskView | null>(null)
const taskListLoading = ref(false)
const taskListLoadError = ref(false)
const deletingRootItem = ref(false)
const deleteTargetRootId = ref<number | null>(null)
const deleteRootOrigin = ref<"detail" | "list">("detail")
const expandedRootIds = ref(new Set<number>())
const claimableCount = ref(0)
const aiReviewAvailable = ref(false)
const plannerDescription = ref("")
const plannerAttachments = ref<{ id: string; filename: string; extracted_text: string }[]>([])
const plannerAttachmentMessage = ref("")
const plannerImportOpen = ref(false)
const plannerImportJson = ref("")
const plannerImportError = ref("")
const plannerExternalMessage = ref("")
const plannerUploading = ref(false)
const plannerDragActive = ref(false)
const plannerFileInput = ref<HTMLInputElement | null>(null)
const plannerDraft = ref<AIPlannerDraft | null>(null)
const plannerPublishing = ref(false)
const plannerTaskDetailsText = ref<{ execution_points: string; cautions: string; prerequisites: string }[]>([])
const plannerSelectedTaskIndex = ref<number | null>(null)
const plannerNewTaskIndex = ref<number | null>(null)
const plannerEmptyDetailSection = ref<"execution_points" | "cautions" | "prerequisites" | null>(null)
const plannerDetailScrollTop = ref(0)
const plannerDetailCloseButton = ref<HTMLButtonElement | null>(null)
const plannerDetailBackButton = ref<HTMLButtonElement | null>(null)
const plannerDetailTitleInput = ref<HTMLInputElement | null>(null)
const plannerAddTaskButton = ref<HTMLButtonElement | null>(null)
const knowledgeDocuments = ref<KnowledgeDocument[]>([])
const knowledgeUploading = ref(false)
const knowledgeSyncing = ref(false)
const knowledgeSyncSummary = ref<KnowledgeSyncSummary | null>(null)

const itemActivityDraft = ref("")
const editingFactScopeId = ref<number | null>(null)
const editingFactScope = ref<ItemFactScope>("global")
const editingFactTaskIds = ref<number[]>([])
const savingFactScopeId = ref<number | null>(null)
const taskResultDraft = ref("")
const taskProgressDraft = ref("")
const taskCompletionDraft = ref("")
const taskCompletionSync = ref(false)
const taskProgressSaving = ref(false)
const taskCompletionSaving = ref(false)
const factExtractionLoading = ref(false)
const factSuggestions = ref<AIItemFactSuggestion[]>([])
const selectedFactSuggestions = ref<string[]>([])
const confirmedFactSupersessions = ref<string[]>([])
const factSuggestionActivityId = ref<number | null>(null)
const itemReviewSummary = ref("")
const itemReviewSuggestions = ref<{ key: string; suggestion: AIItemReviewSuggestion }[]>([])
const itemReviewLoading = ref(false)
const itemReviewApplyingKey = ref("")
let itemReviewEpoch = 0
let factExtractionEpoch = 0
let collaborationRefreshTimer: number | undefined
let collaborationRefreshInFlight = false
let lastCollaborationRefreshAt = 0
let routeLoadSequence = 0
let taskMembersRequest: Promise<TaskAssigneeOption[]> | null = null

const taskSaving = ref(false)
const taskTitle = ref("")
const taskDeliverable = ref("")
const taskExecutionPointsText = ref("")
const taskCautionsText = ref("")
const taskPrerequisitesText = ref("")
const taskCautionsOpen = ref(false)
const taskPrerequisitesOpen = ref(false)
const taskOwnerMode = ref<"assigned" | "claimable">("assigned")
const taskOwnerId = ref<number | null>(null)
const taskOwnerSearch = ref("")
const taskOwnerGroupFilter = ref("")
const taskOwnerClaimable = ref(false)
const taskCollaboratorIds = ref<number[]>([])
const taskCollaboratorSearch = ref("")
const taskCollaboratorGroupFilter = ref("")
const taskCollaborationOpen = ref(false)
const taskDeadline = ref("")
const taskStatus = ref<TaskStatus>("todo")
const taskDependencyIds = ref<number[]>([])

const isAdmin = computed(() => user.value?.role === "admin")
const inviteToken = computed(() =>
  path.value.startsWith("/invite/") ? path.value.slice("/invite/".length) : "",
)
const registerToken = computed(() =>
  path.value.startsWith("/register/") ? path.value.slice("/register/".length) : "",
)
const activeMembers = computed(() => taskMembers.value)
const activeMemberIds = computed(() => new Set(activeMembers.value.map((member) => member.id)))
const editingTaskId = computed(() => taskEditor.value?.kind === "edit" ? taskEditor.value.taskId : null)
const editingTask = computed(() =>
  editingTaskId.value === null ? null : tasks.value.find((task) => task.id === editingTaskId.value) ?? null,
)
const plannerSelectedTask = computed(() => {
  const index = plannerSelectedTaskIndex.value
  return index === null ? null : plannerDraft.value?.tasks[index] ?? null
})
const parentTaskId = computed(() => {
  if (taskEditor.value?.kind === "new-child") return taskEditor.value.parentId
  if (taskEditor.value?.kind === "edit" && editingTask.value?.parent_id !== null) {
    return editingTask.value?.parent_id ?? null
  }
  return null
})
const parentTask = computed(() =>
  parentTaskId.value === null ? null : tasks.value.find((task) => task.id === parentTaskId.value) ?? null,
)
const taskEditorHeading = computed(() =>
  editingTask.value && isIndependentTask(editingTask.value)
    ? "编辑独立任务"
    : taskEditorTitle(taskEditor.value, editingTask.value?.parent_id !== null && editingTask.value !== null),
)
const taskEditorShowsExecutionFields = computed(() =>
  parentTaskId.value !== null || taskEditor.value?.kind === "new-task" ||
  Boolean(editingTask.value && isIndependentTask(editingTask.value)),
)
const ownerOptions = computed<TaskAssigneeOption[]>(() => {
  const options = [...activeMembers.value]
  const owner = editingTask.value?.owner
  if (owner && !activeMemberIds.value.has(owner.id)) {
    options.unshift({ ...owner, team_group: null })
  }
  return options
})
const filteredOwnerOptions = computed(() =>
  filterMembers(ownerOptions.value, taskOwnerSearch.value, taskOwnerGroupFilter.value)
    .filter((member) => !taskOwnerGroupFilter.value || activeMemberIds.value.has(member.id)),
)
const selectedTaskOwner = computed(() =>
  ownerOptions.value.find((member) => member.id === taskOwnerId.value) ?? null,
)
const filteredCollaborators = computed(() =>
  filterMembers(activeMembers.value, taskCollaboratorSearch.value, taskCollaboratorGroupFilter.value)
    .filter((member) => member.id !== taskOwnerId.value),
)
const taskDetailId = computed(() => {
  const match = path.value.match(/^\/tasks\/(\d+)$/)
  return match ? Number(match[1]) : null
})
const teamMemberDetailId = computed(() => {
  const match = path.value.match(/^\/team\/(\d+)$/)
  return match ? Number(match[1]) : null
})
const teamMemberDetail = computed(() =>
  teamMemberDetailId.value === null
    ? null
    : members.value.find((member) => member.id === teamMemberDetailId.value) ?? null,
)
const isTeamRoute = computed(() => path.value === "/team" || teamMemberDetailId.value !== null)
const isMeRoute = computed(() => path.value === "/me" || path.value === "/me/edit")
const myProfileChanged = computed(() =>
  studentIdDraft.value.trim() !== (user.value?.student_id ?? "") ||
  teamGroupDraft.value !== (user.value?.team_group ?? "") ||
  collegeDraft.value !== (user.value?.college ?? ""),
)
const detailTask = computed(() =>
  taskDetailId.value === null ? null : tasks.value.find((task) => task.id === taskDetailId.value) ?? null,
)
const detailRoot = computed(() => {
  const task = detailTask.value
  if (!task) return null
  return task.parent_id === null
    ? task
    : tasks.value.find((candidate) => candidate.id === task.parent_id) ?? null
})
const detailChildren = computed(() =>
  detailRoot.value ? tasks.value.filter((task) => task.parent_id === detailRoot.value?.id) : [],
)
const visibleDetailChildren = computed(() =>
  detailChildrenExpanded.value ? detailChildren.value : detailChildren.value.slice(0, 3),
)
const detailProgress = computed(() => executionSummary(detailChildren.value))
const recentItemFacts = computed(() => [...(detailTask.value?.item_facts ?? [])].slice(-4).reverse())
const visibleDetailFacts = computed(() => {
  const facts = [...(detailRoot.value?.item_facts ?? [])].reverse()
  return detailFactsExpanded.value ? facts : facts.slice(0, 3)
})
const detailTaskActivities = computed(() =>
  itemActivities.value,
)
const canManageFactScope = computed(() => Boolean(
  detailRoot.value && (isAdmin.value || detailRoot.value.owner?.id === user.value?.id),
))
const canWriteDetailItem = computed(() => {
  const root = detailRoot.value
  const currentId = user.value?.id
  if (!root || !currentId) return false
  if (isAdmin.value || root.owner?.id === currentId) return true
  return detailChildren.value.some(
    (task) => task.owner?.id === currentId || task.collaborators.some((member) => member.id === currentId),
  )
})
const canEditDetailResult = computed(
  () => Boolean(detailTask.value && isAdmin.value),
)
const canPublishTaskProgress = computed(() => {
  const task = detailTask.value
  const currentId = user.value?.id
  return Boolean(
    task && (task.parent_id !== null || isIndependentTask(task)) && task.status !== "done" && !task.blocked && currentId &&
    (isAdmin.value || task.owner?.id === currentId || task.collaborators.some((person) => person.id === currentId)),
  )
})
const canCompleteDetailTask = computed(() =>
  Boolean(detailTask.value && (detailTask.value.parent_id !== null || isIndependentTask(detailTask.value)) && detailTask.value.status !== "done" && !detailTask.value.blocked &&
    (isAdmin.value || detailTask.value.owner?.id === user.value?.id)),
)
const availableDependencyTasks = computed(() =>
  parentTaskId.value === null
    ? []
    : tasks.value.filter((task) => task.parent_id === parentTaskId.value && task.id !== editingTaskId.value),
)

const homeOpenTasks = computed(() => homeMineTasks.value.filter((task) => task.status !== "done"))
const homeTaskCards = computed(() => {
  const allChildren = new Set(
    homeAllTasks.value.filter((task) => task.parent_id !== null).map((task) => task.parent_id as number),
  )
  const children = homeOpenTasks.value.filter((task) => task.parent_id !== null)
  const standaloneRoots = homeOpenTasks.value.filter(
    (task) => task.parent_id === null && !allChildren.has(task.id),
  )
  return [...children, ...standaloneRoots].sort(compareTaskDeadlines)
})
const visibleHomeTaskCards = computed(() => homeTaskCards.value.slice(0, 3))
const homeRecentChanges = computed(() => recentBaseChanges(
  homeAllTasks.value,
  homeMineTasks.value,
  baseRecentActivities.value,
  user.value?.id ?? 0,
))
const rootTasks = computed(() => rootsForView(tasks.value, taskView.value, user.value?.id ?? 0))
const deleteTargetRoot = computed(() =>
  tasks.value.find((task) => task.id === deleteTargetRootId.value && task.parent_id === null) ?? null,
)

const statusLabels: Record<TaskStatus, string> = {
  todo: "待开始",
  doing: "进行中",
  done: "已完成",
}
const reviewProposalSections = [
  { label: "执行提示", field: "execution_points" },
  { label: "注意事项", field: "cautions" },
  { label: "开始前需要", field: "prerequisites" },
] as const

const roleLabels: Record<Role, string> = {
  admin: "管理员",
  member: "成员",
}

const groupLabels: Record<TeamGroup, string> = {
  electrical: "电控组",
  mechanical: "机械组",
  vision: "视觉组",
  ai: "AI组",
  operations: "运营组",
}

function taskMemberGroupLabel(member: MemberSummary & { team_group?: TeamGroup | null }) {
  if (!activeMemberIds.value.has(member.id)) return "现有负责人"
  return member.team_group ? groupLabels[member.team_group] : "组别未填写"
}

const membershipLabels: Record<TeamMembership, string> = {
  formal: "正式队员",
  reserve: "梯队成员",
}

const viewLabels: Record<TaskView, string> = {
  mine: "我的",
  claimable: "待认领",
  all: "全部",
}

function messageOf(reason: unknown): string {
  return reason instanceof Error ? reason.message : "操作失败"
}

function requestAppConfirmation(request: ConfirmRequest) {
  if (appConfirmPending.value) return
  appConfirm.value = request
}

function cancelAppConfirmation() {
  if (appConfirmPending.value) return
  appConfirm.value = null
}

async function confirmAppConfirmation() {
  const request = appConfirm.value
  if (!request || appConfirmPending.value) return
  appConfirmPending.value = true
  try {
    await request.action()
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    appConfirmPending.value = false
    appConfirm.value = null
  }
}

function clearFeedback() {
  if (feedbackTimer !== undefined) window.clearTimeout(feedbackTimer)
  feedbackTimer = undefined
  feedback.value = null
}

function showFeedback(kind: "success" | "error" | "info", message: string) {
  clearFeedback()
  feedback.value = { kind, message }
  if (kind !== "error") {
    feedbackTimer = window.setTimeout(clearFeedback, 3_500)
  } else {
    feedbackTimer = window.setTimeout(clearFeedback, 7_000)
  }
}

watch(error, (message) => {
  if (message) showFeedback("error", message)
})
watch(notice, (message) => {
  if (message) showFeedback("success", message)
})
watch(path, (nextPath, previousPath) => {
  if (nextPath === previousPath) return
  fieldErrors.value = {}
  profileFieldErrors.value = {}
  registrationFieldErrors.value = {}
  error.value = ""
  if (feedback.value?.kind === "error") clearFeedback()
})

function clearFieldError(field: string) {
  if (!fieldErrors.value[field]) return
  const next = { ...fieldErrors.value }
  delete next[field]
  fieldErrors.value = next
}

async function showFieldError(field: string, toastMessage: string, inlineMessage: string) {
  fieldErrors.value = { ...fieldErrors.value, [field]: inlineMessage }
  error.value = toastMessage
  if (field.startsWith("planner-item-")) {
    document.querySelector<HTMLDetailsElement>(".planner-item-edit")?.setAttribute("open", "")
  }
  const taskTitleMatch = field.match(/^planner-task-title-(\d+)$/)
  if (taskTitleMatch) plannerSelectedTaskIndex.value = Number(taskTitleMatch[1])
  if (field === "planner-task-details") {
    const match = toastMessage.match(/第 (\d+) 项(怎么做|注意|开始前需要)/)
    if (match) {
      plannerSelectedTaskIndex.value = Number(match[1]) - 1
      plannerEmptyDetailSection.value = match[2] === "怎么做" ? "execution_points" :
        match[2] === "注意" ? "cautions" : "prerequisites"
    }
  }
  await nextTick()
  const targetField = field === "planner-task-details" ?
    plannerEmptyDetailSection.value === "execution_points" ? "planner-execution-points" :
      plannerEmptyDetailSection.value === "cautions" ? "planner-cautions" : "planner-prerequisites" : field
  revealInvalidField(document, targetField)
}

function ensureFactRelatedSelection(scope: ItemFactScope, taskIds: number[]) {
  if (scope !== "related" || taskIds.length || !detailTask.value) return taskIds
  const currentTaskId = detailTask.value.parent_id === null ? null : detailTask.value.id
  return currentTaskId ? [currentTaskId] : detailChildren.value.slice(0, 1).map((task) => task.id)
}

function ensureFactSuggestionTasks(index: number) {
  const suggestion = factSuggestions.value[index]
  if (!suggestion || suggestion.scope !== "related" || suggestion.related_task_ids.length) return
  suggestion.related_task_ids = ensureFactRelatedSelection("related", [])
}

function factScopeDescription(fact: ItemFact) {
  if (fact.scope === "global") return "整个事项"
  return `相关工作 · ${fact.related_tasks.map((task) => task.title).join("、")}`
}

const visibleDetailActivities = computed(() =>
  detailActivitiesExpanded.value ? detailTaskActivities.value : detailTaskActivities.value.slice(0, 3),
)

function navigate(nextPath: string, options: { replace?: boolean } = {}) {
  const nextRoute = nextPath.split("?")[0]
  if (path.value !== nextRoute && isTaskEditorRoute.value) initializedTaskEditorPath = ""
  const wasTaskDetail = /^\/tasks\/\d+$/.test(path.value)
  const isNextTaskDetail = /^\/tasks\/\d+$/.test(nextRoute)
  if (path.value !== nextRoute && (wasTaskDetail || isNextTaskDetail)) {
    clearFactSuggestions()
    taskProgressDraft.value = ""
    taskCompletionDraft.value = ""
    taskCompletionSync.value = false
  }
  if (taskDetailId.value !== null && nextRoute !== path.value) clearItemReview()
  if (window.location.pathname + window.location.search !== nextPath) {
    if (options.replace) window.history.replaceState({}, "", nextPath)
    else window.history.pushState({}, "", nextPath)
  }
  path.value = window.location.pathname
  syncCollaborationRefreshTimer()
  error.value = ""
  fieldErrors.value = {}
  if (feedback.value?.kind === "error") clearFeedback()
  void loadRoute()
}

function clearItemReview() {
  itemReviewEpoch += 1
  itemReviewSummary.value = ""
  itemReviewSuggestions.value = []
  itemReviewApplyingKey.value = ""
}

function clearFactSuggestions() {
  factExtractionEpoch += 1
  factSuggestions.value = []
  selectedFactSuggestions.value = []
  confirmedFactSupersessions.value = []
  factSuggestionActivityId.value = null
  factExtractionLoading.value = false
}

async function refreshExecutionScene(force = false) {
  const taskId = taskDetailId.value
  const selected = detailTask.value
  if (taskId === null || !selected || document.visibilityState !== "visible" || collaborationRefreshInFlight) return
  const now = Date.now()
  if (!force && now - lastCollaborationRefreshAt < 2_000) return
  lastCollaborationRefreshAt = now
  collaborationRefreshInFlight = true
  const routeAtStart = path.value
  try {
    const context = await api.taskContext(taskId)
    if (path.value !== routeAtStart || taskDetailId.value !== taskId) return
    const previousTask = tasks.value.find((task) => task.id === taskId)
    const resultDraftDirty = Boolean(previousTask && taskResultDraft.value !== (previousTask.result ?? ""))
    tasks.value = [context.root, ...context.tasks]
    const refreshedTask = tasks.value.find((task) => task.id === taskId)
    if (refreshedTask) {
      taskResultDraft.value = preserveEditableDraft(
        taskResultDraft.value,
        refreshedTask.result ?? "",
        resultDraftDirty,
      )
    }
    itemActivities.value = mergeRecentActivities(itemActivities.value, context.activity_page.items)
    detailActivitiesHasMore.value = detailActivitiesHasMore.value || context.activity_page.has_more
    if (detailActivitiesNextBeforeId.value === null) {
      detailActivitiesNextBeforeId.value = context.activity_page.next_before_id
    }
  } catch {
    // Background refresh is best effort; preserve the current view and draft text.
  } finally {
    collaborationRefreshInFlight = false
  }
}

function replaceTaskInState(updated: Task) {
  const previous = homeAllTasks.value.find((task) => task.id === updated.id)
    ?? tasks.value.find((task) => task.id === updated.id)
  const wasClaimable = Boolean(previous && claimableTask(previous))
  const fullCurrentTaskSet = taskDetailId.value !== null || (path.value === "/tasks" && taskView.value === "all")
  const currentView = taskDetailId.value !== null ? "all" : taskView.value
  const knownParentContext = updated.parent_id === null
    ? null
    : [...tasks.value, ...homeAllTasks.value, ...homeMineTasks.value].find(
        (task) => task.id === updated.parent_id && task.parent_id === null,
      ) ?? null
  tasks.value = patchTaskCollection(tasks.value, updated, currentView, user.value?.id ?? 0, fullCurrentTaskSet, knownParentContext)
  homeMineTasks.value = patchTaskCollection(homeMineTasks.value, updated, "mine", user.value?.id ?? 0, false, knownParentContext)
  homeAllTasks.value = patchTaskCollection(homeAllTasks.value, updated, "all", user.value?.id ?? 0, true, knownParentContext)
  const isClaimable = claimableTask(updated)
  if (previous && wasClaimable !== isClaimable) {
    claimableCount.value = Math.max(0, claimableCount.value + (isClaimable ? 1 : -1))
  } else if (!previous && isClaimable && path.value === "/") {
    claimableCount.value += 1
  }
}

function patchRootFactsInCollection(collection: Task[], updatedRoot: Task) {
  return collection.map((task) => {
    if (task.id === updatedRoot.id) return updatedRoot
    if (task.parent_id !== updatedRoot.id) return task
    const visibleFacts = updatedRoot.item_facts.filter((fact) =>
      fact.scope === "global" || fact.related_tasks.some((related) => related.id === task.id),
    )
    return { ...task, item_facts: visibleFacts, context_facts: visibleFacts.map((fact) => fact.content) }
  })
}

function replaceRootFactsInState(updatedRoot: Task) {
  tasks.value = patchRootFactsInCollection(tasks.value, updatedRoot)
  homeMineTasks.value = patchRootFactsInCollection(homeMineTasks.value, updatedRoot)
  homeAllTasks.value = patchRootFactsInCollection(homeAllTasks.value, updatedRoot)
}

function pendingTaskAction(taskId: number) {
  return pendingTaskActions.value.get(taskId) ?? ""
}

async function runTaskAction(task: Task, action: string, request: () => Promise<Task>) {
  if (pendingTaskAction(task.id)) return
  error.value = ""
  pendingTaskActions.value = setPendingTaskAction(pendingTaskActions.value, task.id, action)
  try {
    const updated = await request()
    replaceTaskInState(updated)
    clearItemReview()
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    pendingTaskActions.value = setPendingTaskAction(pendingTaskActions.value, task.id, null)
  }
}

async function loadEarlierDetailActivities() {
  const selected = detailTask.value
  const root = detailRoot.value
  const beforeId = detailActivitiesNextBeforeId.value
  if (!selected || !root || !detailActivitiesHasMore.value || beforeId === null || loadingEarlierActivities.value) return
  loadingEarlierActivities.value = true
  const routeAtStart = path.value
  try {
    const page = await api.itemActivityPage(root.id, selected.parent_id === null ? undefined : selected.id, 20, beforeId)
    if (path.value !== routeAtStart) return
    itemActivities.value = mergeRecentActivities(itemActivities.value, page.items)
    detailActivitiesHasMore.value = page.has_more
    detailActivitiesNextBeforeId.value = page.next_before_id
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    loadingEarlierActivities.value = false
  }
}

function handleExecutionRefreshSignal() {
  void refreshExecutionScene()
}

function syncCollaborationRefreshTimer() {
  if (collaborationRefreshTimer !== undefined) {
    window.clearInterval(collaborationRefreshTimer)
    collaborationRefreshTimer = undefined
  }
  if (/^\/tasks\/\d+$/.test(path.value)) {
    collaborationRefreshTimer = window.setInterval(() => {
      void refreshExecutionScene()
    }, 60_000)
  }
}

async function reviewCurrentItemPlan() {
  const root = detailTask.value
  if (!root || root.parent_id !== null || root.kind !== "item" || !aiReviewAvailable.value || itemReviewLoading.value) return
  error.value = ""
  itemReviewLoading.value = true
  clearItemReview()
  const epoch = itemReviewEpoch
  try {
    const result = await api.reviewItemPlan(root.id)
    if (epoch !== itemReviewEpoch) return
    itemReviewSuggestions.value = result.suggestions.map((suggestion, index) => ({
      key: `${Date.now()}-${index}-${Math.random().toString(36).slice(2)}`,
      suggestion,
    }))
    if (itemReviewSuggestions.value.length) itemReviewSummary.value = result.summary
    else notice.value = "方案检查完成，暂未发现调整建议"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    itemReviewLoading.value = false
  }
}

function dismissItemReviewSuggestion(key: string) {
  itemReviewSuggestions.value = removeItemReviewSuggestion(itemReviewSuggestions.value, key)
  if (!itemReviewSuggestions.value.length) itemReviewSummary.value = ""
}

function changesForReviewSuggestion(suggestion: AIItemReviewSuggestion) {
  const current = detailChildren.value.find((task) => task.id === suggestion.target_task_id)
  return itemReviewChanges(current, suggestion.proposed_task)
}

async function applyItemReviewSuggestion(entry: { key: string; suggestion: AIItemReviewSuggestion }) {
  const root = detailTask.value
  if (!root || root.parent_id !== null || root.kind !== "item" || !isAdmin.value || itemReviewApplyingKey.value) return
  error.value = ""
  itemReviewApplyingKey.value = entry.key
  try {
    const applied = await api.applyItemReview(root.id, entry.suggestion)
    replaceTaskInState(applied.task)
    itemActivities.value = prependUniqueActivity(itemActivities.value, applied.activity)
    itemReviewSuggestions.value = removeItemReviewSuggestion(itemReviewSuggestions.value, entry.key)
    if (!itemReviewSuggestions.value.length) itemReviewSummary.value = ""
    notice.value = "已应用这条方案调整"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    itemReviewApplyingKey.value = ""
  }
}

function readTaskView(): TaskView {
  const value = new URLSearchParams(window.location.search).get("view")
  return value === "claimable" || value === "all" ? value : "mine"
}

function navigateTasks(view: TaskView) {
  const url = view === "mine" ? "/tasks" : `/tasks?view=${view}`
  taskView.value = view
  navigate(url)
}

function isRootExpanded(rootId: number) {
  return isExpandedRoot(expandedRootIds.value, rootId)
}

function toggleRootBreakdown(rootId: number) {
  expandedRootIds.value = toggleExpandedRoot(expandedRootIds.value, rootId)
}

function openDeleteRootItemModal(root = detailRoot.value, origin: "detail" | "list" = "detail") {
  if (!isAdmin.value || !root || root.parent_id !== null) return
  deleteTargetRootId.value = root.id
  deleteRootOrigin.value = origin
  const childCount = tasks.value.filter((task) => task.parent_id === root.id).length
  const independent = isIndependentTask(root)
  requestAppConfirmation({
    title: independent ? "删除独立任务？" : "删除事项？",
    description: independent
      ? "将同时删除此任务的进展记录，此操作不可恢复。"
      : `将同时删除此事项下的 ${childCount} 项分工、进展记录和当前信息，此操作不可恢复。`,
    confirmLabel: independent ? "删除任务" : "删除事项",
    danger: true,
    action: confirmDeleteRootItem,
  })
}

async function confirmDeleteRootItem() {
  const root = deleteTargetRoot.value
  if (!isAdmin.value || !root || deletingRootItem.value) return
  const origin = deleteRootOrigin.value
  deletingRootItem.value = true
  try {
    await api.deleteRootTask(root.id)
    tasks.value = removeRootAndChildren(tasks.value, root.id)
    homeMineTasks.value = removeRootAndChildren(homeMineTasks.value, root.id)
    homeAllTasks.value = removeRootAndChildren(homeAllTasks.value, root.id)
    const nextExpanded = new Set(expandedRootIds.value)
    nextExpanded.delete(root.id)
    expandedRootIds.value = nextExpanded
    itemActivities.value = []
    itemActivityDraft.value = ""
    editingFactScopeId.value = null
    clearFactSuggestions()
    clearItemReview()
    deleteTargetRootId.value = null
    if (origin === "detail") {
      navigateTasks("all")
    } else {
      try {
        tasks.value = await api.tasks(taskView.value)
      } catch {
        // Keep the optimistically filtered list if refreshing fails.
      }
    }
    showFeedback("success", isIndependentTask(root) ? "独立任务已删除" : "事项已删除")
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    deletingRootItem.value = false
  }
}

function formatDate(value: string | null) {
  if (!value) return ""
  return new Date(value).toLocaleString("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function toLocalInput(value: string | null) {
  return value ? value.slice(0, 16) : ""
}

function childTasks(parentId: number) {
  return tasks.value.filter((task) => task.parent_id === parentId)
}

function taskViewChildren(parentId: number) {
  return tasksForRoot(tasks.value, parentId, taskView.value, user.value?.id ?? 0)
}

function claimableChildren(parentId: number) {
  return tasks.value.filter((task) => task.parent_id === parentId && claimableTask(task))
}

function homeRoot(task: Task) {
  if (task.parent_id === null) return task
  return homeAllTasks.value.find((candidate) => candidate.id === task.parent_id) ?? null
}

async function loadHomeRecentActivities(relatedTasks: Task[], loadId: number) {
  const memberId = user.value?.id
  const rootIds = [...new Set(relatedTasks.map((task) => task.parent_id ?? task.id))]
  const activities: ItemActivity[] = []
  baseRecentActivities.value = []

  for (let index = 0; index < rootIds.length; index += 4) {
    const batch = rootIds.slice(index, index + 4)
    const pages = await Promise.allSettled(batch.map((rootId) => api.itemActivityPage(rootId, undefined, 5)))
    if (loadId !== routeLoadSequence || path.value !== "/" || user.value?.id !== memberId) return
    for (const page of pages) {
      if (page.status === "fulfilled") activities.push(...page.value.items)
    }
    baseRecentActivities.value = [...activities]
  }
}

function openTaskDetail(task: Task) {
  navigate(`/tasks/${task.id}`)
}

function taskDetailSections(task: Task) {
  const executionHints = [
    ...(task.execution_points ?? []),
    ...(task.cautions ?? []).map((item) => `注意：${item}`),
  ]
  return [
    { title: "执行提示", items: executionHints },
    { title: "开始前需要", items: task.prerequisites ?? [] },
  ].filter((section) => section.items.length)
}

function parseTaskLines(value: string) {
  return value.split("\n").map((line) => line.trim()).filter(Boolean)
}

function taskLineLimitMessage() {
  if (parentTaskId.value === null) return ""
  const limits = [
    [taskExecutionPointsText.value, 6, "怎么做"],
    [taskCautionsText.value, 5, "注意"],
    [taskPrerequisitesText.value, 4, "开始前需要"],
  ] as const
  for (const [value, max, label] of limits) {
    const lines = parseTaskLines(value)
    if (lines.length > max) return `${label}最多填写 ${max} 条。`
    if (lines.some((line) => line.length > 240)) return `${label}每条最多 240 字。`
  }
  return ""
}

function isCollaborator(task: Task) {
  return task.collaborators.some((member) => member.id === user.value?.id)
}

function resetTaskForm() {
  taskTitle.value = ""
  taskDeliverable.value = ""
  taskExecutionPointsText.value = ""
  taskCautionsText.value = ""
  taskPrerequisitesText.value = ""
  taskCautionsOpen.value = false
  taskPrerequisitesOpen.value = false
  taskOwnerMode.value = "assigned"
  taskOwnerId.value = activeMembers.value[0]?.id ?? null
  resetTaskMemberFilters()
  taskOwnerClaimable.value = false
  taskCollaboratorIds.value = []
  taskCollaborationOpen.value = false
  taskDeadline.value = ""
  taskStatus.value = "todo"
  taskDependencyIds.value = []
}

function fillTaskForm(task: Task) {
  taskTitle.value = task.title
  taskDeliverable.value = task.deliverable
  taskExecutionPointsText.value = (task.execution_points ?? []).join("\n")
  taskCautionsText.value = (task.cautions ?? []).join("\n")
  taskPrerequisitesText.value = (task.prerequisites ?? []).join("\n")
  taskCautionsOpen.value = Boolean(taskCautionsText.value.trim())
  taskPrerequisitesOpen.value = Boolean(taskPrerequisitesText.value.trim())
  taskOwnerMode.value = task.owner ? "assigned" : "claimable"
  taskOwnerId.value = task.owner?.id ?? activeMembers.value[0]?.id ?? null
  resetTaskMemberFilters()
  taskOwnerClaimable.value = task.owner_claimable
  taskCollaboratorIds.value = task.collaborators
    .filter((member) => activeMemberIds.value.has(member.id))
    .map((member) => member.id)
  taskCollaborationOpen.value = task.collaboration_open
  taskDeadline.value = toLocalInput(task.deadline)
  taskStatus.value = task.status
  taskDependencyIds.value = task.depends_on_tasks.map((dependency) => dependency.id)
}

function resetTaskMemberFilters() {
  taskOwnerSearch.value = ""
  taskOwnerGroupFilter.value = ""
  taskCollaboratorSearch.value = ""
  taskCollaboratorGroupFilter.value = ""
}

async function ensureTaskAssignees() {
  if (!isAdmin.value || taskMembersLoaded.value) return
  if (taskMembersRequest) {
    await taskMembersRequest
    return
  }
  taskMembersRequest = api.taskAssignees()
  try {
    taskMembers.value = await taskMembersRequest
    taskMembersLoaded.value = true
  } finally {
    taskMembersRequest = null
  }
}

async function startChildTask(parent: Task) {
  try {
    await ensureTaskAssignees()
  } catch (reason) {
    error.value = messageOf(reason)
    return
  }
  navigate(`/tasks/${parent.id}/new-child`)
}

async function startIndependentTask() {
  if (!isAdmin.value) return
  try {
    await ensureTaskAssignees()
  } catch (reason) {
    error.value = messageOf(reason)
    return
  }
  navigate("/tasks/new")
}

async function editTask(task: Task) {
  try {
    await ensureTaskAssignees()
  } catch (reason) {
    error.value = messageOf(reason)
    return
  }
  navigate(`/tasks/${task.id}/edit`)
}

function cancelTaskForm() {
  const destination = taskEditorCancelPath(taskEditor.value)
  navigate(destination, { replace: true })
}

function sameIds(left: number[], right: number[]) {
  const sortedLeft = [...left].sort((a, b) => a - b)
  const sortedRight = [...right].sort((a, b) => a - b)
  return (
    sortedLeft.length === sortedRight.length &&
    sortedLeft.every((id, index) => id === sortedRight[index])
  )
}

async function loadAIReviewAccess() {
  aiReviewAvailable.value = false
  if (user.value?.role !== "admin") return
  try {
    const access = await api.aiReviewAccess()
    aiReviewAvailable.value = access.available
  } catch {
    aiReviewAvailable.value = false
  }
}

async function loadKnowledgeDocuments() {
  knowledgeDocuments.value = await api.knowledgeDocuments()
}

async function ensureCollegeOptions() {
  if (collegeOptions.value.length) return
  collegeOptions.value = await api.colleges()
}

async function loadSchoolLeaveSummary() {
  schoolLeaveTodoCount.value = 0
  if (user.value?.role !== "admin") return
  try {
    schoolLeaveTodoCount.value = (await api.schoolLeaveAdminSummary()).todo_count
  } catch {
    schoolLeaveTodoCount.value = 0
  }
}

async function loadCurrentUser() {
  try {
    user.value = await api.me()
    studentIdDraft.value = user.value.student_id ?? ""
    teamGroupDraft.value = user.value.team_group ?? ""
    collegeDraft.value = user.value.college ?? ""
    await Promise.all([loadAIReviewAccess(), loadSchoolLeaveSummary()])
  } catch (reason) {
    if (reason instanceof ApiError && reason.status === 401) {
      user.value = null
      return
    }
    throw reason
  }
}

async function loadRoute() {
  const loadId = ++routeLoadSequence
  const routePath = path.value
  const routeSearch = window.location.search
  const editorRoute = parseTaskEditorRoute(routePath)
  const isCurrentLoad = () => loadId === routeLoadSequence && routePath === path.value && routeSearch === window.location.search
  loading.value = !initialRouteResolved.value
  taskEditorLoading.value = editorRoute !== null
  routeNotFound.value = false
  error.value = ""
  detailContextLoading.value = taskDetailId.value !== null

  try {
    const publicPage =
      routePath === "/login" ||
      routePath.startsWith("/invite/") ||
      routePath.startsWith("/register/") ||
      routePath.startsWith("/leave/camp/") ||
      routePath.startsWith("/leave/daily/")
    if (!publicPage && !user.value) {
      await loadCurrentUser()
      if (!isCurrentLoad()) return
      if (!user.value) {
        navigate("/login")
        return
      }
    }

    if (routePath.startsWith("/leave/camp/") || routePath.startsWith("/leave/daily/")) {
      // Public leave links intentionally load no authenticated team data.
    } else if (routePath === "/login") {
      if (user.value) {
        navigate("/")
        return
      }
    } else if (routePath.startsWith("/invite/")) {
      invitation.value = await api.invitation(inviteToken.value)
      if (!isCurrentLoad()) return
    } else if (routePath.startsWith("/register/")) {
      registrationInfo.value = null
      registrationChecking.value = true
      registrationEnded.value = false
      registrationLoadError.value = ""
      try {
        registrationInfo.value = await api.teamRegistrationInfo(registerToken.value)
      } catch (reason) {
        if (reason instanceof ApiError && (reason.status === 404 || reason.status === 410)) {
          registrationEnded.value = true
          return
        }
        registrationLoadError.value = messageOf(reason)
        return
      } finally {
        registrationChecking.value = false
      }
      if (!isCurrentLoad()) return
      await ensureCollegeOptions()
      if (!isCurrentLoad()) return
    } else if (routePath === "/admin/tasks") {
      navigate("/tasks")
      return
    } else if (routePath === "/admin/members") {
      navigate("/team")
      return
    } else if (routePath === "/") {
      baseRecentActivities.value = []
      homeAllTasks.value = []
      homeMineTasks.value = []
      claimableCount.value = 0
      const all = await api.tasks("all")
      if (!isCurrentLoad()) return
      homeAllTasks.value = all
      homeMineTasks.value = all.filter((task) =>
        task.owner?.id === user.value?.id || task.collaborators.some((member) => member.id === user.value?.id),
      )
      claimableCount.value = all.filter(claimableTask).length
      void loadHomeRecentActivities(homeMineTasks.value, loadId)
    } else if (editorRoute) {
      if (!isAdmin.value) {
        navigate("/")
        return
      }
      await ensureTaskAssignees()
      if (!isCurrentLoad()) return
      const contextTaskId = editorRoute.kind === "new-child"
        ? editorRoute.parentId
        : editorRoute.kind === "edit"
          ? editorRoute.taskId
          : null
      if (contextTaskId !== null) {
        const context = await api.taskContext(contextTaskId)
        if (!isCurrentLoad()) return
        tasks.value = [context.root, ...context.tasks]
      }
      if (editorRoute.kind === "new-child") {
        const parent = tasks.value.find((task) => task.id === editorRoute.parentId)
        if (!parent || parent.parent_id !== null) {
          routeNotFound.value = true
          return
        }
      }
      if (initializedTaskEditorPath !== routePath) {
        if (editorRoute.kind === "edit") {
          const selected = tasks.value.find((task) => task.id === editorRoute.taskId)
          if (!selected) {
            routeNotFound.value = true
            return
          }
          fillTaskForm(selected)
        } else {
          resetTaskForm()
        }
        initializedTaskEditorPath = routePath
      }
    } else if (taskDetailId.value !== null) {
      const selectedId = taskDetailId.value
      const context = await api.taskContext(selectedId)
      if (!isCurrentLoad()) return
      tasks.value = [context.root, ...context.tasks]
      const selected = tasks.value.find((task) => task.id === selectedId)
      if (!selected) {
        routeNotFound.value = true
        return
      }
      taskResultDraft.value = selected.result ?? ""
      itemActivityDraft.value = ""
      detailFactsExpanded.value = false
      detailChildrenExpanded.value = false
      detailActivitiesExpanded.value = false
      itemActivities.value = context.activity_page.items
      detailActivitiesHasMore.value = context.activity_page.has_more
      detailActivitiesNextBeforeId.value = context.activity_page.next_before_id
    } else if (routePath === "/tasks") {
      taskView.value = readTaskView()
      taskListLoading.value = tasksLoadedScope.value !== taskView.value
      taskListLoadError.value = false
      const taskList = await api.tasks(taskView.value)
      if (!isCurrentLoad()) return
      tasks.value = taskList
      tasksLoadedScope.value = taskView.value
    } else if (routePath === "/planner-draft") {
      if (!isAdmin.value || !plannerDraft.value) {
        navigate("/")
        return
      }
    } else if (routePath === "/knowledge") {
      if (!isAdmin.value) {
        navigate("/")
        return
      }
      await loadKnowledgeDocuments()
      if (!isCurrentLoad()) return
    } else if (teamMemberDetailId.value !== null) {
      if (!isAdmin.value) {
        navigate("/")
        return
      }
      const [teamMembers] = await Promise.all([api.members(), ensureCollegeOptions()])
      members.value = teamMembers
      if (!isCurrentLoad()) return
      if (!members.value.some((member) => member.id === teamMemberDetailId.value)) {
        routeNotFound.value = true
        return
      }
    } else if (routePath === "/team") {
      if (!isAdmin.value) {
        navigate("/")
        return
      }
      const [teamMembers, currentRegistration] = await Promise.all([
        api.members(),
        api.currentTeamRegistration(),
      ])
      if (!isCurrentLoad()) return
      members.value = teamMembers
      registrationWindow.value = currentRegistration
      registrationPath.value = ""
    } else if (routePath === "/leave") {
      // The leave page loads its own independent workflow data.
    } else if (routePath === "/me/edit") {
      await ensureCollegeOptions()
      if (!isCurrentLoad()) return
      studentIdDraft.value = user.value?.student_id ?? ""
      teamGroupDraft.value = user.value?.team_group ?? ""
      collegeDraft.value = user.value?.college ?? ""
    } else if (routePath === "/me") {
      await ensureCollegeOptions()
      if (!isCurrentLoad()) return
    } else {
      routeNotFound.value = true
    }
  } catch (reason) {
    if (!isCurrentLoad()) return
    if (routePath === "/tasks" && tasksLoadedScope.value !== taskView.value) {
      taskListLoadError.value = true
    }
    if (
      reason instanceof ApiError &&
      reason.status === 401 &&
      !routePath.startsWith("/invite/") &&
      !routePath.startsWith("/register/")
    ) {
      user.value = null
      navigate("/login")
      return
    }
    if (reason instanceof ApiError && reason.status === 404 && (taskDetailId.value !== null || editorRoute !== null)) {
      routeNotFound.value = true
      return
    }
    error.value = messageOf(reason)
  } finally {
    if (isCurrentLoad()) {
      loading.value = false
      initialRouteResolved.value = true
      taskEditorLoading.value = false
      detailContextLoading.value = false
      if (routePath === "/tasks") taskListLoading.value = false
    }
  }
}

async function submitLogin() {
  error.value = ""
  notice.value = ""
  try {
    user.value = await api.login(loginEmail.value, loginPassword.value)
    await loadAIReviewAccess()
    loginPassword.value = ""
    navigate("/")
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

async function submitInvitation() {
  error.value = ""
  if (invitePassword.value !== invitePasswordConfirm.value) {
    error.value = "两次输入的密码不一致"
    return
  }

  try {
    await api.acceptInvitation(inviteToken.value, invitePassword.value)
    invitation.value = null
    invitePassword.value = ""
    invitePasswordConfirm.value = ""
    notice.value = "密码已设置，请登录"
    navigate("/login")
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

async function submitRegistration() {
  error.value = ""
  registrationFieldErrors.value = {}
  const normalizedName = registrationName.value.trim()
  const normalizedStudentId = registrationStudentId.value.trim()
  const errors: Record<string, string> = {}
  if (Array.from(normalizedName).length < 2 || Array.from(normalizedName).length > 50) {
    errors.name = "姓名长度需为 2–50 个字符"
  }
  if (!/^\d{8}$/.test(normalizedStudentId)) errors.student_id = "学号必须是 8 位数字"
  if (!collegeOptions.value.some((college) => college.code === registrationCollege.value)) {
    errors.college = "请选择有效学院"
  }
  if (!registrationTeamGroup.value) errors.team_group = "请选择所属组别"
  if (Object.keys(errors).length) {
    registrationFieldErrors.value = errors
    return
  }
  if (registrationPassword.value !== registrationPasswordConfirm.value) {
    registrationFieldErrors.value = { password_confirm: "两次输入的密码不一致" }
    return
  }
  registrationSubmitting.value = true
  try {
    user.value = await api.registerTeamMember(registerToken.value, {
      name: normalizedName,
      student_id: normalizedStudentId,
      college: registrationCollege.value,
      email: registrationEmail.value,
      team_group: registrationTeamGroup.value as TeamGroup,
      password: registrationPassword.value,
    })
    registrationPassword.value = ""
    registrationPasswordConfirm.value = ""
    await loadAIReviewAccess()
    navigate("/")
  } catch (reason) {
    error.value = messageOf(reason)
    const field = reason instanceof ApiError
      ? reason.field ??
        (reason.status === 409 && reason.message.includes("学号")
          ? "student_id"
          : reason.status === 409 && reason.message.includes("邮箱")
            ? "email"
            : null)
      : null
    if (field) registrationFieldErrors.value = { [field]: messageOf(reason) }
  } finally {
    registrationSubmitting.value = false
  }
}

function clearRegistrationFieldError(field: string) {
  if (!registrationFieldErrors.value[field]) return
  const next = { ...registrationFieldErrors.value }
  delete next[field]
  registrationFieldErrors.value = next
}

function clearProfileFieldError(field: string) {
  if (!profileFieldErrors.value[field]) return
  const next = { ...profileFieldErrors.value }
  delete next[field]
  profileFieldErrors.value = next
}

async function openTeamRegistration() {
  if (openingRegistration.value) return
  error.value = ""
  openingRegistration.value = true
  try {
    const opened = await api.openTeamRegistration()
    registrationWindow.value = opened
    registrationPath.value = opened.register_path
    notice.value = "团队注册已开放"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    openingRegistration.value = false
  }
}

async function closeTeamRegistration() {
  if (closingRegistration.value) return
  error.value = ""
  closingRegistration.value = true
  try {
    await api.closeTeamRegistration()
    registrationWindow.value = null
    registrationPath.value = ""
    notice.value = "团队注册已关闭"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    closingRegistration.value = false
  }
}

async function copyTeamRegistration() {
  if (!registrationPath.value) return
  await navigator.clipboard.writeText(window.location.origin + registrationPath.value)
  notice.value = "注册链接已复制"
}

function replaceMemberInState(updated: Member) {
  const exists = members.value.some((member) => member.id === updated.id)
  members.value = exists
    ? members.value.map((member) => member.id === updated.id ? updated : member)
    : [...members.value, updated].sort((left, right) => left.name.localeCompare(right.name))
}

async function regenerateInvite(memberId: number) {
  error.value = ""
  try {
    latestInvite.value = await api.regenerateInvite(memberId)
    replaceMemberInState(latestInvite.value.member)
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

async function copyInvite() {
  if (!latestInvite.value) return
  await navigator.clipboard.writeText(window.location.origin + latestInvite.value.invite_path)
  notice.value = "邀请链接已复制"
}

async function disableMember(memberId: number) {
  requestAppConfirmation({
    title: "停用成员？",
    description: "停用后，该成员会立即退出登录，且无法继续访问 TARS BASE；之后可由管理员恢复。",
    confirmLabel: "停用成员",
    danger: true,
    action: async () => {
      error.value = ""
      try {
        replaceMemberInState(await api.disableMember(memberId))
      } catch (reason) {
        error.value = messageOf(reason)
      }
    },
  })
}

async function enableMember(memberId: number) {
  error.value = ""
  try {
    replaceMemberInState(await api.enableMember(memberId))
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

async function updateMemberProfile(payload: { memberId: number } & MemberProfilePayload) {
  if (memberProfileSavingId.value !== null) return
  error.value = ""
  memberProfileSavingId.value = payload.memberId
  try {
    const { memberId, ...profile } = payload
    replaceMemberInState(await api.updateMemberProfile(memberId, profile))
    const next = { ...memberProfileFieldErrors.value }
    delete next[memberId]
    memberProfileFieldErrors.value = next
    notice.value = "成员资料已更新"
  } catch (reason) {
    error.value = messageOf(reason)
    const field = reason instanceof ApiError
      ? reason.field ?? (reason.status === 409 && reason.message.includes("学号") ? "student_id" : null)
      : null
    if (field) {
      memberProfileFieldErrors.value = {
        ...memberProfileFieldErrors.value,
        [payload.memberId]: { ...memberProfileFieldErrors.value[payload.memberId], [field]: messageOf(reason) },
      }
    }
  } finally {
    memberProfileSavingId.value = null
  }
}

function clearMemberProfileFieldError(memberId: number, field: string) {
  const existing = memberProfileFieldErrors.value[memberId]
  if (!existing?.[field]) return
  const nextMemberErrors = { ...existing }
  delete nextMemberErrors[field]
  const next = { ...memberProfileFieldErrors.value }
  if (Object.keys(nextMemberErrors).length) next[memberId] = nextMemberErrors
  else delete next[memberId]
  memberProfileFieldErrors.value = next
}

function profileValidationError(): [string, string] | null {
  const studentId = studentIdDraft.value.trim()
  if (studentId && !/^\d{8}$/.test(studentId)) return ["student_id", "学号必须是 8 位数字"]
  if (collegeDraft.value && !collegeOptions.value.some((college) => college.code === collegeDraft.value)) {
    return ["college", "请选择有效学院"]
  }
  return null
}

async function saveMyProfile() {
  if (!user.value || profileSaving.value || !myProfileChanged.value) return
  error.value = ""
  notice.value = ""
  profileFieldErrors.value = {}
  const validationError = profileValidationError()
  if (validationError) {
    profileFieldErrors.value = { [validationError[0]]: validationError[1] }
    return
  }
  profileSaving.value = true
  try {
    user.value = await api.updateMeProfile(
      {
        student_id: studentIdDraft.value.trim() || null,
        team_group: teamGroupDraft.value || null,
        college: collegeDraft.value || null,
      },
    )
    studentIdDraft.value = user.value.student_id ?? ""
    teamGroupDraft.value = user.value.team_group ?? ""
    collegeDraft.value = user.value.college ?? ""
    notice.value = "资料已保存"
    navigate("/me")
  } catch (reason) {
    error.value = messageOf(reason)
    const field = reason instanceof ApiError
      ? reason.field ?? (reason.status === 409 && reason.message.includes("学号") ? "student_id" : null)
      : null
    if (field) profileFieldErrors.value = { [field]: messageOf(reason) }
  } finally {
    profileSaving.value = false
  }
}

async function submitTask() {
  if (taskSaving.value) return
  error.value = ""
  fieldErrors.value = {}
  const desiredOwnerId = taskOwnerMode.value === "assigned" ? taskOwnerId.value : null
  const desiredOwnerClaimable =
    taskOwnerMode.value === "claimable" ? true : taskOwnerClaimable.value

  if (!taskTitle.value.trim()) {
    await showFieldError("task-title", "请填写任务标题", "需要填写任务标题")
    return
  }
  if (taskOwnerMode.value === "assigned" && !desiredOwnerId) {
    await showFieldError("task-owner", "请选择负责人", "需要选择负责人")
    return
  }
  const lineLimitError = taskLineLimitMessage()
  if (lineLimitError) {
    const field = lineLimitError.includes("注意") ? "task-cautions" :
      lineLimitError.includes("开始前") ? "task-prerequisites" : "task-execution-points"
    await showFieldError(field, lineLimitError, lineLimitError)
    return
  }
  const executionPoints = parseTaskLines(taskExecutionPointsText.value)
  const cautions = parseTaskLines(taskCautionsText.value)
  const prerequisites = parseTaskLines(taskPrerequisitesText.value)

  taskSaving.value = true
  try {
    let updatedTask: Task
    if (editingTaskId.value) {
      const original = editingTask.value
      if (!original) return

      const payload: Parameters<typeof api.updateTask>[1] = {}
      if (taskTitle.value !== original.title) payload.title = taskTitle.value
      if (taskDeliverable.value !== original.deliverable) payload.deliverable = taskDeliverable.value
      if (JSON.stringify(executionPoints) !== JSON.stringify(original.execution_points ?? [])) payload.execution_points = executionPoints
      if (JSON.stringify(cautions) !== JSON.stringify(original.cautions ?? [])) payload.cautions = cautions
      if (JSON.stringify(prerequisites) !== JSON.stringify(original.prerequisites ?? [])) payload.prerequisites = prerequisites
      if (desiredOwnerId !== original.owner?.id) payload.owner_id = desiredOwnerId
      if (desiredOwnerClaimable !== original.owner_claimable) {
        payload.owner_claimable = desiredOwnerClaimable
      }
      if (taskCollaborationOpen.value !== original.collaboration_open) {
        payload.collaboration_open = taskCollaborationOpen.value
      }
      if (taskDeadline.value !== toLocalInput(original.deadline)) {
        payload.deadline = taskDeadline.value || null
      }
      if (taskStatus.value !== original.status) payload.status = taskStatus.value
      if (!sameIds(taskDependencyIds.value, original.depends_on_tasks.map((dependency) => dependency.id))) {
        payload.depends_on_task_ids = taskDependencyIds.value
      }

      const originalActiveCollaborators = original.collaborators
        .filter((member) => activeMemberIds.value.has(member.id))
        .map((member) => member.id)
      if (!sameIds(taskCollaboratorIds.value, originalActiveCollaborators)) {
        payload.collaborator_ids = taskCollaboratorIds.value
      }

      updatedTask = Object.keys(payload).length
        ? await api.updateTask(editingTaskId.value, payload)
        : original
    } else {
      updatedTask = await api.createTask({
        kind: taskEditor.value?.kind === "new-task" ? "task" : undefined,
        parent_id: parentTaskId.value,
        title: taskTitle.value,
        deliverable: taskDeliverable.value,
        execution_points: executionPoints,
        cautions,
        prerequisites,
        owner_id: desiredOwnerId,
        owner_claimable: desiredOwnerClaimable,
        collaborator_ids: taskCollaboratorIds.value,
        collaboration_open: taskCollaborationOpen.value,
        deadline: taskDeadline.value || null,
        status: taskStatus.value,
        depends_on_task_ids: taskDependencyIds.value,
      })
    }

    replaceTaskInState(updatedTask)
    clearItemReview()
    tasksLoadedScope.value = null
    navigate(taskEditorSuccessPath(taskEditor.value, updatedTask.id), { replace: true })
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    taskSaving.value = false
  }
}

async function refreshTaskList(scope: TaskView) {
  const requestedUrl = window.location.pathname + window.location.search
  try {
    const freshTasks = await api.tasks(scope)
    if (window.location.pathname + window.location.search === requestedUrl && path.value === "/tasks") {
      tasks.value = freshTasks
      tasksLoadedScope.value = scope
    }
  } catch {
    // Keep the successful local patch visible if the follow-up list refresh fails.
  }
}

async function updateOwnTaskStatus(task: Task, status: TaskStatus) {
  await runTaskAction(task, `status:${status}`, () => api.updateTask(task.id, { status }))
}

async function claimTask(task: Task) {
  await runTaskAction(task, "claim", () => api.claimTask(task.id))
}

async function unclaimTask(task: Task) {
  requestAppConfirmation({
    title: "取消负责人认领？",
    description: "取消负责人认领后，该任务会重新进入待认领列表，其他成员可以重新认领。",
    confirmLabel: "取消认领",
    action: () => runTaskAction(task, "unclaim", () => api.unclaimTask(task.id)),
  })
}

async function joinTask(task: Task) {
  await runTaskAction(task, "join", () => api.joinTask(task.id))
}

async function leaveTask(task: Task) {
  await runTaskAction(task, "leave", () => api.leaveTask(task.id))
}

function taskMenuActions(task: Task): TaskActionMenuItem[] {
  const pending = Boolean(pendingTaskAction(task.id))
  const actions: TaskActionMenuItem[] = []
  if (task.owner?.id === user.value?.id && task.owner_claimable && task.status !== "done") {
    actions.push({ key: "unclaim", label: pendingTaskAction(task.id) === "unclaim" ? "取消中…" : "取消认领", disabled: pending })
  }
  if (task.collaboration_open && task.owner?.id !== user.value?.id && !isCollaborator(task) && task.status !== "done") {
    actions.push({ key: "join", label: pendingTaskAction(task.id) === "join" ? "加入中…" : "加入协作", disabled: pending })
  }
  if (task.collaboration_open && isCollaborator(task) && task.status !== "done") {
    actions.push({ key: "leave", label: pendingTaskAction(task.id) === "leave" ? "退出中…" : "退出协作", disabled: pending })
  }
  if (isAdmin.value) actions.push({ key: "edit", label: isIndependentTask(task) ? "编辑任务" : task.parent_id === null ? "编辑事项" : "编辑分工", disabled: pending })
  return actions
}

function handleTaskMenuAction(task: Task, action: string) {
  if (action === "unclaim") void unclaimTask(task)
  else if (action === "join") void joinTask(task)
  else if (action === "leave") void leaveTask(task)
  else if (action === "edit" && isAdmin.value) void editTask(task)
}

function rootTaskMenuActions(task: Task): TaskActionMenuItem[] {
  const pending = Boolean(pendingTaskAction(task.id))
  const actions = taskMenuActions(task).map((action) =>
    action.key === "edit" ? { ...action, label: isIndependentTask(task) ? "编辑任务" : "编辑事项" } : action,
  )
  if (isAdmin.value) {
    actions.push({
      key: "delete",
      label: isIndependentTask(task) ? "删除任务" : "删除事项",
      disabled: pending,
      danger: true,
    })
  }
  return actions
}

function handleRootTaskMenuAction(task: Task, action: string) {
  if (action === "delete" && isAdmin.value) {
    openDeleteRootItemModal(task, "list")
    return
  }
  handleTaskMenuAction(task, action)
}

function detailRootTaskMenuActions(task: Task): TaskActionMenuItem[] {
  const actions = rootTaskMenuActions(task)
  if (task.kind === "item" && task.parent_id === null && aiReviewAvailable.value) {
    const deleteIndex = actions.findIndex((action) => action.key === "delete")
    actions.splice(deleteIndex < 0 ? actions.length : deleteIndex, 0, {
      key: "review",
      label: "检查当前方案",
      disabled: itemReviewLoading.value,
    })
  }
  return actions
}

function handleDetailRootTaskMenuAction(task: Task, action: string) {
  if (action === "review") {
    void reviewCurrentItemPlan()
    return
  }
  if (action === "delete" && isAdmin.value) {
    openDeleteRootItemModal(task, "detail")
    return
  }
  if (action === "edit" && isAdmin.value) {
    editTaskFromDetail(task)
    return
  }
  handleRootTaskMenuAction(task, action)
}


async function saveTaskResult() {
  const task = detailTask.value
  if (!task || !canEditDetailResult.value) return
  error.value = ""
  try {
    const updated = await api.updateTask(task.id, { result: taskResultDraft.value })
    replaceTaskInState(updated)
    clearItemReview()
    notice.value = "执行结果已保存"
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

async function publishTaskProgress() {
  const task = detailTask.value
  const content = taskProgressDraft.value.trim()
  if (!task || !content || !canPublishTaskProgress.value || taskProgressSaving.value) return
  error.value = ""
  clearFactSuggestions()
  taskProgressSaving.value = true
  const epoch = factExtractionEpoch
  try {
    const published = await api.publishTaskProgress(task.id, content)
    replaceTaskInState(published.task)
    itemActivities.value = prependUniqueActivity(itemActivities.value, published.activity)
    taskProgressDraft.value = ""
    clearItemReview()
    notice.value = "进展已发布"
    if (published.task.parent_id !== null && isCurrentFactSuggestionRequest(task.id, taskDetailId.value, epoch, factExtractionEpoch)) {
      factExtractionLoading.value = true
      void extractProgressFacts(task.id, published.task.parent_id as number, published.activity, epoch)
    }
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    taskProgressSaving.value = false
  }
}

async function extractProgressFacts(taskId: number, rootTaskId: number, activity: ItemActivity, epoch: number) {
  try {
    const extracted = await api.extractActivityFacts(rootTaskId, activity.id)
    if (isCurrentFactSuggestionRequest(taskId, taskDetailId.value, epoch, factExtractionEpoch)) {
      factSuggestions.value = extracted.suggestions
      selectedFactSuggestions.value = defaultFactSelection(extracted.suggestions)
      factSuggestionActivityId.value = activity.id
      if (extracted.suggestions.length) {
        notice.value = `进展已发布，有 ${extracted.suggestions.length} 条信息可能需要同步给团队`
      }
    }
  } catch {
    if (isCurrentFactSuggestionRequest(taskId, taskDetailId.value, epoch, factExtractionEpoch)) {
      notice.value = "进展已发布，暂时无法提取可同步信息"
    }
  } finally {
    if (isCurrentFactSuggestionRequest(taskId, taskDetailId.value, epoch, factExtractionEpoch)) {
      factExtractionLoading.value = false
    }
  }
}

async function addSuggestedFactsToItem() {
  const root = detailRoot.value
  const chosen = factSuggestions.value.filter((suggestion) => selectedFactSuggestions.value.includes(suggestion.text))
  if (!root || !chosen.length || !canWriteDetailItem.value || factSuggestionActivityId.value === null) return
  error.value = ""
  try {
    const facts: ItemFactInput[] = chosen.map((suggestion) => ({
      content: suggestion.text,
      scope: suggestion.scope,
      related_task_ids: suggestion.scope === "related" ? suggestion.related_task_ids : [],
      source_activity_id: factSuggestionActivityId.value,
      supersedes_fact_id: canManageFactScope.value && confirmedFactSupersessions.value.includes(suggestion.text)
        ? suggestion.supersedes_fact_id
        : null,
    }))
    const updatedRoot = await api.addScopedFactsBatch(root.id, facts)
    replaceRootFactsInState(updatedRoot)
    clearFactSuggestions()
    clearItemReview()
    notice.value = "已按确认范围同步信息"
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

function dismissFactSuggestions() {
  clearFactSuggestions()
}

async function completeDetailTask() {
  const task = detailTask.value
  const result = taskCompletionDraft.value.trim()
  if (!task || !result || !canCompleteDetailTask.value || taskCompletionSaving.value) return
  const syncToItem = task.parent_id !== null && taskCompletionSync.value
  if (syncToItem && result.length > 500) {
    error.value = "同步到事项信息的最终结果最多 500 字。"
    return
  }
  error.value = ""
  taskCompletionSaving.value = true
  try {
    const completed = await api.completeTask(task.id, result, syncToItem)
    replaceTaskInState(completed.task)
    itemActivities.value = prependUniqueActivity(itemActivities.value, completed.activity)
    if (syncToItem && detailRoot.value) {
      void refreshExecutionScene(true)
    }
    taskCompletionDraft.value = ""
    taskCompletionSync.value = false
    clearFactSuggestions()
    clearItemReview()
    notice.value = "任务已完成"
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    taskCompletionSaving.value = false
  }
}

async function removeCurrentFact(factId: number) {
  const root = detailRoot.value
  if (!root || !canManageFactScope.value) return
  requestAppConfirmation({
    title: "移除当前信息？",
    description: "移除后，这条当前信息将不再参与事项当前上下文；已有的历史动态会保留。",
    confirmLabel: "移除信息",
    danger: true,
    action: async () => {
      error.value = ""
      try {
        const updatedRoot = await api.deleteItemFact(root.id, factId)
        replaceRootFactsInState(updatedRoot)
        clearItemReview()
      } catch (reason) {
        error.value = messageOf(reason)
      }
    },
  })
}

function beginFactScopeEdit(fact: ItemFact) {
  editingFactScopeId.value = fact.id
  editingFactScope.value = fact.scope
  editingFactTaskIds.value = fact.related_tasks.map((task) => task.id)
}

function cancelFactScopeEdit() {
  editingFactScopeId.value = null
  editingFactTaskIds.value = []
}

async function saveFactScope(factId: number) {
  const root = detailRoot.value
  if (!root || !canManageFactScope.value || savingFactScopeId.value !== null) return
  error.value = ""
  savingFactScopeId.value = factId
  try {
    const updatedRoot = await api.updateFactScope(
      root.id,
      factId,
      editingFactScope.value,
      editingFactScope.value === "related" ? editingFactTaskIds.value : [],
    )
    replaceRootFactsInState(updatedRoot)
    cancelFactScopeEdit()
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    savingFactScopeId.value = null
  }
}

async function recordItemActivity() {
  const root = detailRoot.value
  const content = itemActivityDraft.value.trim()
  if (!root || !content || !canWriteDetailItem.value) return
  error.value = ""
  try {
    const activity = await api.addItemActivity(root.id, content, false, "global", [])
    itemActivities.value = prependUniqueActivity(itemActivities.value, activity)
    clearItemReview()
    itemActivityDraft.value = ""
    notice.value = "进展已发布"
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

async function addResultToContext() {
  const task = detailTask.value
  if (!task || !task.result || !canWriteDetailItem.value) return
  error.value = ""
  try {
    const updatedRoot = await api.taskResultToContext(task.id)
    replaceRootFactsInState(updatedRoot)
    clearItemReview()
    notice.value = "执行结果已加入事项信息"
  } catch (reason) {
    error.value = messageOf(reason)
  }
}

function editTaskFromDetail(task: Task) {
  if (!isAdmin.value) return
  clearItemReview()
  void editTask(task)
}

const PLANNER_FILE_EXTENSIONS = new Set([".md", ".txt", ".docx", ".pdf"])
const PLANNER_MAX_FILE_BYTES = 10 * 1024 * 1024
const PLANNER_MAX_FILES = 5
const PLANNER_MAX_CURRENT_CONTEXT_CHARS = 5_000

const fullPlannerAttachmentContext = computed(() =>
  plannerAttachments.value
    .map((attachment) => `文件《${attachment.filename}》：\n${attachment.extracted_text}`)
    .join("\n\n"),
)
const plannerAttachmentContext = computed(() =>
  fullPlannerAttachmentContext.value.slice(0, PLANNER_MAX_CURRENT_CONTEXT_CHARS),
)
const plannerAttachmentContextTruncated = computed(
  () => fullPlannerAttachmentContext.value.length > PLANNER_MAX_CURRENT_CONTEXT_CHARS,
)

async function copyExternalAIPlannerPrompt() {
  plannerExternalMessage.value = ""
  if (plannerDescription.value.trim().length < 10 && !plannerAttachmentContext.value.trim()) {
    plannerExternalMessage.value = "请填写事项描述，或先添加包含有效内容的资料。"
    return
  }
  if (plannerUploading.value) {
    plannerExternalMessage.value = "请等资料读取完成后再复制提示词。"
    return
  }
  const prompt = buildExternalAIPlannerPrompt({
    description: plannerDescription.value,
    currentEventContext: plannerAttachmentContext.value,
  })
  try {
    if (!navigator.clipboard?.writeText) throw new Error("当前浏览器不支持剪贴板写入。")
    await navigator.clipboard.writeText(prompt)
    plannerExternalMessage.value = plannerAttachmentContextTruncated.value
      ? "提示词已复制到剪贴板；资料只包含前 5,000 字，内容不会自动发送，请确认可分享后再粘贴到外部 AI。"
      : "提示词已复制到剪贴板；内容不会自动发送，请确认可分享后再粘贴到外部 AI。"
  } catch (reason) {
    plannerExternalMessage.value = messageOf(reason)
  }
}

function togglePlannerImport() {
  plannerImportOpen.value = !plannerImportOpen.value
  plannerImportError.value = ""
  plannerExternalMessage.value = ""
}

function importExternalAIPlanner() {
  const result = parseExternalAIPlannerDraft(plannerImportJson.value)
  if (!result.ok) {
    plannerImportError.value = result.error
    return
  }
  plannerImportError.value = ""
  plannerExternalMessage.value = ""
  setPlannerDraft(result.draft)
  plannerImportJson.value = ""
  plannerImportOpen.value = false
  navigate("/planner-draft")
  notice.value = "方案已导入草案；请核对并手动确认创建。"
}

function choosePlannerFiles() {
  plannerFileInput.value?.click()
}

function removePlannerAttachment(id: string) {
  plannerAttachments.value = plannerAttachments.value.filter((attachment) => attachment.id !== id)
}

async function addPlannerFiles(files: File[]) {
  plannerAttachmentMessage.value = ""
  error.value = ""
  if (plannerUploading.value) return
  plannerUploading.value = true
  try {
    for (const file of files) {
      if (plannerAttachments.value.length >= PLANNER_MAX_FILES) {
        plannerAttachmentMessage.value = `本次最多添加 ${PLANNER_MAX_FILES} 个文件。`
        break
      }
      const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase()
      if (!PLANNER_FILE_EXTENSIONS.has(extension)) {
        plannerAttachmentMessage.value = `不支持“${file.name}”，请选择 md、txt、docx 或 pdf 文件。`
        continue
      }
      if (file.size > PLANNER_MAX_FILE_BYTES) {
        plannerAttachmentMessage.value = `“${file.name}”超过 10 MiB，无法添加。`
        continue
      }
      try {
        const result: AIPlannerExtractedFile = await api.extractPlannerFile(file)
        if (!result.extracted_text.trim() || result.parse_status === "failed" || result.parse_status === "unparseable") {
          plannerAttachmentMessage.value = `“${result.filename}”${result.error ? `：${result.error}` : "无法提取文字"}`
          continue
        }
        plannerAttachments.value.push({
          id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
          filename: result.filename,
          extracted_text: result.extracted_text,
        })
        if (result.parse_status === "truncated") {
          plannerAttachmentMessage.value = `“${result.filename}”内容较长，已提取可处理部分。`
        }
      } catch (reason) {
        plannerAttachmentMessage.value = `“${file.name}”添加失败：${messageOf(reason)}`
      }
    }
  } finally {
    plannerUploading.value = false
  }
}

function onPlannerFilesSelected(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files ?? [])
  input.value = ""
  void addPlannerFiles(files)
}

function onPlannerDragOver(event: DragEvent) {
  if (event.dataTransfer?.types.includes("Files")) plannerDragActive.value = true
}

function onPlannerDragLeave(event: DragEvent) {
  const target = event.currentTarget
  if (target instanceof HTMLElement && event.relatedTarget instanceof Node && target.contains(event.relatedTarget)) return
  plannerDragActive.value = false
}

function onPlannerDrop(event: DragEvent) {
  event.preventDefault()
  plannerDragActive.value = false
  const files = Array.from(event.dataTransfer?.files ?? [])
  if (files.length) void addPlannerFiles(files)
}

function editPlannerRequest() {
  plannerDraft.value = null
  plannerSelectedTaskIndex.value = null
  plannerNewTaskIndex.value = null
  error.value = ""
  navigate("/")
}

function newPlannerTask(): AIPlannerTaskDraft {
  return {
    title: "",
    deliverable: "",
    deadline: null,
    execution_points: [],
    cautions: [],
    prerequisites: [],
    owner_claimable: true,
    collaboration_open: false,
  }
}

function addPlannerTask() {
  if (!plannerDraft.value) return
  const index = plannerDraft.value.tasks.length
  plannerDraft.value.tasks.push(newPlannerTask())
  plannerTaskDetailsText.value.push({ execution_points: "", cautions: "", prerequisites: "" })
  plannerNewTaskIndex.value = index
  openPlannerTaskDetail(index, true)
}

function removePlannerTask(index: number) {
  plannerDraft.value?.tasks.splice(index, 1)
  plannerTaskDetailsText.value.splice(index, 1)
  if (plannerNewTaskIndex.value === index) plannerNewTaskIndex.value = null
  else if (plannerNewTaskIndex.value !== null && plannerNewTaskIndex.value > index) plannerNewTaskIndex.value -= 1
  if (plannerSelectedTaskIndex.value === index) plannerSelectedTaskIndex.value = null
  else if (plannerSelectedTaskIndex.value !== null && plannerSelectedTaskIndex.value > index) plannerSelectedTaskIndex.value -= 1
}

function plannerTaskStatus(task: AIPlannerTaskDraft) {
  return [task.owner_claimable ? "待认领" : "", task.collaboration_open ? "开放协作" : ""]
    .filter(Boolean)
    .join(" · ")
}

function openPlannerTaskDetail(index: number, focusTitle = false) {
  if (!plannerDraft.value?.tasks[index]) return
  plannerDetailScrollTop.value = window.scrollY
  plannerSelectedTaskIndex.value = index
  plannerEmptyDetailSection.value = null
  void nextTick(() => {
    if (focusTitle) plannerDetailTitleInput.value?.focus()
    else if (window.matchMedia("(max-width: 1100px)").matches) plannerDetailBackButton.value?.focus()
    else plannerDetailCloseButton.value?.focus()
  })
}

function isEmptyNewPlannerTask(index: number) {
  const task = plannerDraft.value?.tasks[index]
  const detail = plannerTaskDetailsText.value[index]
  return Boolean(
    task && detail &&
    !task.title.trim() &&
    !task.deliverable.trim() &&
    !parseTaskLines(detail.execution_points).length &&
    !parseTaskLines(detail.cautions).length &&
    !parseTaskLines(detail.prerequisites).length &&
    task.owner_claimable &&
    !task.collaboration_open,
  )
}

function closePlannerTaskDetail() {
  const index = plannerSelectedTaskIndex.value
  if (index === null) return
  const shouldRemoveEmptyNewTask = plannerNewTaskIndex.value === index && isEmptyNewPlannerTask(index)
  plannerSelectedTaskIndex.value = null
  plannerEmptyDetailSection.value = null
  if (shouldRemoveEmptyNewTask) removePlannerTask(index)
  void nextTick(() => {
    window.scrollTo(0, plannerDetailScrollTop.value)
    const focusIndex = shouldRemoveEmptyNewTask
      ? Math.min(index, Math.max((plannerDraft.value?.tasks.length ?? 1) - 1, 0))
      : index
    const card = document.querySelector<HTMLButtonElement>(`[data-planner-task-index="${focusIndex}"]`)
    if (card) card.focus()
    else plannerAddTaskButton.value?.focus()
  })
}

function deleteSelectedPlannerTask() {
  const index = plannerSelectedTaskIndex.value
  if (index === null) return
  plannerSelectedTaskIndex.value = null
  plannerEmptyDetailSection.value = null
  removePlannerTask(index)
  void nextTick(() => {
    window.scrollTo(0, plannerDetailScrollTop.value)
    const nextIndex = Math.min(index, Math.max((plannerDraft.value?.tasks.length ?? 1) - 1, 0))
    const card = document.querySelector<HTMLButtonElement>(`[data-planner-task-index="${nextIndex}"]`)
    if (card) card.focus()
    else plannerAddTaskButton.value?.focus()
  })
}

function openPlannerEmptyDetailSection(section: "execution_points" | "cautions" | "prerequisites") {
  plannerEmptyDetailSection.value = section
  void nextTick(() => {
    const field = document.querySelector<HTMLTextAreaElement>(`[data-planner-detail-field="${section}"]`)
    field?.focus()
  })
}

function handlePlannerDetailKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && plannerSelectedTaskIndex.value !== null) {
    event.preventDefault()
    closePlannerTaskDetail()
  }
}

function resetPlannerTaskDetails(draft: AIPlannerDraft) {
  plannerTaskDetailsText.value = draft.tasks.map((task) => ({
    execution_points: (task.execution_points ?? []).join("\n"),
    cautions: (task.cautions ?? []).join("\n"),
    prerequisites: (task.prerequisites ?? []).join("\n"),
  }))
}

function syncPlannerTaskDetails() {
  if (!plannerDraft.value) return
  plannerDraft.value.tasks.forEach((task, index) => {
    const text = plannerTaskDetailsText.value[index]
    if (!text) return
    task.execution_points = parseTaskLines(text.execution_points)
    task.cautions = parseTaskLines(text.cautions)
    task.prerequisites = parseTaskLines(text.prerequisites)
  })
}

function plannerTaskLineLimitMessage() {
  for (const [index, text] of plannerTaskDetailsText.value.entries()) {
    const limits = [
      [text.execution_points, 6, "怎么做"],
      [text.cautions, 5, "注意"],
      [text.prerequisites, 4, "开始前需要"],
    ] as const
    for (const [value, max, label] of limits) {
      const lines = parseTaskLines(value)
      if (lines.length > max) return `第 ${index + 1} 项${label}最多填写 ${max} 条。`
      if (lines.some((line) => line.length > 240)) return `第 ${index + 1} 项${label}每条最多 240 字。`
    }
  }
  return ""
}

function setPlannerDraft(draft: AIPlannerDraft) {
  draft.item.deadline = toLocalInput(draft.item.deadline)
  draft.tasks.forEach((task) => {
    task.deadline = toLocalInput(task.deadline)
  })
  plannerDraft.value = draft
  resetPlannerTaskDetails(draft)
  plannerSelectedTaskIndex.value = null
  plannerNewTaskIndex.value = null
}

function dismissPlannerSuggestion(index: number) {
  plannerDraft.value?.suggestions.splice(index, 1)
}

async function publishAIPlan() {
  const draft = plannerDraft.value
  if (!draft) return
  fieldErrors.value = {}
  if (!draft.item.title.trim()) {
    await showFieldError("planner-item-title", "请填写事项标题", "需要填写事项标题")
    return
  }
  const emptyTaskIndex = draft.tasks.findIndex((task) => !task.title.trim())
  if (emptyTaskIndex >= 0) {
    await showFieldError(`planner-task-title-${emptyTaskIndex}`, `请填写第 ${emptyTaskIndex + 1} 项分工标题`, "需要填写标题")
    return
  }
  const lineLimitError = plannerTaskLineLimitMessage()
  if (lineLimitError) {
    await showFieldError("planner-task-details", lineLimitError, lineLimitError)
    return
  }
  syncPlannerTaskDetails()

  error.value = ""
  plannerPublishing.value = true
  try {
    const result = await api.createTaskBatch({
      item: {
        title: draft.item.title.trim(),
        deliverable: draft.item.deliverable.trim(),
        deadline: draft.item.deadline || null,
      },
      tasks: draft.tasks.map((task) => ({
        title: task.title.trim(),
        deliverable: task.deliverable.trim(),
        deadline: task.deadline || null,
        execution_points: task.execution_points,
        cautions: task.cautions,
        prerequisites: task.prerequisites,
        owner_claimable: task.owner_claimable,
        collaboration_open: task.collaboration_open,
      })),
    })
    plannerDraft.value = null
    plannerDescription.value = ""
    plannerAttachments.value = []
    plannerAttachmentMessage.value = ""
    notice.value = `已创建事项和 ${result.tasks.length} 个分工`
    navigateTasks("all")
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    plannerPublishing.value = false
  }
}

async function syncGitHubKnowledge() {
  knowledgeSyncing.value = true
  error.value = ""
  try {
    knowledgeSyncSummary.value = await api.syncGitHubKnowledge()
    await loadKnowledgeDocuments()
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    knowledgeSyncing.value = false
  }
}

async function uploadKnowledgeFile(file: File) {
  knowledgeUploading.value = true
  error.value = ""
  try {
    await api.uploadKnowledgeDocument(file)
    await loadKnowledgeDocuments()
    notice.value = `已添加资料：${file.name}`
  } catch (reason) {
    error.value = messageOf(reason)
  } finally {
    knowledgeUploading.value = false
  }
}

async function removeKnowledgeDocument(document: KnowledgeDocument) {
  requestAppConfirmation({
    title: `删除知识条目“${document.title}”？`,
    description: "删除后，AI 规划将不再使用这份资料，该知识条目也会从当前资料列表中移除。",
    confirmLabel: "删除资料",
    danger: true,
    action: async () => {
      error.value = ""
      try {
        await api.deleteKnowledgeDocument(document.id)
        removePlannerCurrentDocument(document.id)
        await loadKnowledgeDocuments()
      } catch (reason) {
        error.value = messageOf(reason)
      }
    },
  })
}

function knowledgeStatusLabel(document: KnowledgeDocument) {
  if (!document.is_active || document.parse_status === "removed") return "已从来源移除"
  const labels = {
    ready: "可检索",
    truncated: "已截断，可检索",
    failed: "解析失败",
    unparseable: "未提取到文字",
    removed: "已从来源移除",
  }
  const label = labels[document.parse_status]
  return document.parse_error ? `${label} · ${document.parse_error}` : label
}

async function logout() {
  await api.logout()
  user.value = null
  tasks.value = []
  members.value = []
  taskMembers.value = []
  aiReviewAvailable.value = false
  plannerDraft.value = null
  navigate("/login")
}

function handlePopState() {
  const nextPath = window.location.pathname
  if (path.value !== nextPath && isTaskEditorRoute.value) initializedTaskEditorPath = ""
  if (path.value !== nextPath && (/^\/tasks\/\d+$/.test(path.value) || /^\/tasks\/\d+$/.test(nextPath))) {
    clearFactSuggestions()
    taskProgressDraft.value = ""
    taskCompletionDraft.value = ""
    taskCompletionSync.value = false
  }
  if (window.location.pathname !== path.value) clearItemReview()
  path.value = window.location.pathname
  fieldErrors.value = {}
  error.value = ""
  if (feedback.value?.kind === "error") clearFeedback()
  syncCollaborationRefreshTimer()
  void loadRoute()
}

onMounted(async () => {
  window.addEventListener("popstate", handlePopState)
  window.addEventListener("keydown", handlePlannerDetailKeydown)
  window.addEventListener("focus", handleExecutionRefreshSignal)
  document.addEventListener("visibilitychange", handleExecutionRefreshSignal)
  if (!isCampLeavePublicRoute.value && !isDailyLeavePublicRoute.value) {
    try {
      await loadCurrentUser()
    } catch (reason) {
      error.value = messageOf(reason)
    }
  }
  await loadRoute()
  syncCollaborationRefreshTimer()
})

onBeforeUnmount(() => {
  window.removeEventListener("popstate", handlePopState)
  window.removeEventListener("keydown", handlePlannerDetailKeydown)
  window.removeEventListener("focus", handleExecutionRefreshSignal)
  document.removeEventListener("visibilitychange", handleExecutionRefreshSignal)
  if (collaborationRefreshTimer !== undefined) window.clearInterval(collaborationRefreshTimer)
  if (feedbackTimer !== undefined) window.clearTimeout(feedbackTimer)
})
</script>

<template>
  <div v-if="feedback" class="toast-layer" aria-label="操作提示">
    <div class="toast-message" :class="`toast-${feedback.kind}`" :role="feedback.kind === 'error' ? 'alert' : 'status'" :aria-live="feedback.kind === 'error' ? 'assertive' : 'polite'">
      <span>{{ feedback.message }}</span>
      <button type="button" aria-label="关闭提示" @click="clearFeedback">×</button>
    </div>
  </div>

  <ConfirmDialog
    :open="appConfirm !== null"
    :title="appConfirm?.title ?? ''"
    :description="appConfirm?.description ?? ''"
    :confirm-label="appConfirm?.confirmLabel ?? '确认'"
    :danger="appConfirm?.danger ?? false"
    :pending="appConfirmPending"
    @cancel="cancelAppConfirmation"
    @confirm="confirmAppConfirmation"
  />

  <main v-if="path.startsWith('/leave/camp/')" class="auth-shell">
    <CampLeavePublicPage :token="campLeavePublicToken" />
  </main>

  <main v-else-if="path.startsWith('/leave/daily/')" class="auth-shell">
    <DailyLeavePublicPage :token="dailyLeavePublicToken" />
  </main>

  <main v-else-if="path === '/login'" class="auth-shell">
    <form class="auth-form" @submit.prevent="submitLogin">
      <p class="brand">TARS BASE</p>
      <h1>登录</h1>
      <label>
        邮箱
        <input v-model="loginEmail" type="email" autocomplete="email" required />
      </label>
      <label>
        密码
        <input
          v-model="loginPassword"
          type="password"
          autocomplete="current-password"
          required
        />
      </label>
      <button class="primary" type="submit">登录</button>
    </form>
  </main>

  <main v-else-if="path.startsWith('/invite/')" class="auth-shell">
    <section class="auth-form">
      <p class="brand">TARS BASE</p>
      <template v-if="invitation">
        <h1>设置密码</h1>
        <div class="identity">
          <strong>{{ invitation.name }}</strong>
          <span>{{ invitation.email }}</span>
        </div>
        <form @submit.prevent="submitInvitation">
          <label>
            密码
            <input
              v-model="invitePassword"
              type="password"
              minlength="8"
              maxlength="128"
              autocomplete="new-password"
              required
            />
          </label>
          <label>
            确认密码
            <input
              v-model="invitePasswordConfirm"
              type="password"
              minlength="8"
              maxlength="128"
              autocomplete="new-password"
              required
            />
          </label>
          <button class="primary" type="submit">激活账号</button>
        </form>
      </template>
      <div v-else-if="loading" class="tars-loading tars-loading-auth" role="status" aria-live="polite">
        <div class="tars-loading-mark" aria-hidden="true">
          <span class="tars-loading-block block-a"></span>
          <span class="tars-loading-block block-b"></span>
          <span class="tars-loading-block block-c"></span>
          <span class="tars-loading-block block-d"></span>
        </div>
        <div class="tars-loading-copy">
          <strong>TARS BASE</strong>
          <span>正在验证邀请…</span>
        </div>
      </div>
      <div v-else class="empty auth-empty-state">
        <span class="empty-code">BASE / INVITE</span>
        <h1>无法使用邀请</h1>
        <p>{{ error || "邀请无效或已失效，请联系管理员。" }}</p>
        <button class="secondary" type="button" @click="navigate('/login')">返回登录</button>
      </div>
    </section>
  </main>

  <main v-else-if="path.startsWith('/register/')" class="auth-shell">
    <section class="auth-form">
      <p class="brand">TARS BASE</p>
      <template v-if="registrationInfo">
        <h1>加入吉甲大师</h1>
        <p class="muted">请使用本人真实信息完成注册。</p>
        <form @submit.prevent="submitRegistration">
          <label>
            姓名
            <input
              v-model="registrationName"
              autocomplete="name"
              required
              :aria-invalid="Boolean(registrationFieldErrors.name)"
              @input="clearRegistrationFieldError('name')"
            />
            <small v-if="registrationFieldErrors.name" class="field-error">{{ registrationFieldErrors.name }}</small>
          </label>
          <label>
            学号
            <input
              v-model="registrationStudentId"
              maxlength="8"
              inputmode="numeric"
              autocomplete="off"
              required
              :aria-invalid="Boolean(registrationFieldErrors.student_id)"
              @input="clearRegistrationFieldError('student_id')"
            />
            <small v-if="registrationFieldErrors.student_id" class="field-error">{{ registrationFieldErrors.student_id }}</small>
          </label>
          <label>
            所属学院
            <CollegeSelect
              v-model="registrationCollege"
              :options="collegeOptions"
              required
              :invalid="Boolean(registrationFieldErrors.college)"
              @change="clearRegistrationFieldError('college')"
            />
            <small v-if="registrationFieldErrors.college" class="field-error">{{ registrationFieldErrors.college }}</small>
          </label>
          <label>
            邮箱
            <input v-model="registrationEmail" type="email" maxlength="255" autocomplete="email" required />
          </label>
          <label>
            所属组别
            <select v-model="registrationTeamGroup" required>
              <option value="" disabled>请选择</option>
              <option v-for="(label, code) in groupLabels" :key="code" :value="code">{{ label }}</option>
            </select>
          </label>
          <label>
            密码
            <input
              v-model="registrationPassword"
              type="password"
              minlength="8"
              maxlength="128"
              autocomplete="new-password"
              required
            />
          </label>
          <label>
            确认密码
            <input
              v-model="registrationPasswordConfirm"
              type="password"
              minlength="8"
              maxlength="128"
              autocomplete="new-password"
              required
            />
          </label>
          <button class="primary" type="submit" :disabled="registrationSubmitting">
            {{ registrationSubmitting ? "正在注册…" : "注册并进入 TARS BASE" }}
          </button>
        </form>
      </template>

      <div v-else-if="registrationChecking" class="tars-loading tars-loading-auth" role="status" aria-live="polite">
        <div class="tars-loading-mark" aria-hidden="true">
          <span class="tars-loading-block block-a"></span>
          <span class="tars-loading-block block-b"></span>
          <span class="tars-loading-block block-c"></span>
          <span class="tars-loading-block block-d"></span>
        </div>
        <div class="tars-loading-copy">
          <strong>TARS BASE</strong>
          <span>正在验证注册链接…</span>
        </div>
      </div>

      <div v-else-if="registrationLoadError" class="empty auth-empty-state">
        <span class="empty-code">BASE / REGISTER</span>
        <h1>暂时无法验证注册链接</h1>
        <p>{{ registrationLoadError }}</p>
        <button class="secondary" type="button" @click="loadRoute()">重新加载</button>
      </div>

      <div v-else-if="registrationEnded" class="empty auth-empty-state">
        <span class="empty-code">BASE / REGISTER</span>
        <h1>本次团队注册已结束</h1>
        <button class="secondary" type="button" @click="navigate('/login')">返回登录</button>
      </div>
    </section>
  </main>

  <main v-else class="app-shell">
    <div class="brand-ribbon" aria-hidden="true"></div>

    <aside class="desktop-sidebar" aria-label="主导航">
      <div class="sidebar-brand-block">
        <button class="sidebar-brand" type="button" @click="navigate('/')">TARS BASE</button>
        <span>JILIN UNIVERSITY · TARS-GO</span>
      </div>

      <nav class="sidebar-nav">
        <button :class="{ active: path === '/' }" type="button" @click="navigate('/')">Base</button>
        <button :class="{ active: path.startsWith('/tasks') }" type="button" @click="navigateTasks('mine')">
          任务
        </button>
        <button :class="{ active: path === '/leave' }" type="button" @click="navigate('/leave')">
          请假 <span v-if="isAdmin && schoolLeaveTodoCount" class="nav-count">{{ schoolLeaveTodoCount }}</span>
        </button>
        <button
          v-if="isAdmin"
          :class="{ active: isTeamRoute }"
          type="button"
          @click="navigate('/team')"
        >
          团队
        </button>
        <button :class="{ active: isMeRoute }" type="button" @click="navigate('/me')">
          我的
        </button>
      </nav>

      <div class="sidebar-account">
        <div class="sidebar-user">
          <strong>{{ user?.name }}</strong>
          <span>{{ user ? roleLabels[user.role] : "" }}</span>
        </div>
        <div class="sidebar-user-actions">
          <button type="button" @click="navigate('/me')">个人信息</button>
          <button type="button" @click="logout">退出登录</button>
        </div>
      </div>
    </aside>

    <header class="mobile-topbar">
      <span class="brand">TARS BASE</span>
      <span class="product-label">JLU · TARS-GO</span>
    </header>

    <div v-if="loading" class="page tars-loading-page">
      <div class="tars-loading" role="status" aria-live="polite">
        <div class="tars-loading-mark" aria-hidden="true">
          <span class="tars-loading-block block-a"></span>
          <span class="tars-loading-block block-b"></span>
          <span class="tars-loading-block block-c"></span>
          <span class="tars-loading-block block-d"></span>
        </div>
        <div class="tars-loading-copy">
          <strong>TARS BASE</strong>
          <span>正在加载…</span>
        </div>
      </div>
    </div>

    <div v-else class="page">
      <template v-if="routeNotFound">
        <section class="system-state">
          <span class="system-code">BASE / 404</span>
          <h1>这个路径不属于当前 Base</h1>
          <p>可能是链接已经变化，或者地址输入有误。</p>
          <button class="primary" type="button" @click="navigate('/')">返回 Base</button>
        </section>
      </template>

      <section v-else-if="taskDetailId !== null && detailContextLoading" class="system-state" role="status" aria-live="polite">
        <span class="system-code">BASE / TASK</span>
        <h1>正在加载任务</h1>
        <p>正在读取任务信息和最近进展…</p>
      </section>

      <template v-else-if="isTaskEditorRoute">
        <div class="page-title task-editor-heading">
          <div>
            <button class="task-editor-back" type="button" @click="cancelTaskForm">← 返回</button>
            <small v-if="parentTask" class="form-context">分工属于：{{ parentTask.title }}</small>
            <h1>{{ taskEditorHeading }}</h1>
          </div>
        </div>

        <section v-if="taskEditorLoading" class="system-state" role="status" aria-live="polite">
          <span class="loading-dot" aria-hidden="true"></span>
          正在加载事项信息…
        </section>

        <form v-else-if="isAdmin" class="task-editor-form" @submit.prevent="submitTask">
          <label>
            要做什么？
            <input
              v-model="taskTitle"
              data-validation-field="task-title"
              :aria-invalid="Boolean(fieldErrors['task-title'])"
              maxlength="200"
              placeholder="例如：现场摄影"
              @input="clearFieldError('task-title')"
            />
            <small v-if="fieldErrors['task-title']" class="field-error">{{ fieldErrors['task-title'] }}</small>
          </label>

          <fieldset>
            <legend>负责人</legend>
            <div class="choice-row">
              <label class="choice-option">
                <input v-model="taskOwnerMode" type="radio" value="assigned" />
                指定负责人
              </label>
              <label class="choice-option">
                <input v-model="taskOwnerMode" type="radio" value="claimable" />
                待认领
              </label>
            </div>
            <div v-if="taskOwnerMode === 'assigned'" class="member-picker">
              <MemberSearchFilters
                v-model:query="taskOwnerSearch"
                v-model:group="taskOwnerGroupFilter"
                :group-labels="groupLabels"
                search-label="按姓名搜索"
                search-placeholder="搜索负责人姓名"
              />
              <p v-if="selectedTaskOwner" class="member-picker-selection">
                当前负责人：<strong>{{ selectedTaskOwner.name }}</strong>
              </p>
              <div
                class="member-picker-options"
                role="radiogroup"
                aria-label="负责人"
                :aria-invalid="Boolean(fieldErrors['task-owner'])"
                data-validation-field="task-owner"
                tabindex="-1"
              >
                <label v-for="member in filteredOwnerOptions" :key="member.id" class="check-row member-option-row">
                  <input
                    v-model="taskOwnerId"
                    type="radio"
                    name="task-owner"
                    :value="member.id"
                    @change="clearFieldError('task-owner')"
                  />
                  <span class="member-option-copy">
                    <strong>{{ member.name }}{{ activeMemberIds.has(member.id) ? "" : "（已停用）" }}</strong>
                    <small>{{ taskMemberGroupLabel(member) }}</small>
                  </span>
                </label>
                <span v-if="!filteredOwnerOptions.length" class="muted">没有符合条件的负责人。</span>
              </div>
            </div>
            <small v-if="fieldErrors['task-owner']" class="field-error">{{ fieldErrors['task-owner'] }}</small>
          </fieldset>

          <label>
            截止时间（可选）
            <input v-model="taskDeadline" type="datetime-local" />
            <small>没有明确时间可以留空。</small>
          </label>

          <details class="advanced-fields">
            <summary>{{ taskEditorShowsExecutionFields ? "执行说明与协作设置" : "协作设置" }}</summary>
            <div class="advanced-grid">
              <label v-if="taskEditorShowsExecutionFields">
                做到什么算完成
                <textarea
                  v-model="taskDeliverable"
                  maxlength="5000"
                  rows="3"
                  placeholder="写清楚看到什么结果即可判定完成"
                />
              </label>

              <section v-if="taskEditorShowsExecutionFields" class="task-edit-hints">
                <h3>执行提示</h3>
                <label>
                  怎么做（每行一条，最多 6 条）
                  <textarea v-model="taskExecutionPointsText" data-validation-field="task-execution-points" rows="2" placeholder="写完成责任所需的关键步骤" />
                  <small v-if="fieldErrors['task-execution-points']" class="field-error">{{ fieldErrors['task-execution-points'] }}</small>
                </label>
                <label v-if="taskCautionsText.trim() || taskCautionsOpen">
                  注意（每行一条，最多 5 条）
                  <textarea v-model="taskCautionsText" data-validation-field="task-cautions" rows="2" placeholder="只写与当前任务直接相关的提醒" />
                  <small v-if="fieldErrors['task-cautions']" class="field-error">{{ fieldErrors['task-cautions'] }}</small>
                </label>
                <button v-else class="planner-add-detail" type="button" @click="taskCautionsOpen = true">＋ 添加注意</button>
              </section>

              <section v-if="taskEditorShowsExecutionFields" class="task-edit-prerequisites">
                <label v-if="taskPrerequisitesText.trim() || taskPrerequisitesOpen">
                  开始前需要（每行一条，最多 4 条）
                  <textarea v-model="taskPrerequisitesText" data-validation-field="task-prerequisites" rows="2" placeholder="只有缺少时任务就不能合理开始的条件" />
                  <small v-if="fieldErrors['task-prerequisites']" class="field-error">{{ fieldErrors['task-prerequisites'] }}</small>
                </label>
                <button v-else class="planner-add-detail" type="button" @click="taskPrerequisitesOpen = true">＋ 添加开始条件</button>
              </section>

              <fieldset v-if="parentTaskId !== null" class="dependency-edit-list">
                <legend>等待哪些分工（可选）</legend>
                <label v-for="dependency in availableDependencyTasks" :key="dependency.id" class="check-row">
                  <input v-model="taskDependencyIds" type="checkbox" :value="dependency.id" />
                  {{ dependency.title }} · {{ statusLabels[dependency.status] }}
                </label>
                <small v-if="!availableDependencyTasks.length" class="muted">同一事项下还没有其他分工。</small>
              </fieldset>

              <fieldset>
                <legend>协作者（已选 {{ taskCollaboratorIds.length }} 人）</legend>
                <MemberSearchFilters
                  v-model:query="taskCollaboratorSearch"
                  v-model:group="taskCollaboratorGroupFilter"
                  :group-labels="groupLabels"
                  search-label="按姓名搜索"
                  search-placeholder="搜索协作者姓名"
                />
                <div class="member-picker-options">
                  <label v-for="member in filteredCollaborators" :key="member.id" class="check-row member-option-row">
                    <input v-model="taskCollaboratorIds" type="checkbox" :value="member.id" />
                    <span class="member-option-copy">
                      <strong>{{ member.name }}</strong>
                      <small>{{ taskMemberGroupLabel(member) }}</small>
                    </span>
                  </label>
                  <span v-if="!filteredCollaborators.length" class="muted">
                    {{ activeMembers.length <= 1 ? "暂无其他可选成员" : "没有符合条件的协作者。" }}
                  </span>
                </div>
              </fieldset>

              <label class="check-row">
                <input v-model="taskCollaborationOpen" type="checkbox" />
                允许成员自行加入 / 退出协作
              </label>

              <label v-if="taskOwnerMode === 'assigned'" class="check-row">
                <input v-model="taskOwnerClaimable" type="checkbox" />
                允许负责人取消后重新开放认领
              </label>

              <label>
                状态
                <select v-model="taskStatus">
                  <option value="todo">待开始</option>
                  <option value="doing">进行中</option>
                  <option value="done">已完成</option>
                </select>
              </label>
            </div>
          </details>

          <button class="primary task-editor-save" type="submit" :disabled="taskSaving">
            {{ taskSaving ? "正在保存…" : editingTaskId !== null ? "保存修改" : parentTaskId !== null ? "添加分工" : taskEditor?.kind === "new-task" ? "创建独立任务" : "发布事项" }}
          </button>
        </form>
      </template>

      <template v-else-if="path === '/'">
        <section class="base-entry">
          <p class="base-kicker">TARS BASE</p>
          <h1>{{ isAdmin ? "现在要处理什么？" : "现在要处理" }}</h1>
          <button v-if="isAdmin" class="primary" type="button" @click="startIndependentTask">快速创建独立任务</button>

          <div
            v-if="isAdmin"
            class="planner-composer base-composer"
            :class="{ 'is-drag-active': plannerDragActive, 'is-uploading': plannerUploading }"
            @dragenter.prevent="onPlannerDragOver"
            @dragover.prevent="onPlannerDragOver"
            @dragleave="onPlannerDragLeave"
            @drop="onPlannerDrop"
          >
            <textarea
              v-model="plannerDescription"
              maxlength="5000"
              rows="5"
              aria-label="描述一个事项、活动或需要协调的事情"
              placeholder="描述一个事项、活动或需要协调的事情…"
            />
            <div v-if="plannerAttachments.length" class="planner-attachments" aria-label="本次规划附件">
              <span v-for="attachment in plannerAttachments" :key="attachment.id" class="planner-attachment">
                <span class="planner-attachment-icon" aria-hidden="true">↳</span>
                <span class="planner-attachment-name">{{ attachment.filename }}</span>
                <button type="button" :aria-label="`移除 ${attachment.filename}`" @click="removePlannerAttachment(attachment.id)">×</button>
              </span>
            </div>
            <div class="planner-composer-footer">
              <div class="planner-composer-tools">
                <input
                  ref="plannerFileInput"
                  class="visually-hidden"
                  type="file"
                  accept=".md,.txt,.docx,.pdf"
                  multiple
                  @change="onPlannerFilesSelected"
                />
                <button class="planner-add-file" type="button" :disabled="plannerUploading" @click="choosePlannerFiles">
                  {{ plannerUploading ? "正在读取…" : "＋ 添加资料" }}
                </button>
              </div>
              <div class="planner-external-actions">
                <button
                  class="secondary"
                  type="button"
                  :disabled="(plannerDescription.trim().length < 10 && !plannerAttachmentContext.trim()) || plannerUploading"
                  @click="copyExternalAIPlannerPrompt"
                >复制 AI 提示词</button>
                <button class="secondary" type="button" @click="togglePlannerImport">导入 AI 方案</button>
              </div>
            </div>
            <div v-if="plannerImportOpen" class="planner-import-panel">
              <label for="external-planner-json">粘贴外部 AI 返回的 JSON</label>
              <textarea
                id="external-planner-json"
                v-model="plannerImportJson"
                rows="8"
                spellcheck="false"
                aria-describedby="external-planner-json-help"
                placeholder="粘贴符合 AIPlannerDraft 格式的 JSON……"
              />
              <small id="external-planner-json-help">导入只会填入可编辑草案，不会创建事项；检查并手动确认后才会发布。</small>
              <p v-if="plannerImportError" class="planner-import-error" role="alert">{{ plannerImportError }}</p>
              <div class="planner-import-actions">
                <button class="secondary" type="button" @click="togglePlannerImport">取消</button>
                <button class="primary" type="button" :disabled="!plannerImportJson.trim()" @click="importExternalAIPlanner">验证并导入</button>
              </div>
            </div>
          </div>
          <p v-if="isAdmin && plannerAttachmentMessage" class="planner-composer-message" role="status">{{ plannerAttachmentMessage }}</p>
          <p v-if="isAdmin && plannerAttachmentContextTruncated" class="planner-composer-message" role="status">附件内容超过 5,000 字；复制提示词时只包含前 5,000 字。</p>
          <p v-if="isAdmin && plannerExternalMessage" class="planner-composer-message" role="status">{{ plannerExternalMessage }}</p>
        </section>

        <section v-if="homeTaskCards.length" class="base-home-section">
          <div class="section-heading">
            <h2>现在要处理</h2>
          </div>
          <div class="home-task-cards">
            <button
              v-for="task in visibleHomeTaskCards"
              :key="task.id"
              class="home-task-card"
              type="button"
              @click="openTaskDetail(task)"
            >
              <span v-if="task.parent_id" class="state">{{ homeRoot(task)?.title || "事项" }}</span>
              <span v-else class="state">{{ isIndependentTask(task) ? "独立任务" : "事项" }}</span>
              <strong>{{ task.title }}</strong>
              <span class="home-task-meta">
                <TaskStatusIndicator :status="task.status" :task-id="task.id" />
                <template v-if="task.deadline"> · {{ formatDate(task.deadline) }}</template>
              </span>
              <span class="home-task-arrow" aria-hidden="true">›</span>
            </button>
          </div>
          <button v-if="homeTaskCards.length > 3" class="base-home-more" type="button" @click="navigateTasks('mine')">查看全部任务 →</button>
        </section>

        <section v-if="homeRecentChanges.length" class="base-home-section">
          <div class="section-heading">
            <h2>最近与你有关</h2>
          </div>
          <ul class="base-change-list">
            <li v-for="change in homeRecentChanges" :key="change.id" class="base-change-row">
              <span class="base-change-context">{{ change.context }}</span>
              <p>{{ change.content }}</p>
              <time>{{ formatDate(change.created_at) }}</time>
            </li>
          </ul>
        </section>

        <button
          v-if="claimableCount"
          class="claimable-link base-claimable-link"
          type="button"
          @click="navigateTasks('claimable')"
        >
          <span>还有 {{ claimableCount }} 项可以认领 →</span>
        </button>
      </template>

      <template v-else-if="path === '/planner-draft' && plannerDraft">
        <div class="page-title planner-heading">
          <h1>审核事项草案</h1>
          <button type="button" @click="navigate('/')">返回 Base</button>
        </div>

        <section class="planner-result">
          <div class="planner-result-toolbar">
            <button class="planner-back-link" type="button" @click="editPlannerRequest">← 修改原始需求</button>
            <span>方案草案</span>
          </div>
          <div class="planner-result-layout" :class="{ 'is-detail-open': plannerSelectedTaskIndex !== null }">
            <div class="planner-overview-column">
              <section class="planner-overview-heading" aria-labelledby="planner-item-title">
                <div>
                  <p>事项总览</p>
                  <h1 id="planner-item-title">{{ plannerDraft.item.title || "未命名事项" }}</h1>
                  <span>{{ plannerDraft.tasks.length }} 个执行任务<template v-if="plannerDraft.item.deadline"> · 事项时间建议 {{ formatDate(plannerDraft.item.deadline) }}</template></span>
                </div>
                <button
                  ref="plannerAddTaskButton"
                  class="secondary planner-add-task"
                  type="button"
                  @click="addPlannerTask"
                >＋ 添加任务</button>
              </section>

              <section class="planner-section planner-overview-tasks">
                <div class="form-title">
                  <h2>执行分工 <span class="planner-task-count">· {{ plannerDraft.tasks.length }} 项</span></h2>
                </div>
                <div v-if="plannerDraft.tasks.length" class="planner-task-list">
                  <button
                    v-for="(task, index) in plannerDraft.tasks"
                    :key="index"
                    :data-planner-task-index="index"
                    class="planner-task-summary"
                    type="button"
                    :aria-label="`打开第 ${index + 1} 项详情：${task.title || '未命名任务'}`"
                    :aria-expanded="plannerSelectedTaskIndex === index"
                    @click="openPlannerTaskDetail(index)"
                  >
                    <span class="planner-summary-index">{{ String(index + 1).padStart(2, "0") }}</span>
                    <span class="planner-summary-content">
                      <strong>{{ task.title || "未命名分工" }}</strong>
                      <span v-if="task.deliverable" class="planner-summary-deliverable">{{ task.deliverable }}</span>
                      <small v-if="task.deadline" class="planner-summary-deadline">建议截止 {{ formatDate(task.deadline) }}</small>
                      <span v-if="plannerTaskStatus(task)" class="planner-summary-status">{{ plannerTaskStatus(task) }}</span>
                    </span>
                    <span class="planner-summary-chevron" aria-hidden="true">›</span>
                  </button>
                </div>
                <p v-else class="muted">当前没有分工，可以直接发布事项或添加一项。</p>
              </section>

              <details class="planner-item-edit">
                <summary>事项信息</summary>
                <div class="planner-fields">
                  <label>
                    事项标题
                    <input
                      v-model="plannerDraft.item.title"
                      data-validation-field="planner-item-title"
                      :aria-invalid="Boolean(fieldErrors['planner-item-title'])"
                      maxlength="200"
                      @input="clearFieldError('planner-item-title')"
                    />
                    <small v-if="fieldErrors['planner-item-title']" class="field-error">{{ fieldErrors['planner-item-title'] }}</small>
                  </label>
                  <div class="planner-deadline-field">
                    <label>
                      建议截止时间（可选）
                      <input v-model="plannerDraft.item.deadline" type="datetime-local" />
                      <small>可保留、修改或清除；没有可靠时间依据时留空。</small>
                    </label>
                    <button v-if="plannerDraft.item.deadline" class="text-action" type="button" @click="plannerDraft.item.deadline = ''">清除建议</button>
                  </div>
                </div>
              </details>

              <div v-if="plannerDraft.questions.length" class="planner-section planner-questions">
                <h2>需要确认 · {{ plannerDraft.questions.length }}</h2>
                <ul>
                  <li v-for="question in plannerDraft.questions" :key="question">{{ question }}</li>
                </ul>
              </div>

              <div v-if="plannerDraft.suggestions.length" class="planner-section planner-suggestions">
                <h2>可能遗漏 <span class="planner-task-count">· {{ plannerDraft.suggestions.length }}</span></h2>
                <div class="planner-suggestion-list">
                  <article v-for="(suggestion, index) in plannerDraft.suggestions" :key="suggestion.title + '-' + suggestion.reason" class="planner-suggestion">
                    <div>
                      <h3>{{ suggestion.title }}</h3>
                      <p>{{ suggestion.reason }}</p>
                    </div>
                    <div class="planner-suggestion-actions">
                      <button class="text-action" type="button" :disabled="plannerPublishing" @click="dismissPlannerSuggestion(index)">忽略</button>
                    </div>
                  </article>
                </div>
              </div>

              <div class="planner-publish">
                <button class="primary" type="button" :disabled="plannerPublishing" @click="publishAIPlan">
                  {{ plannerPublishing ? "正在创建…" : "确认并创建" }}
                </button>
              </div>
            </div>

            <aside
              v-if="plannerSelectedTask && plannerSelectedTaskIndex !== null"
              class="planner-task-detail"
              :aria-label="`第 ${plannerSelectedTaskIndex + 1} 项任务详情`"
              role="region"
            >
              <header class="planner-task-detail-header">
                <button ref="plannerDetailBackButton" class="planner-detail-back" type="button" @click="closePlannerTaskDetail">← 返回方案</button>
                <div class="planner-detail-heading">
                  <span>{{ String(plannerSelectedTaskIndex + 1).padStart(2, "0") }}</span>
                  <small>任务详情</small>
                </div>
                <button
                  ref="plannerDetailCloseButton"
                  class="planner-detail-close"
                  type="button"
                  aria-label="关闭任务详情"
                  @click="closePlannerTaskDetail"
                >×</button>
              </header>

              <div class="planner-task-detail-body">
                <label class="planner-detail-title-field">
                  任务标题
                  <input
                    ref="plannerDetailTitleInput"
                    v-model="plannerSelectedTask.title"
                    class="planner-task-title"
                    :data-validation-field="`planner-task-title-${plannerSelectedTaskIndex}`"
                    :aria-invalid="Boolean(fieldErrors[`planner-task-title-${plannerSelectedTaskIndex}`])"
                    maxlength="200"
                    aria-label="任务标题"
                    @input="clearFieldError(`planner-task-title-${plannerSelectedTaskIndex}`)"
                  />
                  <small v-if="fieldErrors[`planner-task-title-${plannerSelectedTaskIndex}`]" class="field-error">{{ fieldErrors[`planner-task-title-${plannerSelectedTaskIndex}`] }}</small>
                </label>
                <label class="planner-detail-deliverable">
                  做到什么算完成
                  <textarea v-model="plannerSelectedTask.deliverable" maxlength="5000" rows="3" placeholder="写清楚看到什么结果即可判定完成" />
                </label>
                <div class="planner-detail-deadline">
                  <label>
                    建议截止时间（可选）
                    <input v-model="plannerSelectedTask.deadline" type="datetime-local" />
                    <small>可保留、修改或清除；没有可靠时间依据时留空。</small>
                  </label>
                  <button v-if="plannerSelectedTask.deadline" class="text-action" type="button" @click="plannerSelectedTask.deadline = ''">清除建议</button>
                </div>

                <section
                  v-if="plannerTaskDetailsText[plannerSelectedTaskIndex] && (parseTaskLines(plannerTaskDetailsText[plannerSelectedTaskIndex].execution_points).length || parseTaskLines(plannerTaskDetailsText[plannerSelectedTaskIndex].cautions).length || plannerEmptyDetailSection === 'execution_points' || plannerEmptyDetailSection === 'cautions')"
                  class="planner-detail-section planner-execution-hints"
                >
                  <h3>执行提示</h3>
                  <label v-if="parseTaskLines(plannerTaskDetailsText[plannerSelectedTaskIndex].execution_points).length || plannerEmptyDetailSection === 'execution_points'" class="planner-detail-subfield">
                    怎么做
                    <textarea
                      v-model="plannerTaskDetailsText[plannerSelectedTaskIndex].execution_points"
                      data-planner-detail-field="execution_points"
                      data-validation-field="planner-execution-points"
                      rows="2"
                      maxlength="1600"
                      aria-label="怎么做，每行一条，最多 6 条"
                      placeholder="写完成责任所需的关键步骤；每行一条"
                    />
                  </label>
                  <button v-else class="planner-add-detail" type="button" @click="openPlannerEmptyDetailSection('execution_points')">＋ 添加怎么做</button>
                  <label v-if="parseTaskLines(plannerTaskDetailsText[plannerSelectedTaskIndex].cautions).length || plannerEmptyDetailSection === 'cautions'" class="planner-detail-subfield">
                    注意
                    <textarea
                      v-model="plannerTaskDetailsText[plannerSelectedTaskIndex].cautions"
                      data-planner-detail-field="cautions"
                      data-validation-field="planner-cautions"
                      rows="2"
                      maxlength="1200"
                      aria-label="注意，每行一条，最多 5 条"
                      placeholder="只写与当前任务直接相关的提醒"
                    />
                  </label>
                  <button v-else class="planner-add-detail" type="button" @click="openPlannerEmptyDetailSection('cautions')">＋ 添加注意</button>
                </section>
                <button v-else class="planner-add-detail" type="button" @click="openPlannerEmptyDetailSection('execution_points')">＋ 添加执行提示</button>

                <section
                  v-if="plannerTaskDetailsText[plannerSelectedTaskIndex] && (parseTaskLines(plannerTaskDetailsText[plannerSelectedTaskIndex].prerequisites).length || plannerEmptyDetailSection === 'prerequisites')"
                  class="planner-detail-section"
                >
                  <h3>开始前需要</h3>
                  <textarea
                    v-model="plannerTaskDetailsText[plannerSelectedTaskIndex].prerequisites"
                    data-planner-detail-field="prerequisites"
                    data-validation-field="planner-prerequisites"
                    rows="2"
                    maxlength="960"
                    aria-label="开始前需要，每行一条，最多 4 条"
                    placeholder="只有缺少时任务就不能合理开始的条件"
                  />
                </section>
                <button v-else class="planner-add-detail" type="button" @click="openPlannerEmptyDetailSection('prerequisites')">＋ 添加开始条件</button>

                <div class="planner-options planner-detail-options">
                  <div class="planner-option">
                    <label class="check-row">
                      <input v-model="plannerSelectedTask.owner_claimable" type="checkbox" />
                      开放负责人认领
                    </label>
                    <small v-if="!plannerSelectedTask.owner_claimable" class="muted">关闭后，确认发布时由你暂代负责人。</small>
                  </div>
                  <label class="check-row">
                    <input v-model="plannerSelectedTask.collaboration_open" type="checkbox" />
                    开放成员自行加入协作
                  </label>
                </div>

                <button class="planner-delete-task" type="button" @click="deleteSelectedPlannerTask">删除这项分工</button>
              </div>
            </aside>
          </div>
        </section>
      </template>

      <template v-else-if="taskDetailId !== null && detailTask && detailRoot">
        <div class="page-title execution-detail-heading">
          <div>
            <button class="detail-back" type="button" @click="detailTask.parent_id ? openTaskDetail(detailRoot) : navigateTasks('all')">← 返回</button>
            <span class="state">{{ detailTask.parent_id ? detailRoot.title : isIndependentTask(detailTask) ? "独立任务" : "事项执行" }}</span>
            <h1>{{ detailTask.title }}</h1>
          </div>
          <TaskActionMenu
            v-if="detailTask.parent_id === null"
            :task-id="`detail-root-${detailTask.id}`"
            :aria-label="isIndependentTask(detailTask) ? '独立任务更多操作' : '事项更多操作'"
            :actions="detailRootTaskMenuActions(detailTask)"
            :disabled="Boolean(pendingTaskAction(detailTask.id))"
            @select="handleDetailRootTaskMenuAction(detailTask, $event)"
          />
          <button v-else-if="isAdmin" type="button" @click="editTaskFromDetail(detailTask)">编辑</button>
        </div>

        <template v-if="detailTask.kind === 'item'">
          <section class="execution-section">
            <div class="execution-meta">
              <TaskStatusIndicator
                :status="detailTask.status"
                :task-id="detailTask.id"
                :editable="isAdmin && detailChildren.length === 0"
                :pending="Boolean(pendingTaskAction(detailTask.id)?.startsWith('status:'))"
                :blocked="detailTask.blocked"
                @update-status="updateOwnTaskStatus(detailTask, $event)"
              />
              <span v-if="detailTask.deadline">截止 {{ formatDate(detailTask.deadline) }}</span>
              <span>{{ detailTask.owner ? "总负责人 " + detailTask.owner.name : "总负责人待认领" }}</span>
            </div>
          </section>

          <section v-if="detailChildren.length" class="execution-section progress-summary">
            <div class="progress-summary-heading">
              <strong>{{ detailProgress.label }}</strong>
              <span>{{ detailProgress.detail || "所有分工已完成" }}</span>
            </div>
            <div class="progress-track" role="progressbar" :aria-valuenow="detailProgress.done" :aria-valuemax="detailProgress.total" aria-label="事项完成分工数">
              <span :style="{ width: `${Math.round(detailProgress.done / detailProgress.total * 100)}%` }" />
            </div>
            <small v-if="detailProgress.blocked">{{ detailProgress.blocked }} 项等待前置任务</small>
          </section>

          <section class="execution-section">
            <div class="section-heading review-section-heading">
              <div class="review-section-title"><h2>当前信息</h2><span>{{ detailRoot.item_facts.length }} 条</span></div>
            </div>
            <div v-if="detailRoot.item_facts.length" class="fact-list">
              <article v-for="fact in visibleDetailFacts" :key="fact.id" class="fact-row fact-row-scoped">
                <div class="fact-row-content">
                  <p>{{ fact.content }}</p>
                  <small>{{ factScopeDescription(fact) }}</small>
                </div>
                <div v-if="canManageFactScope && editingFactScopeId === fact.id" class="fact-scope-editor">
                  <label>
                    同步范围
                    <select v-model="editingFactScope">
                      <option value="global">整个事项都需要知道</option>
                      <option value="related">只与部分分工相关</option>
                    </select>
                  </label>
                  <fieldset v-if="editingFactScope === 'related'" class="fact-task-picker">
                    <legend>相关分工</legend>
                    <label v-for="task in detailChildren" :key="task.id" class="check-row">
                      <input v-model="editingFactTaskIds" type="checkbox" :value="task.id" />
                      {{ task.title }}
                    </label>
                  </fieldset>
                  <div class="fact-scope-actions">
                    <button type="button" @click="cancelFactScopeEdit">取消</button>
                    <button class="primary small-action" type="button" :disabled="savingFactScopeId !== null || (editingFactScope === 'related' && !editingFactTaskIds.length)" @click="saveFactScope(fact.id)">{{ savingFactScopeId === fact.id ? '保存中…' : '保存范围' }}</button>
                  </div>
                </div>
                <div v-else-if="canManageFactScope" class="fact-row-actions">
                  <button type="button" @click="beginFactScopeEdit(fact)">调整范围</button>
                  <button type="button" @click="removeCurrentFact(fact.id)">移除</button>
                </div>
                <span v-else class="fact-scope-label">{{ fact.scope === 'global' ? '整个事项' : '与你的工作相关' }}</span>
              </article>
            </div>
            <p v-else class="muted">暂无当前信息。</p>
            <button
              v-if="detailRoot.item_facts.length > 3"
              class="text-action"
              type="button"
              @click="detailFactsExpanded = !detailFactsExpanded"
            >{{ detailFactsExpanded ? "收起" : `展开全部 ${detailRoot.item_facts.length} 条` }}</button>
          </section>

          <section class="execution-section">
            <div class="section-heading breakdown-heading">
              <h2>分工 <span class="task-count">· {{ detailChildren.length }}</span></h2>
              <button v-if="isAdmin" type="button" @click="startChildTask(detailRoot)">＋ 添加分工</button>
            </div>
            <div v-if="detailChildren.length" class="detail-task-list child-task-list">
              <article v-for="task in visibleDetailChildren" :key="task.id" class="child-task-row detail-child-task-row">
                <div class="child-task-heading">
                  <TaskStatusIndicator :status="task.status" :task-id="task.id" :editable="isAdmin" :pending="Boolean(pendingTaskAction(task.id)?.startsWith('status:'))" @update-status="updateOwnTaskStatus(task, $event)" />
                  <small class="child-task-owner">{{ task.owner?.name ?? "待认领" }}</small>
                </div>
                <button class="task-title-link child-task-title" type="button" @click="openTaskDetail(task)"><strong>{{ task.title }}</strong></button>
                <p v-if="task.deliverable" class="child-task-deliverable">{{ task.deliverable }}</p>
                <div v-if="task.deadline || task.blocked || task.collaborators.length || taskMenuActions(task).length || (!task.owner && task.owner_claimable && task.status !== 'done')" class="child-task-footer">
                  <div v-if="task.deadline || task.blocked || task.collaborators.length" class="child-task-metadata">
                    <span v-if="task.deadline" class="child-task-metadata-item">
                      <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></svg>
                      {{ formatDate(task.deadline) }}
                    </span>
                    <span v-if="task.blocked" class="child-task-metadata-item">
                      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.3 9.7 4.9 11a2.4 2.4 0 0 1-3.4-3.4l2-2a2.4 2.4 0 0 1 3.4 0" /><path d="m9.7 6.3 1.4-1.4a2.4 2.4 0 0 1 3.4 3.4l-2 2a2.4 2.4 0 0 1-3.4 0" /><path d="m5.8 10.2 4.4-4.4" /></svg>
                      等待 {{ task.blocked_by.length || 1 }} 项前置
                    </span>
                    <span v-if="task.collaborators.length" class="child-task-metadata-item">
                      <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="6" cy="5" r="2.3" /><path d="M1.8 13v-.8A3.2 3.2 0 0 1 5 9h2a3.2 3.2 0 0 1 3.2 3.2v.8M10.4 3.1a2.2 2.2 0 0 1 0 4.2M12 9.2a2.8 2.8 0 0 1 2.2 2.7v.7" /></svg>
                      {{ task.collaborators.length }} 人协作
                    </span>
                  </div>
                  <div class="child-task-actions">
                    <button
                      v-if="!task.owner && task.owner_claimable && task.status !== 'done'"
                      class="primary small-action"
                      type="button"
                      :disabled="Boolean(pendingTaskAction(task.id))"
                      @click="claimTask(task)"
                    >{{ pendingTaskAction(task.id) === 'claim' ? '认领中…' : '认领任务' }}</button>
                    <TaskActionMenu :task-id="task.id" :actions="taskMenuActions(task)" :disabled="Boolean(pendingTaskAction(task.id))" @select="handleTaskMenuAction(task, $event)" />
                  </div>
                </div>
              </article>
            </div>
            <div v-else class="empty compact-empty"><p>还没有执行分工。</p></div>
            <button
              v-if="detailChildren.length > 3"
              class="text-action"
              type="button"
              @click="detailChildrenExpanded = !detailChildrenExpanded"
            >{{ detailChildrenExpanded ? "收起" : `展开全部 ${detailChildren.length} 项` }}</button>
          </section>

          <section class="execution-section">
            <div class="section-heading"><h2>最近进展</h2></div>
            <div v-if="itemActivities.length" class="activity-list">
              <article v-for="activity in visibleDetailActivities" :key="activity.id" class="activity-row">
                <div class="activity-byline">
                  <time>{{ formatDate(activity.created_at) }}</time>
                  <small>{{ activity.author.name }}</small>
                <span v-if="activity.task_id && activity.task_id !== detailRoot.id" class="activity-source">{{ sourceTaskTitle(activity, tasks) }}</span>
                </div>
                <p>{{ activity.content }}</p>
              </article>
            </div>
            <button
              v-if="detailTaskActivities.length > 3 || detailActivitiesHasMore"
              type="button"
              class="text-action activity-more"
              @click="detailActivitiesExpanded = !detailActivitiesExpanded"
            >{{ detailActivitiesExpanded ? "收起" : "查看全部进展" }}</button>
            <button v-if="detailActivitiesExpanded && detailActivitiesHasMore" type="button" class="text-action activity-more" :disabled="loadingEarlierActivities" @click="loadEarlierDetailActivities">
              {{ loadingEarlierActivities ? '正在加载…' : '查看更早进展' }}
            </button>
            <form v-if="canWriteDetailItem" class="activity-entry" @submit.prevent="recordItemActivity">
              <textarea v-model="itemActivityDraft" maxlength="2000" rows="3" placeholder="记录新动态" />
              <div class="activity-entry-actions">
                <button class="primary" type="submit" :disabled="!itemActivityDraft.trim()">发布更新</button>
              </div>
            </form>
          </section>

          <section v-if="itemReviewLoading || itemReviewSuggestions.length" class="execution-section ai-review-section">
            <div class="ai-review-panel" aria-live="polite">
              <p v-if="itemReviewLoading" class="muted">正在检查当前方案…</p>
              <template v-else>
                <div class="ai-review-heading">
                  <div><span class="eyebrow">AI 检查结果</span><p>{{ itemReviewSummary }}</p></div>
                  <span class="ai-review-count">{{ itemReviewSuggestions.length }} 条建议</span>
                </div>
                <article v-for="entry in itemReviewSuggestions" :key="entry.key" class="ai-review-card">
                  <div class="ai-review-card-heading">
                    <span class="eyebrow">{{ entry.suggestion.kind === "add_task" ? "新增任务" : "调整现有任务" }}</span>
                    <h3>{{ entry.suggestion.kind === "add_task" ? entry.suggestion.proposed_task.title : detailChildren.find((task) => task.id === entry.suggestion.target_task_id)?.title ?? entry.suggestion.proposed_task.title }}</h3>
                  </div>
                  <p class="ai-review-reason"><strong>原因</strong>{{ entry.suggestion.reason }}</p>
                  <div v-if="entry.suggestion.kind === 'update_task'" class="ai-review-diffs">
                    <div v-for="change in changesForReviewSuggestion(entry.suggestion)" :key="change.field" class="ai-review-diff">
                      <strong>{{ change.label }}</strong><div class="ai-review-values"><p class="ai-review-before">{{ change.before }}</p><span aria-hidden="true">→</span><p>{{ change.after }}</p></div>
                    </div>
                  </div>
                  <div v-else class="ai-review-proposal">
                    <div v-if="entry.suggestion.proposed_task.deliverable"><strong>做到什么算完成</strong><p>{{ entry.suggestion.proposed_task.deliverable }}</p></div>
                    <div v-for="section in reviewProposalSections" :key="section.field"><template v-if="entry.suggestion.proposed_task[section.field].length"><strong>{{ section.label }}</strong><ul><li v-for="value in entry.suggestion.proposed_task[section.field]" :key="value">{{ value }}</li></ul></template></div>
                  </div>
                  <div class="ai-review-actions">
                    <button type="button" @click="dismissItemReviewSuggestion(entry.key)">忽略</button>
                    <button v-if="isAdmin" class="primary small-action" type="button" :disabled="Boolean(itemReviewApplyingKey)" @click="applyItemReviewSuggestion(entry)">{{ itemReviewApplyingKey === entry.key ? "正在应用…" : "应用" }}</button>
                  </div>
                </article>
              </template>
            </div>
          </section>
        </template>

        <template v-else>
          <section class="execution-section">
            <div class="execution-meta">
              <TaskStatusIndicator
                :status="detailTask.status"
                :task-id="detailTask.id"
                :editable="isAdmin"
                :pending="Boolean(pendingTaskAction(detailTask.id)?.startsWith('status:'))"
                :blocked="detailTask.blocked"
                @update-status="updateOwnTaskStatus(detailTask, $event)"
              />
              <span>{{ detailTask.owner ? detailTask.owner.name + " 负责" : "待认领" }}</span>
              <span v-if="detailTask.collaborators.length">协作 {{ detailTask.collaborators.map((member) => member.name).join("、") }}</span>
              <span v-if="detailTask.deadline">截止 {{ formatDate(detailTask.deadline) }}</span>
            </div>
          </section>

          <section v-if="detailTask.parent_id !== null" class="execution-section shared-scene">
            <div class="section-heading shared-scene-heading">
              <h2>与你当前工作相关的信息</h2>
              <button type="button" class="text-action" @click="openTaskDetail(detailRoot)">查看全部事项信息 →</button>
            </div>
            <div v-if="detailProgress.total" class="shared-progress-line">
              <strong>{{ detailProgress.label }}</strong>
              <span>{{ detailProgress.detail || "所有分工已完成" }}</span>
              <span v-if="detailProgress.blocked">{{ detailProgress.blocked }} 项等待前置任务</span>
            </div>
            <ul v-if="recentItemFacts.length" class="shared-facts-list">
              <li v-for="fact in recentItemFacts" :key="fact.id">
                <span>{{ fact.content }}</span>
                <small>{{ fact.scope === 'global' ? '整个事项' : '相关分工' }}</small>
              </li>
            </ul>
            <p v-else class="muted">暂时还没有新的确认信息。</p>
          </section>

          <section v-if="detailTask.blocked" class="execution-section dependency-state">
            <div class="section-heading"><h2>等待前置任务</h2></div>
            <ul>
              <li v-for="dependency in detailTask.blocked_by" :key="dependency.id">
                <span>{{ dependency.title }}</span>
                <small>{{ dependency.owner ? `${dependency.owner.name} 负责` : "待认领" }} · {{ statusLabels[dependency.status] }}</small>
              </li>
            </ul>
          </section>
          <p v-else-if="detailTask.depends_on_tasks.length" class="dependency-cleared">前置任务已完成 ✓</p>

          <section v-if="detailTask.deliverable" class="execution-section">
            <div class="section-heading"><h2>做到什么算完成</h2></div>
            <p class="execution-description">{{ detailTask.deliverable }}</p>
          </section>

          <section v-for="section in taskDetailSections(detailTask)" :key="section.title" class="execution-section">
            <div class="section-heading"><h2>{{ section.title }}</h2></div>
            <ul class="execution-list"><li v-for="item in section.items" :key="item">{{ item }}</li></ul>
          </section>

          <section v-if="canPublishTaskProgress" class="execution-section progress-entry-section">
            <div class="section-heading"><h2>更新进展</h2></div>
            <form class="progress-entry" @submit.prevent="publishTaskProgress">
              <label for="task-progress-draft">刚刚发生了什么？</label>
              <textarea id="task-progress-draft" v-model="taskProgressDraft" maxlength="2000" rows="3" placeholder="例如：已经联系对方老师，目前等回复。" />
              <button class="primary" type="submit" :disabled="!taskProgressDraft.trim() || taskProgressSaving">
                {{ taskProgressSaving ? "正在发布…" : "发布更新" }}
              </button>
            </form>
          </section>

          <section v-if="detailTask.parent_id !== null && (factExtractionLoading || factSuggestions.length)" class="execution-section fact-suggestions-panel" aria-live="polite">
            <div class="section-heading"><h2>发现可能需要同步的信息</h2></div>
            <p v-if="factExtractionLoading" class="muted">正在整理这次更新中的已确认信息…</p>
            <template v-else>
              <p>AI 只提供建议。请确认内容与同步范围后再发布。</p>
              <article v-for="(suggestion, index) in factSuggestions" :key="`${index}-${suggestion.text}`" class="fact-suggestion-card">
                <label class="fact-suggestion-check">
                  <input v-model="selectedFactSuggestions" type="checkbox" :value="suggestion.text" />
                  <span>{{ suggestion.text }}<small>{{ suggestion.reason }}</small></span>
                </label>
                <label class="fact-scope-select">
                  同步范围
                  <select v-model="suggestion.scope" @change="ensureFactSuggestionTasks(index)">
                    <option value="global">整个事项都需要知道</option>
                    <option value="related">只与部分分工相关</option>
                  </select>
                </label>
                <fieldset v-if="suggestion.scope === 'related'" class="fact-task-picker">
                  <legend>选择相关分工</legend>
                  <label v-for="task in detailChildren" :key="task.id" class="check-row">
                    <input v-model="suggestion.related_task_ids" type="checkbox" :value="task.id" />
                    {{ task.title }}
                  </label>
                </fieldset>
                <div v-if="suggestion.supersedes_fact_id && detailTask.item_facts.some((fact) => fact.id === suggestion.supersedes_fact_id)" class="fact-replacement">
                  <span>这条信息可能更新现有内容</span>
                  <p>{{ detailTask.item_facts.find((fact) => fact.id === suggestion.supersedes_fact_id)?.content }}</p>
                  <span aria-hidden="true">↓</span>
                  <p>{{ suggestion.text }}</p>
                  <label v-if="canManageFactScope" class="check-row">
                    <input v-model="confirmedFactSupersessions" type="checkbox" :value="suggestion.text" />
                    确认后用新信息替代旧信息
                  </label>
                  <small v-if="!canManageFactScope">替代旧信息需要管理者或事项负责人确认。</small>
                </div>
              </article>
              <div class="fact-suggestion-actions">
                <button type="button" @click="dismissFactSuggestions">不需要同步</button>
                <button
                  class="primary"
                  type="button"
                  :disabled="!selectedFactSuggestions.length || factSuggestions.some((suggestion) => selectedFactSuggestions.includes(suggestion.text) && suggestion.scope === 'related' && !suggestion.related_task_ids.length)"
                  @click="addSuggestedFactsToItem"
                >确认同步</button>
              </div>
            </template>
          </section>

          <section v-if="detailTaskActivities.length" class="execution-section">
            <div class="section-heading"><h2>相关进展</h2></div>
            <div class="activity-list">
              <article v-for="activity in visibleDetailActivities" :key="activity.id" class="activity-row">
                <div class="activity-byline">
                  <time>{{ formatDate(activity.created_at) }}</time>
                  <small>{{ activity.author.name }}</small>
                <span v-if="activity.task_id && activity.task_id !== detailRoot.id" class="activity-source">{{ sourceTaskTitle(activity, tasks) }}</span>
                </div>
                <p>{{ activity.content }}</p>
              </article>
            </div>
            <button
              v-if="detailTaskActivities.length > 3 || detailActivitiesHasMore"
              type="button"
              class="text-action activity-more"
              @click="detailActivitiesExpanded = !detailActivitiesExpanded"
            >{{ detailActivitiesExpanded ? "收起" : "查看全部进展" }}</button>
            <button v-if="detailActivitiesExpanded && detailActivitiesHasMore" type="button" class="text-action activity-more" :disabled="loadingEarlierActivities" @click="loadEarlierDetailActivities">
              {{ loadingEarlierActivities ? '正在加载…' : '查看更早进展' }}
            </button>
          </section>

          <section class="execution-section">
            <div class="section-heading"><h2>最终结果</h2></div>
            <template v-if="canEditDetailResult">
              <textarea v-model="taskResultDraft" maxlength="5000" rows="5" placeholder="记录实际完成后得到的结果" />
              <div class="result-actions">
                <button class="primary" type="button" @click="saveTaskResult">保存结果</button>
              </div>
            </template>
            <p v-else-if="detailTask.result" class="execution-description">{{ detailTask.result }}</p>
            <p v-else class="muted">暂未记录执行结果。</p>
          </section>

          <section v-if="canCompleteDetailTask" class="execution-section complete-task-section">
            <div class="section-heading"><h2>完成任务</h2></div>
            <form class="progress-entry" @submit.prevent="completeDetailTask">
              <label for="task-completion-result">最终结果</label>
              <textarea id="task-completion-result" v-model="taskCompletionDraft" maxlength="5000" rows="3" required placeholder="写下最终完成结果" />
              <label v-if="detailTask.parent_id !== null" class="check-row">
                <input v-model="taskCompletionSync" type="checkbox" />
                将最终确认信息同步给整个事项（最多 500 字）
              </label>
              <button class="primary" type="submit" :disabled="!taskCompletionDraft.trim() || taskCompletionSaving">
                {{ taskCompletionSaving ? "正在完成…" : "完成任务" }}
              </button>
            </form>
          </section>

          <section class="execution-section task-detail-actions">
            <div class="task-actions">
              <button
                v-if="!detailTask.owner && detailTask.owner_claimable && detailTask.status !== 'done'"
                class="primary small-action"
                type="button"
                :disabled="Boolean(pendingTaskAction(detailTask.id))"
                @click="claimTask(detailTask)"
              >{{ pendingTaskAction(detailTask.id) === 'claim' ? '认领中…' : '认领任务' }}</button>
              <button
                v-if="detailTask.owner?.id === user?.id && detailTask.owner_claimable && detailTask.status !== 'done'"
                type="button"
                :disabled="Boolean(pendingTaskAction(detailTask.id))"
                @click="unclaimTask(detailTask)"
              >{{ pendingTaskAction(detailTask.id) === 'unclaim' ? '取消中…' : '取消认领' }}</button>
              <button
                v-if="detailTask.collaboration_open && detailTask.owner?.id !== user?.id && !isCollaborator(detailTask) && detailTask.status !== 'done'"
                type="button"
                :disabled="Boolean(pendingTaskAction(detailTask.id))"
                @click="joinTask(detailTask)"
              >{{ pendingTaskAction(detailTask.id) === 'join' ? '加入中…' : '加入协作' }}</button>
              <button
                v-if="detailTask.collaboration_open && isCollaborator(detailTask) && detailTask.status !== 'done'"
                type="button"
                :disabled="Boolean(pendingTaskAction(detailTask.id))"
                @click="leaveTask(detailTask)"
              >{{ pendingTaskAction(detailTask.id) === 'leave' ? '退出中…' : '退出协作' }}</button>
            </div>
          </section>
        </template>
      </template>

      <template v-else-if="path === '/tasks'">
        <div class="page-title">
          <h1>任务</h1>
          <button v-if="isAdmin" type="button" @click="startIndependentTask">＋ 快速创建独立任务</button>
        </div>

        <div class="view-tabs" role="tablist" aria-label="任务视图">
          <button
            v-for="view in (['mine', 'claimable', 'all'] as TaskView[])"
            :key="view"
            type="button"
            :class="{ active: taskView === view }"
            @click="navigateTasks(view)"
          >
            {{ viewLabels[view] }}
          </button>
        </div>



        <section class="task-board">
          <div v-if="taskListLoading" class="local-route-loading" role="status" aria-live="polite">
            <span class="loading-dot" aria-hidden="true"></span>
            正在加载任务列表…
          </div>
          <div v-else-if="taskListLoadError" class="local-route-loading" role="alert">
            暂时无法加载任务列表。<button class="text-action" type="button" @click="loadRoute">重试</button>
          </div>
          <div v-else-if="rootTasks.length" class="operation-list">
            <article v-for="task in rootTasks" :key="task.id" class="operation-card" :class="{ 'claimable-root-card': taskView === 'claimable' }">
              <template v-if="isIndependentTask(task)">
                <div class="operation-card-top">
                  <div class="operation-main">
                    <div class="root-status-line"><span class="state">独立任务</span><TaskStatusIndicator :status="task.status" :task-id="task.id" :editable="isAdmin && taskView === 'all'" :pending="Boolean(pendingTaskAction(task.id)?.startsWith('status:'))" @update-status="updateOwnTaskStatus(task, $event)" /></div>
                    <button class="task-title-link" type="button" @click="openTaskDetail(task)"><h3>{{ task.title }}</h3></button>
                    <small>{{ task.owner ? task.owner.name + " 负责" : "待认领" }}</small>
                    <small v-if="task.deadline">截止 {{ formatDate(task.deadline) }}</small>
                    <small v-if="task.collaborators.length">协作：{{ task.collaborators.map((member) => member.name).join("、") }}</small>
                    <p v-if="task.deliverable" class="child-task-deliverable">{{ task.deliverable }}</p>
                  </div>
                  <div class="task-actions root-task-actions">
                    <button
                      v-if="!task.owner && task.owner_claimable && task.status !== 'done'"
                      class="primary small-action"
                      type="button"
                      :disabled="Boolean(pendingTaskAction(task.id))"
                      @click="claimTask(task)"
                    >{{ pendingTaskAction(task.id) === 'claim' ? '认领中…' : '认领任务' }}</button>
                    <TaskActionMenu
                      :task-id="`root-${task.id}`"
                      :actions="rootTaskMenuActions(task)"
                      :disabled="Boolean(pendingTaskAction(task.id))"
                      @select="handleRootTaskMenuAction(task, $event)"
                    />
                  </div>
                </div>
              </template>
              <template v-else-if="taskView === 'claimable'">
                <div class="claimable-root-summary">
                  <div class="claimable-root-heading">
                    <div class="root-status-line"><span class="state">事项</span><TaskStatusIndicator :status="task.status" :task-id="task.id" :editable="false" /></div>
                    <button class="task-title-link" type="button" @click="openTaskDetail(task)"><h3>{{ task.title }}</h3></button>
                    <small>{{ task.owner ? "总负责人 " + task.owner.name : "总负责人待认领" }}</small>
                    <strong v-if="claimableChildren(task.id).length" class="claimable-root-count">{{ claimableChildren(task.id).length }} 项待认领</strong>
                  </div>
                  <button
                    v-if="claimableTask(task)"
                    class="primary small-action claimable-root-claim"
                    type="button"
                    :disabled="Boolean(pendingTaskAction(task.id))"
                    @click="claimTask(task)"
                  >{{ pendingTaskAction(task.id) === 'claim' ? '认领中…' : '认领事项负责人' }}</button>
                </div>
                <div v-if="claimableChildren(task.id).length" class="root-breakdown-control">
                  <button
                    class="breakdown-toggle"
                    type="button"
                    :aria-expanded="isRootExpanded(task.id)"
                    :aria-controls="`work-breakdown-${task.id}`"
                    @click="toggleRootBreakdown(task.id)"
                  >{{ isRootExpanded(task.id) ? "收起待认领分工 ▴" : "展开待认领分工 ▾" }}</button>
                </div>
              </template>
              <div v-else class="operation-card-top">
                <div class="operation-main">
                  <div class="root-status-line"><span class="state">事项</span><TaskStatusIndicator :status="task.status" :task-id="task.id" :editable="isAdmin && taskView === 'all' && childTasks(task.id).length === 0" :pending="Boolean(pendingTaskAction(task.id)?.startsWith('status:'))" @update-status="updateOwnTaskStatus(task, $event)" /></div>
                  <button class="task-title-link" type="button" @click="openTaskDetail(task)"><h3>{{ task.title }}</h3></button>
                  <small>{{ task.owner ? "总负责人 " + task.owner.name : "总负责人待认领" }}</small>
                  <small v-if="task.deadline">截止 {{ formatDate(task.deadline) }}</small>
                  <small v-if="task.collaborators.length">
                    协作：{{ task.collaborators.map((member) => member.name).join("、") }}
                  </small>
                  <div v-if="taskView === 'all' && childTasks(task.id).length" class="root-progress-summary">
                    <span>{{ executionSummary(childTasks(task.id)).label }}<template v-if="executionSummary(childTasks(task.id)).detail"> · {{ executionSummary(childTasks(task.id)).detail }}</template></span>
                    <span v-if="executionSummary(childTasks(task.id)).blocked">{{ executionSummary(childTasks(task.id)).blocked }} 项等待前置任务</span>
                  </div>
                </div>

                <div class="task-actions root-task-actions">
                  <button
                    v-if="!task.owner && task.owner_claimable && task.status !== 'done'"
                    class="primary small-action"
                    type="button"
                    :disabled="Boolean(pendingTaskAction(task.id))"
                    @click="claimTask(task)"
                  >{{ pendingTaskAction(task.id) === 'claim' ? '认领中…' : '认领事项负责人' }}</button>
                  <TaskActionMenu
                    :task-id="`root-${task.id}`"
                    :actions="rootTaskMenuActions(task)"
                    :disabled="Boolean(pendingTaskAction(task.id))"
                    @select="handleRootTaskMenuAction(task, $event)"
                  />
                </div>
              </div>

              <template v-if="task.kind === 'item'">
              <div v-if="taskView !== 'claimable'" class="root-breakdown-control">
                <button
                  v-if="taskViewChildren(task.id).length"
                  class="breakdown-toggle"
                  type="button"
                  :aria-expanded="isRootExpanded(task.id)"
                  :aria-controls="`work-breakdown-${task.id}`"
                  @click="toggleRootBreakdown(task.id)"
                >{{ isRootExpanded(task.id) ? "收起分工 ▴" : "展开分工 ▾" }}</button>
                <span v-else-if="taskView === 'all' && !childTasks(task.id).length" class="no-child-tasks">暂无分工</span>
                <span v-else-if="!taskViewChildren(task.id).length" class="no-child-tasks">暂无与你相关的分工</span>
                <button v-if="isAdmin && taskView === 'all' && !childTasks(task.id).length" type="button" class="add-first-child" @click="startChildTask(task)">＋ 添加分工</button>
              </div>

              <div v-if="(taskView === 'claimable' ? claimableChildren(task.id).length : taskViewChildren(task.id).length) && isRootExpanded(task.id)" :id="`work-breakdown-${task.id}`" class="work-breakdown">
                <div class="breakdown-heading">
                  <strong>{{ taskView === 'claimable' ? '待认领分工' : '分工' }} <span class="task-count">· {{ (taskView === 'claimable' ? claimableChildren(task.id) : taskViewChildren(task.id)).length }}</span></strong>
                  <button v-if="isAdmin && taskView === 'all'" type="button" @click="startChildTask(task)">＋ 添加分工</button>
                </div>

                <div class="child-task-list">
                  <article v-for="child in (taskView === 'claimable' ? claimableChildren(task.id) : taskViewChildren(task.id))" :key="child.id" class="child-task-row">
                    <div class="child-task-heading">
                      <TaskStatusIndicator :status="child.status" :task-id="child.id" :editable="isAdmin" :pending="Boolean(pendingTaskAction(child.id)?.startsWith('status:'))" @update-status="updateOwnTaskStatus(child, $event)" />
                      <small class="child-task-owner">{{ child.owner?.name ?? "待认领" }}</small>
                    </div>
                    <button class="task-title-link child-task-title" type="button" @click="openTaskDetail(child)"><strong>{{ child.title }}</strong></button>
                    <p v-if="child.deliverable" class="child-task-deliverable">{{ child.deliverable }}</p>
                    <div v-if="child.deadline || child.blocked || child.collaborators.length || taskMenuActions(child).length || (!child.owner && child.owner_claimable && child.status !== 'done')" class="child-task-footer">
                      <div v-if="child.deadline || child.blocked || child.collaborators.length" class="child-task-metadata">
                        <span v-if="child.deadline" class="child-task-metadata-item">
                          <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></svg>
                          {{ formatDate(child.deadline) }}
                        </span>
                        <span v-if="child.blocked" class="child-task-metadata-item">
                          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6.3 9.7 4.9 11a2.4 2.4 0 0 1-3.4-3.4l2-2a2.4 2.4 0 0 1 3.4 0" /><path d="m9.7 6.3 1.4-1.4a2.4 2.4 0 0 1 3.4 3.4l-2 2a2.4 2.4 0 0 1-3.4 0" /><path d="m5.8 10.2 4.4-4.4" /></svg>
                          等待 {{ child.blocked_by.length || 1 }} 项前置
                        </span>
                        <span v-if="child.collaborators.length" class="child-task-metadata-item">
                          <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="6" cy="5" r="2.3" /><path d="M1.8 13v-.8A3.2 3.2 0 0 1 5 9h2a3.2 3.2 0 0 1 3.2 3.2v.8M10.4 3.1a2.2 2.2 0 0 1 0 4.2M12 9.2a2.8 2.8 0 0 1 2.2 2.7v.7" /></svg>
                          {{ child.collaborators.length }} 人协作
                        </span>
                      </div>
                      <div class="child-task-actions">
                        <button
                          v-if="!child.owner && child.owner_claimable && child.status !== 'done'"
                          class="primary small-action"
                          type="button"
                          :disabled="Boolean(pendingTaskAction(child.id))"
                          @click="claimTask(child)"
                        >{{ pendingTaskAction(child.id) === 'claim' ? '认领中…' : '认领任务' }}</button>
                        <TaskActionMenu :task-id="child.id" :actions="taskMenuActions(child)" :disabled="Boolean(pendingTaskAction(child.id))" @select="handleTaskMenuAction(child, $event)" />
                      </div>
                    </div>
                  </article>
                </div>
              </div>
              </template>
            </article>
          </div>

          <div v-else class="empty empty-action empty-state">
            <span class="empty-code">
              {{ taskView === 'mine' ? 'TASKS / MINE' : taskView === 'claimable' ? 'TASKS / CLAIM' : 'TASKS / ALL' }}
            </span>
            <h3 v-if="taskView === 'mine'">暂时没有你的执行项</h3>
            <h3 v-else-if="taskView === 'claimable'">当前没有待认领项</h3>
            <h3 v-else>运营列表还是空的</h3>
            <p v-if="taskView === 'mine'">目前没有你负责或参与的任务。</p>
            <p v-else-if="taskView === 'claimable'">新的可认领任务出现后，会显示在这里。</p>
            <p v-else>还没有正式发布的事项或独立任务。</p>
          </div>
        </section>
      </template>

      <template v-else-if="path === '/me'">
        <div class="page-title"><h1>我的</h1></div>

        <section class="profile">
          <strong>{{ user?.name }}</strong>
          <span>{{ user?.email }}</span>
          <small>{{ user ? roleLabels[user.role] : "" }}</small>
        </section>

        <section class="profile-section">
          <h2>个人资料</h2>
          <div class="profile-field-row">
            <span class="profile-field-label">学号</span>
            <span class="profile-field-value">{{ user?.student_id || "学号未填写" }}</span>
            <button class="profile-edit-action" type="button" @click="navigate('/me/edit')">编辑 ></button>
          </div>
          <div class="profile-field-row">
            <span class="profile-field-label">所属组别</span>
            <span class="profile-field-value">{{ user?.team_group ? groupLabels[user.team_group] : "未填写" }}</span>
          </div>
          <div class="profile-field-row">
            <span class="profile-field-label">学院</span>
            <span class="profile-field-value">{{ collegeOptions.find((college) => college.code === user?.college)?.name || "未填写" }}</span>
          </div>
          <div class="profile-field-row">
            <span class="profile-field-label">队内身份</span>
            <span class="profile-field-value">{{ user?.team_membership ? membershipLabels[user.team_membership] : "未填写" }}</span>
          </div>
        </section>

        <section class="profile-section profile-account-section">
          <h2>账号</h2>
          <button class="secondary profile-logout" type="button" @click="logout">退出登录</button>
        </section>
      </template>

      <template v-else-if="path === '/me/edit'">
        <button class="profile-back" type="button" @click="navigate('/me')">← 返回我的</button>
        <header class="profile-edit-heading">
          <h1>编辑资料</h1>
        </header>

        <section class="profile-section">
          <h2>学校信息</h2>
          <form class="profile-student-edit-form" @submit.prevent="saveMyProfile">
            <label>
              <span>学号</span>
              <input
                v-model="studentIdDraft"
                maxlength="8"
                inputmode="numeric"
                autocomplete="off"
                placeholder="未填写学号"
                :aria-invalid="Boolean(profileFieldErrors.student_id)"
                @input="clearProfileFieldError('student_id')"
              />
              <small v-if="profileFieldErrors.student_id" class="field-error">{{ profileFieldErrors.student_id }}</small>
            </label>
            <label>
              <span>所属组别</span>
              <select v-model="teamGroupDraft">
                <option value="">未填写</option>
                <option v-for="(label, code) in groupLabels" :key="code" :value="code">{{ label }}</option>
              </select>
            </label>
            <label>
              <span>所属学院</span>
              <CollegeSelect
                v-model="collegeDraft"
                :options="collegeOptions"
                clearable
                placeholder="可留空，搜索学院"
                :invalid="Boolean(profileFieldErrors.college)"
                @change="clearProfileFieldError('college')"
              />
              <small v-if="profileFieldErrors.college" class="field-error">{{ profileFieldErrors.college }}</small>
            </label>
            <button
              class="primary profile-save"
              type="submit"
              :disabled="profileSaving || !myProfileChanged"
            >
              {{ profileSaving ? "保存中…" : "保存修改" }}
            </button>
          </form>
        </section>
      </template>

      <template v-else-if="path === '/leave'">
        <SchoolLeavePage
          v-if="user"
          :current-user="user"
          @navigate="navigate"
          @todo-count="schoolLeaveTodoCount = $event"
        />
      </template>

      <template v-else-if="teamMemberDetailId !== null && teamMemberDetail">
        <MemberDetailPage
          :member="teamMemberDetail"
          :current-user-id="user?.id ?? null"
          :latest-invite="latestInvite"
          :role-labels="roleLabels"
          :group-labels="groupLabels"
          :college-options="collegeOptions"
          :membership-labels="membershipLabels"
          :field-errors="memberProfileFieldErrors[teamMemberDetail.id] ?? {}"
          :format-date="formatDate"
          :profile-saving="memberProfileSavingId === teamMemberDetail.id"
          @regenerate-invite="regenerateInvite"
          @disable-member="disableMember"
          @enable-member="enableMember"
          @update-profile="updateMemberProfile"
          @clear-profile-error="clearMemberProfileFieldError(teamMemberDetail.id, $event)"
          @copy-invite="copyInvite"
          @navigate="navigate"
        />
      </template>

      <template v-else-if="path === '/team'">
        <TeamPage
          :members="members"
          :registration-window="registrationWindow"
          :registration-path="registrationPath"
          :opening-registration="openingRegistration"
          :closing-registration="closingRegistration"
          :role-labels="roleLabels"
          :group-labels="groupLabels"
          :format-date="formatDate"
          @open-registration="openTeamRegistration"
          @close-registration="closeTeamRegistration"
          @copy-registration="copyTeamRegistration"
          @navigate="navigate"
        />
      </template>

      <template v-else-if="path === '/knowledge'">
        <KnowledgePage
          :documents="knowledgeDocuments"
          :uploading="knowledgeUploading"
          :syncing="knowledgeSyncing"
          :summary="knowledgeSyncSummary"
          :format-date="formatDate"
          :status-label="knowledgeStatusLabel"
          @upload="uploadKnowledgeFile"
          @sync="syncGitHubKnowledge"
          @remove="removeKnowledgeDocument"
          @navigate="navigate"
        />
      </template>
    </div>

    <nav
      class="bottom-nav"
      aria-label="主导航"
      :style="{ gridTemplateColumns: `repeat(${isAdmin ? 5 : 4}, 1fr)` }"
    >
      <button :class="{ active: path === '/' }" type="button" @click="navigate('/')">Base</button>
      <button :class="{ active: path.startsWith('/tasks') }" type="button" @click="navigateTasks('mine')">
        任务
      </button>
      <button :class="{ active: path === '/leave' }" type="button" @click="navigate('/leave')">
        请假<span v-if="isAdmin && schoolLeaveTodoCount" class="nav-count">{{ schoolLeaveTodoCount }}</span>
      </button>
      <button
        v-if="isAdmin"
        :class="{ active: isTeamRoute }"
        type="button"
        @click="navigate('/team')"
      >
        团队
      </button>
      <button :class="{ active: isMeRoute }" type="button" @click="navigate('/me')">我的</button>
    </nav>
  </main>
</template>
