# Tashkhees — Architecture

> **Tashkhees** (تشخیص) means *diagnosis* in Urdu.

Tashkhees is an AI-assisted chest radiograph triage and reporting platform. A clinician
uploads a chest X-ray, the system measures a set of **explicit, reproducible radiographic
features** from the image, flags the ones that fall outside reference ranges, and drafts a
structured report. Every number in the report is traceable to a measurement on the pixels —
there is no black box.

---

## 1. The honest framing (read this first)

**Tashkhees is not a medical device and is not for clinical use.** It is a portfolio-grade
engineering demonstration of an explainable medical-imaging pipeline.

The default analysis engine is a **deterministic image-analysis engine**, not a trained
diagnostic neural network. It computes real measurements — cardiothoracic ratio, regional
lung density, costophrenic density, exposure quality — using classical image processing.
Those measurements are genuine: the cardiothoracic ratio it reports is the same quantity a
radiologist measures with a ruler, computed from the actual pixels.

What it deliberately does **not** do is claim to detect pneumonia, nodules, or any specific
pathology from a learned model, because shipping a fake "AI diagnosis" would be dishonest.
Instead the engine exposes a **provider interface** (`app/engine/analyze.py`) so a real
trained model can be dropped in behind the same API without changing anything else.

This is the same design principle used across the challenge: *measure what you can actually
measure, label it honestly, and leave a clean seam for the real model.*

---

## 2. System diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser (mobile-first SPA, vanilla JS, no build step)               │
│  index.html · app.js · styles.css                                    │
│  · login / register        · upload study (drag-drop + camera)       │
│  · study list              · analysis viewer (image + overlay)       │
│  · findings table          · report view / print                     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  fetch() + Bearer JWT
                                ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI application (app/main.py)                                   │
│                                                                      │
│  Middleware:  CORS allow-list · security headers · rate limiting     │
│               (sliding window) · request-id · structured errors      │
│                                                                      │
│  Routers                                                             │
│   /api/auth      register · login · me            (JWT + bcrypt)     │
│   /api/studies   create · list · get · delete     (file upload)      │
│   /api/analysis  run · get · list                 (engine dispatch)  │
│   /api/reports   generate · get · list            (report builder)   │
│   /api/health    liveness + engine + db status                       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
┌─────────────────┐   ┌───────────────────────┐   ┌──────────────────┐
│  Engine         │   │  Persistence          │   │  Storage         │
│                 │   │                       │   │                  │
│ imaging.py      │   │ SQLAlchemy 2.0 ORM    │   │ uploads/         │
│  · grayscale    │   │  User                 │   │  <study_id>.png  │
│  · normalize    │   │  Study                │   │                  │
│  · quality      │   │  Analysis             │   │ dev: local disk  │
│  · lung mask    │   │  Finding              │   │ prod: /tmp on    │
│  · CTR          │   │  Report               │   │  serverless      │
│  · opacity      │   │                       │   │                  │
│  · CP density   │   │ SQLite (dev)          │   └──────────────────┘
│                 │   │ PostgreSQL 16 (prod)  │
│ analyze.py      │   └───────────────────────┘
│  · orchestrate  │
│  · reference    │
│    ranges       │
│  · flags        │
│                 │
│ report.py       │
│  · findings →   │
│    impression   │
│  · disclaimer   │
└─────────────────┘
```

---

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | typed, mature imaging ecosystem |
| Web | FastAPI 0.115 | async, Pydantic-native, OpenAPI for free |
| Validation | Pydantic v2 | request/response contracts, strict types |
| ORM | SQLAlchemy 2.0 (typed `Mapped[]`) | one model layer, two databases |
| DB | SQLite (dev) / PostgreSQL 16 (prod) | zero-setup locally, real DB in prod |
| Auth | JWT HS256 + bcrypt (12 rounds) | stateless, no session store needed |
| Imaging | NumPy + Pillow | real pixel math, no heavyweight deps |
| Rate limit | in-process sliding window | explicit, unit-testable, no dependency |
| Frontend | vanilla JS SPA | no build step, deploys as static files |
| Tests | pytest | 88 tests on engine, API, auth, reports |
| Lint | ruff + black | enforced in CI and locally |
| Deploy | Docker / Vercel serverless | both configs shipped |

---

## 4. Data flow — upload to report

```
1. POST /api/auth/register  →  user row, bcrypt hash, JWT issued
2. POST /api/studies        →  multipart image upload
      · validate content-type (png/jpeg/webp) and size (<= 12 MB)
      · decode with Pillow to prove it is a real image (not a renamed file)
      · reject images below 256x256 (too small to measure anything)
      · persist Study row + write bytes to uploads/<study_id>.<ext>
3. POST /api/analysis/{study_id}
      · load pixels → float32 grayscale, 0..1
      · quality gate: mean intensity, dynamic range, saturation
      · segment body + lung fields
      · measure: CTR, left/right lung density, asymmetry, CP density
      · compare each measurement to a reference range → flag
      · persist Analysis + one Finding row per measurement
4. POST /api/reports/{study_id}
      · read the latest Analysis + Findings
      · compose impression text from the flagged findings
      · attach the mandatory non-clinical disclaimer
      · persist Report
5. GET /api/reports/{id}    →  structured report JSON (and printable view in the SPA)
```

---

## 5. The measurement engine

Every finding is a triple: **measured value · reference range · flag**. Nothing is a
free-floating score.

| Measurement | Method | Reference | Flag when |
|---|---|---|---|
| `cardiothoracic_ratio` | widest dense midline structure ÷ thorax width at the same row | < 0.50 | ≥ 0.50 → *possible cardiomegaly* |
| `lung_density_left` | mean normalized intensity inside the left lung mask | 0.15 – 0.55 | outside → *abnormal density* |
| `lung_density_right` | same, right lung mask | 0.15 – 0.55 | outside → *abnormal density* |
| `density_asymmetry` | \|left − right\| ÷ mean(left, right) | < 0.25 | ≥ 0.25 → *asymmetric opacity* |
| `costophrenic_density` | mean intensity in the bottom-lateral bands | < 0.45 | ≥ 0.45 → *possible effusion* |
| `exposure_quality` | mean intensity + dynamic range of the whole film | 0.25 – 0.75 mean | outside → *suboptimal exposure* |

**Confidence** is not invented. It is derived from two things the engine can actually
observe: the image quality score, and how far the measurement sits from its reference
boundary. A measurement 0.02 inside a boundary on a noisy film gets low confidence; a
measurement 0.20 outside it on a clean film gets high confidence. The formula is in
`analyze.py` and is unit-tested.

---

## 6. Security

- **Passwords**: bcrypt, 12 rounds, never logged, never returned.
- **Tokens**: JWT HS256, 24 h expiry, `SECRET_KEY` from env only — the app refuses to boot
  in production with the default key.
- **Rate limits**: 10/min on `/api/auth/*`, 20/min on analysis runs, 120/min elsewhere.
- **Uploads**: content-type allow-list, size cap, Pillow decode verification, dimension
  floor, filename never trusted (stored as `<uuid>.<ext>`).
- **Headers**: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy` set on every response.
- **CORS**: explicit origin allow-list from env, never `*` with credentials.
- **Errors**: no stack traces to clients; structured `{error, detail, request_id}`.
- **Secrets**: `.env` only. `.env.example` documents every variable. Nothing hardcoded.

---

## 7. Scaling notes

- **Stateless app tier.** JWT means any instance can serve any request; scale horizontally
  behind a load balancer with no sticky sessions.
- **Database.** SQLite is dev-only. Postgres in prod; the ORM layer is identical. Add a
  read replica for the study/report read path when it dominates.
- **Object storage.** Local disk works for one node. Move uploads to S3/GCS and store the
  key on the Study row — the storage call is already isolated in one module.
- **Analysis is CPU-bound.** It is synchronous today because a single film takes ~200 ms.
  If a real CNN is plugged in, move `run_analysis` behind a queue (Celery/RQ) and return
  202 + a job id; the API shape already allows it.
- **Caching.** Analysis results are immutable per study — cache by `study_id` in Redis and
  skip recomputation entirely.
- **Audit.** Every analysis and report row carries `created_at` and the owning user; add an
  append-only audit table before any real deployment.

---

## 8. Repository layout

```
project-day-12-tashkhees/
├── app/
│   ├── main.py            FastAPI app, middleware, router wiring
│   ├── config.py          env-driven settings, prod safety checks
│   ├── database.py        engine, session factory, Base
│   ├── models.py          User, Study, Analysis, Finding, Report
│   ├── schemas.py         Pydantic request/response contracts
│   ├── security.py        bcrypt hashing, JWT encode/decode
│   ├── deps.py            auth dependency, db dependency
│   ├── engine/
│   │   ├── imaging.py     pure pixel math (no I/O, fully unit-tested)
│   │   ├── analyze.py     orchestration, reference ranges, confidence
│   │   └── report.py      findings → impression text
│   ├── routers/           auth, studies, analysis, reports, health
│   └── static/            index.html, app.js, styles.css
├── docs/                  setup.md, usage.md, api.md
├── tests/                 engine, api, auth, report tests
├── scripts/seed.py        demo user + synthetic study
├── Dockerfile · docker-compose.yml · vercel.json · api/index.py
└── ARCHITECTURE.md · README.md · LICENSE · .env.example
```
