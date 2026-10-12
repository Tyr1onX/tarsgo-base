from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_member, require_admin
from ..db import get_db
from ..models import (
    DailyLeaveEntry,
    DailyLeaveWindow,
    Member,
    SchoolLeaveGroupResult,
    SchoolLeaveRequest,
    SchoolLeaveRun,
)
from ..schemas import (
    AdminLeaveRecordOut,
    AdminLeaveRecordType,
    MemberSummary,
    SchoolLeaveAdminConfigOut,
    SchoolLeaveAdminSummaryOut,
    SchoolLeaveGroupMemberOut,
    SchoolLeaveGroupOut,
    SchoolLeaveGroupResultOut,
    SchoolLeaveReasonUpdate,
    SchoolLeaveRequestCreate,
    SchoolLeaveRequestOut,
    SchoolLeaveRequestUpdate,
    SchoolLeaveRunOut,
    SchoolLeaveRunStatus,
)
from ..school_leave import (
    SCHOOL_LEAVE_RESULT_MAX_BYTES,
    SCHOOL_LEAVE_RESULT_TTL,
    build_school_leave_docx,
    build_school_leave_run_docx,
    collect_pending_school_leave,
    delete_school_leave_result_file,
    format_school_leave_time,
    get_leave_contact_phone,
    get_leave_daily_cutoff,
    group_school_leave_requests,
    requests_for_run,
    school_leave_document_filename,
    school_leave_result_download_filename,
    school_leave_result_file_path,
    school_leave_run_document_filename,
    school_leave_now,
    store_school_leave_result_file,
    validate_school_leave_result_upload,
)


router = APIRouter(prefix="/api/school-leave", tags=["school-leave"])


def _result_out(result: SchoolLeaveGroupResult) -> SchoolLeaveGroupResultOut:
    now = school_leave_now()
    return SchoolLeaveGroupResultOut(
        original_filename=result.original_filename,
        mime_type=result.mime_type,
        size_bytes=result.size_bytes,
        uploaded_at=result.uploaded_at,
        expires_at=result.expires_at,
        deleted_at=result.deleted_at,
        available=result.deleted_at is None and result.expires_at > now,
    )


def _request_out(
    request: SchoolLeaveRequest,
    *,
    run_status: SchoolLeaveRunStatus | None = None,
    group_index: int | None = None,
    result_state: str | None = None,
) -> SchoolLeaveRequestOut:
    return SchoolLeaveRequestOut.model_validate(request).model_copy(
        update={
            "run_status": run_status,
            "group_index": group_index,
            "result_state": result_state,
        }
    )


def _run_groups(db: Session, run: SchoolLeaveRun):
    return group_school_leave_requests(requests_for_run(db, run.id))


def _run_out(db: Session, run: SchoolLeaveRun) -> SchoolLeaveRunOut:
    requests = requests_for_run(db, run.id)
    groups = group_school_leave_requests(requests)
    creator = db.get(Member, run.created_by) if run.created_by is not None else None
    downloader = db.get(Member, run.downloaded_by) if run.downloaded_by is not None else None
    results = {
        result.group_index: result
        for result in db.scalars(
            select(SchoolLeaveGroupResult).where(SchoolLeaveGroupResult.run_id == run.id)
        )
    }
    group_outputs = [
        SchoolLeaveGroupOut(
            index=group.index,
            start_at=group.start_at,
            end_at=group.end_at,
            time_text=format_school_leave_time(group.start_at, group.end_at),
            count=len(group.requests),
            members=[
                SchoolLeaveGroupMemberOut(
                    member_id=request.member_id,
                    name=request.member_name_snapshot,
                    student_id=request.student_id_snapshot,
                )
                for request in group.requests
            ],
            result=_result_out(results[group.index]) if group.index in results else None,
        )
        for group in groups
    ]
    return SchoolLeaveRunOut(
        id=run.id,
        collected_at=run.collected_at,
        created_by=MemberSummary.model_validate(creator) if creator else None,
        reason=run.reason,
        status=run.status,
        downloaded_at=run.downloaded_at,
        downloaded_by=MemberSummary.model_validate(downloader) if downloader else None,
        request_count=len(requests),
        member_count=len({request.member_id for request in requests}),
        groups=group_outputs,
        document_ready=bool(get_leave_contact_phone()),
    )


def _get_owned_request(
    db: Session,
    request_id: int,
    member_id: int,
    *,
    lock: bool = False,
) -> SchoolLeaveRequest:
    query = select(SchoolLeaveRequest).where(
        SchoolLeaveRequest.id == request_id,
        SchoolLeaveRequest.member_id == member_id,
    )
    if lock:
        query = query.with_for_update()
    request = db.scalar(query)
    if not request:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="请假申请不存在")
    return request


def _get_admin_run(db: Session, run_id: int, *, lock: bool = False) -> SchoolLeaveRun:
    query = select(SchoolLeaveRun).where(SchoolLeaveRun.id == run_id)
    if lock:
        query = query.with_for_update()
    run = db.scalar(query)
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="汇总批次不存在")
    return run


@router.get("/requests", response_model=list[SchoolLeaveRequestOut])
def list_my_requests(
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> list[SchoolLeaveRequestOut]:
    rows = db.execute(
        select(SchoolLeaveRequest, SchoolLeaveRun)
        .outerjoin(SchoolLeaveRun, SchoolLeaveRun.id == SchoolLeaveRequest.run_id)
        .where(SchoolLeaveRequest.member_id == current.id)
        .order_by(SchoolLeaveRequest.created_at.desc(), SchoolLeaveRequest.id.desc())
    ).all()
    outputs: list[SchoolLeaveRequestOut] = []
    now = school_leave_now()
    for request, run in rows:
        group_index = None
        result_state = None
        if run is not None and request.status == "included":
            for group in _run_groups(db, run):
                if any(item.id == request.id for item in group.requests):
                    group_index = group.index
                    break
            if run.status == "completed" and group_index is not None:
                result = db.scalar(
                    select(SchoolLeaveGroupResult).where(
                        SchoolLeaveGroupResult.run_id == run.id,
                        SchoolLeaveGroupResult.group_index == group_index,
                    )
                )
                if result is not None:
                    result_state = (
                        "available"
                        if result.deleted_at is None and result.expires_at > now
                        else "cleared"
                    )
        outputs.append(
            _request_out(
                request,
                run_status=run.status if run is not None else None,
                group_index=group_index,
                result_state=result_state,
            )
        )
    return outputs


@router.post("/requests", response_model=SchoolLeaveRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: SchoolLeaveRequestCreate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> SchoolLeaveRequestOut:
    if not current.student_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先完善学号，生成学校请假材料时需要使用。",
        )
    request = SchoolLeaveRequest(
        member_id=current.id,
        start_at=payload.start_at,
        end_at=payload.end_at,
        member_name_snapshot=current.name,
        student_id_snapshot=current.student_id,
        status="pending",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return _request_out(request)


@router.patch("/requests/{request_id}", response_model=SchoolLeaveRequestOut)
def update_request(
    request_id: int,
    payload: SchoolLeaveRequestUpdate,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> SchoolLeaveRequestOut:
    request = _get_owned_request(db, request_id, current.id, lock=True)
    if request.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该申请已汇总，不能直接修改")
    request.start_at = payload.start_at
    request.end_at = payload.end_at
    db.commit()
    db.refresh(request)
    return _request_out(request)


@router.post("/requests/{request_id}/withdraw", response_model=SchoolLeaveRequestOut)
def withdraw_request(
    request_id: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> SchoolLeaveRequestOut:
    request = _get_owned_request(db, request_id, current.id, lock=True)
    if request.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有待汇总申请可以撤回")
    request.status = "withdrawn"
    db.commit()
    db.refresh(request)
    return _request_out(request)


@router.get("/admin/config", response_model=SchoolLeaveAdminConfigOut)
def admin_config(
    _: Member = Depends(require_admin),
) -> SchoolLeaveAdminConfigOut:
    try:
        cutoff = get_leave_daily_cutoff()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return SchoolLeaveAdminConfigOut(
        daily_cutoff=cutoff,
        contact_phone_configured=bool(get_leave_contact_phone()),
    )


@router.get("/admin/summary", response_model=SchoolLeaveAdminSummaryOut)
def admin_summary(
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchoolLeaveAdminSummaryOut:
    counts = dict(
        db.execute(
            select(SchoolLeaveRun.status, func.count(SchoolLeaveRun.id))
            .where(SchoolLeaveRun.status.in_(("ready", "awaiting_return")))
            .group_by(SchoolLeaveRun.status)
        ).all()
    )
    ready_count = int(counts.get("ready", 0))
    awaiting_return_count = int(counts.get("awaiting_return", 0))
    return SchoolLeaveAdminSummaryOut(
        ready_count=ready_count,
        awaiting_return_count=awaiting_return_count,
        todo_count=ready_count + awaiting_return_count,
    )


@router.get("/admin/requests", response_model=list[SchoolLeaveRequestOut])
def admin_list_requests(
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[SchoolLeaveRequestOut]:
    requests = list(
        db.scalars(
            select(SchoolLeaveRequest).order_by(
                SchoolLeaveRequest.created_at.desc(),
                SchoolLeaveRequest.id.desc(),
            )
        )
    )
    return [_request_out(request) for request in requests]


@router.get("/admin/records", response_model=list[AdminLeaveRecordOut])
def admin_list_leave_records(
    name: str | None = Query(default=None, max_length=100),
    date_from: date | None = None,
    date_to: date | None = None,
    record_type: AdminLeaveRecordType | None = None,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[AdminLeaveRecordOut]:
    """Read the member-facing daily leave history without changing source records."""
    search_name = (name or "").strip()
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="开始日期不能晚于结束日期")
    if date_to == date.max:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="结束日期超出可查询范围")

    lower_bound = datetime.combine(date_from, time.min) if date_from is not None else None
    upper_bound = datetime.combine(date_to + timedelta(days=1), time.min) if date_to is not None else None
    search_pattern = None
    if search_name:
        escaped_name = search_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search_pattern = f"%{escaped_name}%"
    records: list[AdminLeaveRecordOut] = []

    if record_type in (None, "generated"):
        generated_filters = []
        if search_pattern is not None:
            generated_filters.append(DailyLeaveEntry.name_snapshot.ilike(search_pattern, escape="\\"))
        if lower_bound is not None:
            generated_filters.append(
                or_(
                    and_(DailyLeaveEntry.window_id.is_(None), DailyLeaveEntry.end_at >= lower_bound),
                    and_(DailyLeaveEntry.window_id.is_not(None), DailyLeaveWindow.end_at >= lower_bound),
                )
            )
        if upper_bound is not None:
            generated_filters.append(
                or_(
                    and_(DailyLeaveEntry.window_id.is_(None), DailyLeaveEntry.start_at < upper_bound),
                    and_(DailyLeaveEntry.window_id.is_not(None), DailyLeaveWindow.start_at < upper_bound),
                )
            )
        generated_rows = db.execute(
            select(DailyLeaveEntry, DailyLeaveWindow)
            .outerjoin(DailyLeaveWindow, DailyLeaveWindow.id == DailyLeaveEntry.window_id)
            .where(*generated_filters)
        ).all()
        for entry, window in generated_rows:
            start_at = window.start_at if window is not None else entry.start_at
            end_at = window.end_at if window is not None else entry.end_at
            if start_at is None or end_at is None:
                continue
            is_shared = window is not None
            records.append(
                AdminLeaveRecordOut(
                    id=f"generated:{entry.id}",
                    name=entry.name_snapshot,
                    student_id=entry.student_id_snapshot,
                    start_at=start_at,
                    end_at=end_at,
                    recorded_at=entry.submitted_at,
                    record_type="generated",
                    source_type="shared_activity" if is_shared else "self_service",
                    activity_title=window.title if window is not None else None,
                )
            )

    if record_type in (None, "formal_application"):
        request_filters = []
        if search_pattern is not None:
            request_filters.append(SchoolLeaveRequest.member_name_snapshot.ilike(search_pattern, escape="\\"))
        if lower_bound is not None:
            request_filters.append(SchoolLeaveRequest.end_at >= lower_bound)
        if upper_bound is not None:
            request_filters.append(SchoolLeaveRequest.start_at < upper_bound)
        request_rows = db.execute(
            select(SchoolLeaveRequest, SchoolLeaveRun)
            .outerjoin(SchoolLeaveRun, SchoolLeaveRun.id == SchoolLeaveRequest.run_id)
            .where(*request_filters)
        ).all()
        for request, run in request_rows:
            records.append(
                AdminLeaveRecordOut(
                    id=f"application:{request.id}",
                    name=request.member_name_snapshot,
                    student_id=request.student_id_snapshot,
                    start_at=request.start_at,
                    end_at=request.end_at,
                    recorded_at=request.created_at,
                    record_type="formal_application",
                    source_type="legacy_application",
                    activity_title=run.reason if run is not None else None,
                    activity_at=run.collected_at if run is not None else None,
                    application_status=request.status,
                    summary_status=run.status if run is not None else None,
                )
            )

    records.sort(key=lambda record: (record.recorded_at, record.id), reverse=True)
    return records


@router.get("/admin/runs", response_model=list[SchoolLeaveRunOut])
def admin_list_runs(
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[SchoolLeaveRunOut]:
    runs = list(
        db.scalars(
            select(SchoolLeaveRun).order_by(
                SchoolLeaveRun.collected_at.desc(),
                SchoolLeaveRun.id.desc(),
            )
        )
    )
    return [_run_out(db, run) for run in runs]


@router.post("/admin/runs/collect", response_model=SchoolLeaveRunOut | None)
def admin_collect(
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchoolLeaveRunOut | None:
    run = collect_pending_school_leave(db, created_by=current.id)
    return _run_out(db, run) if run else None


@router.patch("/admin/runs/{run_id}/reason", response_model=SchoolLeaveRunOut)
def update_run_reason(
    run_id: int,
    payload: SchoolLeaveReasonUpdate,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchoolLeaveRunOut:
    run = _get_admin_run(db, run_id, lock=True)
    if run.status != "ready":
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有待下载批次可以修改事由")
    run.reason = payload.reason
    db.commit()
    db.refresh(run)
    return _run_out(db, run)


@router.post("/admin/runs/{run_id}/cancel", response_model=SchoolLeaveRunOut)
def cancel_run(
    run_id: int,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchoolLeaveRunOut:
    try:
        run = _get_admin_run(db, run_id, lock=True)
        if run.status != "ready":
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="只有待下载批次可以取消")
        requests = list(
            db.scalars(
                select(SchoolLeaveRequest)
                .where(
                    SchoolLeaveRequest.run_id == run.id,
                    SchoolLeaveRequest.status == "included",
                )
                .order_by(SchoolLeaveRequest.id)
                .with_for_update()
            )
        )
        for request in requests:
            request.status = "pending"
            request.run_id = None
        run.status = "cancelled"
        db.commit()
        db.refresh(run)
        return _run_out(db, run)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


@router.delete("/admin/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_run_history(
    run_id: int,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    try:
        run = _get_admin_run(db, run_id, lock=True)
        if run.status not in {"completed", "cancelled"}:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="只有已完成或已取消记录可以删除",
            )
        results = list(
            db.scalars(
                select(SchoolLeaveGroupResult)
                .where(SchoolLeaveGroupResult.run_id == run.id)
                .order_by(SchoolLeaveGroupResult.id)
                .with_for_update()
            )
        )
        linked_requests = list(
            db.scalars(
                select(SchoolLeaveRequest)
                .where(SchoolLeaveRequest.run_id == run.id)
                .order_by(SchoolLeaveRequest.id)
                .with_for_update()
            )
        )
        if results:
            db.execute(
                delete(SchoolLeaveGroupResult).where(
                    SchoolLeaveGroupResult.id.in_([result.id for result in results])
                )
            )
        if linked_requests:
            db.execute(
                delete(SchoolLeaveRequest).where(
                    SchoolLeaveRequest.id.in_([request.id for request in linked_requests])
                )
            )
        db.delete(run)
        db.commit()
        for result in results:
            delete_school_leave_result_file(result.stored_name)
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise


def _document_context(
    db: Session,
    run_id: int,
) -> tuple[SchoolLeaveRun, list]:
    run = _get_admin_run(db, run_id)
    if run.status == "cancelled":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="已取消批次不能生成材料")
    contact_phone = get_leave_contact_phone()
    if not contact_phone:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LEAVE_CONTACT_PHONE 未配置，暂时不能生成学校请假材料",
        )
    groups = group_school_leave_requests(requests_for_run(db, run.id))
    if not groups:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该批次没有可生成的请假材料")
    return run, groups


@router.get("/admin/runs/{run_id}/documents/{group_index}")
def download_document(
    run_id: int,
    group_index: int,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    run, groups = _document_context(db, run_id)
    group = next((item for item in groups if item.index == group_index), None)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="时间组不存在")
    content = build_school_leave_docx(run, group, contact_phone=get_leave_contact_phone())
    filename = school_leave_document_filename(group)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/admin/runs/{run_id}/document")
def download_run_document(
    run_id: int,
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    run, groups = _document_context(db, run_id)
    content = build_school_leave_run_docx(
        run,
        groups,
        contact_phone=get_leave_contact_phone(),
    )
    filename = school_leave_run_document_filename(db, run)
    if run.status == "ready":
        run.status = "awaiting_return"
        run.downloaded_at = school_leave_now()
        run.downloaded_by = current.id
        db.commit()
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/admin/runs/{run_id}/history-document")
def download_legacy_history_document(
    run_id: int,
    _: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Read-only download for the legacy history section."""
    run, groups = _document_context(db, run_id)
    content = build_school_leave_run_docx(
        run,
        groups,
        contact_phone=get_leave_contact_phone(),
    )
    filename = school_leave_run_document_filename(db, run)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post(
    "/admin/runs/{run_id}/groups/{group_index}/result",
    response_model=SchoolLeaveGroupResultOut,
)
async def upload_group_result(
    run_id: int,
    group_index: int,
    file: UploadFile = File(...),
    current: Member = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SchoolLeaveGroupResultOut:
    run = _get_admin_run(db, run_id, lock=True)
    if run.status not in {"awaiting_return", "completed"}:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="请先下载请假材料，再上传盖章结果",
        )
    groups = _run_groups(db, run)
    if not any(group.index == group_index for group in groups):
        db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="时间组不存在")

    content = await file.read(SCHOOL_LEAVE_RESULT_MAX_BYTES + 1)
    try:
        original_filename, suffix = validate_school_leave_result_upload(
            file.filename,
            file.content_type,
            content,
        )
    except OverflowError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    stored_name = store_school_leave_result_file(content, suffix)
    previous_stored_name: str | None = None
    try:
        result = db.scalar(
            select(SchoolLeaveGroupResult)
            .where(
                SchoolLeaveGroupResult.run_id == run.id,
                SchoolLeaveGroupResult.group_index == group_index,
            )
            .with_for_update()
        )
        now = school_leave_now()
        if result is None:
            result = SchoolLeaveGroupResult(run_id=run.id, group_index=group_index)
            db.add(result)
        else:
            previous_stored_name = result.stored_name

        result.stored_name = stored_name
        result.original_filename = original_filename
        result.mime_type = file.content_type or ""
        result.size_bytes = len(content)
        result.uploaded_by = current.id
        result.uploaded_at = now
        result.expires_at = now + SCHOOL_LEAVE_RESULT_TTL
        result.deleted_at = None
        db.flush()

        if run.status == "awaiting_return":
            available_group_indexes = set(
                db.scalars(
                    select(SchoolLeaveGroupResult.group_index).where(
                        SchoolLeaveGroupResult.run_id == run.id,
                        SchoolLeaveGroupResult.deleted_at.is_(None),
                        SchoolLeaveGroupResult.expires_at > now,
                    )
                )
            )
            if available_group_indexes == {group.index for group in groups}:
                run.status = "completed"

        db.commit()
        db.refresh(result)
    except Exception:
        db.rollback()
        delete_school_leave_result_file(stored_name)
        raise

    if previous_stored_name and previous_stored_name != stored_name:
        delete_school_leave_result_file(previous_stored_name)
    return _result_out(result)


@router.get("/runs/{run_id}/groups/{group_index}/result")
def download_group_result(
    run_id: int,
    group_index: int,
    current: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
) -> FileResponse:
    run = _get_admin_run(db, run_id)
    group = next((item for item in _run_groups(db, run) if item.index == group_index), None)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="盖章材料不存在")
    if current.role != "admin" and not any(
        request.member_id == current.id for request in group.requests
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="盖章材料不存在")

    result = db.scalar(
        select(SchoolLeaveGroupResult).where(
            SchoolLeaveGroupResult.run_id == run.id,
            SchoolLeaveGroupResult.group_index == group_index,
        )
    )
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="盖章材料不存在")
    if result.deleted_at is not None or result.expires_at <= school_leave_now():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="盖章材料已清理")

    path = school_leave_result_file_path(result.stored_name)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="盖章材料已清理")
    filename = school_leave_result_download_filename(run, result.mime_type)
    return FileResponse(
        path,
        media_type=result.mime_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{quote(filename)}"},
    )
