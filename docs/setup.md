# Setup

## Requirements

- Python 3.11 or newer
- pip
- (optional) Docker + Docker Compose, for the containerised stack
- (optional) PostgreSQL 16, if you don't want the SQLite default

## Local development

```bash
git clone https://github.com/mohdabrarbaloch-arch/day-12-tashkhees.git
cd day-12-tashkhees

python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -e ".[dev]"
```

Create your environment file:

```bash
cp .env.example .env
```

Then generate a real secret and put it in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

You can leave `ENVIRONMENT=development` and the SQLite default for local work — the app
starts with no `.env` at all in development. Production is stricter; see below.

Seed a demo account and a sample study:

```bash
python scripts/seed.py
```

Run the server:

```bash
uvicorn app.main:app --reload --port 8012
```

- App: <http://127.0.0.1:8012>
- API docs: <http://127.0.0.1:8012/docs>
- Health: <http://127.0.0.1:8012/api/health>

Sign in with `demo@tashkhees.pk` / `demo12345`.

## Docker

```bash
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
docker compose up --build
```

This starts the app on port 8012 and PostgreSQL 16 on 5432, and points the app at Postgres
automatically. Uploads and the database live in named volumes, so they survive a restart.

To wipe everything and start clean:

```bash
docker compose down -v
```

## Production checklist

The app enforces these at startup and refuses to boot if any fail:

- [ ] `SECRET_KEY` is set and at least 32 characters
- [ ] `ENVIRONMENT=production`
- [ ] `DEBUG=false`
- [ ] `DATABASE_URL` points at PostgreSQL, not SQLite
- [ ] `CORS_ORIGINS` lists your real front-end origin(s) — never `*`
- [ ] `UPLOAD_DIR` points at a writable path (or object storage, if you've swapped the
      storage module)

## Troubleshooting

**`RuntimeError: Invalid configuration: SECRET_KEY must be set...`**
You're running with `ENVIRONMENT=production` and the default secret. Set a real one.

**`sqlite3.OperationalError: attempt to write a readonly database`**
You're on a serverless platform and `DATABASE_URL` points outside `/tmp`. The app redirects
SQLite to `/tmp` automatically when it detects Vercel or Lambda, but an explicit
`DATABASE_URL` overrides that — point it at Postgres instead.

**Uploads rejected with 415**
Only `image/png`, `image/jpeg`, and `image/webp` are accepted. A `.dcm` DICOM file will be
rejected; convert it to PNG first.

**Uploads rejected with 400 "not a decodable image"**
The file's content-type said image but the bytes aren't. This is the check that stops a
renamed text file from reaching the engine.
