"""Tests for structured, browser-observed publication source evidence."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from wechat_video.publication_source_evidence import (
    EVIDENCE_FILENAME,
    PublicationSourceEvidenceError,
    record_source_evidence,
    validate_binding,
    validate_observation,
)
from wechat_video.upstream_article_source import discover_upstream_literature_runs

from test_upstream_article_source import (  # pytest puts tests/ on sys.path
    ALBUM_URL,
    ARTICLE_URL,
    TITLE,
    _make_upstream_run,
    _make_video_evidence,
)

BIZ_ID = "MzIyMjY1ODkwMA=="


def _observation() -> dict:
    return {
        "schema_version": 1,
        "capture_method": "visible_browser_dom_observation",
        "read_only": True,
        "observed_at": "2026-11-25T10:55:08+08:00",
        "identity": {
            "article_id": "100000764_0",
            "appmsgid": "100000764",
            "account_name": "成核生长",
            "title": TITLE,
            "markdown_sha256": "a" * 64,
        },
        "source_page": {"url": ALBUM_URL},
        "article_entry": {
            "title_text": TITLE,
            "link_attribute": "data-link",
            "link_href_raw": "http://" + ARTICLE_URL.split("https://", 1)[1],
            "resolved_article_url": ARTICLE_URL + "&scene=178&cur_album_id=4776718530358493186&search_click_id=#rd",
            "data_msgid": "2247484414",
            "data_itemidx": "1",
        },
        "dom_relation": {
            "container_tag": "LI",
            "container_attributes": {
                "class": "album__list-item js_album_item",
                "data-msgid": "2247484414",
                "data-itemidx": "1",
                "data-link": "http://" + ARTICLE_URL.split("https://", 1)[1],
                "data-title": TITLE,
            },
            "link_tag": "DIV",
            "link_attributes": {"class": "album__item-title", "role": "link"},
        },
    }


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_validate_observation_accepts_real_shape() -> None:
    evidence = validate_observation(_observation(), expected_biz_id=BIZ_ID)
    assert evidence["observed_at"] == "2026-11-25T10:55:08+08:00"
    assert evidence["article_entry"]["link_attribute"] == "data-link"
    assert evidence["source_page"]["url"] == ALBUM_URL


@pytest.mark.parametrize(
    "mutate",
    [
        lambda o: o.update({"read_only": False}),
        lambda o: o.update({"observed_at": "2026-11-25 10:55:08"}),
        lambda o: o["source_page"].update({"url": ARTICLE_URL}),
        lambda o: o["source_page"].update({"url": ALBUM_URL.replace(BIZ_ID, "WRONGBIZ")}),
        lambda o: o["article_entry"].update({"title_text": "different title"}),
        lambda o: o["article_entry"].update({"link_href_raw": o["article_entry"]["link_href_raw"].replace("sn=", "sn=x")}),
        lambda o: o["article_entry"].update({"data_msgid": "999"}),
        lambda o: o["article_entry"].update({"data_itemidx": "2"}),
        lambda o: o["dom_relation"]["container_attributes"].update({"data-link": "http://example.test/x"}),
        lambda o: o.update({"capture_method": "guessed"}),
    ],
)
def test_validate_observation_rejects_bad_evidence(mutate) -> None:
    observation = _observation()
    mutate(observation)
    with pytest.raises(PublicationSourceEvidenceError):
        validate_observation(observation, expected_biz_id=BIZ_ID)


def test_validate_binding_separates_source_and_verified_url() -> None:
    evidence = validate_observation(_observation(), expected_biz_id=BIZ_ID)
    binding = validate_binding(
        evidence,
        article_id="100000764_0",
        appmsgid="100000764",
        title=TITLE,
        markdown_sha256="a" * 64,
        verified_article_url=ARTICLE_URL,
        expected_biz_id=BIZ_ID,
    )
    assert binding["album_url"] == ALBUM_URL
    assert binding["data_msgid"] == "2247484414"
    assert binding["link_attribute"] == "data-link"


def test_validate_binding_rejects_mismatched_verified_url() -> None:
    evidence = validate_observation(_observation(), expected_biz_id=BIZ_ID)
    with pytest.raises(PublicationSourceEvidenceError):
        validate_binding(
            evidence,
            article_id="100000764_0",
            appmsgid="100000764",
            title=TITLE,
            markdown_sha256="a" * 64,
            verified_article_url=ARTICLE_URL.replace("sn=", "sn=other"),
            expected_biz_id=BIZ_ID,
        )


def _make_recording_bundle(tmp_path: Path, observation: dict):
    root = tmp_path / "outputs"
    bundle = root / "run_100000764_0_article_summary"
    sha = observation["identity"]["markdown_sha256"]
    for name in (
        "url_verification_evidence.json", "upload_preflight_report.json",
        "article_read_count_probe.json", "article_summary_manifest.json", "source_record.json",
    ):
        _write(bundle / name, {})
    _write(bundle / "article_summary_manifest.json", {
        "article_id": "100000764_0", "appmsgid": "100000764",
        "article_title": TITLE, "source_article_sha256": sha,
    })
    _write(bundle / "source_record.json", {
        "article_id": "100000764_0", "appmsgid": "100000764",
        "title": TITLE, "article_markdown_sha256": sha,
    })
    _write(bundle / "url_verification_evidence.json", {"url": ARTICLE_URL})
    return root, bundle


def test_record_source_evidence_writes_once_and_refuses_overwrite(tmp_path: Path) -> None:
    observation = _observation()
    root, bundle = _make_recording_bundle(tmp_path, observation)
    obs_path = tmp_path / "observation.json"
    _write(obs_path, observation)
    before = {p.name: p.read_bytes() for p in bundle.glob("*.json")}

    result = record_source_evidence(
        observation_path=obs_path, evidence_root=root, expected_biz_id=BIZ_ID
    )
    assert result["state"] == "SOURCE_EVIDENCE_RECORDED"
    assert (bundle / EVIDENCE_FILENAME).is_file()
    for name, data in before.items():
        assert (bundle / name).read_bytes() == data
    with pytest.raises(PublicationSourceEvidenceError):
        record_source_evidence(
            observation_path=obs_path, evidence_root=root, expected_biz_id=BIZ_ID
        )


def test_adapter_accepts_new_evidence_without_manifest_canonical_url(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = _make_video_evidence(evidence_root, run_dir)
    for name, key in (("article_summary_manifest.json", "canonical_url"),
                      ("source_record.json", "canonical_url")):
        payload = json.loads((evidence_dir / name).read_text(encoding="utf-8"))
        payload[key] = None
        _write(evidence_dir / name, payload)
    _write(evidence_dir / "upload_preflight_report.json", {
        "url_provenance": {
            "obtained_from": "album_id and data-link prose only, no structured URL"
        }
    })
    sha = json.loads((run_dir / "slot1.manifest.json").read_text(encoding="utf-8"))["output_sha256"]
    observation = _observation()
    observation["identity"]["markdown_sha256"] = sha
    obs_path = tmp_path / "observation.json"
    _write(obs_path, observation)
    record_source_evidence(
        observation_path=obs_path, evidence_root=evidence_root, expected_biz_id=BIZ_ID
    )

    candidates, rejected = discover_upstream_literature_runs(
        root,
        publication_evidence_root=evidence_root,
        account_key="research_subscription",
        account_name="成核生长",
        expected_biz_id=BIZ_ID,
        target_date=date(2026, 11, 22),
        timezone_name="Asia/Shanghai",
    )
    assert len(candidates) == 1, rejected
    assert candidates[0]["canonical_url"] == ARTICLE_URL
    assert candidates[0]["album_url"] == ALBUM_URL
    assert candidates[0]["publication_time_details"]["album_mid"] == "2247484414"
    assert candidates[0]["url_verified_at"].startswith("2026-11-25T10:55:08")
