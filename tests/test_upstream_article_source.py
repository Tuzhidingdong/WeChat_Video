from __future__ import annotations

import hashlib
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

from wechat_video.article_source import load_article_package
from wechat_video.upstream_article_source import (
    UpstreamArticleError,
    discover_upstream_literature_runs,
    materialize_upstream_article_package,
)


TITLE = "俄亥俄州立大学团队发表APL：失配位错剪切应力模板化锁定反铁磁畴"
ARTICLE_URL = "https://mp.weixin.qq.com/s?__biz=MzIyMjY1ODkwMA==&mid=2247484414&idx=1&sn=fixture"
ALBUM_URL = (
    "https://mp.weixin.qq.com/mp/appmsgalbum?"
    "__biz=MzIyMjY1ODkwMA==&action=getalbum&album_id=4776718530358493186"
)
CT = 1795308507


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _make_upstream_run(root: Path, *, run_id: str = "20261121T152703-fixture") -> Path:
    run_dir = root / "2026-11-21" / "research_subscription" / run_id
    run_dir.mkdir(parents=True)
    markdown = (
        f"# {TITLE}\n\n"
        + (
            "研究团队围绕反铁磁畴的形成与演化开展了系统研究，并分析失配位错附近的局部应力。"
            "文章讨论了实验设计、关键变量、观测证据和可能的物理机制。"
            "研究结果表明，界面附近的剪切应力分布能够影响磁畴的空间组织。"
            "作者进一步说明了材料结构、实验条件与机制解释之间的联系。"
            "这些结论需要结合样品条件、测量方法和适用边界理解。\n\n"
        ) * 5
    ).encode("utf-8")
    markdown_sha = hashlib.sha256(markdown).hexdigest()
    (run_dir / "slot1.md").write_bytes(markdown)
    _write(run_dir / "slot1.manifest.json", {
        "output_sha256": markdown_sha,
        "taxonomy_pillar_id": "literature_translation",
        "pillar_id": "literature_manuscript",
    })
    _write(run_dir / "review_state.json", {
        "slots": {"1": {"article_sha256": markdown_sha}},
    })
    _write(run_dir / "prepared_articles.json", [{
        "title": TITLE,
        "md_body": markdown.decode("utf-8"),
        "raw_markdown": markdown.decode("utf-8"),
        "taxonomy_pillar_id": "literature_translation",
        "pillar_id": "literature_manuscript",
        "doi": "10.1063/5.0348548",
        "bundle_path": r"E:\Agent\WeChat\data\literature_cache\fixture",
        "html_body": "<p>fixture article html</p>",
        "cdn_image_urls": [],
        "file_id": "file-fixture",
        "cover_name": "cover-fixture.jpg",
        "micro_tags": ["反铁磁", "失配位错"],
        # Deliberately no published_at: the draft/worker timestamp must never be used.
    }])
    _write(run_dir / "delivery_result.json", {
        "appmsgid": "100000764",
        "account": "成核生长",
        "state": "DRAFT_CREATED_COLLECTION_CONFIGURED",
        "publication_state": "PENDING_PUBLICATION",
    })
    _write(run_dir / "uploaded_assets_manifest.json", {"assets": []})
    return run_dir


def _make_video_evidence(
    evidence_root: Path,
    run_dir: Path,
    *,
    canonical_url: str = ARTICLE_URL,
    image_manifest: dict | None = None,
) -> Path:
    markdown_sha = hashlib.sha256((run_dir / "slot1.md").read_bytes()).hexdigest()
    prepared = json.loads((run_dir / "prepared_articles.json").read_text(encoding="utf-8"))[0]
    evidence_dir = evidence_root / "20261125_100000_100000764_article_summary"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _write(evidence_dir / "article_summary_manifest.json", {
        "schema_version": 1,
        "content_type": "article_summary",
        "appmsgid": "100000764",
        "article_id": "100000764_0",
        "article_title": TITLE,
        "canonical_url": canonical_url,
        "canonical_url_verified": True,
        "source_article_sha256": markdown_sha,
        "account_name": "成核生长",
        "editorial_slot": 1,
        "article_type": "literature_translation",
        "editorial_pillar_id": "literature_manuscript",
        "image_count": len(image_manifest or {}),
        "image_manifest": image_manifest or {},
    })
    _write(evidence_dir / "source_record.json", {
        "source_type": "published_wechat_article",
        "appmsgid": "100000764",
        "article_id": "100000764_0",
        "title": prepared["title"],
        "editorial_slot": 1,
        "article_type": "literature_translation",
        "editorial_pillar_id": "literature_manuscript",
        "canonical_url": canonical_url,
        "canonical_url_verified": True,
        "article_markdown_sha256": markdown_sha,
    })
    # This mirrors the real evidence shape: the file records the URL; it does
    # not serialize browser selector names or DOM attribute names.
    _write(evidence_dir / "url_verification_evidence.json", {"url": canonical_url})
    _write(evidence_dir / "upload_preflight_report.json", {
        "url_provenance": {
            "endpoint": ALBUM_URL,
            "article_url": canonical_url,
        },
    })
    _write(evidence_dir / "article_read_count_probe.json", {
        "url": canonical_url,
        "ct": CT,
        "read_count": 12,
    })
    return evidence_dir


def _discover(root: Path, evidence_root: Path):
    return discover_upstream_literature_runs(
        root,
        publication_evidence_root=evidence_root,
        account_key="research_subscription",
        account_name="成核生长",
        expected_biz_id="MzIyMjY1ODkwMA==",
        target_date=date(2026, 11, 22),
        timezone_name="Asia/Shanghai",
    )


def test_discovers_published_article_from_existing_daily_run_and_external_video_evidence(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = _make_video_evidence(evidence_root, run_dir)

    candidates, rejected = _discover(root, evidence_root)

    assert len(candidates) == 1, rejected
    assert rejected == []
    candidate = candidates[0]
    assert candidate["source_run_dir"] == run_dir
    assert candidate["publication_evidence_dir"] == evidence_dir
    assert candidate["article_id"] == "100000764_0"
    assert candidate["appmsgid"] == "100000764"
    assert candidate["published_at"] == "2026-11-22T00:48:27Z"
    assert candidate["local_date"] == "2026-11-22"
    assert candidate["canonical_url"] == ARTICLE_URL
    assert candidate["publication_time_field_path"] == "$.ct"
    assert candidate["publication_time_details"]["field_path"] == "$.url"
    assert candidate["publication_time_details"]["album_mid"] == "2247484414"
    assert candidate["publication_time_details"]["album_mid"] != candidate["appmsgid"]
    assert candidate["publication_time_details"]["album_item_index"] == "1"


def test_materializes_byte_identical_package_with_external_evidence_provenance(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = _make_video_evidence(evidence_root, run_dir)
    candidates, rejected = _discover(root, evidence_root)
    assert len(candidates) == 1, rejected

    package_dir = materialize_upstream_article_package(
        candidates[0], tmp_path / "Video" / "runtime" / "upstream_article_packages"
    )

    package = load_article_package(package_dir)
    assert package["article"]["article_id"] == "100000764_0"
    assert package["article"]["appmsgid"] == "100000764"
    assert package["article"]["published_at"] == "2026-11-22T00:48:27Z"
    assert package["article"]["publication_time_provenance"]["raw_ct"] == CT
    assert package["article"]["canonical_url"] == ARTICLE_URL
    assert package["article"]["url_provenance"]["endpoint"] == ALBUM_URL
    assert package["article"]["url_provenance"]["evidence_directory"] == str(evidence_dir)
    assert package["article"]["official_album_entry"]["data_msgid"] == "2247484414"
    assert package["markdown_sha256"] == candidates[0]["markdown_sha256"]
    assert (package_dir / "article.md").read_bytes() == (run_dir / "slot1.md").read_bytes()
    assert json.loads((package_dir / "images.json").read_text(encoding="utf-8")) == {"images": []}


def test_reuses_two_verified_original_images_from_matching_video_package(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = evidence_root / "20261125_100000_100000764_article_summary"
    image_dir = evidence_dir / "source" / "images"
    image_dir.mkdir(parents=True)
    context = "研究团队围绕反铁磁畴的形成与演化开展了系统研究"
    records = {}
    for image_id in ("IMG01", "IMG02"):
        image_path = image_dir / f"{image_id}.png"
        image_bytes = f"verified-{image_id}".encode("utf-8")
        image_path.write_bytes(image_bytes)
        records[image_id] = {
            "image_id": image_id,
            "path": str(image_path),
            "caption": context,
            "context": context,
            "image_aspect": 1.5,
            "sha256": hashlib.sha256(image_bytes).hexdigest(),
        }
    _make_video_evidence(evidence_root, run_dir, image_manifest=records)

    class FakeImage:
        size = (300, 200)
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def verify(self):
            return None

    fake_pil = types.ModuleType("PIL")
    fake_pil.Image = types.SimpleNamespace(open=lambda _path: FakeImage())
    monkeypatch.setitem(sys.modules, "PIL", fake_pil)

    candidates, rejected = _discover(root, evidence_root)

    assert len(candidates) == 1, rejected
    assert candidates[0]["verified_video_image_count"] == 2
    assert candidates[0]["image_asset_source"] == "matching_video_production_output"
    package_dir = materialize_upstream_article_package(
        candidates[0], tmp_path / "Video" / "runtime" / "upstream_article_packages"
    )
    image_manifest = json.loads((package_dir / "images.json").read_text(encoding="utf-8"))
    assert len(image_manifest["images"]) == 2
    for record in image_manifest["images"]:
        expected = (image_dir / f"{record['image_id']}.png").read_bytes()
        assert (package_dir / record["file"]).read_bytes() == expected


def test_rejects_mismatched_slot_hash_chain_before_looking_up_publication_evidence(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    _make_video_evidence(evidence_root, run_dir)
    _write(run_dir / "review_state.json", {"slots": {"1": {"article_sha256": "0" * 64}}})

    candidates, rejected = _discover(root, evidence_root)

    assert candidates == []
    assert any("review_state.json slots.1.article_sha256" in item["reason"] for item in rejected)


def test_accepts_ct_probe_without_duplicate_url_when_video_package_binds_article_identity(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = _make_video_evidence(evidence_root, run_dir)
    probe_path = evidence_dir / "article_read_count_probe.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    probe.pop("url")
    _write(probe_path, probe)

    candidates, rejected = _discover(root, evidence_root)

    assert len(candidates) == 1, rejected
    assert rejected == []
    assert candidates[0]["publication_time_details"]["ct_binding"] == (
        "paired_video_output_evidence_bound_by_article_id_appmsgid_title_and_markdown_sha256"
    )


def test_rejects_publication_time_when_video_probe_url_does_not_match_verified_article_url(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = _make_video_evidence(evidence_root, run_dir)
    _write(evidence_dir / "article_read_count_probe.json", {
        "url": "https://mp.weixin.qq.com/s?__biz=MzIyMjY1ODkwMA==&mid=999999&idx=1",
        "ct": CT,
    })

    candidates, rejected = _discover(root, evidence_root)

    assert candidates == []
    assert any("different public article URL" in item["reason"] for item in rejected), rejected


def test_rejects_video_evidence_for_another_public_account(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_dir = _make_video_evidence(evidence_root, run_dir)
    wrong_url = ARTICLE_URL.replace("MzIyMjY1ODkwMA==", "WRONG_BIZ")
    for filename in ("url_verification_evidence.json", "article_read_count_probe.json"):
        _write(evidence_dir / filename, {"url": wrong_url, "ct": CT})
    preflight = _read_json_for_test(evidence_dir / "upload_preflight_report.json")
    preflight["url_provenance"]["article_url"] = wrong_url
    _write(evidence_dir / "upload_preflight_report.json", preflight)
    manifest = _read_json_for_test(evidence_dir / "article_summary_manifest.json")
    source = _read_json_for_test(evidence_dir / "source_record.json")
    manifest["canonical_url"] = wrong_url
    source["canonical_url"] = wrong_url
    _write(evidence_dir / "article_summary_manifest.json", manifest)
    _write(evidence_dir / "source_record.json", source)

    candidates, rejected = _discover(root, evidence_root)

    assert candidates == []
    assert any("__biz" in item["reason"] for item in rejected)


def _read_json_for_test(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_reports_missing_matching_video_evidence_bundle(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    evidence_root.mkdir(parents=True)

    candidates, rejected = _discover(root, evidence_root)

    assert candidates == []
    assert len(rejected) == 1
    assert "No matching Video production evidence bundle" in rejected[0]["reason"]
    assert str(run_dir) == rejected[0]["path"]


def test_refuses_to_overwrite_a_conflicting_materialized_package(tmp_path: Path) -> None:
    root = tmp_path / "WeChat_control" / "data" / "daily_runs"
    evidence_root = tmp_path / "Video" / "outputs"
    run_dir = _make_upstream_run(root)
    _make_video_evidence(evidence_root, run_dir)
    candidates, rejected = _discover(root, evidence_root)
    assert len(candidates) == 1, rejected
    package_root = tmp_path / "Video" / "runtime" / "upstream_article_packages"
    package_dir = materialize_upstream_article_package(candidates[0], package_root)
    (package_dir / "article.md").write_text("changed", encoding="utf-8")

    with pytest.raises(UpstreamArticleError, match="not overwriting"):
        materialize_upstream_article_package(candidates[0], package_root)
