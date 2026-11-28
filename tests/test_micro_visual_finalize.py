import json
from pathlib import Path

from wechat_video import micro_visual_continuation as cont

JOB = "job-finalize-test"


def test_finalize_existing_draft_without_upload(tmp_path: Path, monkeypatch) -> None:
    d = tmp_path / "outputs" / JOB
    d.mkdir(parents=True)
    title = "盐效应与界面离子调控"
    (d / "visual_theme_binding.json").write_text(json.dumps({
        "run_id": "mv-frozen", "article_id": "100000884_0",
        "source_article_sha256": "a" * 64, "source_run_id": "src-run",
    }), encoding="utf-8")
    (d / "channels_draft.json").write_text(json.dumps({"title": title}), encoding="utf-8")
    (d / "flow_generation_event.json").write_text(json.dumps({
        "flow_model": "Omni Flash 1.2", "flow_generation_status": "SUBMITTED",
        "flow_prompt_sha256": "b" * 64,
    }), encoding="utf-8")
    (d / "video_validation_report.json").write_text(json.dumps({
        "status": "PASS", "sha256": "c" * 64,
    }), encoding="utf-8")
    jobs = tmp_path / "runtime/upload_jobs"
    jobs.mkdir(parents=True)
    (jobs / "src-run.json").write_text(json.dumps({
        "state": "DRAFT_SAVED", "logical_job_id": JOB, "title": title,
        "save_click_count": 1,
        "verified_draft": {"title": title, "row_text": title + " 2026-11-28"},
    }), encoding="utf-8")
    monkeypatch.setattr(cont.cu, "_load_config", lambda _r: ({"jobs_dir": "runtime/upload_jobs"}, {}))
    result = cont.finalize_existing_draft(tmp_path, JOB)
    assert result["state"] == "DRAFT_SAVED"
    assert result["verified_draft"]["title"] == title
    assert json.loads((d / "flow_generation_event.json").read_text(encoding="utf-8"))[
        "flow_generation_status"] == "DRAFT_SAVED"
    assert (d / "verified_draft.json").is_file()
    assert (d / "run_result.json").is_file()
