from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from wechat_video.article_source import (
    ArticleSourceError,
    build_article_channels_metadata,
    load_article_package,
    validate_article_summary,
)


ARTICLE_TEXT = """# 测试文章标题

研究团队在受控条件下观察到这一现象，并比较了不同参数组合。研究人员进一步分析了过程中的关键因素，发现体系结构与外部条件共同影响最终结果。

本文围绕实验观察、关键变量和机制解释展开。不同参数会改变体系的能量代价，因此不同路径可能产生不同结果。作者强调，解释实验现象时需要区分直接测量结果和基于结果提出的机制推断。

研究还指出，适用条件和实验边界会影响结论的外推范围。理解这些限制，有助于避免把特定条件下的现象误认为普遍规律。以上内容构成文章的主要证据和结论。
"""


def _make_package(tmp_path: Path) -> tuple[Path, dict]:
    root = tmp_path / "published_article"
    root.mkdir()
    (root / "article.md").write_text(ARTICLE_TEXT, encoding="utf-8")
    (root / "images.json").write_text(json.dumps({"images": []}), encoding="utf-8")
    article = {
        "schema_version": 1,
        "account_name": "成核生长",
        "editorial_slot": 1,
        "editorial_pillar_id": "literature_translation",
        "publication_status": "PUBLISHED",
        "article_id": "100000764_0",
        "title": "一篇用于验证摘要数据契约的已发表精读文章",
        "published_at": "2026-11-21T21:10:55+08:00",
        "canonical_url": "https://mp.weixin.qq.com/s/verifiedArticleIdentifier",
        "canonical_url_verified": True,
        "url_provenance": {
            "endpoint": "/cgi-bin/appmsgpublish?sub=list",
            "field_path": "publish_page.publish_list[0].publish_info.appmsgex[0].link",
            "verified_at": "2026-11-23T12:00:00+08:00",
            "read_only": True,
        },
    }
    (root / "article.json").write_text(
        json.dumps(article, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "schema_version": 1,
        "article_id": article["article_id"],
        "source_article_sha256": hashlib.sha256(ARTICLE_TEXT.encode("utf-8")).hexdigest(),
        "summary_title": "研究机制与实验发现",
        "channels_title": "精读：机制发现",
        "core_thesis": "这篇文章说明，实验现象需要结合关键变量、过程机制和适用条件共同理解。",
        "thesis_claim_ids": ["C1"],
        "claims": [
            {
                "claim_id": "C1",
                "statement": "受控实验比较了不同参数组合。",
                "source_excerpt": "研究团队在受控条件下观察到这一现象，并比较了不同参数组合。",
            }
        ],
        "speech_units": [
            {
                "unit_id": f"U{index:02d}",
                "spoken_text": text,
                "display_text": text,
                "claim_ids": ["C1"],
                "visual_trigger_ids": [f"B{index:02d}"],
                "pause_after_ms": 250,
            }
            for index, text in enumerate(
                [
                    "今天这篇文章提出了一个值得注意的问题，研究者试图解释实验中观察到的关键现象。",
                    "作者通过对照实验比较了不同条件，发现变化并非来自单一因素，而与体系结构有关。",
                    "结果显示，核心参数会改变过程的能量代价，因此不同路径可能产生不同结果。",
                    "这说明理解机制时不能只看最终结果，还需要结合中间过程和适用条件判断。",
                    "对实际研究而言，最重要的是识别决定性因素，并区分实验结果与机制解释。",
                ],
                start=1,
            )
        ],
        "beats": [
            {"beat_id": "B01", "unit_id": "U01", "kind": "hook", "headline": "一个值得追问的问题", "claim_ids": ["C1"]},
            {"beat_id": "B02", "unit_id": "U02", "kind": "quote", "headline": "实验观察", "quote": "研究团队在受控条件下观察到这一现象，并比较了不同参数组合。", "claim_ids": ["C1"]},
            {"beat_id": "B03", "unit_id": "U03", "kind": "mechanism", "headline": "关键变量如何影响结果", "steps": ["比较条件", "识别变量", "解释差异"], "claim_ids": ["C1"]},
            {"beat_id": "B04", "unit_id": "U04", "kind": "compare", "headline": "测量结果与机制解释", "left": {"label": "直接观察", "detail": "实验记录到的现象"}, "right": {"label": "机制解释", "detail": "由证据支持的推断"}, "claim_ids": ["C1"]},
            {"beat_id": "B05", "unit_id": "U05", "kind": "takeaway", "headline": "带走一个判断原则", "body": "区分证据、解释与适用边界。", "claim_ids": ["C1"]},
        ],
    }
    return root, summary


def test_published_article_package_and_summary_validate(tmp_path: Path) -> None:
    article_dir, summary = _make_package(tmp_path)
    package = load_article_package(article_dir)

    validated = validate_article_summary(package, summary)
    metadata = build_article_channels_metadata(
        package["article"], validated, "20261123_100000_100000764_article_summary"
    )

    assert validated["spoken_cjk_characters"] >= 150
    assert metadata["extended_link"]["url"] == package["article"]["canonical_url"]
    assert metadata["extended_link"]["article_id"] == "100000764_0"
    assert metadata["extended_link_required"] is True
    assert metadata["extended_link_status"] == "UNVERIFIED_PLATFORM_UI"
    assert metadata["automatic_publication"] is False


def test_unpublished_source_is_rejected(tmp_path: Path) -> None:
    article_dir, _ = _make_package(tmp_path)
    path = article_dir / "article.json"
    article = json.loads(path.read_text(encoding="utf-8"))
    article["publication_status"] = "DRAFT"
    path.write_text(json.dumps(article), encoding="utf-8")

    with pytest.raises(ArticleSourceError, match="already-published"):
        load_article_package(article_dir)


def test_article_url_with_auth_query_is_rejected(tmp_path: Path) -> None:
    article_dir, _ = _make_package(tmp_path)
    path = article_dir / "article.json"
    article = json.loads(path.read_text(encoding="utf-8"))
    article["canonical_url"] += "?token=12345"
    path.write_text(json.dumps(article), encoding="utf-8")

    with pytest.raises(ArticleSourceError, match="authentication-related"):
        load_article_package(article_dir)


def test_unverified_url_provenance_is_rejected(tmp_path: Path) -> None:
    article_dir, _ = _make_package(tmp_path)
    path = article_dir / "article.json"
    article = json.loads(path.read_text(encoding="utf-8"))
    article["canonical_url_verified"] = False
    path.write_text(json.dumps(article), encoding="utf-8")

    with pytest.raises(ArticleSourceError, match="not been verified"):
        load_article_package(article_dir)


def test_summary_cannot_cite_text_absent_from_original_article(tmp_path: Path) -> None:
    article_dir, summary = _make_package(tmp_path)
    package = load_article_package(article_dir)
    summary["claims"][0]["source_excerpt"] = "这句话完全没有出现在文章原文中。"

    with pytest.raises(ArticleSourceError, match="not an exact excerpt"):
        validate_article_summary(package, summary)


def test_summary_hash_must_match_original_article(tmp_path: Path) -> None:
    article_dir, summary = _make_package(tmp_path)
    package = load_article_package(article_dir)
    summary["source_article_sha256"] = "0" * 64

    with pytest.raises(ArticleSourceError, match="does not match article.md"):
        validate_article_summary(package, summary)


def test_unknown_original_image_reference_is_rejected(tmp_path: Path) -> None:
    article_dir, summary = _make_package(tmp_path)
    package = load_article_package(article_dir)
    summary["beats"][1]["kind"] = "image"
    summary["beats"][1]["image_ids"] = ["IMG404"]

    with pytest.raises(ArticleSourceError, match="unknown article image"):
        validate_article_summary(package, summary)


def test_three_consecutive_same_visual_beats_are_rejected(tmp_path: Path) -> None:
    article_dir, summary = _make_package(tmp_path)
    package = load_article_package(article_dir)
    for beat in summary["beats"][:3]:
        beat["kind"] = "hook"

    with pytest.raises(ArticleSourceError, match="Three consecutive"):
        validate_article_summary(package, summary)


def test_image_paths_cannot_escape_article_package(tmp_path: Path) -> None:
    article_dir, _ = _make_package(tmp_path)
    image_file = tmp_path / "outside.png"
    image_file.write_bytes(b"synthetic")
    image_doc = {"images": [{
        "image_id": "IMG01",
        "file": "../outside.png",
        "image_aspect": 1.0,
    }]}
    (article_dir / "images.json").write_text(
        json.dumps(image_doc), encoding="utf-8"
    )

    with pytest.raises(ArticleSourceError, match="escapes the package"):
        load_article_package(article_dir)


def test_non_literature_slot_is_not_accepted_as_daily_reading_article(tmp_path: Path) -> None:
    article_dir, _ = _make_package(tmp_path)
    path = article_dir / "article.json"
    article = json.loads(path.read_text(encoding="utf-8"))
    article["editorial_slot"] = 2
    path.write_text(json.dumps(article), encoding="utf-8")

    with pytest.raises(ArticleSourceError, match="Slot 1 literature_translation"):
        load_article_package(article_dir)


def test_core_thesis_must_reference_evidence_claims(tmp_path: Path) -> None:
    article_dir, summary = _make_package(tmp_path)
    package = load_article_package(article_dir)
    summary["thesis_claim_ids"] = ["MISSING"]

    with pytest.raises(ArticleSourceError, match="thesis_claim_ids"):
        validate_article_summary(package, summary)
