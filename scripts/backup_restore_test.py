"""Cold restore drill on a fresh CI Compose project, never the source volume."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from backup import Compose, ROOT, backup, restore

SNAPSHOT = '''
import hashlib, json
from pathlib import Path
from sqlalchemy import text
from app.db import engine
from app.models import Member
with engine.connect() as db:
    tables = sorted(db.execute(text("SHOW TABLES")).scalars().all())
    snapshot = {}
    counts = {}
    for name in tables:
        rows = [dict(row) for row in db.execute(text("SELECT * FROM `" + name + "`")).mappings()]
        snapshot[name] = sorted(json.dumps(row, sort_keys=True, default=str, ensure_ascii=False) for row in rows)
        counts[name] = len(rows)
payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode()
root = Path("/opt/tarsgo-knowledge")
files = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}
print(json.dumps({"database_sha256": hashlib.sha256(payload).hexdigest(), "tables": counts, "knowledge_files": files}, sort_keys=True))
'''


def snapshot(compose):
    result = compose.run("run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "api", "-c", SNAPSHOT, capture_output=True, text=True)
    return json.loads(result.stdout)


def main():
    source_project = os.environ["COMPOSE_PROJECT_NAME"]
    source = Compose(source_project)
    with tempfile.TemporaryDirectory(prefix="tarsgo-restore-") as temp:
        directory = Path(temp)
        target = Compose(source_project + "-restore")
        original_storage = os.environ.get("KNOWLEDGE_STORAGE_HOST_DIR")
        # A fictional uploaded original ensures both indexed text and binary
        # source bytes are exercised, even when previous tests cleaned up.
        fixture = '''
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Member
from app.knowledge import create_uploaded_document
with SessionLocal() as db:
    admin = db.scalar(select(Member).where(Member.email == "admin@example.com"))
    create_uploaded_document(db, created_by=admin.id, filename="restore-fixture.md", data="# 恢复演练\\n这是虚构活动资料。".encode())
'''
        source.run("exec", "-T", "api", "python", "-c", fixture, stdout=subprocess.DEVNULL)
        expected = snapshot(source)
        backup(source, directory / "bundle")
        try:
            os.environ["KNOWLEDGE_STORAGE_HOST_DIR"] = str(directory / "restored-knowledge")
            target.run("up", "-d", "--wait", "db", stdout=subprocess.DEVNULL)
            target.run("build", "api", stdout=subprocess.DEVNULL)
            restore(target, directory / "bundle")
            actual = snapshot(target)
            assert actual == expected, "Database rows or knowledge original bytes changed during restore"
            try:
                restore(target, directory / "bundle")
            except ValueError as error:
                assert "not empty" in str(error)
            else:
                raise AssertionError("Restore must refuse an occupied destination")
            target.run("up", "-d", "--no-deps", "--wait", "api", stdout=subprocess.DEVNULL)
            login_check = '''
import json, os, urllib.request
body = json.dumps({"email": "admin@example.com", "password": os.environ["CI_ADMIN_PASSWORD"]}).encode()
request = urllib.request.Request("http://127.0.0.1:8000/api/auth/login", data=body, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(request) as response:
    assert response.status == 200
    assert json.load(response)["role"] == "admin"
'''
            target.run("exec", "-T", "-e", "CI_ADMIN_PASSWORD", "api", "python", "-c", login_check, stdout=subprocess.DEVNULL)
            report = {"passed": True, "database": "MySQL 8.4", "fresh_volume": True, "checks": ["all database rows identical", "all knowledge originals identical", "migration revision preserved", "occupied target refused", "restored API starts", "restored administrator can log in"], "tables": expected["tables"], "knowledge_original_count": len(expected["knowledge_files"])}
            (ROOT / "backup-restore-report.json").write_text(json.dumps(report, indent=2) + "\n")
            print("Cold MySQL restore drill passed: all rows and knowledge files match; restored login works")
        finally:
            try:
                target.run("stop", "api", stdout=subprocess.DEVNULL)
                if (directory / "restored-knowledge").exists():
                    # Originals are intentionally root-owned 0600/0700 in the
                    # API container. Remove only this drill's mounted target
                    # from that container before host temp cleanup.
                    target.files('''
from pathlib import Path
import shutil
root = Path("/opt/tarsgo-knowledge")
for path in root.iterdir():
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
root.chmod(0o755)
''', stdout=subprocess.DEVNULL)
            finally:
                target.run("down", "--volumes", stdout=subprocess.DEVNULL)
                if original_storage is None:
                    os.environ.pop("KNOWLEDGE_STORAGE_HOST_DIR", None)
                else:
                    os.environ["KNOWLEDGE_STORAGE_HOST_DIR"] = original_storage


if __name__ == "__main__":
    main()
