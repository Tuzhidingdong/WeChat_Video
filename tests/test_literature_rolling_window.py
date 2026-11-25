"""Rolling 7-day literature discovery: window, ordering, safety, read-only."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from wechat_video.daily_pipelines import (
    _article_date_window,
    _count_upstream_runs,
    inspect_daily_literature_sources,
)
from wechat_video.publication_source_evidence import record_source_evidence
from wechat_video.upstream_article_source import discover_upstream_literature_runs

BIZ = "MzIyMjY1ODkwMA=="
ALBUM = "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzIyMjY1ODkwMA==&action=getalbum&album_id=4776718530358493186"


def _config(lookback: int = 7) -> dict:
    return {"timezone": "Asia/Shanghai", "literature": {"lookback_days": lookback}}


def _write(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _observation(article_id: str, appmsgid: str, title: str, sha: str, ct: int, mid: str) -> dict:
    raw = f"http://mp.weixin.qq.com/s?__biz={BIZ}&mid={mid}&idx=1&sn={sha[:8]}&chksm={sha[8:16]}#rd"
    resolved = raw.split("#")[0].replace("http://", "https://") + "&scene=178&cur_album_id=4776718530358493186#rd"
    return {
        "schema_version": 1,
        "capture_method": "visible_browser_dom_observation",
        "read_only": True,
        "observed_at": "2026-11-25T11:00:00+08:00",
        "identity": {"article_id": article_id, "appmsgid": appmsgid, "account_name": "成核生长",
                     "title": title, "markdown_sha256": sha},
        "source_page": {"url": ALBUM},
        "article_entry": {"title_text": title, "link_attribute": "data-link", "link_href_raw": raw,
                          "resolved_article_url": resolved, "data_msgid": mid, "data_itemidx": "1"},
        "dom_relation": {"container_tag": "LI", "container_attributes": {
            "class": "album__list-item js_album_item", "data-msgid": mid, "data-itemidx": "1",
            "data-link": raw, "data-title": title},
            "link_tag": "DIV", "link_attributes": {"role": "link"}},
        "publication_probe": {"source": "article_page_visible_publication_date_converted_to_unix_epoch",
                              "visible_publication_date": "2026年11月25日 08:13 北京",
                              "ct": ct, "precision": "minute"},
    }


def _upstream_run(root: Path, date_str: str, run_id: str, appmsgid: str, title: str) -> str:
    run = root / date_str / "research_subscription" / run_id
    run.mkdir(parents=True, exist_ok=True)
    markdown = ("# " + title + "\n\n" + ("证据段落用于满足长度要求。" * 60)).encode("utf-8")
    (run / "slot1.md").write_bytes(markdown)
    sha = hashlib.sha256(markdown).hexdigest()
    _write(run / "slot1.manifest.json", {"output_sha256": sha})
    _write(run / "review_state.json", {"slots": {"1": {"article_sha256": sha}}})
    _write(run / "prepared_articles.json", [{"slot": 1, "title": title,
        "md_body": markdown.decode("utf-8"), "taxonomy_pillar_id": "literature_translation",
        "pillar_id": "literature_manuscript", "bundle_path": "", "cdn_image_urls": []}])
    _write(run / "delivery_result.json", {"appmsgid": appmsgid, "account": "成核生长"})
    _write(run / "uploaded_assets_manifest.json", {"assets": []})
    return sha


def test_default_window_is_today_plus_six_days() -> None:
    start, end, dates = _article_date_window(_config(), None)
    today = datetime.now(timezone(timedelta(hours=8))).date()
    assert end == today
    assert start == today - timedelta(days=6)
    assert len(dates) == 7


def test_explicit_date_is_single_day_diagnostic() -> None:
    start, end, dates = _article_date_window(_config(), "2026-11-24")
    assert start == end == date(2026, 11, 24)
    assert dates == {date(2026, 11, 24)}


def test_configurable_lookback() -> None:
    start, end, dates = _article_date_window(_config(3), None)
    assert len(dates) == 3
    assert start == end - timedelta(days=2)


def test_rolling_discovery_newest_first_and_dedupe(tmp_path: Path) -> None:
    root = tmp_path / "daily_runs"
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    t_old, t_new = "较早文章：晶体生长机制研究", "最新文章：缺陷调控畴结构研究"
    sha_old = _upstream_run(root, "2026-11-23", "run-old", "100000700", t_old)
    sha_new = _upstream_run(root, "2026-11-24", "run-new", "100000800", t_new)
    for article_id, appmsgid, title, sha, ct, mid in (
        ("100000700_0", "100000700", t_old, sha_old, 1795392780, "2247484000"),
        ("100000800_0", "100000800", t_new, sha_new, 1795479180, "2247484414"),
    ):
        obs = tmp_path / f"obs-{article_id}.json"
        _write(obs, _observation(article_id, appmsgid, title, sha, ct, mid))
        record_source_evidence(observation_path=obs, evidence_root=outputs, expected_biz_id=BIZ)

    dates = {date(2026, 11, 23), date(2026, 11, 24)}
    candidates, rejected = discover_upstream_literature_runs(
        root, publication_evidence_root=outputs, account_key="research_subscription",
        account_name="成核生长", expected_biz_id=BIZ, target_date=date(2026, 11, 24),
        timezone_name="Asia/Shanghai", target_dates=dates,
    )
    assert len(candidates) == 2, rejected
    assert candidates[0]["article_id"] == "100000800_0"
    assert candidates[1]["article_id"] == "100000700_0"
    assert candidates[0]["published_at"] > candidates[1]["published_at"]
    assert _count_upstream_runs(root, "research_subscription") == 2


def test_older_article_excluded_from_narrower_window(tmp_path: Path) -> None:
    root = tmp_path / "daily_runs"
    outputs = tmp_path / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    t_old, t_new = "旧文章标题", "新文章标题"
    sha_old = _upstream_run(root, "2026-11-23", "run-old", "100000700", t_old)
    sha_new = _upstream_run(root, "2026-11-24", "run-new", "100000800", t_new)
    for article_id, appmsgid, title, sha, ct, mid in (
        ("100000700_0", "100000700", t_old, sha_old, 1795392780, "2247484000"),
        ("100000800_0", "100000800", t_new, sha_new, 1795479180, "2247484414"),
    ):
        obs = tmp_path / f"obs-{article_id}.json"
        _write(obs, _observation(article_id, appmsgid, title, sha, ct, mid))
        record_source_evidence(observation_path=obs, evidence_root=outputs, expected_biz_id=BIZ)
    candidates, _ = discover_upstream_literature_runs(
        root, publication_evidence_root=outputs, account_key="research_subscription",
        account_name="成核生长", expected_biz_id=BIZ, target_date=date(2026, 11, 24),
        timezone_name="Asia/Shanghai", target_dates={date(2026, 11, 24)},
    )
    assert [c["article_id"] for c in candidates] == ["100000800_0"]


def test_minute_precision_probe_is_preserved(tmp_path: Path) -> None:
    (tmp_path / "outputs").mkdir(parents=True, exist_ok=True)
    obs_path = tmp_path / "obs.json"
    obs = _observation("100000900_0", "100000900", "分钟精度测试文章", "a" * 64, 1795308507, "2247484500")
    _write(obs_path, obs)
    result = record_source_evidence(observation_path=obs_path, evidence_root=tmp_path / "outputs",
                                    expected_biz_id=BIZ)
    stored = json.loads(Path(result["evidence_path"]).read_text(encoding="utf-8"))
    assert stored["publication_probe"]["precision"] == "minute"
    assert stored["publication_probe"]["ct"] == 1795308507
    assert stored["publication_probe"]["source"].startswith("article_page_visible")


def test_real_data_inspection_is_read_only_and_reports_window() -> None:
    root = Path(__file__).resolve().parents[1]
    report = inspect_daily_literature_sources(root, published_date=None)
    assert report["mode"] == "READ_ONLY_DISCOVERY"
    assert report["lookback_days"] == 7
    assert report["window_start"] and report["window_end"]
    assert report["upstream_run_count"] >= 0
    assert "selected_candidate" in report
    assert isinstance(report["deferred_candidates"], list)
    assert all(value is False for value in report["side_effects"].values())
