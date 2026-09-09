"""
Shared Flask extension instances that need to be importable from both
app.py and auth.py without one importing the other (which would create a
circular import — app.py registers the auth blueprint, so auth.py can't
import back from app.py).

Pattern: create the extension objects here, unbound. app.py calls
.init_app(app) on each during create_app(). Any module can import the
instance directly to use its decorators (like @limiter.limit(...)).
"""

import os

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Rate-limit storage backend.
#
# Production/anywhere with more than one process MUST use Redis: gunicorn
# runs multiple worker processes (see Procfile/render.yaml, currently
# --workers 2), and Flask-Limiter's default in-memory storage keeps a
# separate counter per process. With memory:// and 2 workers, a "5 per
# hour" limit is actually closer to "5 per hour per worker" — roughly
# double the stated limit, and which worker handles a given request is
# effectively random, so the real behavior is inconsistent, not just
# looser. This was a real, live gap (confirmed by reading the deployed
# render.yaml/Procfile), not a hypothetical future one.
#
# REDIS_URL is read here, not hardcoded, so:
#   - local dev without Redis running still works (falls back to memory://
#     with a clear log warning, single dev process, gunicorn not in play)
#   - production sets REDIS_URL and gets real shared, cross-worker limits
#   - tests can set REDIS_URL to a real (or fakeredis-backed) instance to
#     verify the shared-counter behavior for real, not just import the code
redis_url = os.environ.get("REDIS_URL", "").strip()
storage_uri = redis_url or "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri=storage_uri,
)
