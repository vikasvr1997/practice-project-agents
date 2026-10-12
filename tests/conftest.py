import os

# Settings the app needs, set before anything imports it.
os.environ.setdefault("APP_API_KEY", "test-key")
os.environ.setdefault("SESSION_BACKEND", "memory")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
