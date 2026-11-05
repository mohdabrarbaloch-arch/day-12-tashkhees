# API Reference

Base URL: `http://127.0.0.1:8012`

All endpoints return JSON unless noted. Authenticated endpoints require
`Authorization: Bearer <token>`.

Errors use a consistent shape:

```json
{
  "error": "http_error",
  "detail": "Study not found",
  "request_id": "a1b2c3d4e5f6"
}
```

Validation errors add a `fields` array:

```json
{
  "error": "validation_error",
  "detail": "Request validation failed",
  "request_id": "a1b2c3d4e5f6",
  "fields": [{ "loc": ["body", "email"], "msg": "value is not a valid email address" }]
}
```

---

## Health

### `GET /api/health`

Liveness probe. Never raises.

```json
{
  "status": "ok",
  "app": "Tashkhees",
  "environment": "development",
  "engine": "deterministic-radiographic-measurement",
  "engine_version": "1.0.0",
  "database": "ok",
  "disclaimer": "This report was produced by an automated measurement tool..."
}
```

`status` is `degraded` when the database is unreachable.

### `GET /api/engine/reference-ranges`

The reference ranges the engine uses, so a client can render them without hardcoding.

```json
{
  "engine": "deterministic-radiographic-measurement",
  "version": "1.0.0",
  "ranges": [
    {
      "key": "cardiothoracic_ratio",
      "label": "Cardiothoracic ratio",
      "low": 0.0,
      "high": 0.5,
      "unit": "ratio",
      "breach_label": "Possible cardiomegaly"
    }
  ]
}
```

---

## Auth

### `POST /api/auth/register`

`201 Created`

```json
{ "email": "you@clinic.pk", "password": "secret123", "full_name": "Dr. Ayesha Khan" }
```

Password must be 8–128 characters with at least one letter and one digit.

Response:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "bearer",
  "expires_in": 86400,
  "user": { "id": 1, "email": "you@clinic.pk", "full_name": "Dr. Ayesha Khan", "role": "clinician", "created_at": "..." }
}
```

| Status | When |
|---|---|
| 201 | created |
| 409 | email already registered |
| 422 | validation failed (weak password, bad email) |
| 429 | rate limited (10/min) |

### `POST /api/auth/login`

`200 OK`. Same response shape as register.

| Status | When |
|---|---|
| 200 | success |
| 401 | wrong password **or** unknown email — deliberately identical |
| 429 | rate limited (10/min) |

### `GET /api/auth/me`

`200 OK` → the `user` object. `401` without a valid token.

---

## Studies

### `POST /api/studies`

`201 Created`. `multipart/form-data`.

| Field | Type | Required | Notes |
|---|---|---|---|
| `file` | file | yes | PNG / JPEG / WebP, ≤ 12 MB, ≥ 256 px |
| `patient_ref` | string | no | ≤ 64 chars |
| `view` | string | no | `PA` (default), `AP`, `LATERAL` |
| `notes` | string | no | ≤ 2000 chars |

```json
{
  "id": 1,
  "patient_ref": "PT-2026-0142",
  "view": "PA",
  "notes": "",
  "filename": "chest.png",
  "content_type": "image/png",
  "size_bytes": 184320,
  "width": 1024,
  "height": 1024,
  "created_at": "2026-11-06T00:12:00Z"
}
```

| Status | When |
|---|---|
| 201 | created |
| 400 | empty file, or bytes are not a decodable image |
| 413 | larger than `MAX_UPLOAD_BYTES` |
| 415 | content-type not in the allow-list |
| 422 | image smaller than `MIN_IMAGE_SIDE` |

### `GET /api/studies?limit=50&offset=0`

`200 OK` → `{ "total": 3, "items": [ ... ] }`. Scoped to the caller. `limit` is clamped to
1–200.

### `GET /api/studies/{id}`

`200 OK` → the study. `404` if it doesn't exist **or belongs to another user** — the two cases
are indistinguishable on purpose.

### `GET /api/studies/{id}/image`

`200 OK` → the stored image bytes with the original content-type. `410 Gone` if the file has
been removed from disk.

### `DELETE /api/studies/{id}`

`204 No Content`. Cascades to analyses and reports, and deletes the stored file.

---

## Analysis

### `POST /api/analysis/{study_id}`

`201 Created`. Runs the engine and persists the findings.

```json
{
  "id": 1,
  "study_id": 1,
  "engine": "deterministic-radiographic-measurement",
  "engine_version": "1.0.0",
  "quality_score": 0.85,
  "summary": "1 parameter(s) outside reference range: cardiothoracic ratio.",
  "abnormal_count": 1,
  "overall_confidence": 0.78,
  "created_at": "...",
  "findings": [
    {
      "key": "cardiothoracic_ratio",
      "label": "Cardiothoracic ratio",
      "value": 0.52,
      "unit": "ratio",
      "ref_low": 0.0,
      "ref_high": 0.5,
      "flag": "high",
      "confidence": 0.78,
      "note": "The cardiac silhouette occupies more than half the thoracic width..."
    }
  ]
}
```

| Status | When |
|---|---|
| 201 | analysed |
| 404 | study not found or not yours |
| 410 | stored image missing |
| 422 | image could not be decoded |
| 429 | rate limited (20/min) |

### `GET /api/analysis/{study_id}`

`200 OK` → the most recent analysis. `404` if none has been run.

### `GET /api/analysis/{study_id}/all`

`200 OK` → every analysis for the study, oldest first.

### `GET /api/analysis/{study_id}/overlay`

`200 OK` → `image/png`. The radiograph with the segmented lung fields tinted (blue = left,
amber = right). This is what the engine measured.

---

## Reports

### `POST /api/reports/{study_id}`

`201 Created`. Composes a report from the study's latest analysis.

```json
{
  "id": 1,
  "study_id": 1,
  "analysis_id": 1,
  "title": "Chest Radiograph — Automated Measurement Report",
  "impression": "Cardiothoracic ratio measures 0.52 (ratio), above the reference range of 0.00–0.50 — possible cardiomegaly. ...",
  "findings_text": "Cardiothoracic ratio: 0.52 ratio (ref 0.00–0.50) — HIGH [confidence 78%]\n...",
  "technique": "Automated analysis of a 1024×1024 px chest radiograph. ...",
  "disclaimer": "This report was produced by an automated measurement tool...",
  "abnormal_count": 1,
  "overall_confidence": 0.78,
  "created_at": "..."
}
```

| Status | When |
|---|---|
| 201 | generated |
| 404 | study not found or not yours |
| 409 | no analysis exists yet — run one first |

### `GET /api/reports/{study_id}`

`200 OK` → the most recent report. `404` if none exists.

### `GET /api/reports/{study_id}/all`

`200 OK` → every report for the study, oldest first.

---

## Rate limits

| Scope | Default |
|---|---|
| `/api/auth/*` | 10 / minute |
| `/api/analysis/*` | 20 / minute |
| everything else under `/api` | 120 / minute |

Exceeding a limit returns `429` with a `Retry-After` header.

## Security headers

Every response carries:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Permissions-Policy: geolocation=(), microphone=(), camera=(self)
Cross-Origin-Opener-Policy: same-origin
X-Request-ID: <12 hex chars>
```

Quote the `X-Request-ID` when reporting a problem — it's in the server log line for that
request.
