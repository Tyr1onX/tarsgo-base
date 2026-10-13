"""Back up Compose MySQL + knowledge originals; restore only to an empty target."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = '''
from pathlib import Path
import sys, tarfile
root = Path("/opt/tarsgo-knowledge")
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise RuntimeError("Knowledge storage contains a non-regular entry")
        archive.add(path, arcname="knowledge/" + str(path.relative_to(root)), recursive=False)
'''
RESTORE_FILES = '''
from pathlib import Path
import sys, tarfile
root = Path("/opt/tarsgo-knowledge")
root.mkdir(parents=True, exist_ok=True)
if any(root.iterdir()):
    raise RuntimeError("Knowledge target is not empty")
with tarfile.open(fileobj=sys.stdin.buffer, mode="r|gz") as archive:
    for member in archive:
        parts = Path(member.name).parts
        if not parts or parts[0] != "knowledge" or ".." in parts or Path(member.name).is_absolute() or not (member.isfile() or member.isdir()):
            raise RuntimeError("Unsafe knowledge archive")
        member.name = str(Path(*parts[1:]))
        archive.extract(member, path=root, filter="data")
'''
CHECK_EMPTY_FILES = '''
from pathlib import Path
root = Path("/opt/tarsgo-knowledge")
if root.exists() and any(root.iterdir()):
    raise RuntimeError("Knowledge target is not empty")
'''


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_bundle(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format") != 1 or set(manifest.get("files", {})) != {"mysql.sql", "knowledge.tar.gz"}:
        raise ValueError("Unsupported or incomplete backup manifest")
    for name, digest in manifest["files"].items():
        path = directory / name
        if not path.is_file() or path.is_symlink() or checksum(path) != digest:
            raise ValueError(f"Backup checksum mismatch: {name}")
    with tarfile.open(directory / "knowledge.tar.gz", "r:gz") as archive:
        for member in archive:
            path = Path(member.name)
            if path.is_absolute() or not path.parts or path.parts[0] != "knowledge" or ".." in path.parts or not (member.isfile() or member.isdir()):
                raise ValueError("Unsafe knowledge archive")
    return manifest


class Compose:
    def __init__(self, project, env_file=None):
        self.command = ["docker", "compose", "--project-name", project]
        if env_file:
            self.command += ["--env-file", str(Path(env_file).resolve())]

    def run(self, *args, **kwargs):
        return subprocess.run(self.command + list(args), cwd=ROOT, check=True, **kwargs)

    def query(self, sql):
        command = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B "$MYSQL_DATABASE" -e "$1"'
        return self.run("exec", "-T", "db", "sh", "-c", command, "mysql-query", sql, capture_output=True, text=True).stdout.strip()

    def api_running(self):
        return bool(self.run("ps", "--status", "running", "-q", "api", capture_output=True, text=True).stdout.strip())

    def files(self, script, **kwargs):
        return self.run("run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "api", "-c", script, **kwargs)


def backup(compose, directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    resume = compose.api_running()
    try:
        if resume:
            compose.run("stop", "api", stdout=subprocess.DEVNULL)
        revision = compose.query("SELECT version_num FROM alembic_version")
        command = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob --default-character-set=utf8mb4 "$MYSQL_DATABASE"'
        with (directory / "mysql.sql").open("xb") as file:
            os.chmod(file.name, 0o600)
            compose.run("exec", "-T", "db", "sh", "-c", command, stdout=file)
        with (directory / "knowledge.tar.gz").open("xb") as file:
            os.chmod(file.name, 0o600)
            compose.files(ARCHIVE, stdout=file)
        manifest = {"format": 1, "created_at": datetime.now(timezone.utc).isoformat(), "alembic_revision": revision,
                    "files": {name: checksum(directory / name) for name in ("mysql.sql", "knowledge.tar.gz")}}
        (directory / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (directory / "manifest.json").chmod(0o600)
        validate_bundle(directory)
    finally:
        if resume:
            compose.run("start", "api", stdout=subprocess.DEVNULL)
    print("Backup completed and checksums verified.")


def restore(compose, directory):
    manifest = validate_bundle(directory)
    if compose.api_running():
        raise ValueError("Restore requires a stopped API and an empty target")
    count = compose.query("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()")
    if count != "0":
        raise ValueError("Refusing restore: target database is not empty")
    compose.files(CHECK_EMPTY_FILES, stdout=subprocess.DEVNULL)
    # Preconditions have been checked before either destination is modified.
    command = 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 "$MYSQL_DATABASE"'
    with (directory / "mysql.sql").open("rb") as file:
        compose.run("exec", "-T", "db", "sh", "-c", command, stdin=file)
    with (directory / "knowledge.tar.gz").open("rb") as file:
        compose.files(RESTORE_FILES, stdin=file, stdout=subprocess.DEVNULL)
    if compose.query("SELECT version_num FROM alembic_version") != manifest["alembic_revision"]:
        raise ValueError("Restored migration revision does not match the backup")
    print("Restore completed. API remains stopped; verify the target before starting it.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Explicit Compose project name")
    parser.add_argument("--env-file")
    parser.add_argument("action", choices=("backup", "restore", "verify"))
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    directory = args.directory.resolve()
    try:
        if directory.is_relative_to(ROOT):
            raise ValueError("Backup directory must be outside the public repository")
        if args.action == "verify":
            validate_bundle(directory)
            print("Backup checksums and archive paths verified.")
        else:
            compose = Compose(args.project, args.env_file)
            (backup if args.action == "backup" else restore)(compose, directory)
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        print(f"Backup operation failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
