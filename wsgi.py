"""
WSGI entry point for FeedBot Dashboard
Run with: gunicorn wsgi:app
"""

import os

# Remove all proxy environment variables to ensure direct connections
for key in list(os.environ.keys()):
    if key.lower().endswith("_proxy"):
        os.environ.pop(key)

from dashboard import app

application = app  # WSGI servers look for 'application' by default

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
