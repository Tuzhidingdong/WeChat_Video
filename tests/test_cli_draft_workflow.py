from __future__ import annotations

import json
from pathlib import Path

from wechat_video import cli


def test_one_click_slice_a_command_uploads_the_exact_run_and_records_draft(
    tmp_path: Path,
    monkeypatch,
) -> None:
    run_dir = tmp_path / "outputs" / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "review_status.json").write_text(
        json.dumps({"automatic_upload": False, "automatic_publication": False}),
        encoding="utf-8",
    )
    (run_dir / "REVIEW.md").write_text("# Review\n", encoding="utf-8")

    calls: dict[str, object] = {}

    def fake_run_slice_a(project_root, *, card_path, script_path, output_root, allow_pending_review):
        calls["run_project_root"] = project_root
        calls["allow_pending_review"] = allow_pending_review
        return run_dir

    def fake_upload(project_root, selected_run):
        calls["upload_project_root"] = project_root
        calls["selected_run"] = selected_run
        return {
            "state": "DRAFT_SAVED",
            "job_id": "run-123",
            "title": "测试科学草稿",
            "account_name": "成核生长",
            "verified_draft": {
                "title": "测试科学草稿",
                "row_text": "测试科学草稿 草稿",
                "draft_list_url": "https://channels.weixin.qq.com/platform/post/list",
            },
            "authorization_basis": "standing_user_instruction_draft_only",
            "automatic_publication": False,
        }

    monkeypatch.setattr(cli, "run_slice_a", fake_run_slice_a)
    monkeypatch.setattr(cli, "upload_run_to_channels", fake_upload)

    result = cli.main([
        "run-slice-a-and-upload-draft",
        "--project-root",
        str(tmp_path),
    ])

    assert result == 0
    assert calls["run_project_root"] == tmp_path
    assert calls["allow_pending_review"] is True
    assert calls["upload_project_root"] == tmp_path
    assert calls["selected_run"] == run_dir

    upload_report = json.loads(
        (run_dir / "channels_upload_report.json").read_text(encoding="utf-8")
    )
    assert upload_report["state"] == "DRAFT_SAVED"
    assert upload_report["source_run_id"] == "run-123"
    assert upload_report["upload_attempt"] == 1
    assert upload_report["account_name"] == "成核生长"
    assert upload_report["automatic_publication"] is False

    review_status = json.loads(
        (run_dir / "review_status.json").read_text(encoding="utf-8")
    )
    assert review_status["draft_upload_status"] == "DRAFT_SAVED"
    assert review_status["automatic_upload"] is True
    assert review_status["automatic_publication"] is False
    assert "## Unpublished Channels draft" in (run_dir / "REVIEW.md").read_text(
        encoding="utf-8"
    )


def test_manual_review_cli_requires_explicit_result_and_confirmation() -> None:
    args = cli.build_parser().parse_args([
        "channels-record-manual-review",
        "--job-id",
        "20261121_224049_critical_nucleus",
        "--result",
        "draft-found",
        "--reviewed-by",
        "local reviewer",
        "--row-text",
        "临界半径如何决定成核 2026-11-22 10:30",
        "--confirmation",
        "CONFIRM CHANNELS DRAFT FOUND 20261121_224049_critical_nucleus",
    ])

    assert args.command == "channels-record-manual-review"
    assert args.result == "draft-found"
    assert args.job_id == "20261121_224049_critical_nucleus"
    assert args.confirmation.startswith("CONFIRM CHANNELS DRAFT FOUND ")
