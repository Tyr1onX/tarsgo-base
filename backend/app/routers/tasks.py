from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, case, delete, or_, select, update
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_member, require_admin
from ..db import get_db
from ..models import ItemActivity, ItemFact, Member, Task, item_fact_tasks, task_collaborators, task_dependencies
from ..schemas import (
    ContextFactsBatchIn,
    TaskCompleteCreate,
    TaskDependencyOut,
    TaskProgressCreate,
    TaskProgressOut,
    ItemActivityCreate,
    ItemActivityOut,
    ItemActivityPageOut,
    ItemFactCreate,
    ItemFactOut,
    ItemFactScopeUpdate,
    ItemFactsBatchIn,
    MemberSummary,
    TaskAssigneeOut,
    TaskBatchCreate,
    TaskBatchOut,
    TaskCreate,
    TaskOut,
    TaskDetailContextOut,
    TaskUpdate,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


def _is_admin(member: Member) -> bool:
    return member.role == "admin"


def _task_query():
    return select(Task).options(
        selectinload(Task.owner),
        selectinload(Task.collaborators),
        selectinload(Task.depends_on_tasks).selectinload(Task.owner),
    )


def _is_task_blocked(task: Task) -> bool:
    return any(dependency.status != "done" for dependency in (task.depends_on_tasks or []))


def _activity_query():
    return select(ItemActivity).options(selectinload(ItemActivity.author))


def _fact_query():
    return select(ItemFact).options(
        selectinload(ItemFact.creator),
        selectinload(ItemFact.related_tasks),
    )


def _visible_facts(db: Session, root: Task, current: Member, task_id: int | None) -> list[ItemFact]:
    if root.kind != "item":
        return []
    query = _fact_query().where(ItemFact.root_task_id == root.id, ItemFact.is_active.is_(True))
    if _is_admin(current) or root.owner_id == current.id:
        return list(db.scalars(query.order_by(ItemFact.created_at.asc(), ItemFact.id.asc())).unique().all())
    if task_id is not None and task_id != root.id:
        is_participant = db.scalar(
            select(Task.id).where(
                Task.id == task_id,
                Task.parent_id == root.id,
                or_(Task.owner_id == current.id, Task.collaborators.any(Member.id == current.id)),
            )
        ) is not None
        if is_participant:
            query = query.where(
                or_(ItemFact.scope == "global", ItemFact.related_tasks.any(Task.id == task_id))
            )
        else:
            query = query.where(ItemFact.scope == "global")
    else:
        participating_ids = list(db.scalars(
            select(Task.id)
            .where(
                Task.parent_id == root.id,
                or_(Task.owner_id == current.id, Task.collaborators.any(Member.id == current.id)),
            )
        ).all())
        if participating_ids:
            query = query.where(
                or_(ItemFact.scope == "global", ItemFact.related_tasks.any(Task.id.in_(participating_ids)))
            )
        else:
            query = query.where(ItemFact.scope == "global")
    return list(db.scalars(query.order_by(ItemFact.created_at.asc(), ItemFact.id.asc())).unique().all())


def _fact_out(fact: ItemFact) -> ItemFactOut:
    return ItemFactOut(
        id=fact.id,
        root_task_id=fact.root_task_id,
        content=fact.content,
        scope=fact.scope,
        related_tasks=[{"id": task.id, "title": task.title} for task in fact.related_tasks],
        source_activity_id=fact.source_activity_id,
        created_by={"id": fact.creator.id, "name": fact.creator.name},
        created_at=fact.created_at,
        superseded_by_id=fact.superseded_by_id,
    )


def _task_out(task: Task, db: Session | None = None, current: Member | None = None) -> TaskOut:
    facts: list[ItemFact] = []
    if db is not None and current is not None:
        root = task if task.parent_id is None else db.get(Task, task.parent_id)
        if root is not None:
            facts = _visible_facts(db, root, current, task.id if task.parent_id is not None else None)
    item_facts = [_fact_out(fact) for fact in facts]
    return TaskOut(
        id=task.id,
        kind=task.kind,
        parent_id=task.parent_id,
        title=task.title,
        deliverable=task.deliverable,
        execution_points=task.execution_points or [],
        cautions=task.cautions or [],
        prerequisites=task.prerequisites or [],
        item_facts=item_facts,
        context_facts=[fact.content for fact in item_facts],
        result=task.result or "",
        owner=MemberSummary.model_validate(task.owner) if task.owner else None,
        owner_claimable=task.owner_claimable,
        collaborators=[MemberSummary.model_validate(member) for member in task.collaborators],
        collaboration_open=task.collaboration_open,
        deadline=task.deadline,
        status=task.status,
        created_by=task.created_by,
        created_at=task.created_at,
        depends_on_tasks=[
            TaskDependencyOut(
                id=dependency.id,
                title=dependency.title,
                status=dependency.status,
                owner=MemberSummary.model_validate(dependency.owner) if dependency.owner else None,
            )
            for dependency in (task.depends_on_tasks or [])
        ],
        blocked=_is_task_blocked(task),
        blocked_by=[
            TaskDependencyOut(
                id=dependency.id,
                title=dependency.title,
                status=dependency.status,
                owner=MemberSummary.model_validate(dependency.owner) if dependency.owner else None,
            )
            for dependency in (task.depends_on_tasks or [])
            if dependency.status != "done"
        ],
    )


def _activity_out(activity: ItemActivity) -> ItemActivityOut:
    return ItemActivityOut(
        id=activity.id,
        root_task_id=activity.root_task_id,
        task_id=activity.task_id,
        author=MemberSummary.model_validate(activity.author),
        content=activity.content,
        created_at=activity.created_at,
    )


def _load_active_members(db: Session, member_ids: set[int]) -> dict[int, Member]:
    if not member_ids:
        return {}
    members = {
        member.id: member
        for member in db.scalars(select(Member).where(Member.id.in_(member_ids), Member.status == "active"))
    }
    if members.keys() != member_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="负责人或协作者不存在或未激活")
    return members


def _get_task(db: Session, task_id: int) -> Task:
    task = db.scalar(_task_query().where(Task.id == task_id))
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return task


def _get_root_task(db: Session, task_id: int) -> Task:
    task = _get_task(db, task_id)
    if task.parent_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="事项动态只能挂在事项上")
    return task


def _root_for_task(db: Session, task: Task) -> Task:
    return task if task.parent_id is None else _get_root_task(db, task.parent_id)


def _can_write_item(db: Session, root: Task, current: Member) -> bool:
    if _is_admin(current) or root.owner_id == current.id:
        return True
    child_id = db.scalar(
        select(Task.id)
        .where(
            Task.parent_id == root.id,
            or_(
                Task.owner_id == current.id,
                Task.collaborators.any(Member.id == current.id),
            ),
        )
        .limit(1)
    )
    return child_id is not None


def _require_item_writer(db: Session, root: Task, current: Member) -> None:
    if root.kind != "item":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="独立任务不支持事项信息")
    if not _can_write_item(db, root, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有事项参与者可以更新事项信息")


def _require_fact_scope_editor(root: Task, current: Member) -> None:
    if not _is_admin(current) and root.owner_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有管理员或事项负责人可以调整当前信息范围")


def _validate_fact_tasks(db: Session, root: Task, scope: str, related_task_ids: list[int]) -> list[Task]:
    if scope == "global":
        if related_task_ids:
            raise HTTPException(status_code=422, detail="整个事项信息不需要选择具体分工")
        return []
    if not related_task_ids:
        raise HTTPException(status_code=422, detail="请选择至少一项相关分工")
    if len(related_task_ids) != len(set(related_task_ids)):
        raise HTTPException(status_code=422, detail="相关分工不能重复")
    tasks = list(db.scalars(
        select(Task).where(Task.id.in_(related_task_ids), Task.parent_id == root.id)
    ).all())
    if {task.id for task in tasks} != set(related_task_ids):
        raise HTTPException(status_code=422, detail="只能关联当前事项下的执行任务")
    return tasks


def _create_item_fact(
    db: Session,
    root: Task,
    current: Member,
    *,
    content: str,
    scope: str = "global",
    related_task_ids: list[int] | None = None,
    source_activity_id: int | None = None,
    supersedes_fact_id: int | None = None,
) -> ItemFact:
    db.scalar(select(Task.id).where(Task.id == root.id).with_for_update())
    text = content.strip()
    if not text or len(text) > 500:
        raise HTTPException(status_code=422, detail="当前信息单条最多 500 字")
    related_task_ids = related_task_ids or []
    related_tasks = _validate_fact_tasks(db, root, scope, related_task_ids)
    if source_activity_id is not None:
        source = db.get(ItemActivity, source_activity_id)
        if source is None or source.root_task_id != root.id:
            raise HTTPException(status_code=422, detail="来源进展不属于当前事项")

    existing = list(db.scalars(select(ItemFact).where(ItemFact.root_task_id == root.id, ItemFact.is_active.is_(True))).all())
    if any(fact.content == text for fact in existing):
        raise HTTPException(status_code=409, detail="当前信息中已存在相同内容")

    previous = None
    if supersedes_fact_id is not None:
        _require_fact_scope_editor(root, current)
        previous = db.get(ItemFact, supersedes_fact_id)
        if previous is None or previous.root_task_id != root.id or not previous.is_active:
            raise HTTPException(status_code=409, detail="待更新的当前信息已变化，请刷新后重试")
    active_count = len(existing) - (1 if previous else 0)
    if active_count >= 30:
        raise HTTPException(status_code=409, detail="当前信息最多保留 30 条")

    fact = ItemFact(
        root_task_id=root.id,
        content=text,
        scope=scope,
        source_activity_id=source_activity_id,
        created_by=current.id,
        related_tasks=related_tasks,
    )
    db.add(fact)
    db.flush()
    if previous is not None:
        previous.is_active = False
        previous.superseded_by_id = fact.id
        previous.superseded_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return fact


def sync_root_status(db: Session, root_id: int) -> None:
    root = db.scalar(select(Task).where(Task.id == root_id).with_for_update())
    if root is None or root.parent_id is not None or root.kind != "item":
        return
    statuses = list(db.scalars(select(Task.status).where(Task.parent_id == root.id)).all())
    if not statuses:
        return
    if all(value == "todo" for value in statuses):
        root.status = "todo"
    elif all(value == "done" for value in statuses):
        root.status = "done"
    else:
        root.status = "doing"


def _can_write_task_progress(task: Task, current: Member) -> bool:
    return (
        _is_admin(current)
        or task.owner_id == current.id
        or any(member.id == current.id for member in task.collaborators)
    )


def _validate_task_dependencies(db: Session, task: Task, dependency_ids: list[int]) -> None:
    if task.parent_id is None:
        if dependency_ids:
            raise HTTPException(status_code=400, detail="事项本身不能设置分工依赖")
        task.depends_on_tasks = []
        return
    if task.id in dependency_ids:
        raise HTTPException(status_code=400, detail="分工不能依赖自己")
    if len(dependency_ids) != len(set(dependency_ids)):
        raise HTTPException(status_code=400, detail="前置分工不能重复")
    targets = list(
        db.scalars(
            select(Task).where(Task.id.in_(dependency_ids), Task.parent_id == task.parent_id)
        ).all()
    ) if dependency_ids else []
    if {target.id for target in targets} != set(dependency_ids):
        raise HTTPException(status_code=400, detail="前置分工必须属于同一事项")

    child_ids = set(db.scalars(select(Task.id).where(Task.parent_id == task.parent_id)).all())
    edges = db.execute(
        select(task_dependencies.c.task_id, task_dependencies.c.depends_on_task_id)
        .where(task_dependencies.c.task_id.in_(child_ids))
    ).all() if child_ids else []
    graph: dict[int, list[int]] = {child_id: [] for child_id in child_ids}
    for child_id, depends_on_id in edges:
        graph.setdefault(child_id, []).append(depends_on_id)
    graph[task.id] = list(dependency_ids)

    visiting: set[int] = set()
    visited: set[int] = set()

    def has_cycle(node: int) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(has_cycle(target) for target in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    if any(has_cycle(node) for node in graph):
        raise HTTPException(status_code=400, detail="分工依赖不能形成循环")
    task.depends_on_tasks = targets


def _validate_parent(db: Session, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = db.get(Task, parent_id)
    if not parent:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="父事项不存在")
    if parent.parent_id is not None or parent.kind != "item":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前阶段只支持一级分工")


def _validate_owner_state(owner_id: int | None, owner_claimable: bool) -> None:
    if owner_id is None and not owner_claimable:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="任务必须指定负责人或开放负责人认领")


def _build_task(db: Session, payload: TaskCreate, current: Member) -> Task:
    _validate_parent(db, payload.parent_id)
    _validate_owner_state(payload.owner_id, payload.owner_claimable)
    if payload.parent_id is not None and payload.kind not in (None, "task"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="事项不能作为分工创建")
    task_kind = "task" if payload.parent_id is not None else payload.kind or "item"

    member_ids = set(payload.collaborator_ids)
    if payload.owner_id is not None:
        member_ids.add(payload.owner_id)
    members = _load_active_members(db, member_ids)

    task = Task(
        kind=task_kind,
        parent_id=payload.parent_id,
        title=payload.title,
        deliverable=payload.deliverable,
        execution_points=payload.execution_points,
        cautions=payload.cautions,
        prerequisites=payload.prerequisites,
        owner_id=payload.owner_id,
        owner_claimable=payload.owner_claimable,
        collaboration_open=payload.collaboration_open,
        deadline=payload.deadline,
        status=payload.status,
        created_by=current.id,
    )
    task.collaborators = [
        members[member_id]
        for member_id in dict.fromkeys(payload.collaborator_ids)
        if member_id != payload.owner_id
    ]
    db.add(task)
    db.flush()
    _validate_task_dependencies(db, task, payload.depends_on_task_ids)
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(
    scope: str = Query(default="mine", pattern="^(mine|claimable|all)$"),
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> list[TaskOut]:
    query = _task_query()
    if scope == "mine":
        mine_filter = or_(Task.owner_id == current.id, Task.collaborators.any(Member.id == current.id))
        parent_ids = set(
            db.scalars(
                select(Task.parent_id)
                .where(Task.parent_id.is_not(None), mine_filter)
                .distinct()
            ).all()
        )
        query = query.where(or_(mine_filter, Task.id.in_(parent_ids)))
    elif scope == "claimable":
        claimable_filter = and_(
            Task.owner_id.is_(None),
            Task.owner_claimable.is_(True),
            Task.status != "done",
        )
        parent_ids = set(
            db.scalars(
                select(Task.parent_id)
                .where(Task.parent_id.is_not(None), claimable_filter)
                .distinct()
            ).all()
        )
        # Child assignments keep their owning item in the response as context.
        # The root is not made claimable by being included here; only rows that
        # satisfy claimable_filter are claim targets.
        query = query.where(or_(claimable_filter, Task.id.in_(parent_ids)))

    tasks = db.scalars(
        query.order_by(case((Task.deadline.is_(None), 1), else_=0), Task.deadline.asc(), Task.id.asc())
    ).unique().all()
    return [_task_out(task, db, current) for task in tasks]


@router.get("/assignees", response_model=list[TaskAssigneeOut])
def list_task_assignees(_: Member = Depends(require_admin), db: Session = Depends(get_db)) -> list[Member]:
    return list(db.scalars(select(Member).where(Member.status == "active").order_by(Member.name.asc(), Member.id.asc())))


@router.get("/{task_id}", response_model=TaskOut)
def get_task(
    task_id: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    return _task_out(_get_task(db, task_id), db, current)


def _visible_activity_query(
    db: Session,
    root: Task,
    current: Member,
    task_id: int | None,
):
    query = _activity_query().where(ItemActivity.root_task_id == root.id)
    if not _is_admin(current) and root.owner_id != current.id:
        if root.kind == "task":
            participant = task_id in (None, root.id) and _can_write_task_progress(root, current)
            return query.where(ItemActivity.task_id == root.id) if participant else query.where(ItemActivity.id < 0)
        related_source_ids = [value for value in db.scalars(
            select(ItemFact.source_activity_id).where(
                ItemFact.root_task_id == root.id,
                ItemFact.scope == "related",
                ItemFact.source_activity_id.is_not(None),
            )
        ).all() if value is not None]

        if task_id is not None:
            task = db.get(Task, task_id)
            if task is None or (task.parent_id != root.id and not (root.kind == "task" and task.id == root.id)):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="执行任务不存在")
            is_participant = db.scalar(select(Task.id).where(
                Task.id == task.id,
                or_(Task.owner_id == current.id, Task.collaborators.any(Member.id == current.id)),
            )) is not None
            participant_task_ids = [task.id] if is_participant else []
        else:
            participant_task_ids = list(db.scalars(select(Task.id).where(
                Task.parent_id == root.id,
                or_(Task.owner_id == current.id, Task.collaborators.any(Member.id == current.id)),
            )).all())

        fact_query = select(ItemFact.source_activity_id).where(ItemFact.root_task_id == root.id)
        if participant_task_ids:
            fact_query = fact_query.where(or_(
                ItemFact.scope == "global",
                ItemFact.related_tasks.any(Task.id.in_(participant_task_ids)),
            ))
        else:
            fact_query = fact_query.where(ItemFact.scope == "global")
        source_ids = [value for value in db.scalars(fact_query).all() if value is not None]

        visible = []
        if participant_task_ids:
            visible.append(ItemActivity.task_id.in_(participant_task_ids))
        root_activity = ItemActivity.task_id.is_(None)
        if related_source_ids:
            root_activity = and_(root_activity, ItemActivity.id.not_in(related_source_ids))
        visible.append(root_activity)
        if source_ids:
            visible.append(ItemActivity.id.in_(source_ids))
        query = query.where(or_(*visible))
    return query


@router.get("/{task_id}/context", response_model=TaskDetailContextOut)
def get_task_context(
    task_id: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskDetailContextOut:
    selected = _get_task(db, task_id)
    root = selected if selected.parent_id is None else _get_task(db, selected.parent_id)
    query = _task_query().where(or_(Task.id == root.id, Task.parent_id == root.id))
    related_tasks = db.scalars(
        query.order_by(case((Task.deadline.is_(None), 1), else_=0), Task.deadline.asc(), Task.id.asc())
    ).unique().all()
    activity_query = _visible_activity_query(
        db,
        root,
        current,
        None if selected.parent_id is None else selected.id,
    )
    activities = db.scalars(
        activity_query.order_by(ItemActivity.created_at.desc(), ItemActivity.id.desc()).limit(6)
    ).all()
    has_more = len(activities) > 5
    page_items = activities[:5]
    return TaskDetailContextOut(
        root=_task_out(root, db, current),
        tasks=[_task_out(task, db, current) for task in related_tasks if task.id != root.id],
        activity_page=ItemActivityPageOut(
            items=[_activity_out(activity) for activity in page_items],
            has_more=has_more,
            next_before_id=page_items[-1].id if has_more and page_items else None,
        ),
    )


@router.delete("/{root_task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_root_task(
    root_task_id: int,
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    root = db.scalar(select(Task).where(Task.id == root_task_id).with_for_update())
    if root is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="事项不存在")
    if root.parent_id is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能删除事项，不能单独删除分工")

    try:
        # The self-referencing tasks.parent_id FK intentionally has no cascade.
        # Delete children first; the existing FKs then cascade their associations,
        # while root-owned activities and facts cascade with the root row.
        db.execute(delete(Task).where(Task.parent_id == root.id))
        db.delete(root)
        db.commit()
    except Exception:
        db.rollback()
        raise


@router.get("/{root_task_id}/activities", response_model=list[ItemActivityOut])
def list_item_activities(
    root_task_id: int,
    task_id: Annotated[int | None, Query(gt=0)] = None,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> list[ItemActivityOut]:
    root = _get_root_task(db, root_task_id)
    query = _visible_activity_query(db, root, current, task_id)
    activities = db.scalars(query.order_by(ItemActivity.created_at.desc(), ItemActivity.id.desc())).all()
    return [_activity_out(activity) for activity in activities]


@router.get("/{root_task_id}/activities/page", response_model=ItemActivityPageOut)
def list_item_activities_page(
    root_task_id: int,
    task_id: Annotated[int | None, Query(gt=0)] = None,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
    before_id: Annotated[int | None, Query(gt=0)] = None,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ItemActivityPageOut:
    root = _get_root_task(db, root_task_id)
    query = _visible_activity_query(db, root, current, task_id)
    if before_id is not None:
        query = query.where(ItemActivity.id < before_id)
    activities = db.scalars(
        query.order_by(ItemActivity.created_at.desc(), ItemActivity.id.desc()).limit(limit + 1)
    ).all()
    has_more = len(activities) > limit
    items = activities[:limit]
    return ItemActivityPageOut(
        items=[_activity_out(activity) for activity in items],
        has_more=has_more,
        next_before_id=items[-1].id if has_more and items else None,
    )


@router.post("/{root_task_id}/activities", response_model=ItemActivityOut, status_code=status.HTTP_201_CREATED)
def create_item_activity(
    root_task_id: int,
    payload: ItemActivityCreate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> ItemActivityOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    activity = ItemActivity(root_task_id=root.id, author_id=current.id, content=payload.content)
    try:
        db.add(activity)
        if payload.add_to_context:
            db.flush()
            _create_item_fact(
                db, root, current,
                content=payload.content,
                scope=payload.fact_scope,
                related_task_ids=payload.related_task_ids,
                source_activity_id=activity.id,
            )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    db.expire(activity)
    saved = db.scalar(_activity_query().where(ItemActivity.id == activity.id))
    if saved is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="动态保存失败")
    return _activity_out(saved)


@router.post("/{task_id}/progress", response_model=TaskProgressOut, status_code=status.HTTP_201_CREATED)
def publish_task_progress(
    task_id: int,
    payload: TaskProgressCreate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskProgressOut:
    task = db.scalar(_task_query().where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if task.parent_id is None and task.kind != "task":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="事项不能发布任务进展")
    if task.status == "done":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已完成任务不能继续发布执行进展")
    if _is_task_blocked(task):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前置分工尚未完成，暂时不能推进该任务")
    if not _can_write_task_progress(task, current):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有任务负责人、协作者或管理员可以发布进展")

    root = task if task.parent_id is None else db.scalar(
        select(Task).where(Task.id == task.parent_id).with_for_update()
    )
    if root is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="所属事项不存在")
    if task.status == "todo":
        task.status = "doing"
    activity = ItemActivity(
        root_task_id=root.id,
        task_id=task.id,
        author_id=current.id,
        content=payload.content,
    )
    db.add(activity)
    sync_root_status(db, root.id)
    try:
        db.commit()
        db.refresh(activity)
    except Exception:
        db.rollback()
        raise
    saved_task = _get_task(db, task.id)
    saved_activity = db.scalar(_activity_query().where(ItemActivity.id == activity.id))
    if saved_activity is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="进展保存失败")
    return TaskProgressOut(task=_task_out(saved_task, db, current), activity=_activity_out(saved_activity))


@router.post("/{task_id}/complete", response_model=TaskProgressOut)
def complete_task(
    task_id: int,
    payload: TaskCompleteCreate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskProgressOut:
    task = db.scalar(_task_query().where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    if task.parent_id is None and task.kind != "task":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="事项不能通过完成任务操作结束")
    if not _is_admin(current) and task.owner_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有任务负责人可以完成任务")
    if task.status == "done":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="任务已经完成")
    if _is_task_blocked(task):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="前置分工尚未完成，暂时不能完成该任务")
    root = task if task.parent_id is None else db.scalar(
        select(Task).where(Task.id == task.parent_id).with_for_update()
    )
    if root is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="所属事项不存在")
    if payload.sync_to_item and root.kind != "item":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="独立任务结果不能同步到事项信息")
    if payload.sync_to_item and len(payload.result) > 500:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="同步到事项信息的结果最多 500 字")

    try:
        task.result = payload.result
        task.status = "done"
        activity = ItemActivity(
            root_task_id=root.id,
            task_id=task.id,
            author_id=current.id,
            content=f"完成任务「{task.title}」。",
        )
        db.add(activity)
        db.flush()
        duplicate_fact = db.scalar(select(ItemFact.id).where(
            ItemFact.root_task_id == root.id,
            ItemFact.is_active.is_(True),
            ItemFact.content == payload.result,
        )) if payload.sync_to_item else None
        if payload.sync_to_item and not duplicate_fact:
            _create_item_fact(
                db, root, current, content=payload.result, source_activity_id=activity.id
            )
        sync_root_status(db, root.id)
        db.commit()
        db.refresh(activity)
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    saved_task = _get_task(db, task.id)
    saved_activity = db.scalar(_activity_query().where(ItemActivity.id == activity.id))
    if saved_activity is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="任务完成记录保存失败")
    return TaskProgressOut(task=_task_out(saved_task, db, current), activity=_activity_out(saved_activity))


@router.post("/{root_task_id}/context-facts", response_model=TaskOut)
def add_context_fact(
    root_task_id: int,
    payload: ItemFactCreate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    _create_item_fact(
        db, root, current, content=payload.content, scope=payload.scope,
        related_task_ids=payload.related_task_ids,
        source_activity_id=payload.source_activity_id,
        supersedes_fact_id=payload.supersedes_fact_id,
    )
    db.commit()
    return _task_out(_get_task(db, root.id), db, current)


@router.post("/{root_task_id}/context-facts/batch", response_model=TaskOut)
def add_context_facts_batch(
    root_task_id: int,
    payload: ContextFactsBatchIn,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    try:
        existing = set(db.scalars(select(ItemFact.content).where(
            ItemFact.root_task_id == root.id, ItemFact.is_active.is_(True)
        )).all())
        for fact in dict.fromkeys(payload.facts):
            if fact not in existing:
                _create_item_fact(db, root, current, content=fact)
                existing.add(fact)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _task_out(_get_task(db, root.id), db, current)


@router.delete("/{root_task_id}/context-facts/{fact_index}", response_model=TaskOut)
def delete_context_fact(
    root_task_id: int,
    fact_index: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    _require_fact_scope_editor(root, current)
    facts = list(db.scalars(select(ItemFact).where(
        ItemFact.root_task_id == root.id, ItemFact.is_active.is_(True)
    ).order_by(ItemFact.created_at.asc(), ItemFact.id.asc())).all())
    if fact_index < 0 or fact_index >= len(facts):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="当前信息不存在")
    facts[fact_index].is_active = False
    db.commit()
    return _task_out(_get_task(db, root.id), db, current)


@router.post("/{root_task_id}/facts/batch", response_model=TaskOut)
def add_scoped_facts_batch(
    root_task_id: int,
    payload: ItemFactsBatchIn,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    try:
        for fact in payload.facts:
            _create_item_fact(
                db, root, current,
                content=fact.content,
                scope=fact.scope,
                related_task_ids=fact.related_task_ids,
                source_activity_id=fact.source_activity_id,
                supersedes_fact_id=fact.supersedes_fact_id,
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return _task_out(_get_task(db, root.id), db, current)


@router.patch("/{root_task_id}/facts/{fact_id}/scope", response_model=TaskOut)
def update_item_fact_scope(
    root_task_id: int,
    fact_id: int,
    payload: ItemFactScopeUpdate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    _require_fact_scope_editor(root, current)
    fact = db.get(ItemFact, fact_id)
    if fact is None or fact.root_task_id != root.id or not fact.is_active:
        raise HTTPException(status_code=404, detail="当前信息不存在")
    fact.related_tasks = _validate_fact_tasks(db, root, payload.scope, payload.related_task_ids)
    fact.scope = payload.scope
    db.commit()
    return _task_out(_get_task(db, root.id), db, current)


@router.delete("/{root_task_id}/facts/{fact_id}", response_model=TaskOut)
def deactivate_item_fact(
    root_task_id: int,
    fact_id: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    root = _get_root_task(db, root_task_id)
    _require_item_writer(db, root, current)
    _require_fact_scope_editor(root, current)
    fact = db.get(ItemFact, fact_id)
    if fact is None or fact.root_task_id != root.id or not fact.is_active:
        raise HTTPException(status_code=404, detail="当前信息不存在")
    fact.is_active = False
    db.commit()
    return _task_out(_get_task(db, root.id), db, current)


@router.post("/{task_id}/result-to-context", response_model=TaskOut)
def add_task_result_to_context(
    task_id: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = _get_task(db, task_id)
    root = _root_for_task(db, task)
    _require_item_writer(db, root, current)
    result = (task.result or "").strip()
    if not result:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="请先填写执行结果")
    activity = ItemActivity(
        root_task_id=root.id,
        author_id=current.id,
        content=f"任务「{task.title}」的执行结果已确认加入事项信息。",
    )
    try:
        db.add(activity)
        db.flush()
        duplicate = db.scalar(select(ItemFact.id).where(
            ItemFact.root_task_id == root.id, ItemFact.is_active.is_(True), ItemFact.content == result
        ))
        if not duplicate:
            _create_item_fact(db, root, current, content=result, source_activity_id=activity.id)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return _task_out(_get_task(db, root.id), db, current)


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, current: Member = Depends(require_admin), db: Session = Depends(get_db)) -> TaskOut:
    task = _build_task(db, payload, current)
    if task.parent_id is not None:
        sync_root_status(db, task.parent_id)
    db.commit()
    db.expire(task)
    return _task_out(_get_task(db, task.id), db, current)


@router.post("/batch", response_model=TaskBatchOut, status_code=status.HTTP_201_CREATED)
def create_task_batch(
    payload: TaskBatchCreate,
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> TaskBatchOut:
    try:
        root = _build_task(
            db,
            TaskCreate(
                title=payload.item.title,
                deliverable=payload.item.deliverable,
                owner_id=current.id,
                owner_claimable=False,
                collaborator_ids=[],
                collaboration_open=False,
                parent_id=None,
                deadline=payload.item.deadline,
                status="todo",
            ),
            current,
        )
        db.flush()

        children: list[Task] = []
        for child in payload.tasks:
            children.append(
                _build_task(
                    db,
                    TaskCreate(
                        title=child.title,
                        deliverable=child.deliverable,
                        execution_points=child.execution_points,
                        cautions=child.cautions,
                        prerequisites=child.prerequisites,
                        owner_id=None if child.owner_claimable else current.id,
                        owner_claimable=child.owner_claimable,
                        collaborator_ids=[],
                        collaboration_open=child.collaboration_open,
                        parent_id=root.id,
                        deadline=child.deadline,
                        status="todo",
                    ),
                    current,
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return TaskBatchOut(
        item=_task_out(_get_task(db, root.id), db, current),
        tasks=[_task_out(_get_task(db, child.id), db, current) for child in children],
    )


@router.patch("/{task_id}", response_model=TaskOut)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> TaskOut:
    task = _get_task(db, task_id)
    fields = payload.model_fields_set

    if not _is_admin(current):
        if task.owner_id != current.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有负责人可以更新任务状态和执行结果")
        has_child_tasks = task.parent_id is None and db.scalar(
            select(Task.id).where(Task.parent_id == task.id).limit(1)
        ) is not None
        if has_child_tasks and "status" in fields:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="事项状态由执行分工自动汇总")
        allowed_fields = {"status", "result"}
        if not fields or not fields.issubset(allowed_fields):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="普通成员只能更新自己负责任务的状态和执行结果")
        if "status" in fields:
            if payload.status is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="任务状态不能为空")
            task.status = payload.status
        if "result" in fields:
            if payload.result is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="执行结果不能为空")
            task.result = payload.result
        if "status" in fields and task.parent_id is not None:
            sync_root_status(db, task.parent_id)
        db.commit()
        db.expire(task)
        return _task_out(_get_task(db, task.id), db, current)

    required_non_null = {
        "title", "deliverable", "execution_points", "cautions", "prerequisites", "result",
        "collaborator_ids", "owner_claimable", "collaboration_open", "status",
    }
    if any(field in fields and getattr(payload, field) is None for field in required_non_null):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="任务字段不能设为空")

    resulting_owner_id = payload.owner_id if "owner_id" in fields else task.owner_id
    resulting_claimable = payload.owner_claimable if "owner_claimable" in fields else task.owner_claimable
    _validate_owner_state(resulting_owner_id, bool(resulting_claimable))

    if "owner_id" in fields and resulting_owner_id is not None:
        _load_active_members(db, {resulting_owner_id})

    for field in (
        "title", "deliverable", "execution_points", "cautions", "prerequisites", "result",
        "owner_claimable", "collaboration_open", "deadline", "status",
    ):
        if field in fields:
            setattr(task, field, getattr(payload, field))

    if "owner_id" in fields:
        task.owner_id = resulting_owner_id

    if "collaborator_ids" in fields:
        collaborator_ids = payload.collaborator_ids or []
        members = _load_active_members(db, set(collaborator_ids))
        task.collaborators = [
            members[member_id]
            for member_id in dict.fromkeys(collaborator_ids)
            if member_id != resulting_owner_id
        ]
    elif "owner_id" in fields and resulting_owner_id is not None:
        task.collaborators = [member for member in task.collaborators if member.id != resulting_owner_id]

    if "depends_on_task_ids" in fields:
        if payload.depends_on_task_ids is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="前置分工列表不能为空")
        _validate_task_dependencies(db, task, payload.depends_on_task_ids)

    if "status" in fields:
        root_id = task.parent_id or task.id
        sync_root_status(db, root_id)

    db.commit()
    db.expire(task)
    return _task_out(_get_task(db, task.id), db, current)


@router.post("/{task_id}/claim", response_model=TaskOut)
def claim_task_owner(task_id: int, current: Member = Depends(get_current_member), db: Session = Depends(get_db)) -> TaskOut:
    result = db.execute(
        update(Task)
        .where(Task.id == task_id, Task.owner_id.is_(None), Task.owner_claimable.is_(True), Task.status != "done")
        .values(owner_id=current.id)
    )
    if result.rowcount != 1:
        db.rollback()
        if db.get(Task, task_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该任务当前不可认领")

    db.execute(delete(task_collaborators).where(task_collaborators.c.task_id == task_id, task_collaborators.c.member_id == current.id))
    db.commit()
    db.expire(db.get(Task, task_id))
    return _task_out(_get_task(db, task_id), db, current)


@router.post("/{task_id}/unclaim", response_model=TaskOut)
def unclaim_task_owner(task_id: int, current: Member = Depends(get_current_member), db: Session = Depends(get_db)) -> TaskOut:
    task = _get_task(db, task_id)
    if task.owner_id != current.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有当前负责人可以取消认领")
    if task.status == "done":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已完成任务不能取消认领")
    if not task.owner_claimable:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该任务不是公开认领任务")
    task.owner_id = None
    db.commit()
    db.expire(task)
    return _task_out(_get_task(db, task_id), db, current)


@router.post("/{task_id}/collaborators/join", response_model=TaskOut)
def join_task_collaboration(task_id: int, current: Member = Depends(get_current_member), db: Session = Depends(get_db)) -> TaskOut:
    task = _get_task(db, task_id)
    if task.status == "done" or not task.collaboration_open:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该任务当前不开放协作")
    if task.owner_id == current.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="负责人无需重复加入协作")
    if all(member.id != current.id for member in task.collaborators):
        task.collaborators.append(current)
        db.commit()
        db.expire(task)
    return _task_out(_get_task(db, task_id), db, current)


@router.post("/{task_id}/collaborators/leave", response_model=TaskOut)
def leave_task_collaboration(task_id: int, current: Member = Depends(get_current_member), db: Session = Depends(get_db)) -> TaskOut:
    task = _get_task(db, task_id)
    if task.status == "done":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已完成任务不能退出协作")
    if not task.collaboration_open:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该任务未开放自主协作")
    task.collaborators = [member for member in task.collaborators if member.id != current.id]
    db.commit()
    db.expire(task)
    return _task_out(_get_task(db, task_id), db, current)
