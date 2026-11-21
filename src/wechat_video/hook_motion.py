"""Pure, Manim-independent geometry for the binary hook's first-frame motion.

The renderer consumes these states directly; the same function is unit-tested so
the first frame, inward 0-2 s failure and outward 2-4 s success are verifiable
without rendering a video.
"""
from __future__ import annotations

import math
from typing import Any

LEFT_ANGLES = (0.6, 2.1, 3.6, 5.1)
RIGHT_ANGLES = (0.9, 2.4, 3.9, 5.4)
LEFT_X_OFFSET = -1.45
RIGHT_X_OFFSET = 1.45
PHASE_SECONDS = 2.0
TOTAL_SECONDS = 2 * PHASE_SECONDS
START_RADIUS = 0.46
END_RADIUS = 0.03
START_SCALE = 1.0
END_SCALE = 0.22


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _side_states(
    angles: tuple[float, ...], progress: float, *, inward: bool, opacity: float
) -> list[dict[str, Any]]:
    q = _clamp01(progress)
    radius = START_RADIUS * (1 - q) + END_RADIUS * q if inward else END_RADIUS * (1 - q) + START_RADIUS * q
    scale = START_SCALE * (1 - q) + END_SCALE * q if inward else END_SCALE * (1 - q) + START_SCALE * q
    states: list[dict[str, Any]] = []
    for index, angle in enumerate(angles):
        states.append(
            {
                "index": index,
                "dx": round(radius * math.cos(angle), 5),
                "dy": round(radius * math.sin(angle), 5),
                "radius": round(0.075 * scale, 5),
                "opacity": round(opacity, 4),
            }
        )
    return states


def hook_particle_states(t_seconds: float) -> dict[str, Any]:
    """Return both sides at time t (0..4 s); every side always has 4 particles.

    Left failure path: starts fully visible at t=0, moves inward and fades to
    zero by t=2. Right success path: starts as a small centre ghost, then grows
    outward from t=2 to t=4. The inactive side is kept as a 0.22 ghost so the
    comparison never disappears (V2 ghost-persistence rule).
    """
    t = max(0.0, min(TOTAL_SECONDS, float(t_seconds)))
    left_active = t < PHASE_SECONDS
    ghost_opacity = 0.22
    if left_active:
        q = t / PHASE_SECONDS
        left = _side_states(LEFT_ANGLES, q, inward=True, opacity=1.0 - q)
        right = _side_states(RIGHT_ANGLES, 0.0, inward=False, opacity=ghost_opacity)
        active = "left"
    else:
        q = (t - PHASE_SECONDS) / PHASE_SECONDS
        left = _side_states(LEFT_ANGLES, 1.0, inward=True, opacity=ghost_opacity)
        right = _side_states(RIGHT_ANGLES, q, inward=False, opacity=0.25 + 0.75 * q)
        active = "right"
    return {
        "t_seconds": round(t, 4),
        "active_side": active,
        "left": left,
        "right": right,
        "left_center_x": LEFT_X_OFFSET,
        "right_center_x": RIGHT_X_OFFSET,
    }


def mean_radial_distance(states: list[dict[str, Any]]) -> float:
    if not states:
        return 0.0
    return sum(math.hypot(s["dx"], s["dy"]) for s in states) / len(states)
