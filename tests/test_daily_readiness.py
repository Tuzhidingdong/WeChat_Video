"""The unified readiness inspection must be side-effect free."""
from __future__ import annotations

from pathlib import Path

from wechat_video.daily_readiness import inspect_daily_two_video_readiness

ROOT = Path(__file__).resolve().parents[1]


def test_readiness_is_read_only() -> None:
    jobs_before = sorted(p.name for p in (ROOT / "runtime/upload_jobs").glob("*"))
    packages_root = ROOT / "runtime/upstream_article_packages"
    packages_before = sorted(p.name for p in packages_root.glob("*")) if packages_root.is_dir() else []

    result = inspect_daily_two_video_readiness(ROOT, published_date="2026-11-25")

    assert result["mode"] == "READ_ONLY"
    assert all(bool(value) is False for value in result["side_effects"].values())
    assert result["literature"]["status"] in {
        "READY_FOR_HUMAN_AUTHORIZATION", "PARTIALLY_READY", "BLOCKED"
    }
    assert result["popularization"]["status"] in {
        "READY_FOR_HUMAN_AUTHORIZATION", "PARTIALLY_READY", "BLOCKED"
    }
    assert result["shared"]["status"] in {
        "READY_FOR_HUMAN_AUTHORIZATION", "PARTIALLY_READY", "BLOCKED"
    }
    assert sorted(p.name for p in (ROOT / "runtime/upload_jobs").glob("*")) == jobs_before
    packages_after = sorted(p.name for p in packages_root.glob("*")) if packages_root.is_dir() else []
    assert packages_after == packages_before
