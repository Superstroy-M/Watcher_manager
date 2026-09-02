"""Тесты веб-авторизации дашборда."""


class TestDashboardAuth:

    def test_anonymous_redirected_from_dashboard(self, anon_client):
        r = anon_client.get("/", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login?next=")

    def test_anonymous_api_returns_401(self, anon_client):
        r = anon_client.get("/api/computers")
        assert r.status_code == 401

    def test_login_success(self, anon_client):
        r = anon_client.post(
            "/login",
            data={"username": "administrator", "password": "superwatcher", "next": "/live"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"] == "/live"

        r2 = anon_client.get("/live")
        assert r2.status_code == 200

    def test_login_wrong_password(self, anon_client):
        r = anon_client.post(
            "/login",
            data={"username": "administrator", "password": "wrong", "next": "/"},
            follow_redirects=False,
        )
        assert r.status_code == 401
        assert "Неверный логин или пароль" in r.text

    def test_logout_clears_session(self, client):
        r = client.get("/logout", follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

        r2 = client.get("/api/computers")
        assert r2.status_code == 401

    def test_api_key_allows_dashboard_api(self, anon_client):
        r = anon_client.get("/api/computers", headers={"X-API-Key": "test-key-123"})
        assert r.status_code == 200

    def test_health_is_public(self, anon_client):
        r = anon_client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_agent_heartbeat_still_public(self, anon_client):
        r = anon_client.post(
            "/api/heartbeat",
            json={"hostname": "auth-test-pc"},
            headers={"X-API-Key": "test-key-123"},
        )
        assert r.status_code == 200
