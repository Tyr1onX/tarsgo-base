from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from .college_dictionary import is_college_code

Role = Literal["admin", "member"]
TeamGroup = Literal["electrical", "mechanical", "vision", "ai", "operations"]
TeamMembership = Literal["formal", "reserve"]
MemberStatus = Literal["invited", "active", "disabled"]
TaskStatus = Literal["todo", "doing", "done"]
TaskKind = Literal["item", "task"]
SchoolLeaveRequestStatus = Literal["pending", "included", "withdrawn"]
SchoolLeaveRunStatus = Literal["ready", "awaiting_return", "completed", "cancelled"]
SchoolLeaveResultState = Literal["available", "cleared"]
CampLeaveType = Literal["winter", "summer"]
CampLeaveStatus = Literal["collecting", "closed"]
CampLeaveParticipantType = Literal["formal", "reserve", "other"]
DailyLeaveParticipantType = Literal["formal", "reserve", "other"]
DailyLeaveWindowStatus = Literal["open", "closed"]
ItemFactScope = Literal["global", "related"]
TaskDetailText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
ContextFactText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ItemActivityText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


def _clean_task_details(values: list[str] | None, *, max_items: int, field_name: str) -> list[str] | None:
    if values is None:
        return None
    result: list[str] = []
    for value in values:
        text = value.strip()
        if not text:
            continue
        if len(text) > 240:
            raise ValueError(f"{field_name}单条内容不能超过 240 字")
        result.append(text)
    if len(result) > max_items:
        raise ValueError(f"{field_name}最多 {max_items} 条")
    return result


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 255 or "@" not in email or " " in email:
        raise ValueError("请输入有效邮箱")
    local, _, domain = email.partition("@")
    if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("请输入有效邮箱")
    return email


def validate_member_name(value: str) -> str:
    value = value.strip()
    if not 2 <= len(value) <= 50:
        raise ValueError("姓名长度需为 2–50 个字符")
    return value


def validate_student_id(value: str) -> str:
    value = value.strip()
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ValueError("学号必须是 8 位数字")
    return value


def validate_college(value: str) -> str:
    value = value.strip()
    if not is_college_code(value):
        raise ValueError("请选择有效学院")
    return value


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str
    student_id: str | None = None
    team_group: TeamGroup | None = None
    college: str | None = None
    team_membership: TeamMembership | None = None
    role: Role
    status: MemberStatus
    created_at: datetime


class CollegeOut(BaseModel):
    code: str
    name: str


class InviteCreate(BaseModel):
    name: str
    email: str = Field(min_length=3, max_length=255)
    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_member_name(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)


class InviteOut(BaseModel):
    member: MemberOut
    invite_path: str
    expires_at: datetime


class InvitationInfo(BaseModel):
    name: str
    email: str
    expires_at: datetime


class InvitationAccept(BaseModel):
    password: str = Field(min_length=8, max_length=128)


class TeamRegistrationInfo(BaseModel):
    expires_at: datetime
    active: bool = True


class TeamRegistrationWindowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    expires_at: datetime
    created_at: datetime


class TeamRegistrationWindowOpenOut(TeamRegistrationWindowOut):
    register_path: str


class TeamRegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    email: str = Field(min_length=3, max_length=255)
    student_id: str
    college: str
    team_group: TeamGroup
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_member_name(value)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("student_id")
    @classmethod
    def validate_student_id(cls, value: str) -> str:
        return validate_student_id(value)

    @field_validator("college")
    @classmethod
    def validate_college(cls, value: str) -> str:
        return validate_college(value)


class MemberSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class TaskAssigneeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    team_group: TeamGroup | None = None


class MemberProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str | None = None
    team_group: TeamGroup | None = None
    college: str | None = None

    @field_validator("student_id")
    @classmethod
    def normalize_student_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if len(value) != 8 or not value.isascii() or not value.isdigit():
            raise ValueError("学号必须是 8 位数字")
        return value

    @field_validator("college")
    @classmethod
    def validate_college(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not is_college_code(value):
            raise ValueError("请选择有效学院")
        return value


class AdminMemberProfileUpdate(MemberProfileUpdate):
    team_membership: TeamMembership | None = None


def _normalize_school_leave_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        raise ValueError("请使用学校所在地的明确本地时间，不要包含时区偏移")
    value = value.replace(second=0, microsecond=0)
    if value.minute % 5 != 0:
        raise ValueError("请假时间请按 5 分钟粒度填写")
    return value


class SchoolLeaveRequestCreate(BaseModel):
    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _normalize_school_leave_datetime(value)

    @model_validator(mode="after")
    def validate_order(self):
        if self.start_at >= self.end_at:
            raise ValueError("开始时间必须早于结束时间")
        return self


class SchoolLeaveRequestUpdate(SchoolLeaveRequestCreate):
    pass


class SchoolLeaveRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    member_id: int
    start_at: datetime
    end_at: datetime
    member_name_snapshot: str
    student_id_snapshot: str
    status: SchoolLeaveRequestStatus
    run_id: int | None
    run_status: SchoolLeaveRunStatus | None = None
    group_index: int | None = None
    result_state: SchoolLeaveResultState | None = None
    created_at: datetime
    updated_at: datetime


def _normalize_daily_leave_datetime(value: datetime) -> datetime:
    if value.tzinfo is not None:
        raise ValueError("请使用北京时间，不要包含时区偏移")
    return value.replace(second=0, microsecond=0)


class DailyLeaveWindowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    start_at: datetime
    end_at: datetime
    open_until: datetime | None = None
    team_open: bool = True
    public_enabled: bool = False

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("活动名称不能为空")
        return value

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _normalize_daily_leave_datetime(value)

    @field_validator("open_until")
    @classmethod
    def normalize_optional_open_until(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _normalize_daily_leave_datetime(value)

    @model_validator(mode="after")
    def validate_times(self):
        if self.start_at >= self.end_at:
            raise ValueError("活动开始时间必须早于结束时间")
        if self.open_until is None:
            self.open_until = self.end_at
        if self.open_until > self.end_at:
            raise ValueError("开放截止时间不能晚于活动结束时间")
        return self


class DailyLeaveSelfServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime

    @field_validator("start_at", "end_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        return _normalize_daily_leave_datetime(value)

    @model_validator(mode="after")
    def validate_times(self):
        if self.start_at >= self.end_at:
            raise ValueError("开始时间必须早于结束时间")
        return self


class DailyLeaveWindowMemberOut(BaseModel):
    id: int
    title: str
    start_at: datetime
    end_at: datetime
    open_until: datetime
    status: DailyLeaveWindowStatus
    accepting_participants: bool


class DailyLeaveWindowAdminOut(BaseModel):
    id: int
    title: str
    start_at: datetime
    end_at: datetime
    open_until: datetime
    team_open: bool
    public_enabled: bool
    status: DailyLeaveWindowStatus
    accepting_participants: bool
    entry_count: int
    public_path: str | None
    created_at: datetime


class DailyLeavePublicWindowOut(BaseModel):
    start_at: datetime
    end_at: datetime
    accepting_participants: bool


class DailyLeavePublicEntryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    student_id: str
    college: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return validate_member_name(value)

    @field_validator("student_id")
    @classmethod
    def check_student_id(cls, value: str) -> str:
        return validate_student_id(value)

    @field_validator("college")
    @classmethod
    def check_college(cls, value: str) -> str:
        return validate_college(value)


class SchoolLeaveReasonUpdate(BaseModel):
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reason")
    @classmethod
    def clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请假事由不能为空")
        return value


class SchoolLeaveGroupMemberOut(BaseModel):
    member_id: int
    name: str
    student_id: str


class SchoolLeaveGroupResultOut(BaseModel):
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime
    expires_at: datetime
    deleted_at: datetime | None
    available: bool


class SchoolLeaveGroupOut(BaseModel):
    index: int
    start_at: datetime
    end_at: datetime
    time_text: str
    count: int
    members: list[SchoolLeaveGroupMemberOut]
    result: SchoolLeaveGroupResultOut | None = None


class CampLeaveEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=100)
    type: CampLeaveType
    start_date: date
    end_date: date
    collection_deadline: datetime

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("活动名称不能为空")
        return value

    @field_validator("collection_deadline")
    @classmethod
    def validate_deadline(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            raise ValueError("收集截止时间请使用北京时间，不要包含时区偏移")
        return value.replace(second=0, microsecond=0)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.start_date > self.end_date:
            raise ValueError("活动开始日期不能晚于结束日期")
        return self


class CampLeavePublicParticipantCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    student_id: str
    college: str

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return validate_member_name(value)

    @field_validator("student_id")
    @classmethod
    def validate_student_id(cls, value: str) -> str:
        return validate_student_id(value)

    @field_validator("college")
    @classmethod
    def validate_college(cls, value: str) -> str:
        return validate_college(value)


class CampLeaveEventMemberOut(BaseModel):
    id: int
    title: str
    type: CampLeaveType
    start_date: date
    end_date: date
    collection_deadline: datetime
    status: CampLeaveStatus
    accepting_participants: bool
    joined: bool
    participant_type: CampLeaveParticipantType | None = None
    submitted_at: datetime | None = None


class CampLeaveAdminEventOut(BaseModel):
    id: int
    title: str
    type: CampLeaveType
    start_date: date
    end_date: date
    collection_deadline: datetime
    status: CampLeaveStatus
    accepting_participants: bool
    participant_count: int
    public_path: str
    created_at: datetime


class CampLeaveParticipantOut(BaseModel):
    id: int
    name: str
    student_id: str
    college: str
    college_name: str
    participant_type: CampLeaveParticipantType
    submitted_at: datetime


class CampLeaveParticipantGroupOut(BaseModel):
    college: str
    college_name: str
    count: int
    participants: list[CampLeaveParticipantOut]


class CampLeaveAdminEventDetailOut(BaseModel):
    event: CampLeaveAdminEventOut
    groups: list[CampLeaveParticipantGroupOut]


class CampLeavePublicEventOut(BaseModel):
    title: str
    type: CampLeaveType
    start_date: date
    end_date: date
    collection_deadline: datetime
    status: CampLeaveStatus
    accepting_participants: bool


class CampLeavePublicSubmissionOut(BaseModel):
    submitted: bool = True


class SchoolLeaveRunOut(BaseModel):
    id: int
    collected_at: datetime
    created_by: MemberSummary | None
    reason: str
    status: SchoolLeaveRunStatus
    downloaded_at: datetime | None
    downloaded_by: MemberSummary | None
    request_count: int
    member_count: int
    groups: list[SchoolLeaveGroupOut]
    document_ready: bool


class SchoolLeaveAdminConfigOut(BaseModel):
    daily_cutoff: str
    contact_phone_configured: bool


class SchoolLeaveAdminSummaryOut(BaseModel):
    ready_count: int
    awaiting_return_count: int
    todo_count: int


class TaskCreate(BaseModel):
    kind: TaskKind | None = None
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(default="", max_length=5000)
    execution_points: list[TaskDetailText] = Field(default_factory=list, max_length=6)
    cautions: list[TaskDetailText] = Field(default_factory=list, max_length=5)
    prerequisites: list[TaskDetailText] = Field(default_factory=list, max_length=4)
    owner_id: int | None = None
    owner_claimable: bool = False
    collaborator_ids: list[int] = Field(default_factory=list)
    collaboration_open: bool = False
    parent_id: int | None = None
    deadline: datetime | None = None
    status: TaskStatus = "todo"
    depends_on_task_ids: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("任务内容不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_deliverable(cls, value: str) -> str:
        return value.strip()

    @field_validator("execution_points")
    @classmethod
    def clean_execution_points(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=6, field_name="执行要点") or []

    @field_validator("cautions")
    @classmethod
    def clean_cautions(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=5, field_name="注意事项") or []

    @field_validator("prerequisites")
    @classmethod
    def clean_prerequisites(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=4, field_name="前置条件") or []

    @model_validator(mode="after")
    def validate_owner(self):
        if self.owner_id is None and not self.owner_claimable:
            raise ValueError("任务必须指定负责人或开放负责人认领")
        return self


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    deliverable: str | None = Field(default=None, max_length=5000)
    execution_points: list[TaskDetailText] | None = Field(default=None, max_length=6)
    cautions: list[TaskDetailText] | None = Field(default=None, max_length=5)
    prerequisites: list[TaskDetailText] | None = Field(default=None, max_length=4)
    result: str | None = Field(default=None, max_length=5000)
    owner_id: int | None = None
    owner_claimable: bool | None = None
    collaborator_ids: list[int] | None = None
    collaboration_open: bool | None = None
    deadline: datetime | None = None
    status: TaskStatus | None = None
    depends_on_task_ids: list[int] | None = Field(default=None, max_length=20)

    @field_validator("title")
    @classmethod
    def strip_optional_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("任务内容不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_optional_deliverable(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()

    @field_validator("execution_points")
    @classmethod
    def clean_optional_execution_points(cls, value: list[str] | None) -> list[str] | None:
        return _clean_task_details(value, max_items=6, field_name="执行要点")

    @field_validator("cautions")
    @classmethod
    def clean_optional_cautions(cls, value: list[str] | None) -> list[str] | None:
        return _clean_task_details(value, max_items=5, field_name="注意事项")

    @field_validator("prerequisites")
    @classmethod
    def clean_optional_prerequisites(cls, value: list[str] | None) -> list[str] | None:
        return _clean_task_details(value, max_items=4, field_name="前置条件")

    @field_validator("result")
    @classmethod
    def strip_optional_result(cls, value: str | None) -> str | None:
        return None if value is None else value.strip()


class TaskDependencyOut(BaseModel):
    id: int
    title: str
    status: TaskStatus
    owner: MemberSummary | None


class ItemFactTaskOut(BaseModel):
    id: int
    title: str


class ItemFactOut(BaseModel):
    id: int
    root_task_id: int
    content: str
    scope: ItemFactScope
    related_tasks: list[ItemFactTaskOut] = Field(default_factory=list)
    source_activity_id: int | None = None
    created_by: MemberSummary
    created_at: datetime
    superseded_by_id: int | None = None


class TaskOut(BaseModel):
    id: int
    kind: TaskKind
    parent_id: int | None
    title: str
    deliverable: str
    execution_points: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    item_facts: list[ItemFactOut] = Field(default_factory=list)
    # Kept as a response convenience; values are derived from visible ItemFact rows.
    context_facts: list[str] = Field(default_factory=list)
    result: str = ""
    owner: MemberSummary | None
    owner_claimable: bool
    collaborators: list[MemberSummary]
    collaboration_open: bool
    deadline: datetime | None
    status: TaskStatus
    created_by: int
    created_at: datetime
    depends_on_tasks: list[TaskDependencyOut] = Field(default_factory=list)
    blocked: bool = False
    blocked_by: list[TaskDependencyOut] = Field(default_factory=list)


class ItemFactCreate(BaseModel):
    content: ContextFactText
    scope: ItemFactScope = "global"
    related_task_ids: list[int] = Field(default_factory=list, max_length=20)
    source_activity_id: int | None = Field(default=None, ge=1)
    supersedes_fact_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "global" and self.related_task_ids:
            raise ValueError("整个事项信息不需要选择具体分工")
        if self.scope == "related" and not self.related_task_ids:
            raise ValueError("请选择至少一项相关分工")
        if len(set(self.related_task_ids)) != len(self.related_task_ids):
            raise ValueError("相关分工不能重复")
        return self


class ItemFactScopeUpdate(BaseModel):
    scope: ItemFactScope
    related_task_ids: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "global" and self.related_task_ids:
            raise ValueError("整个事项信息不需要选择具体分工")
        if self.scope == "related" and not self.related_task_ids:
            raise ValueError("请选择至少一项相关分工")
        if len(set(self.related_task_ids)) != len(self.related_task_ids):
            raise ValueError("相关分工不能重复")
        return self


class ItemActivityCreate(BaseModel):
    content: ItemActivityText
    add_to_context: bool = False
    fact_scope: ItemFactScope = "global"
    related_task_ids: list[int] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_fact_scope(self):
        if not self.add_to_context and (self.related_task_ids or self.fact_scope != "global"):
            raise ValueError("请选择同步事项信息后再设置同步范围")
        if self.fact_scope == "global" and self.related_task_ids:
            raise ValueError("整个事项信息不需要选择具体分工")
        if self.fact_scope == "related" and self.add_to_context and not self.related_task_ids:
            raise ValueError("请选择至少一项相关分工")
        if len(set(self.related_task_ids)) != len(self.related_task_ids):
            raise ValueError("相关分工不能重复")
        return self


class ItemActivityOut(BaseModel):
    id: int
    root_task_id: int
    task_id: int | None = None
    author: MemberSummary
    content: str
    created_at: datetime


class ItemActivityPageOut(BaseModel):
    items: list[ItemActivityOut]
    has_more: bool
    next_before_id: int | None = None


class TaskDetailContextOut(BaseModel):
    root: TaskOut
    tasks: list[TaskOut]
    activity_page: ItemActivityPageOut


class TaskProgressCreate(BaseModel):
    content: ItemActivityText


class TaskCompleteCreate(BaseModel):
    result: str = Field(min_length=1, max_length=5000)
    sync_to_item: bool = False

    @field_validator("result")
    @classmethod
    def strip_completion_result(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请填写最终结果")
        return value


class TaskProgressOut(BaseModel):
    task: TaskOut
    activity: ItemActivityOut


class ContextFactsBatchIn(BaseModel):
    facts: list[ContextFactText] = Field(min_length=1, max_length=30)


class ItemFactsBatchIn(BaseModel):
    facts: list[ItemFactCreate] = Field(min_length=1, max_length=5)


class AIItemFactSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: ContextFactText
    reason: str = Field(min_length=1, max_length=200)
    scope: ItemFactScope
    related_task_ids: list[int] = Field(max_length=20)
    supersedes_fact_id: int | None = Field(ge=1)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope == "global" and self.related_task_ids:
            raise ValueError("整个事项信息不能关联具体分工")
        if len(set(self.related_task_ids)) != len(self.related_task_ids):
            raise ValueError("相关分工不能重复")
        return self


class AIItemFactExtractionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    suggestions: list[AIItemFactSuggestion] = Field(max_length=5)


class AIItemFactExtractionRequest(BaseModel):
    activity_id: int = Field(ge=1)


class AIPlannerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=10, max_length=5000)
    item_title: str | None = Field(default=None, max_length=200)
    current_event_context: str | None = Field(default=None, max_length=5000)
    current_event_document_ids: list[int] = Field(default_factory=list, max_length=5)
    excluded_historical_document_ids: list[int] = Field(default_factory=list, max_length=6)

    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("请再补充一些事项背景")
        return value

    @field_validator("item_title")
    @classmethod
    def strip_item_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("current_event_context")
    @classmethod
    def strip_current_event_context(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("current_event_document_ids")
    @classmethod
    def validate_document_ids(cls, value: list[int]) -> list[int]:
        if any(document_id < 1 for document_id in value) or len(set(value)) != len(value):
            raise ValueError("资料选择无效")
        return value

    @field_validator("excluded_historical_document_ids")
    @classmethod
    def validate_excluded_document_ids(cls, value: list[int]) -> list[int]:
        if any(document_id < 1 for document_id in value) or len(set(value)) != len(value):
            raise ValueError("资料排除项无效")
        return value


class AIPlannerItemDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(max_length=1000)
    deadline: datetime | None

    @field_validator("title")
    @classmethod
    def strip_item_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("事项标题不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_item_deliverable(cls, value: str) -> str:
        return value.strip()


class AIPlannerTaskDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(max_length=1000)
    deadline: datetime | None
    execution_points: list[TaskDetailText] = Field(max_length=6)
    cautions: list[TaskDetailText] = Field(max_length=5)
    prerequisites: list[TaskDetailText] = Field(max_length=4)
    owner_claimable: bool
    collaboration_open: bool

    @field_validator("title")
    @classmethod
    def strip_task_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分工标题不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_task_deliverable(cls, value: str) -> str:
        return value.strip()

    @field_validator("execution_points")
    @classmethod
    def clean_execution_points(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=6, field_name="执行要点") or []

    @field_validator("cautions")
    @classmethod
    def clean_cautions(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=5, field_name="注意事项") or []

    @field_validator("prerequisites")
    @classmethod
    def clean_prerequisites(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=4, field_name="前置条件") or []


class AIPlannerSuggestionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=200)

    @field_validator("title", "reason")
    @classmethod
    def strip_suggestion_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("可能遗漏内容不能为空")
        return value


class AIPlannerDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: AIPlannerItemDraft
    tasks: list[AIPlannerTaskDraft] = Field(min_length=1, max_length=15)
    questions: list[str] = Field(max_length=6)
    suggestions: list[AIPlannerSuggestionDraft] = Field(max_length=3)

    @model_validator(mode="before")
    @classmethod
    def default_suggestions(cls, value):
        if isinstance(value, dict) and "suggestions" not in value:
            value = dict(value)
            value["suggestions"] = []
        return value

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            text = value.strip()
            if not text:
                continue
            if len(text) > 200:
                raise ValueError("确认问题过长")
            result.append(text)
        return result


class AIPlannerRefineRequest(AIPlannerRequest):
    model_config = ConfigDict(extra="forbid")
    draft: AIPlannerDraft
    instruction: str = Field(min_length=1, max_length=1000)
    scope_task_index: int | None = Field(default=None, ge=0, le=14)

    @field_validator("instruction")
    @classmethod
    def strip_instruction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("请输入调整要求")
        return value

    @model_validator(mode="after")
    def validate_refine_draft(self):
        if self.scope_task_index is not None and self.scope_task_index >= len(self.draft.tasks):
            raise ValueError("指定的分工不存在")
        if len(self.draft.model_dump_json()) > 30_000:
            raise ValueError("当前草案过长，请先删减后再调整")
        return self


class AIPlannerAccessOut(BaseModel):
    available: bool


class KnowledgeDocumentOut(BaseModel):
    id: int
    source_type: Literal["github", "upload"]
    source_name: str
    display_name: str
    title: str
    parse_status: Literal["ready", "truncated", "failed", "unparseable", "removed"]
    parse_error: str | None
    is_active: bool
    synced_at: datetime
    source_updated_at: datetime | None


class KnowledgeReferenceOut(BaseModel):
    id: int
    source_type: Literal["github", "upload"]
    source_name: str
    source_label: str
    title: str


class AIPlannerGenerateOut(BaseModel):
    draft: AIPlannerDraft
    current_event_documents: list[KnowledgeReferenceOut] = Field(default_factory=list)
    historical_documents: list[KnowledgeReferenceOut] = Field(default_factory=list)


class AIItemReviewTaskProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(max_length=5000)
    execution_points: list[TaskDetailText] = Field(max_length=6)
    cautions: list[TaskDetailText] = Field(max_length=5)
    prerequisites: list[TaskDetailText] = Field(max_length=4)

    @field_validator("title")
    @classmethod
    def strip_review_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分工标题不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_review_deliverable(cls, value: str) -> str:
        return value.strip()

    @field_validator("execution_points")
    @classmethod
    def clean_review_execution_points(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=6, field_name="执行要点") or []

    @field_validator("cautions")
    @classmethod
    def clean_review_cautions(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=5, field_name="注意事项") or []

    @field_validator("prerequisites")
    @classmethod
    def clean_review_prerequisites(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=4, field_name="前置条件") or []


class AIItemReviewSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["update_task", "add_task"]
    target_task_id: int | None
    reason: str = Field(min_length=1, max_length=500)
    proposed_task: AIItemReviewTaskProposal

    @field_validator("reason")
    @classmethod
    def strip_review_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("建议原因不能为空")
        return value

    @model_validator(mode="after")
    def validate_review_target(self):
        if self.kind == "update_task" and self.target_task_id is None:
            raise ValueError("调整任务必须指定目标分工")
        if self.kind == "add_task" and self.target_task_id is not None:
            raise ValueError("新增任务不能指定目标分工")
        return self


class AIItemReviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=500)
    suggestions: list[AIItemReviewSuggestion] = Field(max_length=6)

    @field_validator("summary")
    @classmethod
    def strip_review_summary(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("检查摘要不能为空")
        return value


class AIItemReviewApplyOut(BaseModel):
    task: TaskOut
    activity: ItemActivityOut


class AIPlannerExtractOut(BaseModel):
    filename: str
    extracted_text: str
    parse_status: Literal["ready", "truncated", "failed", "unparseable"]
    error: str | None = None


class KnowledgeSyncOut(BaseModel):
    added: int
    updated: int
    unchanged: int
    failed: int
    removed: int


class TaskBatchItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(default="", max_length=5000)
    deadline: datetime | None = None

    @field_validator("title")
    @classmethod
    def strip_batch_item_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("事项标题不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_batch_item_deliverable(cls, value: str) -> str:
        return value.strip()


class TaskBatchChildIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    deliverable: str = Field(default="", max_length=5000)
    deadline: datetime | None = None
    execution_points: list[TaskDetailText] = Field(default_factory=list, max_length=6)
    cautions: list[TaskDetailText] = Field(default_factory=list, max_length=5)
    prerequisites: list[TaskDetailText] = Field(default_factory=list, max_length=4)
    owner_claimable: bool = True
    collaboration_open: bool = False

    @field_validator("title")
    @classmethod
    def strip_batch_child_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("分工标题不能为空")
        return value

    @field_validator("deliverable")
    @classmethod
    def strip_batch_child_deliverable(cls, value: str) -> str:
        return value.strip()

    @field_validator("execution_points")
    @classmethod
    def clean_execution_points(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=6, field_name="执行要点") or []

    @field_validator("cautions")
    @classmethod
    def clean_cautions(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=5, field_name="注意事项") or []

    @field_validator("prerequisites")
    @classmethod
    def clean_prerequisites(cls, value: list[str]) -> list[str]:
        return _clean_task_details(value, max_items=4, field_name="前置条件") or []


class TaskBatchCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: TaskBatchItemIn
    tasks: list[TaskBatchChildIn] = Field(default_factory=list, max_length=15)


class TaskBatchOut(BaseModel):
    item: TaskOut
    tasks: list[TaskOut]
