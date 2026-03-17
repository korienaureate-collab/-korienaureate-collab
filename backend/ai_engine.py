"""
AI Validation Engine
Provides rule-based shot validation with a clear interface
designed for seamless replacement with a real ML/LLM model.

Architecture:
  - AIValidationResult: immutable result object
  - BaseAIEngine: abstract interface (swap implementations freely)
  - RuleBasedAIEngine: production-ready heuristic engine
  - AIEngineFactory: creates the appropriate engine based on config
"""

from __future__ import annotations

import math
import random
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Result contract
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AIValidationResult:
    approved: bool
    confidence: float          # 0.0 – 1.0
    reason: str
    model_version: str
    latency_ms: float

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "confidence": self.confidence,
            "reason": self.reason,
            "model_version": self.model_version,
            "latency_ms": self.latency_ms,
        }


# ---------------------------------------------------------------------------
# Abstract interface
# ---------------------------------------------------------------------------

class BaseAIEngine(ABC):
    """
    Contract that every AI backend must satisfy.
    Swap this for an LLM or computer-vision model without touching engine.py.
    """

    @abstractmethod
    def validate(
        self,
        *,
        ball_id: str,
        zone: str,
        last_ball_id: Optional[str],
        last_zone: Optional[str],
        history: list,
    ) -> AIValidationResult:
        ...

    @property
    @abstractmethod
    def model_version(self) -> str:
        ...


# ---------------------------------------------------------------------------
# Rule-based implementation
# ---------------------------------------------------------------------------

class RuleBasedAIEngine(BaseAIEngine):
    """
    Heuristic validation engine.

    Rules (in priority order):
      1. Impossible zone transitions (e.g. green → water → green)
      2. Suspicious ball ID patterns
      3. Velocity / frequency anomaly (too many shots in short window)
      4. Confidence scoring based on zone risk
    """

    _VERSION = "rule-based-v1.2"

    # Zone transition weights: (from_zone, to_zone) → penalty 0-1
    # 0 = perfectly fine, 1 = physically impossible
    _TRANSITION_PENALTY: dict[tuple[str, str], float] = {
        ("green", "water"): 0.05,        # unusual but possible
        ("water", "green"): 0.85,        # near-impossible without retrieval
        ("out_of_bounds", "green"): 0.90,
        ("out_of_bounds", "fairway"): 0.70,
        ("bunker", "water"): 0.60,
    }

    # High-risk zones reduce confidence even when valid
    _ZONE_BASE_CONFIDENCE: dict[str, float] = {
        "green": 0.97,
        "fairway": 0.95,
        "rough": 0.88,
        "bunker": 0.82,
        "water": 0.75,
        "out_of_bounds": 0.70,
    }

    # Maximum shots per 10-second window before frequency alert
    _FREQUENCY_LIMIT = 5

    def __init__(self, *, noise_factor: float = 0.02):
        """
        noise_factor: adds tiny randomness to simulate real model variance.
        Set to 0.0 for deterministic mode.
        """
        self._noise = noise_factor

    @property
    def model_version(self) -> str:
        return self._VERSION

    def validate(
        self,
        *,
        ball_id: str,
        zone: str,
        last_ball_id: Optional[str],
        last_zone: Optional[str],
        history: list,
    ) -> AIValidationResult:
        t_start = time.perf_counter()

        approved, confidence, reason = self._run_rules(
            ball_id=ball_id,
            zone=zone,
            last_ball_id=last_ball_id,
            last_zone=last_zone,
            history=history,
        )

        # Apply tiny noise to simulate real-model variance
        if self._noise > 0:
            noise = random.gauss(0, self._noise)
            confidence = max(0.0, min(1.0, confidence + noise))

        latency = round((time.perf_counter() - t_start) * 1000, 3)

        return AIValidationResult(
            approved=approved,
            confidence=round(confidence, 4),
            reason=reason,
            model_version=self._VERSION,
            latency_ms=latency,
        )

    # ------------------------------------------------------------------
    # Rule pipeline
    # ------------------------------------------------------------------

    def _run_rules(
        self,
        *,
        ball_id: str,
        zone: str,
        last_ball_id: Optional[str],
        last_zone: Optional[str],
        history: list,
    ) -> tuple[bool, float, str]:

        # Rule 1: Zone transition anomaly
        if last_zone is not None:
            penalty = self._TRANSITION_PENALTY.get((last_zone, zone), 0.0)
            if penalty > 0.75:
                conf = round(1.0 - penalty, 3)
                return False, conf, f"Anomalous zone transition: {last_zone} → {zone}"

        # Rule 2: Ball ID format anomaly
        if not self._is_valid_ball_format(ball_id):
            return False, 0.3, f"Suspicious ball ID format: '{ball_id}'"

        # Rule 3: Shot frequency (too fast = sensor glitch)
        freq_ok, freq_reason = self._check_frequency(history)
        if not freq_ok:
            return False, 0.4, freq_reason

        # Rule 4: Repeated identical shots (possible stuck sensor)
        if self._is_stuck_sensor(ball_id, zone, history):
            return False, 0.35, "Repeated identical ball+zone (possible stuck sensor)"

        # All rules passed — calculate confidence
        base_conf = self._ZONE_BASE_CONFIDENCE.get(zone, 0.85)

        # Slight confidence boost for familiar ball ID
        if last_ball_id is not None and last_ball_id == ball_id:
            base_conf = min(1.0, base_conf + 0.02)

        # Apply transition soft-penalty even on approved shots
        if last_zone is not None:
            penalty = self._TRANSITION_PENALTY.get((last_zone, zone), 0.0)
            base_conf = max(0.0, base_conf - penalty * 0.5)

        return True, base_conf, "OK"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_valid_ball_format(ball_id: str) -> bool:
        """
        Accepted formats: 1-20 alphanumeric chars, dashes allowed.
        Rejects: whitespace-only, all-special-chars, too short (1 char edge cases).
        """
        if not ball_id or len(ball_id) < 2:
            return False
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
        return all(c in allowed for c in ball_id)

    @staticmethod
    def _check_frequency(history: list) -> tuple[bool, str]:
        if len(history) < RuleBasedAIEngine._FREQUENCY_LIMIT:
            return True, ""
        recent = history[-RuleBasedAIEngine._FREQUENCY_LIMIT :]
        window = recent[-1].timestamp - recent[0].timestamp
        if window < 10.0:
            rate = round(RuleBasedAIEngine._FREQUENCY_LIMIT / max(window, 0.1), 1)
            return False, f"Shot frequency too high: {rate} shots/sec (possible sensor error)"
        return True, ""

    @staticmethod
    def _is_stuck_sensor(ball_id: str, zone: str, history: list) -> bool:
        if len(history) < 3:
            return False
        last_three = history[-3:]
        return all(s.ball_id == ball_id and s.zone == zone for s in last_three)


# ---------------------------------------------------------------------------
# Stub for future real AI (LLM / CV model)
# ---------------------------------------------------------------------------

class RemoteAIEngine(BaseAIEngine):
    """
    Placeholder for a real remote AI service (LLM, CV pipeline, etc.).
    Drop your HTTP client / model SDK call into `validate()`.
    """

    _VERSION = "remote-ai-v0.1-stub"

    @property
    def model_version(self) -> str:
        return self._VERSION

    def validate(self, *, ball_id, zone, last_ball_id, last_zone, history):
        # TODO: call real AI endpoint
        # response = ai_client.analyze(ball_id=ball_id, zone=zone, ...)
        # return AIValidationResult(approved=response.approved, ...)
        raise NotImplementedError("RemoteAIEngine is not yet connected to a model.")


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class AIEngineFactory:
    """Returns the appropriate AI engine based on runtime config."""

    @staticmethod
    def create(mode: str = "rule_based", **kwargs) -> BaseAIEngine:
        if mode == "rule_based":
            return RuleBasedAIEngine(**kwargs)
        if mode == "remote":
            return RemoteAIEngine()
        raise ValueError(f"Unknown AI engine mode: '{mode}'")
