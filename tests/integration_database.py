"""Opt-in local Docker test: migrations and project backup/restore, no host ports.

Run: WOMANUP_LOCAL_INTEGRATION=1 python3 tests/integration_database.py
Requires local desktop-linux context and the prebuilt backend image below.
No production connection or persistent Docker volume is used.
"""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backup
import database


def run(*args, data=None, capture=False):
    return subprocess.run(list(args), input=data, check=True,
                          stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                          stderr=subprocess.PIPE).stdout


def main():
    if os.environ.get("WOMANUP_LOCAL_INTEGRATION") != "1":
        raise RuntimeError("Opt in with WOMANUP_LOCAL_INTEGRATION=1")
    if run("docker", "context", "show", capture=True).decode().strip() != "desktop-linux":
        raise RuntimeError("Test requires the local desktop-linux Docker context")
    suffix = uuid.uuid4().hex[:10]
    container = "womanup-db-qa-" + suffix
    network = "womanup-db-qa-" + suffix
    password = secrets.token_urlsafe(32)
    root_repo = Path(__file__).resolve().parents[2]
    run("docker", "network", "create", "--internal", network)
    try:
        run("docker", "run", "--rm", "-d", "--name", container, "--network", network,
            "--tmpfs", "/var/lib/postgresql", "-e", "POSTGRES_PASSWORD=" + password,
            "pgvector/pgvector:pg18@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11")
        for attempt in range(60):
            if subprocess.run(["docker", "exec", container, "pg_isready", "-U", "postgres"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("Local QA database did not become ready")

        def admin(sql, db="postgres"):
            return run("docker", "exec", "-i", container, "psql", "-X", "-U", "postgres",
                       "-d", db, "-v", "ON_ERROR_STOP=1", "-At", data=sql.encode(), capture=True).decode().strip()

        admin(f"CREATE ROLE womanup_user LOGIN PASSWORD '{password}';"
              "CREATE DATABASE womanup_db OWNER womanup_user;"
              "CREATE DATABASE other_project_qa;")
        admin("CREATE TABLE sentinel (value text); INSERT INTO sentinel VALUES ('unchanged');", "other_project_qa")
        admin('CREATE EXTENSION vector; CREATE EXTENSION pg_trgm; CREATE EXTENSION "uuid-ossp";', "womanup_db")
        with tempfile.TemporaryDirectory(prefix="womanup-qa-") as directory, \
                patch.object(database, "CONTAINER", container):
            root = Path(directory)
            (root / "config").mkdir()
            (root / "data/media").mkdir(parents=True)
            values = {"DB_HOST": container, "DB_PORT": "5432", "DB_NAME": "womanup_db",
                      "DB_USER": "womanup_user", "POSTGRES_PASSWORD": password}
            (root / "config/database.env").write_text("".join(f"{k}={v}\n" for k, v in values.items()))
            database.preflight(values)
            print("PASS: TCP application login, owner privileges and required extensions")

            # Run the full real migration chain as the non-admin application role.
            run("docker", "run", "--rm", "--network", network,
                "-v", f"{root_repo / 'backend/app'}:/app/app:ro",
                "-v", f"{root_repo / 'backend/alembic'}:/app/alembic:ro",
                "-v", f"{root_repo / 'backend/alembic.ini'}:/app/alembic.ini:ro",
                "-e", f"DATABASE_URL=postgresql+asyncpg://womanup_user:{password}@{container}:5432/womanup_db",
                "womenup-backend-ci:python-3.14-alpine", "alembic", "upgrade", "head")
            revision = database.revision(values)
            assert revision, "Migration revision missing"
            print("PASS: full Alembic chain as womanup_user; revision " + revision)
            database.query(values, "CREATE TABLE backup_probe (id integer PRIMARY KEY, value text);"
                           "INSERT INTO backup_probe VALUES (1, 'original');")
            (root / "data/media/sample.txt").write_text("original media")

            def operation(unused_root, action, *options):
                with patch.object(sys, "argv", ["database.py", str(root / "config"), action, *map(str, options)]):
                    database.main()

            with patch.object(backup, "database", side_effect=operation):
                snapshot = backup.backup(root)
                database.query(values, "UPDATE backup_probe SET value='changed';")
                (root / "data/media/sample.txt").write_text("changed media")
                backup.restore(root, snapshot)
            assert database.query(values, "SELECT value FROM backup_probe WHERE id=1;") == "original"
            assert (root / "data/media/sample.txt").read_text() == "original media"
            assert list((root / "data").glob("media-before-*")), "Old media was not retained"
            assert database.revision(values) == revision
            assert admin("SELECT value FROM sentinel;", "other_project_qa") == "unchanged"
            assert admin("SELECT count(*) FROM pg_extension WHERE extname IN ('vector','pg_trgm','uuid-ossp');",
                         "womanup_db") == "3"
            assert admin("SELECT count(*) FROM pg_extension e JOIN pg_roles r ON e.extowner=r.oid "
                         "WHERE e.extname IN ('vector','pg_trgm','uuid-ossp') AND r.rolname='postgres';",
                         "womanup_db") == "3"
            print("PASS: database/media restored, old media retained, administrator-owned extensions and other database unchanged")
    finally:
        # Remove only the unique containers/network created by this local test.
        subprocess.run(["docker", "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
