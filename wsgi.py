"""
WSGI entry point for FeedBot Dashboard
Run with: gunicorn wsgi:app
"""

import os

from proxy_utils import normalize_proxy_environment

normalize_proxy_environment()

from dashboard import app

application = app  # WSGI servers look for 'application' by default

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
