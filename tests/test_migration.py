"""Configuration and recovery safeguards, with no production connections."""
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup
import database
import preflight
from render_config import render


def environment():
    return {"APP_DOMAIN": "womanup.uz", "DB_HOST": "postgres", "DB_PORT": "5432",
            "DB_NAME": "womanup_db", "DB_USER": "womanup_user",
            "DB_NETWORK": "infrastructure_database", "INGRESS_NETWORK": "agrozanjir_web",
            "POSTGRES_PASSWORD": "test-" + "x" * 32, "JWT_SECRET_KEY": "x" * 64}


class ConfigTests(unittest.TestCase):
    def render(self, changes=None):
        env = environment() | (changes or {})
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, env, clear=True):
            render(Path(directory))
            return {path.name: dict(line.split("=", 1) for line in path.read_text().splitlines())
                    for path in Path(directory).iterdir()}

    def test_shared_database_and_no_administrator_configuration(self):
        files = self.render()
        self.assertEqual(set(files), {"backend.env", "database.env", "frontend.env", "deploy.env"})
        url = urlsplit(files["backend.env"]["DATABASE_URL"])
        self.assertEqual((url.hostname, url.port, url.username, url.path),
                         ("postgres", 5432, "womanup_user", "/womanup_db"))
        self.assertNotIn("POSTGRES_PASSWORD", files["backend.env"])
        self.assertEqual(files["database.env"]["DB_USER"], "womanup_user")

    def test_application_password_is_encoded_without_hex_restriction(self):
        password = "test:@/?#%$'\"\\ =" + "x" * 12
        files = self.render({"POSTGRES_PASSWORD": password})
        self.assertEqual(unquote(urlsplit(files["backend.env"]["DATABASE_URL"]).password), password)
        self.assertEqual(files["database.env"]["POSTGRES_PASSWORD"], password)

    def test_invalid_or_missing_database_configuration_fails(self):
        for key, value in (("DB_HOST", ""), ("DB_HOST", "host/path"), ("DB_PORT", "0"),
                           ("DB_PORT", "65536"), ("DB_PORT", "abc"), ("DB_NAME", "postgres"),
                           ("DB_NAME", "agrozanjir_db"), ("DB_USER", "postgres"),
                           ("DB_NETWORK", ""), ("INGRESS_NETWORK", "bad network"),
                           ("POSTGRES_PASSWORD", ""), ("POSTGRES_PASSWORD", "bad\npassword")):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.render({key: value})

    def test_frontend_cannot_receive_database_credentials(self):
        files = self.render()
        self.assertFalse(any(key.startswith("DB_") or "PASSWORD" in key
                             for key in files["frontend.env"]))


class DatabaseTests(unittest.TestCase):
    def test_password_never_appears_in_command_arguments(self):
        values = environment()
        command = database.command(values, "psql", "-d", values["DB_NAME"])
        self.assertNotIn(values["POSTGRES_PASSWORD"], " ".join(command))
        self.assertIn("womanup_user", command)
        self.assertIn("infrastructure-postgres-postgres-1", command)

    def test_preflight_requires_existing_extensions_and_unprivileged_owner(self):
        for identity, extensions, success in (
            ("womanup_db|womanup_user|t|t|t", "plpgsql\nvector\npg_trgm\nuuid-ossp", True),
            ("womanup_db|womanup_user|t|t|t", "plpgsql", False),
            ("womanup_db|womanup_user|t|f|t", "vector\npg_trgm\nuuid-ossp", False),
            ("womanup_db|womanup_user|f|t|t", "vector\npg_trgm\nuuid-ossp", False),
        ):
            with self.subTest(identity=identity, extensions=extensions), \
                    patch.object(database, "query", side_effect=[identity, extensions]):
                if success:
                    database.preflight(environment())
                else:
                    with self.assertRaises(RuntimeError):
                        database.preflight(environment())

    def test_settings_reject_another_tenant(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "database.env").write_text("DB_NAME=agrozanjir_db\nDB_USER=agrozanjir_user\n")
            with self.assertRaises(ValueError):
                database.settings(path)


class RecoveryTests(unittest.TestCase):
    def test_media_archive_rejects_traversal_links_and_special_files(self):
        for name, kind in (("../outside", tarfile.REGTYPE), ("/etc/passwd", tarfile.REGTYPE),
                           ("media/link", tarfile.SYMTYPE), ("media/hard", tarfile.LNKTYPE),
                           ("media/pipe", tarfile.FIFOTYPE)):
            with self.subTest(name=name, kind=kind), io.BytesIO() as stream:
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    archive.addfile(member)
                stream.seek(0)
                with tarfile.open(fileobj=stream) as archive, self.assertRaises(ValueError):
                    backup.media_members(archive)

    def test_media_archive_accepts_regular_project_files(self):
        with io.BytesIO() as stream:
            with tarfile.open(fileobj=stream, mode="w") as archive:
                archive.addfile(tarfile.TarInfo("media/photo.png"))
            stream.seek(0)
            with tarfile.open(fileobj=stream) as archive:
                self.assertEqual(len(backup.media_members(archive)), 1)

    def test_wrong_tenant_manifest_fails_before_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "manifest.json").write_text(json.dumps({"database": "agrozanjir_db"}))
            with patch.object(backup, "database") as access, self.assertRaises(ValueError):
                backup.restore(path, path)
            access.assert_not_called()


    def test_corrupt_snapshot_fails_before_database_access(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "database.dump").write_bytes(b"corrupt")
            (path / "manifest.json").write_text(json.dumps({
                "database": "womanup_db", "role": "womanup_user", "schema": "public",
                "media": "local-only", "sha256": {"database.dump": "incorrect"}}))
            with patch.object(backup, "database") as access, self.assertRaises(ValueError):
                backup.restore(path, path)
            access.assert_not_called()


class HostIsolationTests(unittest.TestCase):
    def check(self, containers=None, aliases=None, project="other", project_ids=""):
        network = {"Name": "ingress", "Containers": containers or {}}
        db = {"Name": "database", "Containers": {"db": {"Name": database.CONTAINER}}}
        inspected = {"Config": {"Labels": {"com.docker.compose.project": project,
                     "com.docker.compose.project.working_dir": "/opt/another-app"}},
                     "NetworkSettings": {"Networks": {"ingress": {"Aliases": aliases or []}}}}
        with patch.object(Path, "read_text", return_value="DB_NETWORK=database\nINGRESS_NETWORK=ingress\n"), \
                patch.object(Path, "is_symlink", return_value=False), \
                patch.object(preflight, "inspect", side_effect=[[db], [network], [inspected]]), \
                patch.object(preflight.subprocess, "check_output", return_value=project_ids):
            preflight.check(Path("/opt/womanup"))

    @unittest.skipIf(os.name == "nt", "Host path checks run on Linux")
    def test_alias_collision_fails(self):
        with self.assertRaises(ValueError):
            self.check(containers={"another": {}}, aliases=["womanup-proxy"])

    @unittest.skipIf(os.name == "nt", "Host path checks run on Linux")
    def test_compose_project_outside_root_fails(self):
        with self.assertRaises(ValueError):
            self.check(project_ids="existing-container")

    @unittest.skipIf(os.name == "nt", "Host path checks run on Linux")
    def test_available_shared_networks_pass(self):
        self.check()



if __name__ == "__main__":
    unittest.main()
