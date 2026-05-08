"""Shared pytest setup for collection-time application imports."""

import os


os.environ.setdefault("TAPIS_ADMIN_TOKEN", "admin-token")
os.environ.setdefault("TAPIS_BASE_URL", "https://tapis.test")
os.environ.setdefault("TAPIS_TENANT", "testtenant")
