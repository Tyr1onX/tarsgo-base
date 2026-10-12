from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Index,
    JSON,
    String,
    Table,
    Text,
    text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .college_dictionary import COLLEGE_CODES

from .db import Base


ROLE_VALUES = ("admin", "member")
TEAM_GROUP_VALUES = ("electrical", "mechanical", "vision", "ai", "operations")
MEMBER_STATUS_VALUES = ("invited", "active", "disabled")
TASK_STATUS_VALUES = ("todo", "doing", "done")
SCHOOL_LEAVE_REQUEST_STATUS_VALUES = ("pending", "included", "withdrawn")
SCHOOL_LEAVE_RUN_STATUS_VALUES = ("ready", "awaiting_return", "completed", "cancelled")
CAMP_LEAVE_TYPE_VALUES = ("winter", "summer")
CAMP_LEAVE_STATUS_VALUES = ("collecting", "closed")
CAMP_LEAVE_PARTICIPANT_TYPE_VALUES = ("formal", "reserve", "other")
DAILY_LEAVE_WINDOW_STATUS_VALUES = ("open", "closed")
DAILY_LEAVE_PARTICIPANT_TYPE_VALUES = ("formal", "reserve", "other")


task_collaborators = Table(
    "task_collaborators",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("member_id", ForeignKey("members.id", ondelete="CASCADE"), primary_key=True),
)


task_dependencies = Table(
    "task_dependencies",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Column("depends_on_task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    CheckConstraint("task_id <> depends_on_task_id", name="ck_task_dependencies_not_self"),
    Index("ix_task_dependencies_depends_on", "depends_on_task_id"),
)


item_fact_tasks = Table(
    "item_fact_tasks",
    Base.metadata,
    Column("fact_id", ForeignKey("item_facts.id", ondelete="CASCADE"), primary_key=True),
    Column("task_id", ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_item_fact_tasks_task_id", "task_id"),
)


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        CheckConstraint("role IN ('admin','member')", name="ck_members_role"),
        CheckConstraint("status IN ('invited','active','disabled')", name="ck_members_status"),
        CheckConstraint(
            "team_group IS NULL OR team_group IN ('electrical','mechanical','vision','ai','operations')",
            name="ck_members_team_group",
        ),
        CheckConstraint(
            "college IS NULL OR college IN ("
            + ",".join(f"'{code}'" for code in sorted(COLLEGE_CODES))
            + ")",
            name="ck_members_college",
        ),
        CheckConstraint(
            "team_membership IS NULL OR team_membership IN ('formal','reserve')",
            name="ck_members_team_membership",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    student_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    team_group: Mapped[str | None] = mapped_column(String(20), nullable=True)
    college: Mapped[str | None] = mapped_column(String(50), nullable=True)
    team_membership: Mapped[str | None] = mapped_column(String(20), nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="member")
    status: Mapped[str] = mapped_column(String(20), default="invited")
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())


class TeamRegistrationWindow(Base):
    __tablename__ = "team_registration_windows"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())

    creator: Mapped[Member | None] = relationship()


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())

    member: Mapped[Member] = relationship()


class LoginSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime())
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())

    member: Mapped[Member] = relationship()


class SchoolLeaveRun(Base):
    __tablename__ = "school_leave_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready','awaiting_return','completed','cancelled')",
            name="ck_school_leave_runs_status",
        ),
        Index("ix_school_leave_runs_status_collected", "status", "collected_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="ready", nullable=False)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    downloaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)

    creator: Mapped[Member | None] = relationship(foreign_keys=[created_by])
    downloader: Mapped[Member | None] = relationship(foreign_keys=[downloaded_by])
    requests: Mapped[list["SchoolLeaveRequest"]] = relationship(
        back_populates="run", order_by="SchoolLeaveRequest.id"
    )
    results: Mapped[list["SchoolLeaveGroupResult"]] = relationship(
        back_populates="run",
        order_by="SchoolLeaveGroupResult.group_index",
        cascade="all, delete-orphan",
    )


class SchoolLeaveGroupResult(Base):
    __tablename__ = "school_leave_group_results"
    __table_args__ = (
        UniqueConstraint("run_id", "group_index", name="uq_school_leave_group_results_run_group"),
        Index("ix_school_leave_group_results_cleanup", "expires_at", "deleted_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("school_leave_runs.id", ondelete="CASCADE"), nullable=False
    )
    group_index: Mapped[int] = mapped_column(Integer(), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(100), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    run: Mapped[SchoolLeaveRun] = relationship(back_populates="results")
    uploader: Mapped[Member | None] = relationship(foreign_keys=[uploaded_by])


class SchoolLeaveRequest(Base):
    __tablename__ = "school_leave_requests"
    __table_args__ = (
        CheckConstraint("status IN ('pending','included','withdrawn')", name="ck_school_leave_requests_status"),
        CheckConstraint("start_at < end_at", name="ck_school_leave_requests_time_order"),
        Index("ix_school_leave_requests_status_created", "status", "created_at"),
        Index("ix_school_leave_requests_run", "run_id"),
        Index("ix_school_leave_requests_member_created", "member_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    member_name_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    student_id_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("school_leave_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    member: Mapped[Member] = relationship(foreign_keys=[member_id])
    run: Mapped[SchoolLeaveRun | None] = relationship(back_populates="requests")


class DailyLeaveWindow(Base):
    __tablename__ = "daily_leave_windows"
    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="ck_daily_leave_windows_status"),
        CheckConstraint("start_at < end_at", name="ck_daily_leave_windows_time_order"),
        CheckConstraint(
            "public_enabled = 0 OR public_token IS NOT NULL",
            name="ck_daily_leave_windows_public_token_required",
        ),
        CheckConstraint(
            "public_enabled = 1 OR public_token IS NULL",
            name="ck_daily_leave_windows_public_token_disabled",
        ),
        UniqueConstraint("public_token", name="uq_daily_leave_windows_public_token"),
        Index("ix_daily_leave_windows_status_open_until", "status", "open_until"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    open_until: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    team_open: Mapped[bool] = mapped_column(Boolean(), default=True, server_default=text("1"), nullable=False)
    public_enabled: Mapped[bool] = mapped_column(Boolean(), default=False, server_default=text("0"), nullable=False)
    public_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", server_default="open", nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)

    creator: Mapped[Member | None] = relationship()
    entries: Mapped[list["DailyLeaveEntry"]] = relationship(
        back_populates="window", cascade="all, delete-orphan"
    )


class DailyLeaveEntry(Base):
    __tablename__ = "daily_leave_entries"
    __table_args__ = (
        CheckConstraint(
            "participant_type IN ('formal','reserve','other')",
            name="ck_daily_leave_entries_participant_type",
        ),
        CheckConstraint("CHAR_LENGTH(name_snapshot) BETWEEN 2 AND 50", name="ck_daily_leave_entries_name_length"),
        CheckConstraint("CHAR_LENGTH(student_id_snapshot) = 8", name="ck_daily_leave_entries_student_id_length"),
        CheckConstraint(
            "college_snapshot IN (" + ",".join(f"'{code}'" for code in sorted(COLLEGE_CODES)) + ")",
            name="ck_daily_leave_entries_college",
        ),
        CheckConstraint(
            "(window_id IS NOT NULL AND start_at IS NULL AND end_at IS NULL) OR "
            "(window_id IS NULL AND start_at IS NOT NULL AND end_at IS NOT NULL AND start_at < end_at)",
            name="ck_daily_leave_entries_source_time_shape",
        ),
        UniqueConstraint("window_id", "student_id_snapshot", name="uq_daily_leave_window_student"),
        UniqueConstraint("window_id", "member_id", name="uq_daily_leave_window_member"),
        Index("ix_daily_leave_entries_window_college", "window_id", "college_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    window_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_leave_windows.id", ondelete="CASCADE"), nullable=True
    )
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    name_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    student_id_snapshot: Mapped[str] = mapped_column(String(8), nullable=False)
    college_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    participant_type: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)

    window: Mapped[DailyLeaveWindow | None] = relationship(back_populates="entries")
    member: Mapped[Member | None] = relationship()


class CampLeaveEvent(Base):
    __tablename__ = "camp_leave_events"
    __table_args__ = (
        CheckConstraint("type IN ('winter','summer')", name="ck_camp_leave_events_type"),
        CheckConstraint("status IN ('collecting','closed')", name="ck_camp_leave_events_status"),
        CheckConstraint("start_date <= end_date", name="ck_camp_leave_events_date_order"),
        UniqueConstraint("public_token", name="uq_camp_leave_events_public_token"),
        Index("ix_camp_leave_events_status_deadline", "status", "collection_deadline"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    start_date: Mapped[date] = mapped_column(Date(), nullable=False)
    end_date: Mapped[date] = mapped_column(Date(), nullable=False)
    collection_deadline: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="collecting", server_default="collecting", nullable=False)
    # This is a high-entropy bearer secret. It is exposed only by admin APIs and
    # is never included in member-facing event or public registration responses.
    public_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)

    creator: Mapped[Member | None] = relationship()
    participants: Mapped[list["CampLeaveParticipant"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class CampLeaveParticipant(Base):
    __tablename__ = "camp_leave_participants"
    __table_args__ = (
        CheckConstraint(
            "participant_type IN ('formal','reserve','other')",
            name="ck_camp_leave_participants_type",
        ),
        CheckConstraint(
            "CHAR_LENGTH(name_snapshot) BETWEEN 2 AND 50",
            name="ck_camp_leave_participants_name_length",
        ),
        CheckConstraint(
            "CHAR_LENGTH(student_id_snapshot) = 8",
            name="ck_camp_leave_participants_student_id",
        ),
        CheckConstraint(
            "college_snapshot IN (" + ",".join(f"'{code}'" for code in sorted(COLLEGE_CODES)) + ")",
            name="ck_camp_leave_participants_college",
        ),
        UniqueConstraint("event_id", "student_id_snapshot", name="uq_camp_leave_event_student"),
        UniqueConstraint("event_id", "member_id", name="uq_camp_leave_event_member"),
        Index("ix_camp_leave_participants_event_college", "event_id", "college_snapshot"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("camp_leave_events.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    name_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    student_id_snapshot: Mapped[str] = mapped_column(String(8), nullable=False)
    college_snapshot: Mapped[str] = mapped_column(String(50), nullable=False)
    participant_type: Mapped[str] = mapped_column(String(20), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)

    event: Mapped[CampLeaveEvent] = relationship(back_populates="participants")
    member: Mapped[Member | None] = relationship()


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('todo','doing','done')", name="ck_tasks_status"),
        CheckConstraint(
            "kind IN ('item','task') AND (parent_id IS NULL OR kind = 'task')",
            name="ck_tasks_kind",
        ),
        CheckConstraint(
            "owner_id IS NOT NULL OR owner_claimable = 1",
            name="ck_tasks_owner_or_claimable",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), default="item", server_default="item", nullable=False)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(200))
    deliverable: Mapped[str] = mapped_column(Text())
    execution_points: Mapped[list[str]] = mapped_column(
        JSON(), default=list, server_default=text("(JSON_ARRAY())"), nullable=False
    )
    cautions: Mapped[list[str]] = mapped_column(
        JSON(), default=list, server_default=text("(JSON_ARRAY())"), nullable=False
    )
    prerequisites: Mapped[list[str]] = mapped_column(
        JSON(), default=list, server_default=text("(JSON_ARRAY())"), nullable=False
    )
    result: Mapped[str] = mapped_column(Text(), default="", nullable=False)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    owner_claimable: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="0")
    collaboration_open: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="0")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="todo")
    created_by: Mapped[int] = mapped_column(ForeignKey("members.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())

    owner: Mapped[Member | None] = relationship(foreign_keys=[owner_id])
    creator: Mapped[Member] = relationship(foreign_keys=[created_by])
    collaborators: Mapped[list[Member]] = relationship(secondary=task_collaborators)
    depends_on_tasks: Mapped[list["Task"]] = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin=lambda: Task.id == task_dependencies.c.task_id,
        secondaryjoin=lambda: Task.id == task_dependencies.c.depends_on_task_id,
        order_by=lambda: Task.id,
    )


class ItemActivity(Base):
    __tablename__ = "item_activities"
    __table_args__ = (
        Index("ix_item_activities_root_created", "root_task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    root_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)

    root_task: Mapped[Task] = relationship(foreign_keys=[root_task_id])
    task: Mapped[Task | None] = relationship(foreign_keys=[task_id])
    author: Mapped[Member] = relationship(foreign_keys=[author_id])


class ItemFact(Base):
    __tablename__ = "item_facts"
    __table_args__ = (
        CheckConstraint("scope IN ('global','related')", name="ck_item_facts_scope"),
        Index("ix_item_facts_root_active", "root_task_id", "is_active", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    root_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    source_activity_id: Mapped[int | None] = mapped_column(
        ForeignKey("item_activities.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("members.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="1", nullable=False)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("item_facts.id", ondelete="SET NULL"), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    related_tasks: Mapped[list[Task]] = relationship(secondary=item_fact_tasks)
    source_activity: Mapped[ItemActivity | None] = relationship(foreign_keys=[source_activity_id])
    creator: Mapped[Member] = relationship(foreign_keys=[created_by])


class AIPlannerDailyUsage(Base):
    __tablename__ = "ai_planner_daily_usage"
    __table_args__ = (
        UniqueConstraint("member_id", "usage_date", name="uq_ai_planner_usage_member_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id", ondelete="CASCADE"))
    usage_date: Mapped[date] = mapped_column(Date())
    request_count: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    input_tokens: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    total_tokens: Mapped[int] = mapped_column(BigInteger(), default=0, server_default="0")
    knowledge_context_chars: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        CheckConstraint("source_type IN ('github','upload')", name="ck_knowledge_source_type"),
        CheckConstraint(
            "parse_status IN ('ready','truncated','failed','unparseable','removed')",
            name="ck_knowledge_parse_status",
        ),
        UniqueConstraint("source_key_hash", name="uq_knowledge_source_key_hash"),
        Index("ix_knowledge_source_active_status", "source_type", "source_name", "is_active", "parse_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_text: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_blob_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    git_commit_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now(), nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(20), nullable=False)
    parse_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, server_default="1", nullable=False)
