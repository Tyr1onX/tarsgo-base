"""Fictional event rehearsal through HTTP and real DB transactions; no live AI."""
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.auth import hash_password
from app.ai_planner import PlannerProviderError, get_planner_provider
from app.db import SessionLocal
from app.main import app
from app.models import AIPlannerDailyUsage, Member


def main():
    token = secrets.token_hex(5)
    checks = []
    root_ids, member_ids = [], []
    clients = []

    def check(name, condition):
        assert condition, name
        checks.append({"name": name, "passed": True})

    def request(client, method, path, data=None, status=200):
        response = client.request(method, "/api" + path, json=data)
        assert response.status_code == status, (method, path, response.status_code, response.text)
        return response.json() if response.content else None

    try:
        for i, role in enumerate(["admin", "manager"] + ["member"] * 6):
            password = secrets.token_urlsafe(24)
            email = f"rehearsal-{token}-{i}@example.invalid"
            with SessionLocal() as db:
                member = Member(name=f"模拟成员{i + 1}", email=email, role=role, status="active", password_hash=hash_password(password))
                db.add(member); db.commit(); member_ids.append(member.id)
            client = TestClient(app)
            request(client, "POST", "/auth/login", {"email": email, "password": password})
            clients.append(client)
        admin, manager, a, b, c, d, outsider, reserve = clients
        root = request(manager, "POST", "/tasks", {"title": "模拟校园机器人展示", "owner_id": member_ids[1]}, 201)
        root_ids.append(root["id"])
        rid = root["id"]

        def create(title, **extra):
            return request(manager, "POST", "/tasks", {"title": title, "parent_id": rid, "owner_claimable": True, **extra}, 201)

        confirm = create("确认时间与场地", deliverable="取得主办方确认的时间、入口和展示区域")
        equipment = create("准备展示设备", deliverable="按清单检查设备并交给现场负责人", depends_on_task_ids=[confirm["id"]])
        photography = create("现场摄影", collaboration_open=True, deliverable="拍摄约定环节并归档原图")
        supplies = create("周边物资保障", deliverable="按确认数量送达现场并完成交接")
        archive = create("整理活动资料", depends_on_task_ids=[equipment["id"], photography["id"], supplies["id"]])
        check("所有成员能看到事项和五项分工", len(request(outsider, "GET", f"/tasks/{rid}/context")["tasks"]) == 5)
        check("没有可靠日期时分工截止时间为空", equipment["deadline"] is None)

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda client: client.post(f"/api/tasks/{confirm['id']}/claim"), [a, b]))
        check("同时认领仅一人成功", sorted(r.status_code for r in responses) == [200, 409])
        winner = a if responses[0].status_code == 200 else b
        request(c, "POST", f"/tasks/{equipment['id']}/claim")
        request(c, "POST", f"/tasks/{equipment['id']}/progress", {"content": "提前开始"}, 409)
        request(c, "POST", f"/tasks/{equipment['id']}/complete", {"result": "绕过依赖"}, 409)
        for state in ["doing", "done"]:
            request(c, "PATCH", f"/tasks/{equipment['id']}", {"status": state}, 403)
        request(c, "PATCH", f"/tasks/{equipment['id']}", {"result": "绕过结果记录"}, 403)
        check("被阻塞任务不能通过任何成员入口推进或完成", request(c, "GET", f"/tasks/{equipment['id']}")["status"] == "todo")
        request(winner, "POST", f"/tasks/{confirm['id']}/progress", {"content": "已确认 10 月 18 日 09:00 在东门集合。"}, 201)
        check("首次进展推进分工和事项状态", request(outsider, "GET", f"/tasks/{rid}")["status"] == "doing")
        request(winner, "POST", f"/tasks/{confirm['id']}/complete", {"result": "10 月 18 日 09:00 东门集合。", "sync_to_item": True})
        check("前置完成后解除阻塞", not request(c, "GET", f"/tasks/{equipment['id']}")["blocked"])

        old = request(manager, "POST", f"/tasks/{rid}/context-facts", {"content": "展示设备从东门进入。", "scope": "related", "related_task_ids": [equipment["id"]]})
        old_id = next(f["id"] for f in old["item_facts"] if f["content"] == "展示设备从东门进入。")
        check("认领前可见完成标准和前置要求", bool(request(reserve, "GET", f"/tasks/{equipment['id']}")["deliverable"]))
        check("任务专属信息按参与关系过滤", "展示设备从东门进入。" not in request(outsider, "GET", f"/tasks/{equipment['id']}")["context_facts"])
        request(c, "POST", f"/tasks/{equipment['id']}/progress", {"content": "设备检查完成，等待车辆。"}, 201)
        request(c, "POST", f"/tasks/{equipment['id']}/unclaim")
        request(reserve, "POST", f"/tasks/{equipment['id']}/claim")
        inherited = request(reserve, "GET", f"/tasks/{equipment['id']}/context")
        check("临时换人继承任务事实和历史", "展示设备从东门进入。" in inherited["root"]["context_facts"] and any(x["content"] == "设备检查完成，等待车辆。" for x in inherited["activity_page"]["items"]))
        check("原负责人退出后不再收到专属信息", "展示设备从东门进入。" not in request(c, "GET", f"/tasks/{equipment['id']}")["context_facts"])
        new = request(manager, "POST", f"/tasks/{rid}/context-facts", {"content": "主办方改为北门进入。", "scope": "related", "related_task_ids": [equipment["id"]], "supersedes_fact_id": old_id})
        check("地点变更替换当前事实", "展示设备从东门进入。" not in new["context_facts"] and "主办方改为北门进入。" in new["context_facts"])
        request(manager, "PATCH", f"/tasks/{equipment['id']}", {"owner_id": member_ids[3], "deadline": "2026-10-18T08:30:00"})
        history = request(manager, "GET", f"/tasks/{rid}/activities")
        check("负责人和截止时间修改留下交接动态", any("负责人：" in x["content"] and "截止时间：" in x["content"] for x in history))
        count = len(history)
        request(manager, "PATCH", f"/tasks/{equipment['id']}", {"owner_id": member_ids[3], "deadline": "2026-10-18T08:30:00"})
        check("未变化字段不生成重复交接动态", len(request(manager, "GET", f"/tasks/{rid}/activities")) == count)
        request(b, "POST", f"/tasks/{equipment['id']}/complete", {"result": "设备已移交，按北门路线入场。"})

        request(d, "POST", f"/tasks/{photography['id']}/claim")
        request(c, "POST", f"/tasks/{photography['id']}/collaborators/join")
        request(c, "POST", f"/tasks/{photography['id']}/complete", {"result": "协作者不应完成"}, 403)
        progress = request(c, "POST", f"/tasks/{photography['id']}/progress", {"content": "确认原图将在活动结束后归档。"}, 201)
        class UnavailableProvider:
            def extract_facts(self, context):
                raise PlannerProviderError("simulated provider unavailable")
        app.dependency_overrides[get_planner_provider] = lambda: UnavailableProvider()
        try:
            response = c.post(f"/api/ai/items/{rid}/extract-facts", json={"activity_id": progress["activity"]["id"]})
            check("AI 失败不回滚进展", response.status_code == 503 and any(x["id"] == progress["activity"]["id"] for x in request(c, "GET", f"/tasks/{rid}/activities?task_id={photography['id']}")))
        finally:
            app.dependency_overrides.pop(get_planner_provider, None)
        request(d, "POST", f"/tasks/{photography['id']}/complete", {"result": "已拍摄约定环节，原图已归档。"})
        request(a, "POST", f"/tasks/{supplies['id']}/claim")
        request(a, "POST", f"/tasks/{supplies['id']}/complete", {"result": "物资已送达并交接。"})
        check("归档任务等待所有前置完成", not request(reserve, "GET", f"/tasks/{archive['id']}")["blocked"])
        request(reserve, "POST", f"/tasks/{archive['id']}/claim")
        request(reserve, "POST", f"/tasks/{archive['id']}/complete", {"result": "活动清单、现场原图和交接结果已整理。"})
        check("全部分工完成后事项自动完成", request(outsider, "GET", f"/tasks/{rid}")["status"] == "done")
        request(reserve, "POST", f"/tasks/{archive['id']}/complete", {"result": "重复完成"}, 409)
        request(reserve, "POST", f"/tasks/{archive['id']}/unclaim", status=409)
        check("重复完成和完成后取消认领均被拒绝", True)
        request(manager, "PATCH", f"/tasks/{archive['id']}", {"status": "doing"})
        check("管理者纠正状态可追踪并重算事项", request(manager, "GET", f"/tasks/{rid}")["status"] == "doing" and any("管理者纠正状态" in x["content"] for x in request(manager, "GET", f"/tasks/{rid}/activities")))
        request(reserve, "POST", f"/tasks/{archive['id']}/complete", {"result": "补充资料后重新完成归档。"})
        request(admin, "POST", f"/members/{member_ids[7]}/disable")
        check("停用成员的现有登录立即失效", reserve.get("/api/auth/me").status_code == 401)
        check("完成结果可查询", request(manager, "GET", f"/tasks/{archive['id']}")["result"] == "补充资料后重新完成归档。")
        output = {"event": "模拟校园机器人展示", "members": 8, "assignments": 5, "database": SessionLocal.kw["bind"].dialect.name, "live_model_calls": 0, "checks": checks}
        Path("operations-simulation-report.json").write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"Operations rehearsal passed: {len(checks)} checks, 8 fictional members, 5 assignments")
    finally:
        for root_id in root_ids:
            request(clients[0], "DELETE", f"/tasks/{root_id}", status=204)
        with SessionLocal() as db:
            db.execute(delete(AIPlannerDailyUsage).where(AIPlannerDailyUsage.member_id.in_(member_ids)))
            db.execute(delete(Member).where(Member.id.in_(member_ids))); db.commit()
        for client in clients:
            client.close()


if __name__ == "__main__":
    main()
