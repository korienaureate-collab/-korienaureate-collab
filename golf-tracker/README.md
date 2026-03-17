# Golf Tracking System

Production-grade golf ball tracking system with real-time analytics.

## Architecture

```
backend/
├── app.py          Flask + SocketIO server, REST endpoints
├── engine.py       Core state machine (shots, scoring, history)
├── ai_engine.py    AI validation layer (rule-based, extensible)
├── wsgi.py         Gunicorn production entry point
└── requirements.txt

frontend/
├── index.html      Dashboard UI
├── styles.css      Dark theme stylesheet
└── app.js          WebSocket client + UI controller
```

## Quick Start

```bash
cd backend
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000

## REST API

| Method | Endpoint | Description                     |
|--------|----------|---------------------------------|
| GET    | /data    | Current session state + history |
| POST   | /shot    | Submit a ball+zone detection    |
| POST   | /reset   | Reset session                   |
| GET    | /health  | Health check                    |

### POST /shot
```json
{ "ball_id": "BALL-01", "zone": "fairway" }
```

Valid zones: `fairway`, `green`, `rough`, `bunker`, `water`, `out_of_bounds`

## WebSocket Events

| Event        | Direction | Payload                       |
|--------------|-----------|-------------------------------|
| shot_update  | S → C     | `{ shot, state }`             |
| state_update | S → C     | `{ state }`                   |
| request_state| C → S     | (empty) triggers state_update |

## Scoring

| Result        | Base Score | Zone Multiplier |
|---------------|-----------|-----------------|
| valid         | +10       | Green ×2.0, Fairway ×1.5, Rough ×1.0, Bunker ×0.8, Water ×0.5, OOB ×0.0 |
| mismatch      | −5        | —               |
| ai_rejected   | −8        | —               |
| invalid_zone  | −3        | —               |
| invalid_ball  | −3        | —               |

## Swapping the AI Engine

Replace `RuleBasedAIEngine` with any backend by implementing `BaseAIEngine`:

```python
class MyMLEngine(BaseAIEngine):
    def validate(self, *, ball_id, zone, last_ball_id, last_zone, history):
        # Call your model here
        return AIValidationResult(approved=True, confidence=0.97, ...)
```

Then in `app.py`:
```python
ai = MyMLEngine()
engine = GolfTrackingEngine(ai_engine=ai)
```

## Production Deployment

```bash
gunicorn --worker-class eventlet -w 1 wsgi:app
```

Set env vars:
- `PORT` — server port (default 5000)
- `SECRET_KEY` — Flask secret key
- `AI_MODE` — `rule_based` or `remote`
- `FLASK_DEBUG` — `true` for debug mode
