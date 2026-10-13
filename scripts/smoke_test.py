import json
import os
import secrets
import sys
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener


BASE_URL = sys.argv[2].rstrip("/") if len(sys.argv) > 2 else "http://127.0.0.1"
ADMIN_EMAIL = "admin@example.com"
OWNER_EMAIL = "lisi@example.com"
SECOND_MEMBER_EMAIL = "zhaoliu@example.com"
ROOT_TITLE = "春屿展示"
ROOT_FINAL_TITLE = "春屿展示（确认）"
CLAIM_CHILD_TITLE = "周边物资保障"
COLLAB_CHILD_TITLE = "现场摄影"
RELEASABLE_TITLE = "直播间值守"


def opener():
    return build_opener(HTTPCookieProcessor(CookieJar()))


def call(client, path, *, method="GET", data=None, expected=200):
    body = None if data is None else json.dumps(data).encode()
    request = Request(
        BASE_URL + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        with client.open(request, timeout=10) as response:
            payload = response.read()
            status = response.status
    except HTTPError as error:
        payload = error.read()
        status = error.code

    if status != expected:
        raise AssertionError(
            f"{method} {path}: expected {expected}, got {status}: {payload.decode()}"
        )

    if not payload:
        return None
    return json.loads(payload)


def upload_markdown(client, *, content=None, filename="ci-fixture.md", expected=201):
    boundary = "tarsgo-knowledge-smoke-boundary"
    if content is None:
        content = b"# CI fixture\nCurrent event material for authorization smoke."
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    request = Request(
        BASE_URL + "/api/knowledge/uploads",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with client.open(request, timeout=10) as response:
            payload = response.read()
            status = response.status
    except HTTPError as error:
        payload = error.read()
        status = error.code
    if status != expected:
        raise AssertionError(f"POST /api/knowledge/uploads: expected {expected}, got {status}: {payload.decode()}")
    return json.loads(payload) if payload else None


def login(email, password, *, expected=200):
    client = opener()
    result = call(
        client,
        "/api/auth/login",
        method="POST",
        data={"email": email, "password": password},
        expected=expected,
    )
    if expected == 200:
        assert result["email"] == email
    return client


def invite(admin, name, email):
    return call(
        admin,
        "/api/members/invite",
        method="POST",
        data={"name": name, "email": email},
        expected=201,
    )


def activate(invitation):
    token = invitation["invite_path"].rsplit("/", 1)[1]
    info = call(opener(), f"/api/invitations/{token}")
    assert info["name"] == invitation["member"]["name"]
    password = secrets.token_urlsafe(18)
    call(
        opener(),
        f"/api/invitations/{token}/accept",
        method="POST",
        data={"password": password},
        expected=204,
    )
    call(opener(), f"/api/invitations/{token}", expected=404)
    return password


def create_task(admin, **overrides):
    payload = {
        "title": "默认运营任务",
        "deliverable": "",
        "owner_id": None,
        "owner_claimable": True,
        "collaborator_ids": [],
        "collaboration_open": False,
        "parent_id": None,
        "deadline": "2026-10-15T18:00:00",
        "status": "todo",
    }
    payload.update(overrides)
    return call(admin, "/api/tasks", method="POST", data=payload, expected=201)


def run_workflow():
    admin_password = os.environ["CI_ADMIN_PASSWORD"]

    call(opener(), "/api/auth/me", expected=401)
    call(opener(), "/api/tasks?scope=all", expected=401)
    call(opener(), "/api/members", expected=401)
    call(opener(), "/api/knowledge", expected=401)
    call(opener(), "/api/knowledge/search?q=fixture", expected=401)
    call(opener(), "/api/knowledge/sync/github", method="POST", expected=401)

    admin = login(ADMIN_EMAIL, admin_password)
    assert isinstance(call(admin, "/api/knowledge"), list)
    uploaded_knowledge = upload_markdown(admin)
    assert uploaded_knowledge["title"] == "ci-fixture"
    knowledge_results = call(admin, "/api/knowledge/search?q=fixture")
    assert any(reference["id"] == uploaded_knowledge["id"] for reference in knowledge_results)
    upload_markdown(admin, content=b"x" * (10 * 1024 * 1024 + 64 * 1024), filename="too-large.txt", expected=413)
    call(admin, f"/api/knowledge/{uploaded_knowledge['id']}", method="DELETE", expected=204)

    owner_invite = invite(admin, "李四", OWNER_EMAIL)
    owner_id = owner_invite["member"]["id"]
    owner_password = activate(owner_invite)

    second_invite = invite(admin, "赵六", SECOND_MEMBER_EMAIL)
    second_id = second_invite["member"]["id"]
    second_password = activate(second_invite)

    owner = login(OWNER_EMAIL, owner_password)
    second = login(SECOND_MEMBER_EMAIL, second_password)

    call(owner, "/api/members", expected=403)
    call(owner, "/api/knowledge", expected=403)
    call(owner, "/api/knowledge/search?q=fixture", expected=403)
    call(owner, "/api/knowledge/sync/github", method="POST", expected=403)
    call(owner, "/api/knowledge/999999", method="DELETE", expected=403)
    upload_markdown(owner, expected=403)
    call(owner, "/api/tasks/assignees", expected=403)
    call(
        owner,
        "/api/tasks",
        method="POST",
        data={
            "title": "成员不能创建事项",
            "deliverable": "",
            "owner_id": owner_id,
            "owner_claimable": False,
            "collaborator_ids": [],
            "collaboration_open": False,
            "parent_id": None,
            "deadline": None,
            "status": "todo",
        },
        expected=403,
    )

    admin_profile = call(admin, "/api/auth/me")
    admin_id = admin_profile["id"]
    assignees = call(admin, "/api/tasks/assignees")
    assert {item["id"] for item in assignees} >= {admin_id, owner_id, second_id}

    call(
        admin,
        "/api/tasks",
        method="POST",
        data={
            "title": "无负责人且不可认领",
            "deliverable": "",
            "owner_id": None,
            "owner_claimable": False,
            "collaborator_ids": [],
            "collaboration_open": False,
            "parent_id": None,
            "deadline": "2026-10-15T18:00:00",
            "status": "todo",
        },
        expected=422,
    )

    root = create_task(
        admin,
        title=ROOT_TITLE,
        deliverable="完成展示现场整体执行。",
        owner_id=admin_id,
        owner_claimable=False,
        collaborator_ids=[second_id],
        collaboration_open=False,
        deadline="2026-09-21T18:00:00",
    )
    assert root["parent_id"] is None
    assert root["owner"]["id"] == admin_id
    assert root["context_facts"] == []
    assert root["result"] == ""

    claim_child = create_task(
        admin,
        title=CLAIM_CHILD_TITLE,
        parent_id=root["id"],
        execution_points=["按清单逐项检查", "确认控制功能正常"],
        cautions=["备用配件一并清点"],
        prerequisites=["展示项目清单已确认"],
        owner_id=None,
        owner_claimable=True,
        collaboration_open=True,
        deadline="2026-09-21T15:00:00",
    )
    assert claim_child["parent_id"] == root["id"]
    assert claim_child["owner"] is None
    assert claim_child["owner_claimable"] is True
    assert claim_child["execution_points"] == ["按清单逐项检查", "确认控制功能正常"]
    assert claim_child["cautions"] == ["备用配件一并清点"]
    assert claim_child["prerequisites"] == ["展示项目清单已确认"]
    claim_child = call(
        admin,
        f"/api/tasks/{claim_child['id']}",
        method="PATCH",
        data={"cautions": ["出发前再次清点备用配件"]},
    )
    assert claim_child["cautions"] == ["出发前再次清点备用配件"]

    collaboration_child = create_task(
        admin,
        title=COLLAB_CHILD_TITLE,
        parent_id=root["id"],
        owner_id=admin_id,
        owner_claimable=False,
        collaboration_open=True,
        deadline="2026-09-21T17:00:00",
    )
    collaboration_child = call(
        admin,
        f"/api/tasks/{collaboration_child['id']}",
        method="PATCH",
        data={"result": "管理员可以记录任务执行结果。"},
    )
    assert collaboration_child["result"] == "管理员可以记录任务执行结果。"

    call(
        admin,
        "/api/tasks",
        method="POST",
        data={
            "title": "不允许的二级分工",
            "deliverable": "",
            "owner_id": admin_id,
            "owner_claimable": False,
            "collaborator_ids": [],
            "collaboration_open": False,
            "parent_id": claim_child["id"],
            "deadline": "2026-09-21T16:00:00",
            "status": "todo",
        },
        expected=400,
    )

    all_for_owner = call(owner, "/api/tasks?scope=all")
    all_ids = {item["id"] for item in all_for_owner}
    assert {root["id"], claim_child["id"], collaboration_child["id"]} <= all_ids
    member_visible_child = next(item for item in all_for_owner if item["id"] == claim_child["id"])
    assert member_visible_child["execution_points"] == ["按清单逐项检查", "确认控制功能正常"]
    assert member_visible_child["cautions"] == ["出发前再次清点备用配件"]
    assert member_visible_child["prerequisites"] == ["展示项目清单已确认"]

    call(
        owner,
        f"/api/tasks/{root['id']}",
        method="PATCH",
        data={"title": "成员不应能修改结构"},
        expected=403,
    )
    call(
        owner,
        f"/api/tasks/{claim_child['id']}",
        method="PATCH",
        data={"execution_points": ["成员不应能改结构"]},
        expected=403,
    )

    waiting = call(owner, "/api/tasks?scope=claimable")
    assert claim_child["id"] in {item["id"] for item in waiting}

    claimed = call(second, f"/api/tasks/{claim_child['id']}/claim", method="POST")
    assert claimed["owner"]["id"] == second_id
    call(owner, f"/api/tasks/{claim_child['id']}/claim", method="POST", expected=409)

    joined = call(owner, f"/api/tasks/{collaboration_child['id']}/collaborators/join", method="POST")
    assert owner_id in {item["id"] for item in joined["collaborators"]}
    left = call(owner, f"/api/tasks/{collaboration_child['id']}/collaborators/leave", method="POST")
    assert owner_id not in {item["id"] for item in left["collaborators"]}

    collaborator_joined = call(second, f"/api/tasks/{collaboration_child['id']}/collaborators/join", method="POST")
    assert second_id in {item["id"] for item in collaborator_joined["collaborators"]}
    collaborator_activity = call(
        second,
        f"/api/tasks/{root['id']}/activities",
        method="POST",
        data={"content": "协作者可以记录所属事项动态。", "add_to_context": False},
        expected=201,
    )
    assert collaborator_activity["author"]["id"] == second_id
    call(second, f"/api/tasks/{collaboration_child['id']}/collaborators/leave", method="POST")

    reassigned = call(
        admin,
        f"/api/tasks/{claim_child['id']}",
        method="PATCH",
        data={"owner_id": owner_id},
    )
    assert reassigned["owner"]["id"] == owner_id

    execution_result = "主办方确认 8:30 东门集合，9:00 开始，现场提供桌椅和 220V 电源。"
    call(
        owner,
        f"/api/tasks/{claim_child['id']}",
        method="PATCH",
        data={"status": "doing", "result": execution_result},
        expected=403,
    )
    progress = call(
        owner, f"/api/tasks/{claim_child['id']}/progress", method="POST",
        data={"content": execution_result}, expected=201,
    )
    assert progress["task"]["status"] == "doing"
    completed = call(
        owner, f"/api/tasks/{claim_child['id']}/complete", method="POST",
        data={"result": execution_result, "sync_to_item": False},
    )
    assert completed["task"]["result"] == execution_result
    call(manager, f"/api/tasks/{claim_child['id']}", method="PATCH", data={"status": "doing"})
    call(
        second,
        f"/api/tasks/{claim_child['id']}",
        method="PATCH",
        data={"result": "非负责人不应能填写结果"},
        expected=403,
    )
    call(
        owner,
        f"/api/tasks/{claim_child['id']}",
        method="PATCH",
        data={"title": "负责人不应能修改结构", "result": execution_result},
        expected=403,
    )

    # Item activity and current facts are writable only by item participants.
    call(
        second,
        f"/api/tasks/{root['id']}/activities",
        method="POST",
        data={"content": "旁观成员不应能写事项动态", "add_to_context": False},
        expected=403,
    )
    activity = call(
        owner,
        f"/api/tasks/{root['id']}/activities",
        method="POST",
        data={"content": "主办方要求当天提前 20 分钟完成布展。", "add_to_context": True},
        expected=201,
    )
    assert activity["root_task_id"] == root["id"]
    assert activity["author"]["id"] == owner_id
    root_with_activity_fact = call(owner, f"/api/tasks/{root['id']}")
    assert root_with_activity_fact["context_facts"] == ["主办方要求当天提前 20 分钟完成布展。"]
    call(
        owner,
        f"/api/tasks/{root['id']}/context-facts",
        method="POST",
        data={"content": "字" * 501},
        expected=422,
    )
    call(owner, f"/api/tasks/{root['id']}/result-to-context", method="POST", expected=409)

    manual_fact = call(
        owner,
        f"/api/tasks/{root['id']}/context-facts",
        method="POST",
        data={"content": "活动地点已确认。"},
    )
    assert manual_fact["context_facts"][-1] == "活动地点已确认。"
    # A regular participant may add an item fact, but only the item owner or
    # admin may change its scope or deactivate it. Verify both sides of that
    # boundary before checking that the source activity remains in history.
    call(
        owner,
        f"/api/tasks/{root['id']}/context-facts/1",
        method="DELETE",
        expected=403,
    )
    after_delete = call(
        admin,
        f"/api/tasks/{root['id']}/context-facts/1",
        method="DELETE",
    )
    assert after_delete["context_facts"] == ["主办方要求当天提前 20 分钟完成布展。"]
    activities_after_delete = call(admin, f"/api/tasks/{root['id']}/activities")
    assert any(item["content"] == "主办方要求当天提前 20 分钟完成布展。" for item in activities_after_delete)

    promoted = call(
        owner,
        f"/api/tasks/{claim_child['id']}/result-to-context",
        method="POST",
    )
    assert execution_result in promoted["context_facts"]
    activities = call(owner, f"/api/tasks/{root['id']}/activities")
    assert any("执行结果已确认加入事项信息" in item["content"] for item in activities)
    call(
        owner,
        f"/api/tasks/{claim_child['id']}/activities",
        method="POST",
        data={"content": "动态不能挂到分工", "add_to_context": False},
        expected=400,
    )

    before_failed_activity = len(activities)
    call(
        owner,
        f"/api/tasks/{root['id']}/activities",
        method="POST",
        data={"content": "字" * 501, "add_to_context": True},
        expected=422,
    )
    assert len(call(owner, f"/api/tasks/{root['id']}/activities")) == before_failed_activity
    assert call(owner, f"/api/tasks/{root['id']}")["context_facts"] == promoted["context_facts"]

    releasable = create_task(
        admin,
        title=RELEASABLE_TITLE,
        owner_id=None,
        owner_claimable=True,
        collaboration_open=False,
        deadline="2026-09-21T16:30:00",
    )
    claimed_by_owner = call(owner, f"/api/tasks/{releasable['id']}/claim", method="POST")
    assert claimed_by_owner["owner"]["id"] == owner_id
    released = call(owner, f"/api/tasks/{releasable['id']}/unclaim", method="POST")
    assert released["owner"] is None
    assert released["owner_claimable"] is True

    call(owner, f"/api/tasks/{releasable['id']}/claim", method="POST")
    call(
        owner,
        f"/api/tasks/{releasable['id']}",
        method="PATCH",
        data={"status": "done"},
    )
    call(owner, f"/api/tasks/{releasable['id']}/unclaim", method="POST", expected=409)

    disabled = call(admin, f"/api/members/{second_id}/disable", method="POST")
    assert disabled["status"] == "disabled"
    call(second, "/api/auth/me", expected=401)
    login(SECOND_MEMBER_EMAIL, second_password, expected=403)

    disabled_target = create_task(
        admin,
        title="停用成员不可认领",
        owner_id=None,
        owner_claimable=True,
        deadline="2026-09-22T12:00:00",
    )
    call(second, f"/api/tasks/{disabled_target['id']}/claim", method="POST", expected=401)

    root_updated = call(
        admin,
        f"/api/tasks/{root['id']}",
        method="PATCH",
        data={"title": ROOT_FINAL_TITLE},
    )
    assert root_updated["title"] == ROOT_FINAL_TITLE
    assert [item["id"] for item in root_updated["collaborators"]] == [second_id]

    all_after = call(owner, "/api/tasks?scope=all")
    root_after = next(item for item in all_after if item["id"] == root["id"])
    children = [item for item in all_after if item["parent_id"] == root["id"]]
    assert root_after["parent_id"] is None
    assert {item["title"] for item in children} >= {CLAIM_CHILD_TITLE, COLLAB_CHILD_TITLE}

    print("V0.2 operations workflow smoke test passed")


def verify_persistence():
    admin = login(ADMIN_EMAIL, os.environ["CI_ADMIN_PASSWORD"])
    members = call(admin, "/api/members")
    by_email = {member["email"]: member for member in members}
    assert by_email[OWNER_EMAIL]["status"] == "active"
    assert by_email[SECOND_MEMBER_EMAIL]["status"] == "disabled"

    tasks = call(admin, "/api/tasks?scope=all")
    root = next(item for item in tasks if item["title"] == ROOT_FINAL_TITLE)
    claim_child = next(item for item in tasks if item["title"] == CLAIM_CHILD_TITLE)
    collaboration_child = next(item for item in tasks if item["title"] == COLLAB_CHILD_TITLE)
    releasable = next(item for item in tasks if item["title"] == RELEASABLE_TITLE)

    assert root["parent_id"] is None
    assert by_email[SECOND_MEMBER_EMAIL]["id"] in {
        item["id"] for item in root["collaborators"]
    }
    assert claim_child["parent_id"] == root["id"]
    assert claim_child["owner"]["id"] == by_email[OWNER_EMAIL]["id"]
    assert claim_child["status"] == "doing"
    assert "主办方确认 8:30 东门集合" in claim_child["result"]
    assert root["context_facts"]
    assert any("主办方确认 8:30 东门集合" in fact for fact in root["context_facts"])
    assert call(admin, f"/api/tasks/{root['id']}/activities")
    assert claim_child["execution_points"] == ["按清单逐项检查", "确认控制功能正常"]
    assert claim_child["cautions"] == ["出发前再次清点备用配件"]
    assert claim_child["prerequisites"] == ["展示项目清单已确认"]
    assert collaboration_child["parent_id"] == root["id"]
    assert collaboration_child["collaboration_open"] is True
    assert releasable["status"] == "done"

    print("V0.2 database restart persistence check passed")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "workflow"
    if phase == "workflow":
        run_workflow()
    elif phase == "persistence":
        verify_persistence()
    else:
        raise SystemExit(f"unknown phase: {phase}")
