"""Vercel serverless entrypoint.

Vercel's Python runtime imports this module and looks for a module-level ASGI
callable named ``app``. Everything real lives in ``app.main``; this file only
exists to expose it at the path Vercel expects.

Two things matter here and both are easy to get wrong:

1. ``includeFiles`` in ``vercel.json`` must resolve from the *project root* so
   the whole ``app/`` package ships. The legacy ``builds`` block resolved it
   relative to this file's own directory, which silently produced a bundle with
   no ``app`` package and a 500 on every request.
2. ``init_db()`` runs at import time. Vercel does not reliably fire the ASGI
   lifespan handler, so relying on the startup hook leaves the tables missing.
"""

from __future__ import annotations

import contextlib
import os
import sys

# Make the project root importable when Vercel runs this file as a script.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402,F401  (Vercel looks for `app`)

# Serverless filesystems are read-only outside /tmp, so the SQLite fallback and
# the upload directory both need to land there. app.database handles the URL;
# this makes the intent explicit for anyone reading the deploy config.
os.environ.setdefault("VERCEL", "1")

# A failure here surfaces as a 500 on the first request, which is far easier to
# debug than an import-time crash that takes the whole function down.
with contextlib.suppress(Exception):
    init_db()
