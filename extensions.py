"""
Shared Flask extension instances that need to be importable from both
app.py and auth.py without one importing the other (which would create a
circular import — app.py registers the auth blueprint, so auth.py can't
import back from app.py).

Pattern: create the extension objects here, unbound. app.py calls
.init_app(app) on each during create_app(). Any module can import the
instance directly to use its decorators (like @limiter.limit(...)).
"""

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
    storage_uri="memory://",
)
