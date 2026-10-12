export type Role = "admin" | "member"
export type TeamGroup = "electrical" | "mechanical" | "vision" | "ai" | "operations"
export type TeamMembership = "formal" | "reserve"
export type MemberStatus = "invited" | "active" | "disabled"
export type TaskStatus = "todo" | "doing" | "done"
export type TaskKind = "item" | "task"
export type TaskView = "mine" | "claimable" | "all"
export type ItemFactScope = "global" | "related"

export interface Member {
  id: number
  name: string
  email: string
  student_id: string | null
  team_group: TeamGroup | null
  college: string | null
  team_membership: TeamMembership | null
  role: Role
  status: MemberStatus
  created_at: string
}

export interface MemberSummary {
  id: number
  name: string
}

export interface TaskAssigneeOption extends MemberSummary {
  team_group: TeamGroup | null
}

export interface Task {
  id: number
  kind: TaskKind
  parent_id: number | null
  title: string
  deliverable: string
  execution_points: string[]
  cautions: string[]
  prerequisites: string[]
  item_facts: ItemFact[]
  context_facts: string[]
  result: string
  owner: MemberSummary | null
  owner_claimable: boolean
  collaborators: MemberSummary[]
  collaboration_open: boolean
  deadline: string | null
  status: TaskStatus
  created_by: number
  created_at: string
  depends_on_tasks: TaskDependency[]
  blocked: boolean
  blocked_by: TaskDependency[]
}

export interface TaskDependency {
  id: number
  title: string
  status: TaskStatus
  owner: MemberSummary | null
}

export interface ItemActivity {
  id: number
  root_task_id: number
  task_id: number | null
  author: MemberSummary
  content: string
  created_at: string
}

export interface ItemActivityPage {
  items: ItemActivity[]
  has_more: boolean
  next_before_id: number | null
}

export interface TaskDetailContext {
  root: Task
  tasks: Task[]
  activity_page: ItemActivityPage
}

export interface ItemFact {
  id: number
  root_task_id: number
  content: string
  scope: ItemFactScope
  related_tasks: Array<{ id: number; title: string }>
  source_activity_id: number | null
  created_by: MemberSummary
  created_at: string
  superseded_by_id: number | null
}

export interface ItemFactInput {
  content: string
  scope: ItemFactScope
  related_task_ids: number[]
  source_activity_id?: number | null
  supersedes_fact_id?: number | null
}

export interface TaskProgressResult {
  task: Task
  activity: ItemActivity
}

export interface AIItemFactSuggestion {
  text: string
  reason: string
  scope: ItemFactScope
  related_task_ids: number[]
  supersedes_fact_id: number | null
}

export interface AIItemFactExtractionResult {
  suggestions: AIItemFactSuggestion[]
}

export interface InviteResult {
  member: Member
  invite_path: string
  expires_at: string
}

export interface CollegeOption {
  code: string
  name: string
}

export interface MemberProfilePayload {
  student_id: string | null
  team_group: TeamGroup | null
  college: string | null
  team_membership: TeamMembership | null
}

export interface MyProfilePayload {
  student_id: string | null
  team_group: TeamGroup | null
  college: string | null
}

export interface InvitationInfo {
  name: string
  email: string
  expires_at: string
}

export interface TeamRegistrationInfo {
  expires_at: string
  active: boolean
}

export interface TeamRegistrationWindow {
  id: number
  expires_at: string
  created_at: string
}

export interface TeamRegistrationWindowOpen extends TeamRegistrationWindow {
  register_path: string
}

export interface TeamRegistrationPayload {
  name: string
  email: string
  student_id: string
  college: string
  team_group: TeamGroup
  password: string
}

export type SchoolLeaveRequestStatus = "pending" | "included" | "withdrawn"
export type SchoolLeaveRunStatus = "ready" | "awaiting_return" | "completed" | "cancelled"
export type SchoolLeaveResultState = "available" | "cleared"

export interface SchoolLeaveRequest {
  id: number
  member_id: number
  start_at: string
  end_at: string
  member_name_snapshot: string
  student_id_snapshot: string
  status: SchoolLeaveRequestStatus
  run_id: number | null
  run_status: SchoolLeaveRunStatus | null
  group_index: number | null
  result_state: SchoolLeaveResultState | null
  created_at: string
  updated_at: string
}

export interface SchoolLeaveGroupMember {
  member_id: number
  name: string
  student_id: string
}

export interface SchoolLeaveGroupResult {
  original_filename: string
  mime_type: string
  size_bytes: number
  uploaded_at: string
  expires_at: string
  deleted_at: string | null
  available: boolean
}

export interface SchoolLeaveGroup {
  index: number
  start_at: string
  end_at: string
  time_text: string
  count: number
  members: SchoolLeaveGroupMember[]
  result: SchoolLeaveGroupResult | null
}

export interface SchoolLeaveRun {
  id: number
  collected_at: string
  created_by: MemberSummary | null
  reason: string
  status: SchoolLeaveRunStatus
  downloaded_at: string | null
  downloaded_by: MemberSummary | null
  request_count: number
  member_count: number
  groups: SchoolLeaveGroup[]
  document_ready: boolean
}

export interface SchoolLeaveAdminConfig {
  daily_cutoff: string
  contact_phone_configured: boolean
}

export interface SchoolLeaveAdminSummary {
  ready_count: number
  awaiting_return_count: number
  todo_count: number
}

export type DailyLeaveWindowStatus = "open" | "closed"

export interface DailyLeaveWindowMember {
  id: number
  title: string
  start_at: string
  end_at: string
  open_until: string
  status: DailyLeaveWindowStatus
  accepting_participants: boolean
}

export interface DailyLeaveWindowAdmin extends DailyLeaveWindowMember {
  team_open: boolean
  public_enabled: boolean
  entry_count: number
  public_path: string | null
  created_at: string
}

export interface DailyLeaveWindowCreatePayload {
  title: string
  start_at: string
  end_at: string
}

export interface DailyLeavePublicWindow {
  start_at: string
  end_at: string
  accepting_participants: boolean
}

export interface DailyLeaveSelfServicePayload {
  start_at: string
  end_at: string
}

export interface DailyLeavePublicEntry {
  name: string
  student_id: string
  college: string
}

export type CampLeaveType = "winter" | "summer"
export type CampLeaveStatus = "collecting" | "closed"
export type CampLeaveParticipantType = "formal" | "reserve" | "other"

export interface CampLeaveEventMember {
  id: number
  title: string
  type: CampLeaveType
  start_date: string
  end_date: string
  collection_deadline: string
  status: CampLeaveStatus
  accepting_participants: boolean
  joined: boolean
  participant_type: CampLeaveParticipantType | null
  submitted_at: string | null
}

export interface CampLeaveAdminEvent {
  id: number
  title: string
  type: CampLeaveType
  start_date: string
  end_date: string
  collection_deadline: string
  status: CampLeaveStatus
  accepting_participants: boolean
  participant_count: number
  public_path: string
  created_at: string
}

export interface CampLeaveParticipant {
  id: number
  name: string
  student_id: string
  college: string
  college_name: string
  participant_type: CampLeaveParticipantType
  submitted_at: string
}

export interface CampLeaveParticipantGroup {
  college: string
  college_name: string
  count: number
  participants: CampLeaveParticipant[]
}

export interface CampLeaveAdminEventDetail {
  event: CampLeaveAdminEvent
  groups: CampLeaveParticipantGroup[]
}

export interface CampLeavePublicEvent {
  title: string
  type: CampLeaveType
  start_date: string
  end_date: string
  collection_deadline: string
  status: CampLeaveStatus
  accepting_participants: boolean
}

export interface CampLeaveEventCreatePayload {
  title: string
  type: CampLeaveType
  start_date: string
  end_date: string
  collection_deadline: string
}

export interface AIReviewAccess { available: boolean }
export interface AIPlannerItemDraft {
  title: string
  deliverable: string
  deadline: string | null
}
export interface AIPlannerTaskDraft {
  title: string
  deliverable: string
  deadline: string | null
  execution_points: string[]
  cautions: string[]
  prerequisites: string[]
  owner_claimable: boolean
  collaboration_open: boolean
}
export interface AIPlannerSuggestionDraft {
  title: string
  reason: string
}
export interface AIPlannerDraft {
  item: AIPlannerItemDraft
  tasks: AIPlannerTaskDraft[]
  questions: string[]
  suggestions: AIPlannerSuggestionDraft[]
}
export interface TaskBatchPayload {
  item: { title: string; deliverable: string; deadline: string | null }
  tasks: AIPlannerTaskDraft[]
}
export interface TaskBatchResult {
  item: Task
  tasks: Task[]
}

export type KnowledgeParseStatus = "ready" | "truncated" | "failed" | "unparseable" | "removed"
export interface KnowledgeDocument {
  id: number
  source_type: "github" | "upload"
  source_name: string
  display_name: string
  title: string
  parse_status: KnowledgeParseStatus
  parse_error: string | null
  is_active: boolean
  synced_at: string
  source_updated_at: string | null
}
export interface AIItemReviewTaskProposal {
  title: string
  deliverable: string
  execution_points: string[]
  cautions: string[]
  prerequisites: string[]
}
export interface AIItemReviewSuggestion {
  kind: "update_task" | "add_task"
  target_task_id: number | null
  reason: string
  proposed_task: AIItemReviewTaskProposal
}
export interface AIItemReviewResult {
  summary: string
  suggestions: AIItemReviewSuggestion[]
}
export interface AIPlannerExtractedFile {
  filename: string
  extracted_text: string
  parse_status: "ready" | "truncated" | "failed" | "unparseable"
  error: string | null
}
export interface KnowledgeSyncSummary {
  added: number
  updated: number
  unchanged: number
  failed: number
  removed: number
}
