import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix" and os.environ.get("DEPLOY_TEST_ROOT"),
                     "Deployment shell simulation runs on Linux CI")
class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.environ["DEPLOY_TEST_ROOT"])
        self.root.mkdir(exist_ok=True)
        for child in self.root.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        self.release = self.root / "release"
        shutil.copytree(SOURCE, self.release, ignore=shutil.ignore_patterns(".git", ".runtime", ".tools", "reports", "__pycache__"))
        config = self.root / "config"
        config.mkdir()
        for name in ("backend", "frontend", "postgres", "migration"):
            (config / (name + ".env")).write_text("TEST=true\n")
        (config / "deploy.env").write_text("APP_DOMAIN=womanup.uz\n")
        shutil.copytree(config, self.root / "config.previous")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        shutil.copy(SOURCE / "tests/mock-docker.py", self.bin / "docker")
        (self.bin / "docker").chmod(0o755)
        (self.bin / "curl").write_text("#!/bin/sh\nexit 0\n")
        (self.bin / "curl").chmod(0o755)
        self.env = dict(os.environ, MOCK_ROOT=str(self.root), RELEASE=str(self.release),
                        PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.image("backend", "a")
        self.image("frontend", "b")

    def image(self, app, digit):
        value = f"ghcr.io/womenup-d/{app}@sha256:" + digit * 64
        path = self.release / "apps" / app / "image.env"
        path.write_text(f"{app.upper()}_IMAGE={value}\n{app.upper()}_VERSION={app}-" + digit * 40 + "\n")
        return value

    def run_deploy(self, success=True, **env):
        result = subprocess.run(["bash", str(self.release / "scripts/deploy.sh"), str(self.root)],
                                env=self.env | env, text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def commands(self):
        return [json.loads(line) for line in (self.root / "commands.jsonl").read_text().splitlines()]

    def test_first_deploy_and_unchanged_rerun(self):
        self.run_deploy()
        self.assertTrue((self.root / "state/backend.hash").exists())
        (self.root / "commands.jsonl").write_text("")
        self.run_deploy()
        self.assertFalse(any("up" in c["args"] for c in self.commands()))

    def test_frontend_update_does_not_restart_backend_or_database(self):
        self.run_deploy()
        self.image("frontend", "c")
        (self.root / "commands.jsonl").write_text("")
        self.run_deploy()
        ups = [c for c in self.commands() if "up" in c["args"]]
        self.assertEqual(len(ups), 1)
        self.assertEqual(ups[0]["args"][-1], "frontend")

    def test_failed_frontend_restores_previous_image(self):
        self.run_deploy()
        bad = self.image("frontend", "c")
        result = self.run_deploy(success=False, MOCK_FAIL_IMAGE=bad)
        self.assertIn("Previous frontend restored", result.stderr)
        self.assertIn("b" * 64, (self.root / "state/frontend.env").read_text())
        self.assertFalse((self.root / "state/frontend.hash").exists())

    def test_failed_backend_with_same_schema_rolls_back(self):
        self.run_deploy()
        bad = self.image("backend", "c")
        result = self.run_deploy(success=False, MOCK_FAIL_IMAGE=bad)
        self.assertIn("Previous backend restored", result.stderr)
        self.assertIn("a" * 64, (self.root / "state/backend.env").read_text())

    def test_changed_schema_prevents_automatic_rollback(self):
        self.run_deploy()
        bad = self.image("backend", "c")
        result = self.run_deploy(success=False, MOCK_FAIL_IMAGE=bad, MOCK_NEW_SCHEMA="0013")
        self.assertIn("Automatic rollback unavailable", result.stderr)
        self.assertFalse((self.root / "state/backend.hash").exists())

    def test_failed_migration_does_not_mark_release_successful(self):
        self.run_deploy()
        self.image("backend", "c")
        result = self.run_deploy(success=False, MOCK_MIGRATION_FAIL="1")
        self.assertIn("Migration failed", result.stderr)
        self.assertIn("a" * 64, (self.root / "state/backend.env").read_text())
        self.assertFalse((self.root / "state/backend.hash").exists())
