"""Exercise corrupt archives and occupied restore targets without Docker."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock

from backup import checksum, restore, validate_bundle


class BackupSafetyTests(unittest.TestCase):
    def bundle(self, root, name="knowledge/sample.md", kind=tarfile.REGTYPE):
        (root / "mysql.sql").write_text("-- fictional test data\n")
        with tarfile.open(root / "knowledge.tar.gz", "w:gz") as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            content = b"fictional knowledge"
            member.size = len(content) if kind == tarfile.REGTYPE else 0
            if kind == tarfile.SYMTYPE:
                member.linkname = "/etc/passwd"
            archive.addfile(member, io.BytesIO(content) if member.size else None)
        (root / "manifest.json").write_text(json.dumps({"format": 1, "alembic_revision": "0009", "files": {n: checksum(root / n) for n in ("mysql.sql", "knowledge.tar.gz")}}))

    def test_valid_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.bundle(root)
            self.assertEqual(validate_bundle(root)["alembic_revision"], "0009")

    def test_corruption_rejected_before_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.bundle(root)
            (root / "mysql.sql").write_text("damaged")
            compose = Mock()
            with self.assertRaisesRegex(ValueError, "checksum"):
                restore(compose, root)
            compose.run.assert_not_called(); compose.query.assert_not_called()

    def test_unsafe_paths_and_links(self):
        for name, kind in [("knowledge/../../outside", tarfile.REGTYPE), ("/outside", tarfile.REGTYPE), ("knowledge/link", tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); self.bundle(root, name, kind)
                with self.assertRaisesRegex(ValueError, "Unsafe"):
                    validate_bundle(root)

    def test_occupied_database_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.bundle(root)
            compose = Mock(); compose.api_running.return_value = False; compose.query.return_value = "12"
            with self.assertRaisesRegex(ValueError, "not empty"):
                restore(compose, root)
            compose.run.assert_not_called(); compose.files.assert_not_called()

    def test_running_api_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self.bundle(root)
            compose = Mock(); compose.api_running.return_value = True
            with self.assertRaisesRegex(ValueError, "stopped API"):
                restore(compose, root)
            compose.run.assert_not_called(); compose.query.assert_not_called()


if __name__ == "__main__":
    unittest.main()
