"""Cloud is a separate read-only demo, never an online trading shortcut."""
import importlib
import os
import re
import unittest
from unittest.mock import patch

ENV = {"DDM_CLOUD_USER": "jesaias\n", "DDM_CLOUD_PASS": "test-only-long-cloud-password\n",
       "DDM_CLOUD_SESSION_SECRET": "test-only-session-secret-more-than-32-characters\n"}
BASE = "https://example.vercel.app"


class CloudTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ, ENV):
            self.module = importlib.import_module("cloud.server")
            self.app = self.module.create_app()
        self.client = self.app.test_client()
        response = self.client.get("/login", base_url=BASE)
        self.csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)

    def login(self, password="test-only-long-cloud-password"):
        return self.client.post("/login", data={"username": "jesaias", "password": password,
                                                "csrf_token": self.csrf}, base_url=BASE)

    def test_no_default_cloud_password(self):
        self.assertEqual(self.login("miebs112").status_code, 200)
        self.assertEqual(self.client.get("/api/terminal/overview", base_url=BASE).status_code, 401)
        with patch.dict(os.environ, {"DDM_CLOUD_PASS": "", "DDM_CLOUD_SESSION_SECRET": ""}):
            with self.assertRaises(RuntimeError):
                self.module.create_app()

    def test_login_and_demo_without_network_or_database(self):
        self.assertEqual(self.login().status_code, 302)
        with patch.object(self.module.feeds.requests, "get", side_effect=AssertionError("Network forbidden")), patch.object(self.module.intelligence.database, "connection", side_effect=AssertionError("DB forbidden")):
            response = self.client.get("/api/terminal/overview", base_url=BASE)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["deployment"], "READ_ONLY_DEMO")
            self.assertEqual(response.json["account"]["equity"], 0)
            self.assertTrue(response.json["opportunities"])
            detail = self.client.get("/api/terminal/decisions/1?mode=DEMO", base_url=BASE)
            self.assertEqual(detail.status_code, 200)
        page = self.client.get("/", base_url=BASE)
        self.assertIn('data-cloud-readonly="true"', page.text)
        self.assertIn("ONLINE-DEMO", page.text)

    def test_all_money_and_secret_mutations_are_blocked(self):
        self.login()
        with self.client.session_transaction() as session:
            session["csrf"] = "test-csrf"
        for path in ("/api/live/cycle", "/api/live/flatten", "/api/scheduler/start", "/api/settings", "/api/terminal/deposit", "/api/terminal/bets", "/api/terminal/lab/results", "/api/terminal/settle"):
            result = self.client.post(path, json={}, headers={"X-CSRF-Token": "test-csrf"}, base_url=BASE)
            self.assertEqual(result.status_code, 403, path)
        self.assertEqual(self.client.post("/api/terminal/scan", json={"mode": "DEMO"}, base_url=BASE).status_code, 403)
        self.assertEqual(self.client.get("/api/terminal/overview?mode=REAL", base_url=BASE).status_code, 400)

    def test_secure_cookie_and_no_secret_echo(self):
        response = self.login()
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        configuration = self.client.get("/api/settings", base_url=BASE)
        self.assertEqual(configuration.status_code, 200)
        self.assertTrue(all(not p["configured"] and not p["active"] for p in configuration.json["providers"]))
        self.assertNotIn("test-only-long-cloud-password", configuration.text)
