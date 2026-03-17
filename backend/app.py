"""
Golf Tracking System — Flask + SocketIO Application
Production entry point.

Endpoints:
  GET  /           → serves the dashboard
  GET  /data        → current state snapshot
  POST /shot        → submit a ball+zone detection
  POST /reset       → reset session

WebSocket events (server → client):
  shot_update       → new shot processed
  state_update      → full state refresh
  error_event       → validation / server error
"""

from __future__ import annotations

import os
import time
import logging
from functools import wraps
from typing import Any

from flask import Flask, jsonify, request, send_from_directory
from flask_socketio import SocketIO, emit

from engine import GolfTrackingEngine
from ai_engine import AIEngineFactory


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("golf.app")


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(ai_mode: str = "rule_based") -> tuple[Flask, SocketIO]:
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
    app = Flask(__name__, static_folder=frontend_dir, static_url_path="")

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "golf-dev-secret-change-in-prod")
    app.config["JSON_SORT_KEYS"] = False

    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        async_mode="threading",
        logger=False,
        engineio_logger=False,
    )

    # Shared engine instance (thread-safe via GIL for this use case)
    ai = AIEngineFactory.create(ai_mode)
    engine = GolfTrackingEngine(ai_engine=ai)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def api_response(data: Any, status: int = 200):
        resp = jsonify({"ok": status < 400, "data": data, "ts": time.time()})
        resp.status_code = status
        return resp

    def handle_errors(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except ValueError as exc:
                log.warning("Validation error: %s", exc)
                return api_response({"error": str(exc)}, 400)
            except Exception as exc:
                log.exception("Unexpected error in %s", f.__name__)
                return api_response({"error": "Internal server error"}, 500)
        return wrapper

    # ------------------------------------------------------------------
    # Static / dashboard
    # ------------------------------------------------------------------

    @app.route("/")
    def dashboard():
        return send_from_directory(frontend_dir, "index.html")

    # ------------------------------------------------------------------
    # REST: /data
    # ------------------------------------------------------------------

    @app.route("/data", methods=["GET"])
    @handle_errors
    def get_data():
        return api_response(engine.get_state())

    # ------------------------------------------------------------------
    # REST: /shot
    # ------------------------------------------------------------------

    @app.route("/shot", methods=["POST"])
    @handle_errors
    def post_shot():
        body = request.get_json(silent=True) or {}
        ball_id = body.get("ball_id", "").strip()
        zone = body.get("zone", "").strip()

        if not ball_id:
            return api_response({"error": "ball_id is required"}, 400)
        if not zone:
            return api_response({"error": "zone is required"}, 400)

        shot = engine.process_shot(ball_id, zone)
        state = engine.get_state()

        payload = {
            "shot": shot.to_dict(),
            "state": state["state"],
        }

        # Push real-time update to all connected clients
        socketio.emit("shot_update", payload)

        log.info(
            "Shot processed | ball=%s zone=%s result=%s score_delta=%+d",
            shot.ball_id,
            shot.zone,
            shot.result.value,
            shot.score_delta,
        )

        return api_response(payload, 201)

    # ------------------------------------------------------------------
    # REST: /reset
    # ------------------------------------------------------------------

    @app.route("/reset", methods=["POST"])
    @handle_errors
    def post_reset():
        result = engine.reset()
        state = engine.get_state()
        payload = {"reset": result, "state": state["state"]}

        socketio.emit("state_update", payload)
        log.info("Session reset | new_session=%s", result["new_session"])

        return api_response(payload)

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    @socketio.on("connect")
    def on_connect():
        log.info("Client connected: %s", request.sid)
        # Send full state on connect so the client starts hydrated
        emit("state_update", {"state": engine.get_state()})

    @socketio.on("disconnect")
    def on_disconnect():
        log.info("Client disconnected: %s", request.sid)

    @socketio.on("request_state")
    def on_request_state():
        emit("state_update", {"state": engine.get_state()})

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "ts": time.time()})

    return app, socketio


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    ai_mode = os.environ.get("AI_MODE", "rule_based")

    app, socketio = create_app(ai_mode=ai_mode)

    log.info("Starting Golf Tracking System on port %d (debug=%s, ai_mode=%s)", port, debug, ai_mode)
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
