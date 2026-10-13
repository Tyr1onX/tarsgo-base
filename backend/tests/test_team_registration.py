"""MySQL-backed coverage for team registration, group profiles, and two-role auth."""

from datetime import timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select

from app.auth import COOKIE_NAME, get_current_member, hash_token, utcnow, verify_password
from app.college_dictionary import COLLEGES
from app.db import SessionLocal, get_db
from app.main import app
from app.models import Invitation, LoginSession, Member, MemberIdentityAudit, TeamRegistrationWindow
from app.schemas import Role, TeamRegistrationIn


GROUPS = ("electrical", "mechanical", "vision", "ai", "operations")


def main() -> None:
    token = uuid4().hex
    admin_email = f"registration-admin-{token}@example.invalid"
    member_email = f"registration-member-{token}@example.invalid"
    first_email = f"registration-first-{token}@example.invalid"
    second_email = f"registration-second-{token}@example.invalid"
    third_email = f"registration-third-{token}@example.invalid"
    invited_email = f"registration-invited-{token}@example.invalid"
    created_member_ids: set[int] = set()
    created_window_ids: set[int] = set()

    try:
        try:
            TypeAdapter(Role).validate_python("manager")
        except ValidationError:
            pass
        else:
            raise AssertionError("removed manager role must fail schema validation")

        with SessionLocal() as db:
            admin = Member(
                name="注册测试管理员",
                email=admin_email,
                role="admin",
                status="active",
            )
            member = Member(
                name="注册测试成员",
                email=member_email,
                student_id=None,
                team_group=None,
                role="member",
                status="active",
            )
            db.add_all([admin, member])
            db.commit()
            db.refresh(admin)
            db.refresh(member)
            created_member_ids.update((admin.id, member.id))

            previous_overrides = dict(app.dependency_overrides)

            def override_database():
                yield db

            app.dependency_overrides[get_db] = override_database

            def set_actor(actor: Member | None) -> None:
                if actor is None:
                    app.dependency_overrides.pop(get_current_member, None)
                else:
                    app.dependency_overrides[get_current_member] = lambda: actor

            try:
                client = TestClient(app)

                # Admin APIs enforce authentication and admin role.
                set_actor(None)
                assert client.post("/api/team-registration/admin/open").status_code == 401
                set_actor(member)
                assert client.post("/api/team-registration/admin/open").status_code == 403

                set_actor(admin)
                opened = client.post("/api/team-registration/admin/open")
                assert opened.status_code == 201, opened.text
                opened_json = opened.json()
                assert opened_json["register_path"].startswith("/register/")
                raw_token = opened_json["register_path"].rsplit("/", 1)[1]
                window_id = opened_json["id"]
                created_window_ids.add(window_id)

                db.expire_all()
                window = db.get(TeamRegistrationWindow, window_id)
                assert window is not None
                assert window.token_hash == hash_token(raw_token)
                assert raw_token != window.token_hash
                ttl = window.expires_at - window.created_at
                assert timedelta(hours=71, minutes=59) <= ttl <= timedelta(hours=72, minutes=1)

                # Only one live window is allowed, and current state never returns the raw link.
                assert client.post("/api/team-registration/admin/open").status_code == 409
                current = client.get("/api/team-registration/admin/current")
                assert current.status_code == 200
                assert current.json()["id"] == window_id
                assert "register_path" not in current.json()

                valid = client.get(f"/api/team-registration/{raw_token}")
                assert valid.status_code == 200
                assert valid.json()["active"] is True
                assert client.get("/api/team-registration/not-a-real-token").status_code == 404

                set_actor(member)
                historical_me = client.get("/api/auth/me")
                assert historical_me.status_code == 200
                assert historical_me.json()["college"] is None
                assert historical_me.json()["team_membership"] is None

                set_actor(admin)
                college_response = client.get("/api/colleges")
                assert college_response.status_code == 200
                college_options = college_response.json()
                assert len(college_options) == 45 == len(COLLEGES)
                assert len({option["code"] for option in college_options}) == 45
                assert all(option["name"] and option["code"] for option in college_options)
                valid_college = college_options[0]["code"]
                base_payload = {
                    "name": "  Ada Q·赵  ",
                    "email": first_email,
                    "student_id": f"{int(token[:16], 16) % 100_000_000:08d}",
                    "college": valid_college,
                    "team_group": "operations",
                    "password": "registration-password",
                }
                for boundary_name in ("AB", "N" * 50):
                    validated = TeamRegistrationIn.model_validate({**base_payload, "name": boundary_name})
                    assert validated.name == boundary_name
                assert client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={**base_payload, "role": "admin"},
                ).status_code == 422
                assert client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={**base_payload, "team_group": "运营部"},
                ).status_code == 422
                assert client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={**base_payload, "team_membership": "formal"},
                ).status_code == 422
                assert client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={**base_payload, "password": "short"},
                ).status_code == 422
                for invalid_name in ("", "A", "  ", "N" * 51):
                    invalid = client.post(
                        f"/api/team-registration/{raw_token}/register",
                        json={**base_payload, "name": invalid_name},
                    )
                    assert invalid.status_code == 422, invalid.text
                for invalid_student_id in ("1234567", "123456789", "1234abcd", "１２３４５６７８"):
                    invalid = client.post(
                        f"/api/team-registration/{raw_token}/register",
                        json={**base_payload, "student_id": invalid_student_id},
                    )
                    assert invalid.status_code == 422, invalid.text
                for invalid_fields in (
                    {"college": "not-a-college"},
                ):
                    invalid = client.post(
                        f"/api/team-registration/{raw_token}/register",
                        json={**base_payload, **invalid_fields},
                    )
                    assert invalid.status_code == 422, invalid.text
                missing_college_payload = {
                    key: value for key, value in base_payload.items() if key != "college"
                }
                assert client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json=missing_college_payload,
                ).status_code == 422

                # Public self-registration creates an active member and a real login session.
                set_actor(None)
                registered = client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json=base_payload,
                )
                assert registered.status_code == 201, registered.text
                registered_json = registered.json()
                registered_id = registered_json["id"]
                created_member_ids.add(registered_id)
                assert registered_json["role"] == "member"
                assert registered_json["status"] == "active"
                assert registered_json["team_group"] == "operations"
                assert registered_json["name"] == "Ada Q·赵"
                assert registered_json["college"] == valid_college
                assert registered_json["team_membership"] is None
                cookie = registered.headers.get("set-cookie", "")
                assert COOKIE_NAME in cookie and "HttpOnly" in cookie

                db.expire_all()
                registered_row = db.get(Member, registered_id)
                assert registered_row is not None
                assert registered_row.password_hash
                assert registered_row.password_hash != base_payload["password"]
                assert verify_password(base_payload["password"], registered_row.password_hash)
                assert db.scalar(
                    select(LoginSession.id).where(LoginSession.member_id == registered_id)
                ) is not None

                me = client.get("/api/auth/me")
                assert me.status_code == 200
                assert me.json()["id"] == registered_id
                assert me.json()["college"] == valid_college
                assert me.json()["team_membership"] is None
                assert me.json()["identity_locked"] is True

                # Unlocked historical/incomplete accounts may finish identity once, then the API locks it.
                set_actor(member)
                first_identity = client.patch(
                    "/api/auth/me",
                    json={"name": "注册测试成员完成", "student_id": "26000801", "college": valid_college},
                )
                assert first_identity.status_code == 200, first_identity.text
                assert first_identity.json()["identity_locked"] is True
                assert client.patch(
                    "/api/auth/me", json={"name": "试图自行改名", "student_id": "26000802"}
                ).status_code == 409
                assert client.patch(
                    "/api/auth/me", json={"student_id": "26000803"}
                ).json()["detail"] == "姓名和学号注册后不可自行修改。如需更正，请联系管理员。"
                assert client.patch("/api/auth/me", json={"name": None}).status_code == 409
                assert client.patch("/api/auth/me", json={"student_id": "invalid"}).status_code == 409

                # Ordinary profile edits update school and group fields without identity.
                set_actor(None)
                with TestClient(app) as anonymous_client:
                    assert anonymous_client.patch(
                    "/api/auth/me", json={"student_id": "26000804"}
                    ).status_code == 401
                for group in GROUPS:
                    updated = client.patch(
                        "/api/auth/me",
                        json={"team_group": group},
                    )
                    assert updated.status_code == 200, updated.text
                    assert updated.json()["team_group"] == group
                    assert updated.json()["student_id"] == base_payload["student_id"]

                updated_profile = client.patch(
                    "/api/auth/me",
                    json={"college": valid_college, "team_membership": "formal"},
                )
                assert updated_profile.status_code == 422, updated_profile.text
                assert client.get("/api/auth/me").json()["team_membership"] is None
                assert client.patch(
                    "/api/auth/me", json={"student_id": "not-8-digits"}
                ).status_code == 409
                for invalid_profile in (
                    {"college": "not-a-college"},
                    {"team_membership": "formal"},
                ):
                    invalid = client.patch("/api/auth/me", json=invalid_profile)
                    assert invalid.status_code == 422, invalid.text

                # Unique constraints are surfaced as stable API conflicts.
                duplicate_email = client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={
                        **base_payload,
                        "student_id": f"{(int(base_payload['student_id']) + 1) % 100_000_000:08d}",
                    },
                )
                assert duplicate_email.status_code == 409
                assert duplicate_email.json()["detail"] == "该邮箱已注册，请直接登录。"

                duplicate_student = client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={
                        **base_payload,
                        "email": second_email,
                    },
                )
                assert duplicate_student.status_code == 409
                assert duplicate_student.json()["detail"] == "该学号已被使用。"

                # Admin identity corrections are unique, auditable, and hidden from ordinary members.
                set_actor(admin)
                admin_edit = client.patch(
                    f"/api/members/{registered_id}/profile",
                    json={
                        "name": "管理员更正姓名",
                        "student_id": f"{(int(base_payload['student_id']) + 2) % 100_000_000:08d}",
                        "team_group": "electrical",
                        "college": valid_college,
                        "team_membership": "formal",
                    },
                )
                assert admin_edit.status_code == 200, admin_edit.text
                assert admin_edit.json()["team_group"] == "electrical"
                assert admin_edit.json()["college"] == valid_college
                assert admin_edit.json()["team_membership"] == "formal"
                assert admin_edit.json()["name"] == "管理员更正姓名"
                assert admin_edit.json()["identity_locked"] is True
                duplicate_admin_edit = client.patch(
                    f"/api/members/{registered_id}/profile",
                    json={"student_id": "26000801"},
                )
                assert duplicate_admin_edit.status_code == 409
                identity_audit = client.get(f"/api/members/{registered_id}/identity-audit")
                assert identity_audit.status_code == 200
                assert {(item["field"], item["old_value"], item["new_value"]) for item in identity_audit.json()} == {
                    ("name", "Ada Q·赵", "管理员更正姓名"),
                    ("student_id", base_payload["student_id"], admin_edit.json()["student_id"]),
                }
                assert all(item["admin_id"] == admin.id and item["changed_at"] for item in identity_audit.json())

                set_actor(member)
                assert client.get(f"/api/members/{registered_id}/identity-audit").status_code == 403
                self_identity_edit = client.patch(
                    "/api/auth/me", json={"name": "再次自助修改", "student_id": "26000805"}
                )
                assert self_identity_edit.status_code == 409
                assert client.patch(
                    f"/api/members/{registered_id}/profile",
                    json={"team_group": "vision"},
                ).status_code == 403

                # Invited members may be prefilled by an administrator and still complete registration.
                set_actor(admin)
                invited_response = client.post(
                    "/api/members/invite",
                    json={"name": "邀请预填姓名", "email": invited_email},
                )
                assert invited_response.status_code == 201, invited_response.text
                invited_id = invited_response.json()["member"]["id"]
                created_member_ids.add(invited_id)
                assert invited_response.json()["member"]["identity_locked"] is False
                invitation_token = invited_response.json()["invite_path"].rsplit("/", 1)[1]
                preset_id = f"{(int(base_payload['student_id']) + 20) % 100_000_000:08d}"
                prefill = client.patch(
                    f"/api/members/{invited_id}/profile",
                    json={"name": "管理员预填姓名", "student_id": preset_id, "college": valid_college},
                )
                assert prefill.status_code == 200 and prefill.json()["identity_locked"] is False
                invite_info = client.get(f"/api/invitations/{invitation_token}")
                assert invite_info.status_code == 200
                assert invite_info.json()["student_id"] == preset_id
                assert invite_info.json()["college"] == valid_college
                rejected_accept = client.post(
                    f"/api/invitations/{invitation_token}/accept",
                    json={
                        "name": "新成员完成",
                        "student_id": admin_edit.json()["student_id"],
                        "college": valid_college,
                        "password": "invited-password",
                    },
                )
                assert rejected_accept.status_code == 409, f"unexpected status {rejected_accept.status_code}: {rejected_accept.text}"
                accepted = client.post(
                    f"/api/invitations/{invitation_token}/accept",
                    json={
                        "name": "邀请成员已注册",
                        "student_id": preset_id,
                        "college": valid_college,
                        "password": "invited-password",
                    },
                )
                assert accepted.status_code == 204, accepted.text
                db.expire_all()
                invited_member = db.get(Member, invited_id)
                assert invited_member is not None
                assert invited_member.status == "active" and invited_member.identity_locked is True
                assert invited_member.name == "邀请成员已注册" and invited_member.student_id == preset_id
                assert db.scalar(select(Invitation.id).where(Invitation.member_id == invited_id)) is None

                # Closing invalidates the old raw token immediately; reopening creates a different token.
                set_actor(admin)
                closed = client.post("/api/team-registration/admin/close")
                assert closed.status_code == 204
                assert client.get(f"/api/team-registration/{raw_token}").status_code == 410
                assert client.post(
                    f"/api/team-registration/{raw_token}/register",
                    json={
                        **base_payload,
                        "email": third_email,
                        "student_id": f"{(int(base_payload['student_id']) + 3) % 100_000_000:08d}",
                    },
                ).status_code == 410

                reopened = client.post("/api/team-registration/admin/open")
                assert reopened.status_code == 201, reopened.text
                reopened_json = reopened.json()
                reopened_id = reopened_json["id"]
                created_window_ids.add(reopened_id)
                reopened_token = reopened_json["register_path"].rsplit("/", 1)[1]
                assert reopened_token != raw_token
                assert client.get(f"/api/team-registration/{raw_token}").status_code == 410

                # Expiry needs no background job: it is evaluated at request time.
                db.expire_all()
                reopened_window = db.get(TeamRegistrationWindow, reopened_id)
                assert reopened_window is not None
                reopened_window.expires_at = utcnow() - timedelta(seconds=1)
                db.commit()
                assert client.get(f"/api/team-registration/{reopened_token}").status_code == 410
                assert client.post(
                    f"/api/team-registration/{reopened_token}/register",
                    json={
                        **base_payload,
                        "email": third_email,
                        "student_id": f"{(int(base_payload['student_id']) + 3) % 100_000_000:08d}",
                    },
                ).status_code == 410

                set_actor(admin)
                assert client.get("/api/team-registration/admin/current").json() is None

            finally:
                app.dependency_overrides.clear()
                app.dependency_overrides.update(previous_overrides)

    finally:
        with SessionLocal() as db:
            if created_window_ids:
                db.execute(
                    delete(TeamRegistrationWindow).where(
                        TeamRegistrationWindow.id.in_(created_window_ids)
                    )
                )
            if created_member_ids:
                db.execute(
                    delete(MemberIdentityAudit).where(MemberIdentityAudit.member_id.in_(created_member_ids))
                )
                db.execute(delete(Member).where(Member.id.in_(created_member_ids)))
            db.commit()

    print("Team registration tests passed")


if __name__ == "__main__":
    main()
