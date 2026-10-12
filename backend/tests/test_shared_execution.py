"""MySQL-backed regression coverage for the shared execution scene slice."""

import os
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, or_, select, update

from app.ai_planner import (
    PlannerFactExtractionGeneration,
    PlannerProviderError,
)
from app.db import SessionLocal
from app.models import (
    AIPlannerDailyUsage,
    ItemActivity,
    ItemFact,
    Member,
    Task,
    task_collaborators,
    task_dependencies,
)
from app.routers import ai_items, ai_planner as planner_router, tasks as tasks_router
from app.schemas import (
    AIItemFactExtractionOut,
    AIItemFactSuggestion,
    AIItemFactExtractionRequest,
    ContextFactsBatchIn,
    TaskCompleteCreate,
    TaskCreate,
    TaskProgressCreate,
    TaskUpdate,
)


class FakeFactProvider:
    def __init__(self, suggestions=None, failure=None):
        self.calls = 0
        self.context = ""
        self.suggestions = suggestions or []
        self.failure = failure

    def extract_facts(self, context: str) -> PlannerFactExtractionGeneration:
        self.calls += 1
        self.context = context
        if self.failure:
            raise self.failure
        return PlannerFactExtractionGeneration(
            extraction=AIItemFactExtractionOut(suggestions=self.suggestions),
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
        )


def expect_http(expected: int, callback) -> HTTPException:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == expected, (exc.status_code, exc.detail)
        return exc
    raise AssertionError(f"expected HTTP {expected}")


def create_task(db, admin, *, title, parent_id=None, owner_id=None,
                owner_claimable=False, collaborator_ids=None, dependencies=None, kind=None):
    task = tasks_router.create_task(
        TaskCreate(
            kind=kind,
            title=title,
            deliverable=f"{title}已完成并可核验。",
            parent_id=parent_id,
            owner_id=owner_id,
            owner_claimable=owner_claimable,
            collaborator_ids=collaborator_ids or [],
            collaboration_open=True,
            deadline=datetime.now() + timedelta(days=1),
            depends_on_task_ids=dependencies or [],
        ),
        current=admin,
        db=db,
    )
    return task.id


def current_fact_texts(db, root_id):
    return list(db.scalars(
        select(ItemFact.content)
        .where(ItemFact.root_task_id == root_id, ItemFact.is_active.is_(True))
        .order_by(ItemFact.created_at.asc(), ItemFact.id.asc())
    ).all())


def replace_fixture_facts(db, root_id, actor, contents):
    db.execute(
        update(ItemFact)
        .where(ItemFact.root_task_id == root_id, ItemFact.is_active.is_(True))
        .values(is_active=False)
    )
    db.flush()
    root = db.get(Task, root_id)
    for content in contents:
        tasks_router._create_item_fact(db, root, actor, content=content)
    db.commit()


def main() -> None:
    token = uuid.uuid4().hex[:12]
    root_ids: set[int] = set()
    child_ids: set[int] = set()
    fixture_member_ids: set[int] = set()

    try:
        with SessionLocal() as db:
            admin = db.scalar(select(Member).where(Member.email == "admin@example.com"))
            assert admin is not None and admin.status == "active"
            optional_root = tasks_router.create_task(
                TaskCreate(
                    title=f"Smoke optional deadline root {token}",
                    owner_id=admin.id,
                    owner_claimable=False,
                    deadline=None,
                ),
                current=admin,
                db=db,
            )
            root_ids.add(optional_root.id)
            assert optional_root.deadline is None
            optional_child = tasks_router.create_task(
                TaskCreate(
                    title=f"Smoke optional deadline child {token}",
                    parent_id=optional_root.id,
                    owner_claimable=True,
                    deadline=None,
                ),
                current=admin,
                db=db,
            )
            child_ids.add(optional_child.id)
            assert optional_child.deadline is None
            tasks_router.update_task(
                optional_root.id,
                TaskUpdate(deadline=datetime.now() + timedelta(days=2)),
                current=admin,
                db=db,
            )
            cleared_root = tasks_router.update_task(
                optional_root.id,
                TaskUpdate(deadline=None),
                current=admin,
                db=db,
            )
            assert cleared_root.deadline is None and db.get(Task, optional_root.id).deadline is None

            owner = Member(name="Smoke Owner", email=f"scene-owner-{token}@example.invalid", role="member", status="active")
            collaborator = Member(name="Smoke Collaborator", email=f"scene-collab-{token}@example.invalid", role="member", status="active")
            unrelated = Member(name="Smoke Outsider", email=f"scene-outsider-{token}@example.invalid", role="member", status="active")
            db.add_all([owner, collaborator, unrelated])
            db.commit()
            db.refresh(owner)
            db.refresh(collaborator)
            db.refresh(unrelated)
            fixture_member_ids.update((owner.id, collaborator.id, unrelated.id))

            # Standalone tasks use the existing claim, collaboration, progress,
            # completion, and activity history paths without becoming items.
            standalone_id = create_task(
                db,
                admin,
                title=f"Smoke 独立任务 {token}",
                kind="task",
                owner_claimable=True,
                collaborator_ids=[],
            )
            root_ids.add(standalone_id)
            standalone_wire = tasks_router.get_task(standalone_id, current=admin, db=db)
            assert standalone_wire.kind == "task" and standalone_wire.parent_id is None
            expect_http(
                400,
                lambda: tasks_router.create_task(
                    TaskCreate(
                        kind="task",
                        title="独立任务下不能再建分工",
                        parent_id=standalone_id,
                        owner_id=owner.id,
                        owner_claimable=False,
                    ),
                    current=admin,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                400,
                lambda: tasks_router.add_context_facts_batch(
                    standalone_id,
                    ContextFactsBatchIn(facts=["独立任务不产生事项信息"]),
                    current=admin,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                403,
                lambda: tasks_router.publish_task_progress(
                    standalone_id,
                    TaskProgressCreate(content="无关成员不能发布进展"),
                    current=unrelated,
                    db=db,
                ),
            )
            db.rollback()
            claimed_standalone = tasks_router.claim_task_owner(
                standalone_id, current=owner, db=db,
            )
            assert claimed_standalone.owner and claimed_standalone.owner.id == owner.id
            joined_standalone = tasks_router.join_task_collaboration(
                standalone_id, current=collaborator, db=db,
            )
            assert any(person.id == collaborator.id for person in joined_standalone.collaborators)
            standalone_progress = tasks_router.publish_task_progress(
                standalone_id,
                TaskProgressCreate(content="独立任务已有可见进展记录。"),
                current=collaborator,
                db=db,
            )
            assert standalone_progress.task.kind == "task"
            assert standalone_progress.task.status == "doing"
            assert standalone_progress.activity.root_task_id == standalone_id
            assert standalone_progress.activity.task_id == standalone_id
            assert [entry.id for entry in tasks_router.list_item_activities(
                standalone_id, current=collaborator, db=db,
            )] == [standalone_progress.activity.id]
            assert tasks_router.list_item_activities(
                standalone_id, current=unrelated, db=db,
            ) == []
            expect_http(
                403,
                lambda: tasks_router.complete_task(
                    standalone_id,
                    TaskCompleteCreate(result="协作者不能完成负责人任务"),
                    current=collaborator,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                400,
                lambda: tasks_router.complete_task(
                    standalone_id,
                    TaskCompleteCreate(result="不能同步到事项", sync_to_item=True),
                    current=owner,
                    db=db,
                ),
            )
            db.rollback()
            completed_standalone = tasks_router.complete_task(
                standalone_id,
                TaskCompleteCreate(result="独立任务结果已留痕。"),
                current=owner,
                db=db,
            )
            assert completed_standalone.task.kind == "task"
            assert completed_standalone.task.status == "done"
            assert completed_standalone.task.result == "独立任务结果已留痕。"
            assert completed_standalone.activity.root_task_id == standalone_id
            assert completed_standalone.activity.task_id == standalone_id
            standalone_context = tasks_router.get_task_context(
                standalone_id, current=admin, db=db,
            )
            assert standalone_context.root.kind == "task" and standalone_context.tasks == []
            assert {activity.id for activity in standalone_context.activity_page.items} == {
                standalone_progress.activity.id,
                completed_standalone.activity.id,
            }

            root_id = create_task(db, admin, title=f"Smoke 共享事项 {token}", owner_id=admin.id)
            root_ids.add(root_id)
            first_id = create_task(
                db,
                admin,
                title="确认来访时间与人数",
                parent_id=root_id,
                owner_claimable=True,
            )
            child_ids.add(first_id)
            second_id = create_task(
                db,
                admin,
                title="准备参观路线",
                parent_id=root_id,
                owner_id=collaborator.id,
                dependencies=[first_id],
            )
            child_ids.add(second_id)
            third_id = create_task(
                db,
                admin,
                title="准备展示设备",
                parent_id=root_id,
                owner_id=owner.id,
            )
            child_ids.add(third_id)

            detail_context = tasks_router.get_task_context(first_id, current=admin, db=db)
            assert detail_context.root.id == root_id
            assert detail_context.root.kind == "item"
            assert {task.id for task in detail_context.tasks} == {first_id, second_id, third_id}
            assert detail_context.activity_page.items == []
            assert not detail_context.activity_page.has_more

            first = tasks_router._get_task(db, first_id)
            first_wire = tasks_router._task_out(first)
            assert first_wire.kind == "task"
            assert first_wire.status == "todo" and not first_wire.blocked
            second_wire = tasks_router._task_out(tasks_router._get_task(db, second_id))
            assert second_wire.blocked is True
            assert [entry.id for entry in second_wire.blocked_by] == [first_id]
            expect_http(
                409,
                lambda: tasks_router.publish_task_progress(
                    second_id,
                    TaskProgressCreate(content="前置任务未完成时不能推进"),
                    current=collaborator,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                409,
                lambda: tasks_router.complete_task(
                    second_id,
                    TaskCompleteCreate(result="前置任务未完成时不能完成"),
                    current=collaborator,
                    db=db,
                ),
            )
            db.rollback()

            # Dependencies are limited to siblings, cannot self-reference, and cannot cycle.
            foreign_root_id = create_task(db, admin, title=f"Smoke 另一事项 {token}", owner_id=admin.id)
            root_ids.add(foreign_root_id)
            foreign_child_id = create_task(
                db, admin, title="另一事项分工", parent_id=foreign_root_id, owner_id=owner.id
            )
            child_ids.add(foreign_child_id)
            empty_root_id = create_task(db, admin, title=f"Smoke 无分工事项 {token}", owner_id=admin.id)
            root_ids.add(empty_root_id)
            tasks_router.update_task(empty_root_id, TaskUpdate(status="doing"), current=admin, db=db)
            tasks_router.sync_root_status(db, empty_root_id)
            assert db.get(Task, empty_root_id).status == "doing"

            standalone_member_task_id = create_task(
                db, admin, title="成员独立任务状态兼容", owner_id=owner.id
            )
            root_ids.add(standalone_member_task_id)
            tasks_router.update_task(
                standalone_member_task_id,
                TaskUpdate(status="doing"),
                current=owner,
                db=db,
            )
            assert db.get(Task, standalone_member_task_id).status == "doing"

            assert db.get(Task, root_id).status == "todo"
            expect_http(
                400,
                lambda: tasks_router.update_task(
                    second_id,
                    TaskUpdate(depends_on_task_ids=[foreign_child_id]),
                    current=admin,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                400,
                lambda: tasks_router.update_task(
                    first_id,
                    TaskUpdate(depends_on_task_ids=[first_id]),
                    current=admin,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                400,
                lambda: tasks_router.update_task(
                    first_id,
                    TaskUpdate(depends_on_task_ids=[second_id]),
                    current=admin,
                    db=db,
                ),
            )
            db.rollback()
            assert tasks_router._task_out(tasks_router._get_task(db, second_id)).blocked is True

            claimed = tasks_router.claim_task_owner(first_id, current=owner, db=db)
            assert claimed.owner and claimed.owner.id == owner.id
            assert claimed.status == "todo"  # Claiming is not progress.
            joined = tasks_router.join_task_collaboration(first_id, current=collaborator, db=db)
            assert any(person.id == collaborator.id for person in joined.collaborators)

            # First waiting-for-reply update moves child and root to doing atomically.
            first_progress = tasks_router.publish_task_progress(
                first_id,
                TaskProgressCreate(content="已经联系对方老师，目前等待回复。"),
                current=owner,
                db=db,
            )
            assert first_progress.task.status == "doing"
            assert first_progress.activity.task_id == first_id
            assert first_progress.activity.root_task_id == root_id
            db.expire_all()
            assert db.get(Task, root_id).status == "doing"
            assert tasks_router._task_out(tasks_router._get_task(db, second_id)).blocked is True

            # Any active authorized contributor can request one extraction; no facts are auto-written.
            with patch.dict(os.environ, {"AI_PLANNER_ENABLED": "true", "AI_API_KEY": "test", "AI_MODEL": "test"}):
                no_fact_provider = FakeFactProvider()
                no_facts = ai_items.extract_activity_facts(
                    root_id,
                    AIItemFactExtractionRequest(activity_id=first_progress.activity.id),
                    current=owner,
                    db=db,
                    provider=no_fact_provider,
                )
                assert no_fact_provider.calls == 1 and no_facts.suggestions == []
                assert current_fact_texts(db, root_id) == []

                # A second authorized task participant may request the same root-scoped extraction.
                collaborator_provider = FakeFactProvider()
                collaborator_no_facts = ai_items.extract_activity_facts(
                    root_id,
                    AIItemFactExtractionRequest(activity_id=first_progress.activity.id),
                    current=collaborator,
                    db=db,
                    provider=collaborator_provider,
                )
                assert collaborator_provider.calls == 1 and collaborator_no_facts.suggestions == []

                # Subsequent update by a collaborator keeps doing, and the timeline links to the child.
                confirmed = "已确认周三 14:00 到达，一教 109，预计 20 人，从东门进入。"
                second_progress = tasks_router.publish_task_progress(
                    first_id,
                    TaskProgressCreate(content=confirmed),
                    current=collaborator,
                    db=db,
                )
                assert second_progress.task.status == "doing"
                assert second_progress.activity.task_id == first_id

                for index in range(6):
                    db.add(ItemActivity(
                        root_task_id=root_id,
                        author_id=admin.id,
                        content=f"分页测试动态 {index}",
                    ))
                db.commit()
                paged_context = tasks_router.get_task_context(first_id, current=admin, db=db)
                assert len(paged_context.activity_page.items) == 5
                assert paged_context.activity_page.has_more
                assert paged_context.activity_page.next_before_id == paged_context.activity_page.items[-1].id
                first_page = tasks_router.list_item_activities_page(
                    root_id, limit=3, current=admin, db=db,
                )
                assert len(first_page.items) == 3 and first_page.has_more
                second_page = tasks_router.list_item_activities_page(
                    root_id, limit=3, before_id=first_page.next_before_id, current=admin, db=db,
                )
                assert len(second_page.items) == 3
                assert not ({activity.id for activity in first_page.items} & {activity.id for activity in second_page.items})

                suggestions = [
                    AIItemFactSuggestion(text="来访时间为周三 14:00。", reason="更新明确写明到达时间。", scope="global", related_task_ids=[], supersedes_fact_id=None),
                    AIItemFactSuggestion(text="来访地点为一教 109。", reason="更新明确写明地点。", scope="global", related_task_ids=[], supersedes_fact_id=None),
                    AIItemFactSuggestion(text="预计来访人数为 20 人。", reason="更新明确写明人数。", scope="global", related_task_ids=[], supersedes_fact_id=None),
                ]
                fact_provider = FakeFactProvider(suggestions=suggestions)
                extracted = ai_items.extract_activity_facts(
                    root_id,
                    AIItemFactExtractionRequest(activity_id=second_progress.activity.id),
                    current=collaborator,
                    db=db,
                    provider=fact_provider,
                )
                assert fact_provider.calls == 1 and len(extracted.suggestions) == 3
                assert owner.name not in fact_provider.context and owner.email not in fact_provider.context
                assert collaborator.name not in fact_provider.context and collaborator.email not in fact_provider.context
                assert current_fact_texts(db, root_id) == []  # Suggestions require human confirmation.

                outsider_provider = FakeFactProvider(suggestions=suggestions)
                expect_http(
                    403,
                    lambda: ai_items.extract_activity_facts(
                        root_id,
                        AIItemFactExtractionRequest(activity_id=second_progress.activity.id),
                        current=unrelated,
                        db=db,
                        provider=outsider_provider,
                    ),
                )
                assert outsider_provider.calls == 0

                outsider_activity = ItemActivity(
                    root_task_id=root_id,
                    task_id=first_id,
                    author_id=unrelated.id,
                    content="由测试夹具模拟的无权限活动",
                )
                db.add(outsider_activity)
                db.commit()
                outsider_participant_provider = FakeFactProvider(suggestions=suggestions)
                expect_http(
                    403,
                    lambda: ai_items.extract_activity_facts(
                        root_id,
                        AIItemFactExtractionRequest(activity_id=outsider_activity.id),
                        current=unrelated,
                        db=db,
                        provider=outsider_participant_provider,
                    ),
                )
                assert outsider_participant_provider.calls == 0

                # Provider failure happens after the saved progress and does not undo it.
                failure_progress = tasks_router.publish_task_progress(
                    first_id,
                    TaskProgressCreate(content="正在继续跟进，还没有收到最终回复。"),
                    current=owner,
                    db=db,
                )
                failure_provider = FakeFactProvider(failure=PlannerProviderError("synthetic"))
                expect_http(
                    503,
                    lambda: ai_items.extract_activity_facts(
                        root_id,
                        AIItemFactExtractionRequest(activity_id=failure_progress.activity.id),
                        current=owner,
                        db=db,
                        provider=failure_provider,
                    ),
                )
                assert failure_provider.calls == 1
                db.expire_all()
            assert db.get(ItemActivity, failure_progress.activity.id) is not None
            assert db.get(Task, first_id).status == "doing"
            usage_date = planner_router._usage_date()
            owner_usage = db.scalar(
                select(AIPlannerDailyUsage.request_count).where(
                    AIPlannerDailyUsage.member_id == owner.id,
                    AIPlannerDailyUsage.usage_date == usage_date,
                )
            )
            collaborator_usage = db.scalar(
                select(AIPlannerDailyUsage.request_count).where(
                    AIPlannerDailyUsage.member_id == collaborator.id,
                    AIPlannerDailyUsage.usage_date == usage_date,
                )
            )
            assert owner_usage == 2 and collaborator_usage == 2

            # Exact duplicate is ignored, additions are atomic, and capacity is enforced.
            tasks_router.add_context_facts_batch(
                root_id,
                ContextFactsBatchIn(facts=[suggestions[0].text, suggestions[1].text, suggestions[0].text]),
                current=collaborator,
                db=db,
            )
            root = db.get(Task, root_id)
            assert current_fact_texts(db, root_id) == [suggestions[0].text, suggestions[1].text]
            tasks_router.add_context_facts_batch(
                root_id,
                ContextFactsBatchIn(facts=[suggestions[0].text]),
                current=collaborator,
                db=db,
            )
            assert current_fact_texts(db, root_id) == [suggestions[0].text, suggestions[1].text]

            replace_fixture_facts(db, root_id, owner, [f"已确认事项 {index}" for index in range(28)])
            tasks_router.add_context_facts_batch(
                root_id,
                ContextFactsBatchIn(facts=["新增事实甲", "新增事实甲", "新增事实乙"]),
                current=owner,
                db=db,
            )
            assert len(current_fact_texts(db, root_id)) == 30
            expect_http(
                409,
                lambda: tasks_router.add_context_facts_batch(
                    root_id,
                    ContextFactsBatchIn(facts=["超额事实一", "超额事实二"]),
                    current=owner,
                    db=db,
                ),
            )
            db.rollback()
            assert len(current_fact_texts(db, root_id)) == 30
            try:
                ContextFactsBatchIn(facts=[f"fact {index}" for index in range(31)])
            except ValidationError:
                pass
            else:
                raise AssertionError("batch API must reject more than 30 submitted facts")
            try:
                ContextFactsBatchIn(facts=["x" * 501])
            except ValidationError:
                pass
            else:
                raise AssertionError("batch API must reject facts longer than 500 characters")

            replace_fixture_facts(db, root_id, owner, [])

            # Unrelated active members retain task-structure read access but
            # only see global history, not task-scoped execution history.
            assert tasks_router.get_task(second_id, current=unrelated, db=db).id == second_id
            activities = tasks_router.list_item_activities(root_id, current=unrelated, db=db)
            assert all(activity.task_id != first_id for activity in activities)
            expect_http(
                403,
                lambda: tasks_router.publish_task_progress(
                    third_id,
                    TaskProgressCreate(content="越权进展"),
                    current=unrelated,
                    db=db,
                ),
            )
            db.rollback()
            expect_http(
                403,
                lambda: tasks_router.add_context_facts_batch(
                    root_id,
                    ContextFactsBatchIn(facts=["越权信息"]),
                    current=unrelated,
                    db=db,
                ),
            )
            db.rollback()

            # Collaborators can contribute progress but cannot complete someone else's task.
            expect_http(
                403,
                lambda: tasks_router.complete_task(
                    first_id,
                    TaskCompleteCreate(result="协作者不能单独完成"),
                    current=collaborator,
                    db=db,
                ),
            )
            db.rollback()

            # Complete saves result + status + linked activity + optional current fact in one commit.
            result = "来访时间、地点和人员安排已经全部确认。"
            completed = tasks_router.complete_task(
                first_id,
                TaskCompleteCreate(result=result, sync_to_item=True),
                current=owner,
                db=db,
            )
            assert completed.task.status == "done" and completed.task.result == result
            assert completed.task.deliverable == "确认来访时间与人数已完成并可核验。"
            assert completed.task.execution_points == []
            assert completed.task.cautions == [] and completed.task.prerequisites == []
            assert completed.activity.task_id == first_id
            assert result in current_fact_texts(db, root_id)
            assert tasks_router._task_out(tasks_router._get_task(db, second_id)).blocked is False
            db.expire_all()
            assert db.get(Task, root_id).status == "doing"
            expect_http(
                409,
                lambda: tasks_router.publish_task_progress(
                    first_id,
                    TaskProgressCreate(content="完成后不可再发布"),
                    current=owner,
                    db=db,
                ),
            )
            db.rollback()

            # Completion overflow rolls back result, status, activity and root facts together.
            overflow_id = create_task(db, admin, title="原子完成校验", parent_id=root_id, owner_id=owner.id)
            child_ids.add(overflow_id)
            replace_fixture_facts(db, root_id, owner, [f"上限事实 {index}" for index in range(30)])
            before_activity_ids = {activity.id for activity in tasks_router.list_item_activities(root_id, current=owner, db=db)}
            expect_http(
                409,
                lambda: tasks_router.complete_task(
                    overflow_id,
                    TaskCompleteCreate(result="这条信息加入事项后会超限", sync_to_item=True),
                    current=owner,
                    db=db,
                ),
            )
            db.rollback()
            db.expire_all()
            assert db.get(Task, overflow_id).status == "todo" and db.get(Task, overflow_id).result == ""
            assert {activity.id for activity in tasks_router.list_item_activities(root_id, current=owner, db=db)} == before_activity_ids

            # Clear fixture facts, finish remaining work, then verify deterministic root aggregation.
            replace_fixture_facts(db, root_id, owner, [])
            tasks_router.complete_task(
                second_id,
                TaskCompleteCreate(result="参观路线已准备完成。"),
                current=collaborator,
                db=db,
            )
            assert "参观路线已准备完成。" not in current_fact_texts(db, root_id)
            tasks_router.complete_task(
                third_id,
                TaskCompleteCreate(result="展示设备已准备完成。"),
                current=owner,
                db=db,
            )
            tasks_router.complete_task(
                overflow_id,
                TaskCompleteCreate(result="原子校验任务完成。"),
                current=owner,
                db=db,
            )
            db.expire_all()
            assert db.get(Task, root_id).status == "done"

            # Admin status corrections are supported and always recompute root status.
            tasks_router.update_task(first_id, TaskUpdate(status="doing"), current=admin, db=db)
            assert db.get(Task, root_id).status == "doing"
            tasks_router.update_task(first_id, TaskUpdate(status="done"), current=admin, db=db)
            assert db.get(Task, root_id).status == "done"
            expect_http(
                403,
                lambda: tasks_router.update_task(root_id, TaskUpdate(status="doing"), current=owner, db=db),
            )
            db.rollback()

            print("Shared execution MySQL integration passed")

    finally:
        with SessionLocal() as cleanup:
            if child_ids:
                cleanup.execute(
                    delete(task_dependencies).where(
                        or_(
                            task_dependencies.c.task_id.in_(child_ids),
                            task_dependencies.c.depends_on_task_id.in_(child_ids),
                        )
                    )
                )
                cleanup.execute(delete(task_collaborators).where(task_collaborators.c.task_id.in_(child_ids)))
            if root_ids:
                cleanup.execute(delete(ItemActivity).where(ItemActivity.root_task_id.in_(root_ids)))
                cleanup.execute(delete(Task).where(Task.parent_id.in_(root_ids)))
                cleanup.execute(delete(Task).where(Task.id.in_(root_ids)))
            if fixture_member_ids:
                cleanup.execute(delete(AIPlannerDailyUsage).where(AIPlannerDailyUsage.member_id.in_(fixture_member_ids)))
                cleanup.execute(delete(Member).where(Member.id.in_(fixture_member_ids)))
            cleanup.commit()


if __name__ == "__main__":
    main()
