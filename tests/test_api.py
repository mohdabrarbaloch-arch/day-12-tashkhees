"""End-to-end API tests: auth, upload, analysis, reports, security."""

from __future__ import annotations

from tests.conftest import make_radiograph, png_bytes

# --------------------------------------------------------------------------
# Health
# --------------------------------------------------------------------------


def test_health_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert "NOT a medical device" in body["disclaimer"]


def test_reference_ranges_endpoint(client):
    resp = client.get("/api/engine/reference-ranges")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["ranges"]) >= 6
    assert all("key" in r and "low" in r and "high" in r for r in body["ranges"])


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------


def test_register_returns_token_and_user(client):
    resp = client.post(
        "/api/auth/register",
        json={"email": "a@b.pk", "password": "secret123", "full_name": "A B"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["access_token"]
    assert body["user"]["email"] == "a@b.pk"
    assert "password" not in body["user"]


def test_register_rejects_weak_password(client):
    resp = client.post("/api/auth/register", json={"email": "a@b.pk", "password": "allletters"})
    assert resp.status_code == 422


def test_register_rejects_duplicate_email(client):
    payload = {"email": "dup@b.pk", "password": "secret123"}
    assert client.post("/api/auth/register", json=payload).status_code == 201
    assert client.post("/api/auth/register", json=payload).status_code == 409


def test_login_succeeds_with_correct_password(client):
    client.post("/api/auth/register", json={"email": "l@b.pk", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"email": "l@b.pk", "password": "secret123"})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_login_fails_with_wrong_password(client):
    client.post("/api/auth/register", json={"email": "w@b.pk", "password": "secret123"})
    resp = client.post("/api/auth/login", json={"email": "w@b.pk", "password": "wrongpass1"})
    assert resp.status_code == 401


def test_login_unknown_user_is_401_not_404(client):
    resp = client.post("/api/auth/login", json={"email": "nobody@b.pk", "password": "secret123"})
    assert resp.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_profile(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "tester@tashkhees.pk"


def test_invalid_token_is_rejected(client):
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------
# Studies
# --------------------------------------------------------------------------


def test_upload_requires_auth(client):
    files = {"file": ("x.png", png_bytes(make_radiograph(300, 300)), "image/png")}
    assert client.post("/api/studies", files=files).status_code == 401


def test_upload_creates_study(client, auth_headers):
    files = {"file": ("chest.png", png_bytes(make_radiograph(400, 400)), "image/png")}
    resp = client.post(
        "/api/studies",
        files=files,
        data={"patient_ref": "PT-001", "view": "PA"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["patient_ref"] == "PT-001"
    assert body["width"] == 400 and body["height"] == 400
    assert body["size_bytes"] > 0


def test_upload_rejects_non_image_content_type(client, auth_headers):
    files = {"file": ("x.txt", b"hello", "text/plain")}
    resp = client.post("/api/studies", files=files, headers=auth_headers)
    assert resp.status_code == 415


def test_upload_rejects_renamed_non_image(client, auth_headers):
    files = {"file": ("fake.png", b"this is not a png at all", "image/png")}
    resp = client.post("/api/studies", files=files, headers=auth_headers)
    assert resp.status_code == 400


def test_upload_rejects_tiny_image(client, auth_headers):
    files = {"file": ("tiny.png", png_bytes(make_radiograph(64, 64)), "image/png")}
    resp = client.post("/api/studies", files=files, headers=auth_headers)
    assert resp.status_code == 422


def test_list_studies_is_scoped_to_owner(client, auth_headers):
    files = {"file": ("a.png", png_bytes(make_radiograph(300, 300)), "image/png")}
    client.post("/api/studies", files=files, headers=auth_headers)
    resp = client.get("/api/studies", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_study_image_is_served(client, auth_headers):
    files = {"file": ("a.png", png_bytes(make_radiograph(300, 300)), "image/png")}
    sid = client.post("/api/studies", files=files, headers=auth_headers).json()["id"]
    resp = client.get(f"/api/studies/{sid}/image", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_other_user_cannot_read_study(client, auth_headers):
    files = {"file": ("a.png", png_bytes(make_radiograph(300, 300)), "image/png")}
    sid = client.post("/api/studies", files=files, headers=auth_headers).json()["id"]

    other = client.post("/api/auth/register", json={"email": "other@b.pk", "password": "secret123"}).json()[
        "access_token"
    ]
    resp = client.get(f"/api/studies/{sid}", headers={"Authorization": f"Bearer {other}"})
    assert resp.status_code == 404


def test_delete_study_removes_it(client, auth_headers):
    files = {"file": ("a.png", png_bytes(make_radiograph(300, 300)), "image/png")}
    sid = client.post("/api/studies", files=files, headers=auth_headers).json()["id"]
    assert client.delete(f"/api/studies/{sid}", headers=auth_headers).status_code == 204
    assert client.get(f"/api/studies/{sid}", headers=auth_headers).status_code == 404


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _upload(client, headers, **kwargs):
    files = {"file": ("a.png", png_bytes(make_radiograph(400, 400, **kwargs)), "image/png")}
    return client.post("/api/studies", files=files, headers=headers).json()["id"]


def test_analysis_creates_findings(client, auth_headers):
    sid = _upload(client, auth_headers)
    resp = client.post(f"/api/analysis/{sid}", headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert len(body["findings"]) >= 6
    assert body["engine"]
    assert 0.0 <= body["overall_confidence"] <= 1.0


def test_analysis_404_for_unknown_study(client, auth_headers):
    assert client.post("/api/analysis/9999", headers=auth_headers).status_code == 404


def test_latest_analysis_404_before_running(client, auth_headers):
    sid = _upload(client, auth_headers)
    assert client.get(f"/api/analysis/{sid}", headers=auth_headers).status_code == 404


def test_latest_analysis_returns_result(client, auth_headers):
    sid = _upload(client, auth_headers)
    client.post(f"/api/analysis/{sid}", headers=auth_headers)
    resp = client.get(f"/api/analysis/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["study_id"] == sid


def test_reanalysis_appends_a_second_run(client, auth_headers):
    sid = _upload(client, auth_headers)
    client.post(f"/api/analysis/{sid}", headers=auth_headers)
    client.post(f"/api/analysis/{sid}", headers=auth_headers)
    resp = client.get(f"/api/analysis/{sid}/all", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_overlay_returns_png(client, auth_headers):
    sid = _upload(client, auth_headers)
    resp = client.get(f"/api/analysis/{sid}/overlay", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"


# --------------------------------------------------------------------------
# Reports
# --------------------------------------------------------------------------


def test_report_requires_analysis_first(client, auth_headers):
    sid = _upload(client, auth_headers)
    assert client.post(f"/api/reports/{sid}", headers=auth_headers).status_code == 409


def test_report_generation_includes_disclaimer(client, auth_headers):
    sid = _upload(client, auth_headers)
    client.post(f"/api/analysis/{sid}", headers=auth_headers)
    resp = client.post(f"/api/reports/{sid}", headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert "NOT a medical device" in body["disclaimer"]
    assert body["impression"]
    assert body["findings_text"]


def test_latest_report_returns_most_recent(client, auth_headers):
    sid = _upload(client, auth_headers)
    client.post(f"/api/analysis/{sid}", headers=auth_headers)
    client.post(f"/api/reports/{sid}", headers=auth_headers)
    resp = client.get(f"/api/reports/{sid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["study_id"] == sid


# --------------------------------------------------------------------------
# Security headers
# --------------------------------------------------------------------------


def test_security_headers_present(client):
    resp = client.get("/api/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "X-Request-ID" in resp.headers


def test_validation_error_shape(client):
    resp = client.post("/api/auth/register", json={"email": "not-an-email", "password": "x"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"] == "validation_error"
    assert "fields" in body
