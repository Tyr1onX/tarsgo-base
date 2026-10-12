import type {
  AIPlannerExtractedFile,
  AIReviewAccess,
  CampLeaveAdminEvent,
  CampLeaveAdminEventDetail,
  CampLeaveEventCreatePayload,
  CampLeaveEventMember,
  CampLeavePublicEvent,
  DailyLeavePublicEntry,
  DailyLeavePublicWindow,
  DailyLeaveWindowAdmin,
  DailyLeaveWindowCreatePayload,
  DailyLeaveWindowMember,
  DailyLeaveSelfServicePayload,
  AIItemReviewResult,
  AIItemReviewSuggestion,
  AIItemFactExtractionResult,
  CollegeOption,
  InvitationInfo,
  InviteResult,
  ItemActivity,
  ItemActivityPage,
  ItemFactInput,
  Member,
  MemberProfilePayload,
  MyProfilePayload,
  MemberSummary,
  TaskAssigneeOption,
  TaskKind,
  KnowledgeDocument,
  KnowledgeSyncSummary,
  Role,
  TeamGroup,
  TeamRegistrationInfo,
  TeamRegistrationPayload,
  TeamRegistrationWindow,
  TeamRegistrationWindowOpen,
  SchoolLeaveAdminConfig,
  SchoolLeaveAdminSummary,
  SchoolLeaveGroupResult,
  SchoolLeaveRequest,
  SchoolLeaveRun,
  Task,
  TaskDetailContext,
  TaskProgressResult,
  TaskBatchPayload,
  TaskBatchResult,
  TaskStatus,
  TaskView,
} from "./types"

export class ApiError extends Error {
  status: number
  field: string | null
  constructor(status: number, message: string, field: string | null = null) {
    super(message)
    this.status = status
    this.field = field
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: {
      ...(init?.body && !(typeof FormData !== "undefined" && init.body instanceof FormData)
        ? { "Content-Type": "application/json" }
        : {}),
      ...init?.headers,
    },
  })
  if (!response.ok) {
    let message = "操作失败"
    let field: string | null = null
    try {
      const data = (await response.json()) as { detail?: unknown }
      if (typeof data.detail === "string") message = data.detail
      else if (Array.isArray(data.detail) && data.detail.length) {
        const issue = data.detail[0] as { loc?: unknown[]; msg?: unknown }
        if (typeof issue.msg === "string") message = issue.msg.replace(/^Value error, /, "")
        const location = Array.isArray(issue.loc) ? issue.loc : []
        const candidate = location.at(-1)
        if (typeof candidate === "string") field = candidate
      }
    } catch {}
    throw new ApiError(response.status, message, field)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

async function downloadFile(url: string, fallbackName: string, init?: RequestInit) {
  const response = await fetch(url, init)
  if (!response.ok) {
    let message = "下载失败"
    try {
      const data = (await response.json()) as { detail?: string }
      if (data.detail) message = data.detail
    } catch {}
    throw new ApiError(response.status, message)
  }
  const disposition = response.headers.get("content-disposition") ?? ""
  const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  return {
    blob: await response.blob(),
    filename: encodedName ? decodeURIComponent(encodedName) : fallbackName,
  }
}

export interface TaskPayload {
  kind?: TaskKind
  title: string
  deliverable?: string
  execution_points?: string[]
  cautions?: string[]
  prerequisites?: string[]
  owner_id: number | null
  owner_claimable: boolean
  collaborator_ids: number[]
  collaboration_open: boolean
  parent_id?: number | null
  deadline?: string | null
  status: TaskStatus
  depends_on_task_ids?: number[]
}

export const api = {
  me: () => request<Member>("/api/auth/me"),
  colleges: () => request<CollegeOption[]>("/api/colleges"),
  updateMeProfile: (payload: MyProfilePayload) =>
    request<Member>("/api/auth/me", {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  login: (email: string, password: string) =>
    request<Member>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  invitation: (token: string) => request<InvitationInfo>(`/api/invitations/${encodeURIComponent(token)}`),
  acceptInvitation: (token: string, password: string) =>
    request<void>(`/api/invitations/${encodeURIComponent(token)}/accept`, {
      method: "POST",
      body: JSON.stringify({ password }),
    }),

  members: () => request<Member[]>("/api/members"),
  inviteMember: (name: string, email: string) =>
    request<InviteResult>("/api/members/invite", {
      method: "POST",
      body: JSON.stringify({ name, email }),
    }),
  regenerateInvite: (memberId: number) => request<InviteResult>(`/api/members/${memberId}/invite`, { method: "POST" }),
  disableMember: (memberId: number) => request<Member>(`/api/members/${memberId}/disable`, { method: "POST" }),
  enableMember: (memberId: number) => request<Member>(`/api/members/${memberId}/enable`, { method: "POST" }),
  updateMemberProfile: (memberId: number, payload: MemberProfilePayload) =>
    request<Member>(`/api/members/${memberId}/profile`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),

  currentTeamRegistration: () =>
    request<TeamRegistrationWindow | null>("/api/team-registration/admin/current"),
  openTeamRegistration: () =>
    request<TeamRegistrationWindowOpen>("/api/team-registration/admin/open", { method: "POST" }),
  closeTeamRegistration: () =>
    request<void>("/api/team-registration/admin/close", { method: "POST" }),
  teamRegistrationInfo: (token: string) =>
    request<TeamRegistrationInfo>(`/api/team-registration/${encodeURIComponent(token)}`),
  registerTeamMember: (token: string, payload: TeamRegistrationPayload) =>
    request<Member>(`/api/team-registration/${encodeURIComponent(token)}/register`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  schoolLeaveRequests: () => request<SchoolLeaveRequest[]>("/api/school-leave/requests"),
  createSchoolLeaveRequest: (startAt: string, endAt: string) =>
    request<SchoolLeaveRequest>("/api/school-leave/requests", {
      method: "POST",
      body: JSON.stringify({ start_at: startAt, end_at: endAt }),
    }),
  updateSchoolLeaveRequest: (requestId: number, startAt: string, endAt: string) =>
    request<SchoolLeaveRequest>(`/api/school-leave/requests/${requestId}`, {
      method: "PATCH",
      body: JSON.stringify({ start_at: startAt, end_at: endAt }),
    }),
  withdrawSchoolLeaveRequest: (requestId: number) =>
    request<SchoolLeaveRequest>(`/api/school-leave/requests/${requestId}/withdraw`, { method: "POST" }),
  schoolLeaveAdminConfig: () => request<SchoolLeaveAdminConfig>("/api/school-leave/admin/config"),
  schoolLeaveAdminSummary: () => request<SchoolLeaveAdminSummary>("/api/school-leave/admin/summary"),
  schoolLeaveAdminRequests: () => request<SchoolLeaveRequest[]>("/api/school-leave/admin/requests"),
  schoolLeaveRuns: () => request<SchoolLeaveRun[]>("/api/school-leave/admin/runs"),
  collectSchoolLeave: () => request<SchoolLeaveRun | null>("/api/school-leave/admin/runs/collect", { method: "POST" }),
  updateSchoolLeaveRunReason: (runId: number, reason: string) =>
    request<SchoolLeaveRun>(`/api/school-leave/admin/runs/${runId}/reason`, {
      method: "PATCH",
      body: JSON.stringify({ reason }),
    }),
  cancelSchoolLeaveRun: (runId: number) =>
    request<SchoolLeaveRun>(`/api/school-leave/admin/runs/${runId}/cancel`, { method: "POST" }),
  uploadSchoolLeaveResult: (runId: number, groupIndex: number, file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<SchoolLeaveGroupResult>(
      `/api/school-leave/admin/runs/${runId}/groups/${groupIndex}/result`,
      { method: "POST", body: form },
    )
  },
  schoolLeaveResultUrl: (runId: number, groupIndex: number) =>
    `/api/school-leave/runs/${runId}/groups/${groupIndex}/result`,
  downloadSchoolLeaveRunDocument: async (runId: number) => {
    const response = await fetch(`/api/school-leave/admin/runs/${runId}/document`)
    if (!response.ok) {
      let message = "下载失败"
      try {
        const data = (await response.json()) as { detail?: string }
        if (data.detail) message = data.detail
      } catch {}
      throw new ApiError(response.status, message)
    }
    const disposition = response.headers.get("content-disposition") ?? ""
    const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1] ?? "吉甲大师请假条.docx"
    return { blob: await response.blob(), filename: decodeURIComponent(encodedName) }
  },
  downloadLegacySchoolLeaveRunDocument: (runId: number) =>
    downloadFile(`/api/school-leave/admin/runs/${runId}/history-document`, "历史请假汇总.docx"),
  downloadLegacySchoolLeaveGroupDocument: (runId: number, groupIndex: number) =>
    downloadFile(`/api/school-leave/admin/runs/${runId}/documents/${groupIndex}`, "历史请假材料.docx"),
  deleteSchoolLeaveRun: (runId: number) =>
    request<void>(`/api/school-leave/admin/runs/${runId}`, { method: "DELETE" }),

  dailyLeaveWindows: () => request<DailyLeaveWindowMember[]>("/api/daily-leave/windows"),
  dailyLeaveAdminWindows: () => request<DailyLeaveWindowAdmin[]>("/api/daily-leave/admin/windows"),
  createDailyLeaveWindow: (payload: DailyLeaveWindowCreatePayload) =>
    request<DailyLeaveWindowAdmin>("/api/daily-leave/admin/windows", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  enableDailyLeavePublicLink: (windowId: number) =>
    request<DailyLeaveWindowAdmin>(`/api/daily-leave/admin/windows/${windowId}/public-link`, { method: "POST" }),
  closeDailyLeaveWindow: (windowId: number) =>
    request<DailyLeaveWindowAdmin>(`/api/daily-leave/admin/windows/${windowId}/close`, { method: "POST" }),
  generateDailyLeaveSelfServiceDocument: (payload: DailyLeaveSelfServicePayload, offline = false) =>
    downloadFile(
      `/api/daily-leave/self-service/document${offline ? "?offline=true" : ""}`,
      "请假条.docx",
      { method: "POST", body: JSON.stringify(payload), headers: { "Content-Type": "application/json" } },
    ),
  downloadDailyLeaveDocument: (windowId: number, offline = false) =>
    downloadFile(
      `/api/daily-leave/windows/${windowId}/document${offline ? "?offline=true" : ""}`,
      "请假条.docx",
    ),
  publicDailyLeaveWindow: (token: string) =>
    request<DailyLeavePublicWindow>(`/api/daily-leave/public/${encodeURIComponent(token)}`),
  generatePublicDailyLeaveDocument: (token: string, payload: DailyLeavePublicEntry, offline = false) =>
    downloadFile(
      `/api/daily-leave/public/${encodeURIComponent(token)}/document${offline ? "?offline=true" : ""}`,
      "请假条.docx",
      { method: "POST", body: JSON.stringify(payload), headers: { "Content-Type": "application/json" } },
    ),

  campLeaveEvents: () => request<CampLeaveEventMember[]>("/api/camp-leave/events"),
  createCampLeaveEvent: (payload: CampLeaveEventCreatePayload) =>
    request<CampLeaveAdminEvent>("/api/camp-leave/admin/events", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  campLeaveAdminEvents: () => request<CampLeaveAdminEvent[]>("/api/camp-leave/admin/events"),
  campLeaveAdminEvent: (eventId: number) =>
    request<CampLeaveAdminEventDetail>(`/api/camp-leave/admin/events/${eventId}`),
  joinCampLeaveEvent: (eventId: number) =>
    request<CampLeaveEventMember>(`/api/camp-leave/events/${eventId}/join`, { method: "POST" }),
  leaveCampLeaveEvent: (eventId: number) =>
    request<CampLeaveEventMember>(`/api/camp-leave/events/${eventId}/leave`, { method: "POST" }),
  closeCampLeaveEvent: (eventId: number) =>
    request<CampLeaveAdminEvent>(`/api/camp-leave/admin/events/${eventId}/close`, { method: "POST" }),
  removeCampLeaveParticipant: (eventId: number, participantId: number) =>
    request<void>(`/api/camp-leave/admin/events/${eventId}/participants/${participantId}`, { method: "DELETE" }),
  publicCampLeaveEvent: (token: string) =>
    request<CampLeavePublicEvent>(`/api/camp-leave/public/${encodeURIComponent(token)}`),
  publicJoinCampLeaveEvent: (token: string, payload: { name: string; student_id: string; college: string }) =>
    request<{ submitted: boolean }>(`/api/camp-leave/public/${encodeURIComponent(token)}/participants`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  downloadCampLeaveAdminCollegeDocument: (eventId: number, college: string, offline = false) =>
    downloadFile(
      `/api/camp-leave/admin/events/${eventId}/colleges/${encodeURIComponent(college)}/document${offline ? "?offline=true" : ""}`,
      "集中请假名单.docx",
    ),
  downloadCampLeaveMemberDocument: (eventId: number) =>
    downloadFile(`/api/camp-leave/events/${eventId}/document`, "集中请假名单.docx"),

  aiReviewAccess: () => request<AIReviewAccess>("/api/ai/planner/access"),
  reviewItemPlan: (rootTaskId: number) =>
    request<AIItemReviewResult>(`/api/ai/items/${rootTaskId}/review`, { method: "POST" }),
  applyItemReview: (rootTaskId: number, suggestion: AIItemReviewSuggestion) =>
    request<{ task: Task; activity: ItemActivity }>(`/api/ai/items/${rootTaskId}/review/apply`, {
      method: "POST",
      body: JSON.stringify(suggestion),
    }),
  extractPlannerFile: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<AIPlannerExtractedFile>("/api/ai/planner/extract", {
      method: "POST",
      body: form,
    })
  },

  knowledgeDocuments: () => request<KnowledgeDocument[]>("/api/knowledge"),
  syncGitHubKnowledge: () =>
    request<KnowledgeSyncSummary>("/api/knowledge/sync/github", { method: "POST" }),
  uploadKnowledgeDocument: (file: File) => {
    const form = new FormData()
    form.append("file", file)
    return request<KnowledgeDocument>("/api/knowledge/uploads", { method: "POST", body: form })
  },
  deleteKnowledgeDocument: (documentId: number) =>
    request<void>(`/api/knowledge/${documentId}`, { method: "DELETE" }),

  taskAssignees: () => request<TaskAssigneeOption[]>("/api/tasks/assignees"),
  tasks: (scope: TaskView = "mine") => request<Task[]>(`/api/tasks?scope=${scope}`),
  taskContext: (taskId: number) => request<TaskDetailContext>(`/api/tasks/${taskId}/context`),
  deleteRootTask: (rootTaskId: number) =>
    request<void>(`/api/tasks/${rootTaskId}`, { method: "DELETE" }),
  itemActivities: (rootTaskId: number, taskId?: number) => request<ItemActivity[]>(
    `/api/tasks/${rootTaskId}/activities${taskId === undefined ? "" : `?task_id=${taskId}`}`,
  ),
  itemActivityPage: (rootTaskId: number, taskId?: number, limit = 20, beforeId?: number) => {
    const query = new URLSearchParams({ limit: String(limit) })
    if (taskId !== undefined) query.set("task_id", String(taskId))
    if (beforeId !== undefined) query.set("before_id", String(beforeId))
    return request<ItemActivityPage>(`/api/tasks/${rootTaskId}/activities/page?${query}`)
  },
  addItemActivity: (
    rootTaskId: number,
    content: string,
    addToContext: boolean,
    factScope: "global" | "related" = "global",
    relatedTaskIds: number[] = [],
  ) =>
    request<ItemActivity>(`/api/tasks/${rootTaskId}/activities`, {
      method: "POST",
      body: JSON.stringify({
        content,
        add_to_context: addToContext,
        fact_scope: factScope,
        related_task_ids: relatedTaskIds,
      }),
    }),
  publishTaskProgress: (taskId: number, content: string) =>
    request<TaskProgressResult>(`/api/tasks/${taskId}/progress`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  completeTask: (taskId: number, result: string, syncToItem: boolean) =>
    request<TaskProgressResult>(`/api/tasks/${taskId}/complete`, {
      method: "POST",
      body: JSON.stringify({ result, sync_to_item: syncToItem }),
    }),
  extractActivityFacts: (rootTaskId: number, activityId: number) =>
    request<AIItemFactExtractionResult>(`/api/ai/items/${rootTaskId}/extract-facts`, {
      method: "POST",
      body: JSON.stringify({ activity_id: activityId }),
    }),
  addContextFact: (rootTaskId: number, content: string) =>
    request<Task>(`/api/tasks/${rootTaskId}/context-facts`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  addContextFactsBatch: (rootTaskId: number, facts: string[]) =>
    request<Task>(`/api/tasks/${rootTaskId}/context-facts/batch`, {
      method: "POST",
      body: JSON.stringify({ facts }),
    }),
  addScopedFactsBatch: (rootTaskId: number, facts: ItemFactInput[]) =>
    request<Task>(`/api/tasks/${rootTaskId}/facts/batch`, {
      method: "POST",
      body: JSON.stringify({ facts }),
    }),
  updateFactScope: (rootTaskId: number, factId: number, scope: "global" | "related", relatedTaskIds: number[]) =>
    request<Task>(`/api/tasks/${rootTaskId}/facts/${factId}/scope`, {
      method: "PATCH",
      body: JSON.stringify({ scope, related_task_ids: relatedTaskIds }),
    }),
  deleteItemFact: (rootTaskId: number, factId: number) =>
    request<Task>(`/api/tasks/${rootTaskId}/facts/${factId}`, { method: "DELETE" }),
  deleteContextFact: (rootTaskId: number, factIndex: number) =>
    request<Task>(`/api/tasks/${rootTaskId}/context-facts/${factIndex}`, { method: "DELETE" }),
  taskResultToContext: (taskId: number) =>
    request<Task>(`/api/tasks/${taskId}/result-to-context`, { method: "POST" }),
  createTask: (payload: TaskPayload) =>
    request<Task>("/api/tasks", { method: "POST", body: JSON.stringify(payload) }),
  createTaskBatch: (payload: TaskBatchPayload) =>
    request<TaskBatchResult>("/api/tasks/batch", { method: "POST", body: JSON.stringify(payload) }),
  updateTask: (taskId: number, payload: Partial<Omit<TaskPayload, "parent_id" | "kind">> & { result?: string }) =>
    request<Task>(`/api/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  claimTask: (taskId: number) => request<Task>(`/api/tasks/${taskId}/claim`, { method: "POST" }),
  unclaimTask: (taskId: number) => request<Task>(`/api/tasks/${taskId}/unclaim`, { method: "POST" }),
  joinTask: (taskId: number) => request<Task>(`/api/tasks/${taskId}/collaborators/join`, { method: "POST" }),
  leaveTask: (taskId: number) => request<Task>(`/api/tasks/${taskId}/collaborators/leave`, { method: "POST" }),
}
