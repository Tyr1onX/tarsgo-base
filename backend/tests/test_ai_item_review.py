import hashlib
import os
from datetime import datetime, timezone
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai_planner import PlannerReviewGeneration
from app.db import SessionLocal
from app.auth import get_current_member
from app.db import get_db
from app.main import app
from app.models import AIPlannerDailyUsage, ItemActivity, ItemFact, KnowledgeDocument, Member, Task
from app.routers import ai_items, ai_planner
from app.schemas import (
    AIItemReviewOut,
    AIItemReviewSuggestion,
    AIItemReviewTaskProposal,
)


class FakeReviewProvider:
    def __init__(self, review: AIItemReviewOut):
        self.review_result = review
        self.calls = 0
        self.context = ""

    def review(self, context: str) -> PlannerReviewGeneration:
        self.calls += 1
        self.context = context
        return PlannerReviewGeneration(
            review=self.review_result,
            input_tokens=31,
            output_tokens=17,
            total_tokens=48,
        )


def _suggestion(kind, target_id, *, title, deliverable, execution_points):
    return AIItemReviewSuggestion(
        kind=kind,
        target_task_id=target_id,
        reason="本次已确认的信息要求调整当前方案。",
        proposed_task=AIItemReviewTaskProposal(
            title=title,
            deliverable=deliverable,
            execution_points=execution_points,
            cautions=["仅按本次明确要求执行。"],
            prerequisites=[],
        ),
    )


def expect_http(expected: int, callback, *, detail: str | None = None) -> None:
    try:
        callback()
    except HTTPException as exc:
        assert exc.status_code == expected, (exc.status_code, exc.detail)
        if detail is not None:
            assert exc.detail == detail, exc.detail
        return
    raise AssertionError(f"expected HTTP {expected}")


def main() -> None:
    with SessionLocal() as db:
        member = db.scalar(
            select(Member)
            .where(Member.role == "member", Member.status == "active")
            .order_by(Member.id)
            .limit(1)
        )
        assert member
        admin = Member(
            name="Review 测试管理员",
            email="ai-review-admin@example.com",
            password_hash=None,
            role="admin",
            status="active",
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        os.environ.update({
            "AI_PLANNER_ENABLED": "true",
            "AI_API_KEY": "ci-placeholder",
            "AI_MODEL": "ci-placeholder",
            "KNOWLEDGE_ENABLED": "true",
        })

        deadline = datetime(2026, 10, 12, 18, 0)
        root = Task(
            kind="item",
            parent_id=None,
            title="测试事项：小学机器人科技展",
            deliverable="",
            owner_id=admin.id,
            owner_claimable=False,
            collaboration_open=False,
            deadline=deadline,
            status="doing",
            created_by=admin.id,
        )
        db.add(root)
        db.flush()
        db.add(ItemFact(
            root_task_id=root.id,
            content="主办方要求提前 20 分钟完成布展。",
            scope="global",
            created_by=admin.id,
            is_active=True,
        ))
        todo = Task(
            kind="task",
            parent_id=root.id,
            title="完成现场布展与设备运行确认",
            deliverable="展示设备按计划完成布置并可运行。",
            execution_points=["按活动流程完成布置"],
            cautions=["仅按本次明确要求执行。"],
            prerequisites=[],
            result="先前已完成场地初检。",
            owner_id=admin.id,
            owner_claimable=False,
            collaboration_open=True,
            collaborators=[member],
            deadline=datetime(2026, 10, 11, 18, 0),
            status="todo",
            created_by=admin.id,
        )
        done = Task(
            kind="task",
            parent_id=root.id,
            title="确认活动时间地点与主办方基础条件",
            deliverable="主办方已确认时间、地点及现场条件。",
            execution_points=[],
            cautions=[],
            prerequisites=[],
            result="主办方已确认时间、地点及现场条件。",
            owner_id=admin.id,
            owner_claimable=False,
            collaboration_open=False,
            deadline=deadline,
            status="done",
            created_by=admin.id,
        )
        db.add_all([todo, done])
        db.flush()
        activity = ItemActivity(
            root_task_id=root.id,
            author_id=admin.id,
            content=f"主办方当天要求提前 20 分钟完成布展；对接人 {admin.name} / {admin.email}。",
        )
        reminder_doc = KnowledgeDocument(
            source_type="github",
            source_name="team-operations",
            source_path="knowledge/playbooks/technology-exhibition.md",
            source_key_hash=hashlib.sha256(f"review-test-{root.id}".encode()).hexdigest(),
            title="科技展执行手册",
            content_text=(
                "## 科技展现场执行\n确保展示设备和物资交接清楚。\n"
                "## 可提醒事项\n本团队历史手册提到可考虑直播、宣传和战队周边。\n"
            ),
            content_hash=hashlib.sha256(b"review-fixture").hexdigest(),
            synced_at=datetime.now(timezone.utc).replace(tzinfo=None),
            parse_status="ready",
            is_active=True,
        )
        db.add_all([activity, reminder_doc])
        db.commit()
        root_id, todo_id, done_id, doc_id = root.id, todo.id, done.id, reminder_doc.id

        before_tasks = db.scalar(select(func.count(Task.id))) or 0
        before_activities = db.scalar(select(func.count(ItemActivity.id))) or 0
        original = db.get(Task, todo_id)
        original_state = {
            "title": original.title,
            "deliverable": original.deliverable,
            "execution_points": list(original.execution_points),
            "owner_id": original.owner_id,
            "status": original.status,
            "result": original.result,
            "deadline": original.deadline,
            "collaboration_open": original.collaboration_open,
            "owner_claimable": original.owner_claimable,
            "collaborators": [entry.id for entry in original.collaborators],
            "created_by": original.created_by,
        }
        update = _suggestion(
            "update_task",
            todo_id,
            title="完成现场布展与设备运行确认",
            deliverable="展示设备按计划完成布置并可运行。",
            execution_points=["按主办方要求提前 20 分钟完成布展", "确认展示设备可正常运行"],
        )
        duplicate_add = _suggestion(
            "add_task",
            None,
            title=todo.title,
            deliverable=todo.deliverable,
            execution_points=list(todo.execution_points),
        )
        new_add = _suggestion(
            "add_task",
            None,
            title="整理并提交活动总结材料",
            deliverable="活动总结已按主办方要求整理并提交。",
            execution_points=["汇总本次活动结果", "按主办方要求整理并提交材料"],
        )
        invalid_update = _suggestion(
            "update_task",
            99999999,
            title="不存在目标",
            deliverable="无",
            execution_points=[],
        )
        done_update = _suggestion(
            "update_task",
            done_id,
            title=done.title,
            deliverable="重新确认时间地点。",
            execution_points=[],
        )
        provider = FakeReviewProvider(
            AIItemReviewOut(
                summary="方案可以继续执行，有一项新要求需要纳入布展任务。",
                suggestions=[invalid_update, done_update, duplicate_add, update, new_add],
            )
        )
        result = ai_items.review_item_plan(root_id, current=admin, db=db, provider=provider)
        assert provider.calls == 1
        assert [item.kind for item in result.suggestions] == ["update_task", "add_task"]
        assert result.suggestions[0].target_task_id == todo_id
        assert (db.scalar(select(func.count(Task.id))) or 0) == before_tasks
        db.expire_all()
        unchanged = db.get(Task, todo_id)
        assert unchanged.title == original_state["title"]
        assert unchanged.execution_points == original_state["execution_points"]
        assert "主办方要求提前 20 分钟" in provider.context
        assert "先前已完成场地初检" in provider.context
        assert "当天要求提前 20 分钟" in provider.context
        assert "科技展执行手册" in provider.context
        assert "本团队历史手册提到可考虑直播" not in provider.context
        assert admin.name not in provider.context and admin.email not in provider.context
        assert "[成员]" in provider.context and "[邮箱]" in provider.context
        assert (db.scalar(select(func.count(ItemActivity.id))) or 0) == before_activities

        usage_date = ai_planner._usage_date()
        usage_before_apply = db.scalar(
            select(AIPlannerDailyUsage.request_count).where(
                AIPlannerDailyUsage.member_id == admin.id,
                AIPlannerDailyUsage.usage_date == usage_date,
            )
        )
        activity_count_before_apply = db.scalar(select(func.count(ItemActivity.id))) or 0
        applied_update = ai_items.apply_item_review_suggestion(
            root_id,
            result.suggestions[0],
            current=admin,
            db=db,
        )
        updated = applied_update.task
        assert updated.execution_points == ["按主办方要求提前 20 分钟完成布展", "确认展示设备可正常运行"]
        assert updated.title == original_state["title"]
        assert updated.owner and updated.owner.id == original_state["owner_id"]
        assert updated.status == original_state["status"]
        assert updated.result == original_state["result"]
        assert updated.deadline == original_state["deadline"]
        assert updated.collaboration_open == original_state["collaboration_open"]
        assert updated.owner_claimable == original_state["owner_claimable"]
        assert [entry.id for entry in updated.collaborators] == original_state["collaborators"]
        assert updated.created_by == original_state["created_by"]
        assert "根据方案检查调整任务" in applied_update.activity.content
        assert result.suggestions[0].reason not in applied_update.activity.content
        assert (db.scalar(select(func.count(ItemActivity.id))) or 0) == activity_count_before_apply + 1

        applied_add = ai_items.apply_item_review_suggestion(
            root_id,
            result.suggestions[1],
            current=admin,
            db=db,
        )
        new_task = applied_add.task
        assert new_task.parent_id == root_id
        assert new_task.status == "todo" and new_task.result == ""
        assert new_task.owner is None and new_task.owner_claimable
        assert not new_task.collaboration_open
        assert new_task.deadline == deadline
        assert "根据方案检查新增任务" in applied_add.activity.content
        assert (db.scalar(select(func.count(Task.id))) or 0) == before_tasks + 1

        atomic_candidate = _suggestion(
            "update_task",
            todo_id,
            title="完成现场布展与设备运行确认",
            deliverable="临时验证事务回滚。",
            execution_points=list(updated.execution_points),
        )
        activity_count_before_failed_apply = db.scalar(select(func.count(ItemActivity.id))) or 0
        try:
            with patch.object(db, "commit", side_effect=RuntimeError("simulated commit failure")):
                ai_items.apply_item_review_suggestion(
                    root_id,
                    atomic_candidate,
                    current=admin,
                    db=db,
                )
        except RuntimeError:
            pass
        else:
            raise AssertionError("apply should propagate a failed transaction")
        db.expire_all()
        assert db.get(Task, todo_id).deliverable == original_state["deliverable"]
        assert (db.scalar(select(func.count(ItemActivity.id))) or 0) == activity_count_before_failed_apply

        usage_after_apply = db.scalar(
            select(AIPlannerDailyUsage.request_count).where(
                AIPlannerDailyUsage.member_id == admin.id,
                AIPlannerDailyUsage.usage_date == usage_date,
            )
        )
        assert usage_before_apply == usage_after_apply

        expect_http(
            409,
            lambda: ai_items.apply_item_review_suggestion(
                root_id,
                done_update,
                current=admin,
                db=db,
            ),
        )
        expect_http(
            404,
            lambda: ai_items.apply_item_review_suggestion(
                root_id,
                _suggestion(
                "update_task", 99999999, title="外部任务", deliverable="不应修改。", execution_points=[]
                ),
                current=admin,
                db=db,
            ),
        )
        expect_http(
            403,
            lambda: ai_items.review_item_plan(root_id, current=member, db=db, provider=provider),
        )
        second_admin = Member(
            name="Review 第二管理员",
            email="ai-review-second-admin@example.com",
            password_hash=None,
            role="admin",
            status="active",
        )
        db.add(second_admin)
        db.commit()
        db.refresh(second_admin)
        second_admin_provider = FakeReviewProvider(
            AIItemReviewOut(summary="第二位管理员可检查当前方案。", suggestions=[])
        )
        second_admin_result = ai_items.review_item_plan(
            root_id,
            current=second_admin,
            db=db,
            provider=second_admin_provider,
        )
        assert second_admin_provider.calls == 1 and second_admin_result.suggestions == []
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_member] = lambda: member
        try:
            denied_apply = TestClient(app).post(
                f"/api/ai/items/{root_id}/review/apply",
                json=result.suggestions[0].model_dump(mode="json"),
            )
            assert denied_apply.status_code == 403, denied_apply.text
        finally:
            app.dependency_overrides.clear()
        expect_http(
            400,
            lambda: ai_items.review_item_plan(todo_id, current=admin, db=db, provider=provider),
        )

        empty_provider = FakeReviewProvider(AIItemReviewOut(summary="当前方案暂未发现需要调整的地方。", suggestions=[]))
        empty_result = ai_items.review_item_plan(root_id, current=admin, db=db, provider=empty_provider)
        assert empty_provider.calls == 1 and empty_result.suggestions == []

        usage = db.scalar(
            select(AIPlannerDailyUsage).where(
                AIPlannerDailyUsage.member_id == admin.id,
                AIPlannerDailyUsage.usage_date == usage_date,
            )
        )
        assert usage is not None
        usage.request_count = ai_planner.DAILY_REQUEST_LIMIT
        db.commit()
        denied_review_provider = FakeReviewProvider(
            AIItemReviewOut(summary="不应调用 provider。", suggestions=[])
        )
        expect_http(
            429,
            lambda: ai_items.review_item_plan(
                root_id,
                current=admin,
                db=db,
                provider=denied_review_provider,
            ),
            detail=ai_planner.DAILY_REQUEST_LIMIT_MESSAGE,
        )
        assert denied_review_provider.calls == 0

        # Test malformed forbidden proposal fields are rejected by the strict schema.
        try:
            AIItemReviewSuggestion.model_validate(
                {
                    "kind": "add_task",
                    "target_task_id": None,
                    "reason": "不应包含负责人字段",
                    "proposed_task": {
                        "title": "禁止字段",
                        "deliverable": "内容",
                        "execution_points": [],
                        "cautions": [],
                        "prerequisites": [],
                        "owner_id": admin.id,
                    },
                }
            )
        except Exception:
            pass
        else:
            raise AssertionError("AI review proposal must reject forbidden member/task fields")

        for row in db.scalars(select(ItemActivity).where(ItemActivity.root_task_id == root_id)).all():
            db.delete(row)
        for task in db.scalars(select(Task).where(Task.parent_id == root_id)).all():
            db.delete(task)
        db.flush()
        db.delete(db.get(Task, root_id))
        db.delete(db.get(KnowledgeDocument, doc_id))
        for usage in db.scalars(
            select(AIPlannerDailyUsage).where(AIPlannerDailyUsage.member_id.in_([admin.id, second_admin.id]))
        ).all():
            db.delete(usage)
        db.delete(second_admin)
        db.delete(admin)
        db.commit()
        assert db.scalar(select(func.count(Task.id))) == before_tasks - 3


if __name__ == "__main__":
    main()
