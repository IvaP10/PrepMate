import os
import sys

from dotenv import load_dotenv

os.environ.setdefault("JWT_SECRET", "test-jwt-secret-value-with-32-chars")
os.environ.setdefault("ENVIRONMENT", "test")

WORKSPACE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_ROOT not in sys.path:
    sys.path.insert(0, WORKSPACE_ROOT)

load_dotenv(os.path.join(WORKSPACE_ROOT, "key.env"))
