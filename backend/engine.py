"""
Golf Tracking Engine
Core state management for the golf ball tracking system.
Handles shot recording, scoring, history, and validation.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class ShotResult(str, Enum):
    VALID = "valid"
    MISMATCH = "mismatch"
    INVALID_ZONE = "invalid_zone"
    INVALID_BALL = "invalid_ball"
    AI_REJECTED = "ai_rejected"


class Zone(str, Enum):
    FAIRWAY = "fairway"
    GREEN = "green"
    ROUGH = "rough"
    BUNKER = "bunker"
    WATER = "water"
    OUT_OF_BOUNDS = "out_of_bounds"


# Score configuration
SCORE_CONFIG = {
    ShotResult.VALID: 10,
    ShotResult.MISMATCH: -5,
    ShotResult.INVALID_ZONE: -3,
    ShotResult.INVALID_BALL: -3,
    ShotResult.AI_REJECTED: -8,
}

ZONE_MULTIPLIERS = {
    Zone.GREEN: 2.0,
    Zone.FAIRWAY: 1.5,
    Zone.ROUGH: 1.0,
    Zone.BUNKER: 0.8,
    Zone.WATER: 0.5,
    Zone.OUT_OF_BOUNDS: 0.0,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Shot:
    shot_id: str
    ball_id: str
    zone: str
    result: ShotResult
    score_delta: int
    cumulative_score: int
    timestamp: float
    ai_confidence: float
    ai_notes: str
    processing_time_ms: float

    def to_dict(self) -> dict:
        d = asdict(self)
        d["result"] = self.result.value
        d["timestamp_formatted"] = time.strftime(
            "%H:%M:%S", time.localtime(self.timestamp)
        )
        return d


@dataclass
class EngineState:
    session_id: str
    total_shots: int = 0
    valid_shots: int = 0
    mismatch_shots: int = 0
    rejected_shots: int = 0
    score: int = 0
    last_ball_id: Optional[str] = None
    last_zone: Optional[str] = None
    session_start: float = field(default_factory=time.time)

    @property
    def accuracy(self) -> float:
        if self.total_shots == 0:
            return 0.0
        return round(self.valid_shots / self.total_shots * 100, 1)

    @property
    def session_duration(self) -> float:
        return round(time.time() - self.session_start, 1)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "total_shots": self.total_shots,
            "valid_shots": self.valid_shots,
            "mismatch_shots": self.mismatch_shots,
            "rejected_shots": self.rejected_shots,
            "score": self.score,
            "accuracy": self.accuracy,
            "last_ball_id": self.last_ball_id,
            "last_zone": self.last_zone,
            "session_duration": self.session_duration,
            "session_start": self.session_start,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class GolfTrackingEngine:
    """
    Central state machine for the golf tracking system.

    Responsibilities:
      - Accept ball/zone detection events
      - Validate inputs against known rules
      - Delegate AI validation
      - Maintain shot history (last 10 shots)
      - Manage scoring with configurable multipliers and penalties
    """

    HISTORY_SIZE = 10

    def __init__(self, ai_engine=None):
        self._ai_engine = ai_engine
        self._state = self._create_new_state()
        self._history: deque[Shot] = deque(maxlen=self.HISTORY_SIZE)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_shot(
        self,
        ball_id: str,
        zone: str,
        *,
        ai_confidence: Optional[float] = None,
        ai_notes: str = "",
    ) -> Shot:
        """
        Process a detected ball + zone event.

        Returns the resulting Shot record.
        Raises ValueError on completely invalid inputs before scoring.
        """
        t_start = time.perf_counter()

        ball_id = ball_id.strip().upper()
        zone = zone.strip().lower()

        # --- Input validation ---
        result, notes = self._validate_inputs(ball_id, zone)

        # --- AI validation (if inputs are structurally valid) ---
        if result == ShotResult.VALID and self._ai_engine is not None:
            ai_result = self._ai_engine.validate(
                ball_id=ball_id,
                zone=zone,
                last_ball_id=self._state.last_ball_id,
                last_zone=self._state.last_zone,
                history=list(self._history),
            )
            if not ai_result.approved:
                result = ShotResult.AI_REJECTED
                notes = ai_result.reason
            if ai_confidence is None:
                ai_confidence = ai_result.confidence

        if ai_confidence is None:
            ai_confidence = 1.0 if result == ShotResult.VALID else 0.0

        # --- Check continuity (same ball, different zone is valid; different
        #     ball mid-sequence is a mismatch unless first shot) ---
        if result == ShotResult.VALID:
            if (
                self._state.last_ball_id is not None
                and self._state.last_ball_id != ball_id
            ):
                result = ShotResult.MISMATCH
                notes = (
                    f"Ball ID changed mid-sequence: "
                    f"{self._state.last_ball_id} → {ball_id}"
                )

        # --- Scoring ---
        score_delta = self._calculate_score(result, zone)

        # --- Persist ---
        processing_ms = round((time.perf_counter() - t_start) * 1000, 2)
        shot = self._record_shot(
            ball_id=ball_id,
            zone=zone,
            result=result,
            score_delta=score_delta,
            ai_confidence=ai_confidence,
            ai_notes=notes,
            processing_ms=processing_ms,
        )

        return shot

    def get_state(self) -> dict:
        return {
            "state": self._state.to_dict(),
            "history": [s.to_dict() for s in reversed(self._history)],
        }

    def reset(self) -> dict:
        """Reset the session, preserving engine configuration."""
        old_session = self._state.session_id
        self._state = self._create_new_state()
        self._history.clear()
        return {"reset": True, "previous_session": old_session, "new_session": self._state.session_id}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _create_new_state() -> EngineState:
        return EngineState(session_id=str(uuid.uuid4())[:8].upper())

    def _validate_inputs(self, ball_id: str, zone: str) -> tuple[ShotResult, str]:
        valid_zones = {z.value for z in Zone}

        if not ball_id:
            return ShotResult.INVALID_BALL, "Empty ball ID"
        if len(ball_id) > 20:
            return ShotResult.INVALID_BALL, "Ball ID too long (max 20 chars)"
        if zone not in valid_zones:
            return ShotResult.INVALID_ZONE, f"Unknown zone '{zone}'"

        return ShotResult.VALID, ""

    def _calculate_score(self, result: ShotResult, zone: str) -> int:
        base = SCORE_CONFIG.get(result, 0)
        if result == ShotResult.VALID:
            multiplier = ZONE_MULTIPLIERS.get(Zone(zone), 1.0)
            return round(base * multiplier)
        return base

    def _record_shot(
        self,
        ball_id: str,
        zone: str,
        result: ShotResult,
        score_delta: int,
        ai_confidence: float,
        ai_notes: str,
        processing_ms: float,
    ) -> Shot:
        self._state.total_shots += 1
        self._state.score += score_delta

        if result == ShotResult.VALID:
            self._state.valid_shots += 1
        elif result == ShotResult.MISMATCH:
            self._state.mismatch_shots += 1
        elif result in (ShotResult.AI_REJECTED, ShotResult.INVALID_BALL, ShotResult.INVALID_ZONE):
            self._state.rejected_shots += 1

        self._state.last_ball_id = ball_id
        self._state.last_zone = zone

        shot = Shot(
            shot_id=str(uuid.uuid4())[:8].upper(),
            ball_id=ball_id,
            zone=zone,
            result=result,
            score_delta=score_delta,
            cumulative_score=self._state.score,
            timestamp=time.time(),
            ai_confidence=round(ai_confidence, 3),
            ai_notes=ai_notes,
            processing_time_ms=processing_ms,
        )
        self._history.append(shot)
        return shot
