"""
WSGI entry point for production deployment (gunicorn + eventlet).

Usage:
  gunicorn --worker-class eventlet -w 1 wsgi:app
"""

import os
from app import create_app

_app, socketio = create_app(ai_mode=os.environ.get("AI_MODE", "rule_based"))
app = _app  # gunicorn needs a module-level 'app'
