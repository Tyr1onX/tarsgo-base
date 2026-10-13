from fastapi import FastAPI, HTTPException, Request
from starlette.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from .db import check_database
from .knowledge import MAX_UPLOAD_BYTES
from .routers import (
    admin_updates,
    ai_items,
    ai_planner,
    auth,
    camp_leave,
    colleges,
    daily_leave_v2,
    invitations,
    knowledge,
    members,
    school_leave,
    tasks,
    team_registration,
)

app = FastAPI(title="TARS-Go Platform API")
app.include_router(auth.router)
app.include_router(colleges.router)
app.include_router(invitations.router)
app.include_router(members.router)
app.include_router(team_registration.router)
app.include_router(school_leave.router)
app.include_router(daily_leave_v2.router)
app.include_router(admin_updates.router)
app.include_router(camp_leave.router)
app.include_router(tasks.router)
app.include_router(ai_planner.router)
app.include_router(ai_items.router)
app.include_router(knowledge.router)

MAX_UPLOAD_REQUEST_BYTES = MAX_UPLOAD_BYTES + 64 * 1024
DOCUMENT_UPLOAD_PATHS = {"/api/knowledge/uploads", "/api/ai/planner/extract"}


class DocumentUploadTooLarge(Exception):
    pass


class DocumentUploadSizeLimitMiddleware:
    def __init__(self, application):
        self.application = application

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] not in DOCUMENT_UPLOAD_PATHS
        ):
            await self.application(scope, receive, send)
            return

        content_length = next(
            (value for name, value in scope.get("headers", []) if name.lower() == b"content-length"),
            None,
        )
        try:
            if content_length is not None and int(content_length) > MAX_UPLOAD_REQUEST_BYTES:
                response = JSONResponse(status_code=413, content={"detail": "单个文件不能超过 10 MiB"})
                await response(scope, receive, send)
                return
        except ValueError:
            pass

        received_bytes = 0

        async def limited_receive():
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > MAX_UPLOAD_REQUEST_BYTES:
                    raise DocumentUploadTooLarge
            return message

        await self.application(scope, limited_receive, send)


@app.exception_handler(DocumentUploadTooLarge)
async def document_upload_too_large(_: Request, __: DocumentUploadTooLarge) -> JSONResponse:
    return JSONResponse(status_code=413, content={"detail": "单个文件不能超过 10 MiB"})


app.add_middleware(DocumentUploadSizeLimitMiddleware)


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        check_database()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}
