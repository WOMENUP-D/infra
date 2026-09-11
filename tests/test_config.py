import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


render = module("render_config").render
read_image = module("validate_images").read_image


class ConfigTests(unittest.TestCase):
    def test_render_keeps_secrets_out_of_frontend(self):
        values = {
            "APP_DOMAIN": "womanup.uz",
            "POSTGRES_PASSWORD": "a" * 64,
            "MIGRATION_DB_PASSWORD": "b" * 64,
            "APP_DB_PASSWORD": "c" * 64,
            "BACKEND_SECRETS_JSON": '{"JWT_SECRET_KEY":"' + "s" * 64 + '","FIREBASE_PRIVATE_KEY":"line1\\nline2","SMTP_PASSWORD":"dollar$quote\'"}',
            "BACKEND_VARS_JSON": '{"NEWS_INGEST_ENABLED":false,"CORS_ORIGINS":"https://wrong.example"}',
            "FIREBASE_WEB_PROJECT_ID": "public-project",
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, values, clear=True):
            out = Path(tmp)
            render(out)
            backend = (out / "backend.env").read_text()
            frontend = (out / "frontend.env").read_text()
            self.assertIn("ENVIRONMENT=production", backend)
            self.assertIn("CORS_ORIGINS=https://womanup.uz", backend)
            self.assertIn(r"FIREBASE_PRIVATE_KEY=line1\nline2", backend)
            self.assertIn("SMTP_PASSWORD=dollar$quote'", backend)
            self.assertIn("FIREBASE_WEB_PROJECT_ID=public-project", frontend)
            self.assertNotIn("JWT", frontend)
            self.assertNotIn("PRIVATE_KEY", frontend)
            self.assertNotIn("s" * 64, frontend)

    def test_rejects_missing_secret_and_domain_injection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                render(Path(tmp))
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"APP_DOMAIN": "example.com\nEVIL=1"}, clear=True):
            with self.assertRaises(ValueError):
                render(Path(tmp))

    def test_image_contract_and_injection_rejection(self):
        valid = "BACKEND_IMAGE=ghcr.io/womenup-d/backend@sha256:" + "a" * 64 + "\nBACKEND_VERSION=backend-" + "b" * 40 + "\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.env"
            path.write_text(valid)
            self.assertEqual(len(read_image(path, "backend")), 2)
            for invalid in (
                valid.replace("@sha256:" + "a" * 64, ":latest"),
                valid.replace("womenup-d", "attacker"),
                valid + "EXTRA=$(id)\n",
                valid.replace("backend-" + "b" * 40, "backend-short"),
            ):
                path.write_text(invalid)
                with self.assertRaises(ValueError):
                    read_image(path, "backend")
            path.write_text("# waiting for first release\n")
            self.assertEqual(read_image(path, "backend"), {})
