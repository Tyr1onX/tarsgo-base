from getpass import getpass

from sqlalchemy import select

from .auth import hash_password
from .db import SessionLocal
from .models import Member
from .schemas import normalize_email


def main() -> None:
    name = input("管理员姓名: ").strip()
    email = normalize_email(input("管理员邮箱: "))
    password = getpass("管理员密码（至少 8 位）: ")
    confirm = getpass("再次输入密码: ")

    if not name:
        raise SystemExit("姓名不能为空")
    if len(password) < 8 or len(password) > 128:
        raise SystemExit("密码长度必须为 8-128 位")
    if password != confirm:
        raise SystemExit("两次密码不一致")

    with SessionLocal() as db:
        if db.scalar(select(Member.id).where(Member.email == email)) is not None:
            raise SystemExit("该邮箱已存在")
        member = Member(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role="admin",
            status="active",
            identity_locked=True,
        )
        db.add(member)
        db.commit()

    print("管理员已创建")


if __name__ == "__main__":
    main()
