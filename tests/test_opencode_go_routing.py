"""OpenCode Go provider routing is explicit and fail-closed."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wechat_video import daily_pipelines as daily

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "tests/fixtures/opencode_go_free_catalog.json").read_text(encoding="utf-8"))


def _config(model: str) -> dict:
    return {
        "timezone": "Asia/Shanghai",
        "opencode": {"executable": "opencode", "agent": "daily-content-planner",
                     "model": model, "require_explicit_model": True},
        "upload": {"account_name": "成核生长"},
    }


def test_configured_model_uses_go_provider_and_known_catalog() -> None:
    config = json.loads((ROOT / "configs/daily_pipelines.json").read_text(encoding="utf-8"))
    model = config["opencode"]["model"]
    assert model.startswith("opencode-go/")
    assert model != "opencode/tidepool-alpha-free"
    model_id = model.split("/", 1)[1]
    free_ids = {item["id"] for item in CATALOG["models"]}
    assert model_id in free_ids
    selected = next(item for item in CATALOG["models"] if item["id"] == model_id)
    assert selected["cost"] == {"input": 0, "output": 0, "cache_read": 0}
    assert selected["limited_regions"] is False
    assert config["literature"]["lookback_days"] == 7
    assert config["literature"]["selection_policy"] == "newest_first"


def test_ordinary_opencode_provider_is_rejected() -> None:
    with pytest.raises(daily.DailyPipelineError, match="opencode-go/"):
        daily._validate_planner_model("opencode/tidepool-alpha-free")
    with pytest.raises(daily.DailyPipelineError):
        daily._validate_planner_model("hy4-flash-free")
    assert daily._validate_planner_model("opencode-go/hy4-flash-free") == "opencode-go/hy4-flash-free"


def test_planner_command_uses_configured_go_model_without_session_reuse(monkeypatch) -> None:
    captured: dict = {}

    class Completed:
        returncode = 0
        stdout = json.dumps({"type": "text", "text": "{}"})
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return Completed()

    monkeypatch.setattr(daily.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setattr(daily.subprocess, "run", fake_run)
    monkeypatch.setattr(daily, "_extract_model_text", lambda raw: "{}")
    monkeypatch.setattr(daily, "_extract_model_usage", lambda raw: {"complete": True, "session_ids": []})

    target = ROOT / "configs/daily_pipelines.json"
    attachment = ROOT / "README.md"
    result = daily._run_content_planner(
        ROOT, _config("opencode-go/hy4-flash-free"), prompt="test prompt", attachments=[attachment]
    )
    assert result["_planner_run_metadata"]["model"] == "opencode-go/hy4-flash-free"
    cmd = captured["cmd"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "opencode-go/hy4-flash-free"
    assert "--agent" in cmd
    assert cmd[cmd.index("--agent") + 1] == "daily-content-planner"
    assert "--session" not in cmd and "--continue" not in cmd
    assert not any("tidepool" in str(arg) for arg in cmd)


def test_go_validation_never_falls_back_when_catalog_unavailable() -> None:
    config = _config("opencode/tidepool-alpha-free")
    with pytest.raises(daily.DailyPipelineError):
        daily._planner_preflight(config)
