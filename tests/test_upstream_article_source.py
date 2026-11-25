from __future__ import annotations

import hashlib
import json
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
ARTICLE_URL = "https://mp.weixin.qq.com/s/published-article-fixture"
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
        "account_name": "成核生长",
        "state": "DRAFT_CREATED_COLLECTION_CONFIGURED",
        "publication_state": "PENDING_PUBLICATION",
    })
    _write(run_dir / "url_verification_evidence.json", {
        "source_page_url": ALBUM_URL,
        "selector": "li.album__list-item[data-link]",
        "attribute": "data-link",
        "data-link": ARTICLE_URL,
        "data-msgid": "2247484414",
        "data-itemidx": "1",
        "title": TITLE,
        "visible_article_page": True,
    })
    _write(run_dir / "upload_preflight_report.json", {
        "url_provenance": {
            "endpoint": ALBUM_URL,
            "field_path": "li.album__list-item[data-link]",
            "article_url": ARTICLE_URL,
        },
    })
    _write(run_dir / "article_read_count_probe.json", {
        "url": ARTICLE_URL,
        "ct": CT,
        "read_count": 12,
    })
    _write(run_dir / "uploaded_assets_manifest.json", {"assets": []})
    return run_dir


def _discover(root: Path):
    return discover_upstream_literature_runs(
        root,
        account_key="research_subscription",
        account_name="成核生长",
        expected_biz_id="MzIyMjY1ODkwMA==",
        target_date=date(2026, 11, 22),
        timezone_name="Asia/Shanghai",
    )


def test_discovers_published_article_from_existing_daily_run_without_manual_package(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    run_dir = _make_upstream_run(root)

    candidates, rejected = _discover(root)

    assert len(candidates) == 1, rejected
    assert rejected == []
    candidate = candidates[0]
    assert candidate["source_run_dir"] == run_dir
    assert candidate["article_id"] == "100000764_0"
    assert candidate["appmsgid"] == "100000764"
    assert candidate["published_at"] == "2026-11-22T00:48:27Z"
    assert candidate["local_date"] == "2026-11-22"
    assert candidate["canonical_url"] == ARTICLE_URL
    assert candidate["publication_time_field_path"] == "$.ct"
    assert candidate["publication_time_details"]["album_mid"] == "2247484414"
    assert candidate["publication_time_details"]["album_mid"] != candidate["appmsgid"]


def test_materializes_byte_identical_video_local_package_and_preserves_provenance(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    _make_upstream_run(root)
    candidates, _ = _discover(root)
    package_dir = materialize_upstream_article_package(
        candidates[0], tmp_path / "Video" / "runtime" / "upstream_article_packages"
    )

    package = load_article_package(package_dir)
    assert package["article"]["article_id"] == "100000764_0"
    assert package["article"]["appmsgid"] == "100000764"
    assert package["article"]["published_at"] == "2026-11-22T00:48:27Z"
    assert package["article"]["publication_time_provenance"]["raw_ct"] == CT
    assert package["article"]["canonical_url"] == ARTICLE_URL
    assert package["markdown_sha256"] == candidates[0]["markdown_sha256"]
    assert (package_dir / "article.md").read_bytes() == (
        Path(candidates[0]["source_run_dir"]) / "slot1.md"
    ).read_bytes()
    assert json.loads((package_dir / "images.json").read_text(encoding="utf-8")) == {"images": []}


def test_rejects_mismatched_slot_hash_chain(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    run_dir = _make_upstream_run(root)
    _write(run_dir / "review_state.json", {"slots": {"1": {"article_sha256": "0" * 64}}})

    candidates, rejected = _discover(root)

    assert candidates == []
    assert any("review_state.json slots.1.article_sha256" in item["reason"] for item in rejected)


def test_accepts_ct_from_same_run_probe_when_probe_omits_duplicate_article_url(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    run_dir = _make_upstream_run(root)
    probe = json.loads((run_dir / "article_read_count_probe.json").read_text(encoding="utf-8"))
    probe.pop("url")
    _write(run_dir / "article_read_count_probe.json", probe)

    candidates, rejected = _discover(root)

    assert len(candidates) == 1
    assert rejected == []
    assert candidates[0]["publication_time_details"]["ct_binding"] == (
        "same_run_article_read_count_probe_scoped_by_verified_album_evidence"
    )


def test_rejects_publication_time_when_probe_url_does_not_match_album_data_link(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    run_dir = _make_upstream_run(root)
    _write(run_dir / "article_read_count_probe.json", {
        "url": "https://mp.weixin.qq.com/s/a-different-article",
        "ct": CT,
    })

    candidates, rejected = _discover(root)

    assert candidates == []
    assert any("different article URL" in item["reason"] for item in rejected), rejected


def test_rejects_album_page_for_another_public_account(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    run_dir = _make_upstream_run(root)
    wrong_album = ALBUM_URL.replace("MzIyMjY1ODkwMA==", "WRONG_BIZ")
    evidence = json.loads((run_dir / "url_verification_evidence.json").read_text(encoding="utf-8"))
    preflight = json.loads((run_dir / "upload_preflight_report.json").read_text(encoding="utf-8"))
    evidence["source_page_url"] = wrong_album
    preflight["url_provenance"]["endpoint"] = wrong_album
    _write(run_dir / "url_verification_evidence.json", evidence)
    _write(run_dir / "upload_preflight_report.json", preflight)

    candidates, rejected = _discover(root)

    assert candidates == []
    assert any("album __biz mismatch" in item["reason"] for item in rejected)


def test_refuses_to_overwrite_a_conflicting_materialized_package(tmp_path: Path) -> None:
    root = tmp_path / "data" / "daily_runs"
    _make_upstream_run(root)
    candidates, _ = _discover(root)
    package_root = tmp_path / "Video" / "runtime" / "upstream_article_packages"
    package_dir = materialize_upstream_article_package(candidates[0], package_root)
    (package_dir / "article.md").write_text("changed", encoding="utf-8")

    with pytest.raises(UpstreamArticleError, match="not overwriting"):
        materialize_upstream_article_package(candidates[0], package_root)
