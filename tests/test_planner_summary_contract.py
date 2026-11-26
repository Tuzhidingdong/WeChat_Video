"""Self-contained offline tests for the strict planner contract and adapter.

All article data is synthetic and constructed under tmp_path. No local outputs/
or content/ files are required, so these tests run in a clean GitHub checkout.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wechat_video.article_source import load_article_package
from wechat_video.planner_output_schema import (
    PlannerContractError, _CJK_RE, validate_planner_output,
)
from wechat_video.planner_summary_adapter import adapt_planner_output
from wechat_video.source_paragraphs import build_paragraph_index

ARTICLE_ID = "TEST001_0"
APPMSGID = "TEST001"
SYNTHETIC_TITLE = "合成测试文章：盐调控单层薄膜的界面组装"
CAPTION = "图一｜合成薄膜的显微结构与孔径分布"
QUOTE = "这种方法把普通盐变成界面组装的开关。"

PARAGRAPHS = [
    "# 合成测试文章：盐调控单层薄膜的界面组装",
    "研究对象是一种层状聚合物薄膜。传统界面组装常形成多层堆叠，难以获得真正的单层结构。",
    "研究者向水相体系加入氯化钾，利用离子屏蔽与盐析效应稳定复合胶束，并驱动其在油水界面横向铺展。",
    "显微图像显示，所得薄膜横向尺寸约为2.5微米，平均孔径约为13纳米，厚度仅为4纳米。",
    "升温到三百三十三开尔文后，薄膜形貌保持不变；冷却到二百九十三开尔文后，结构几乎原样恢复。",
    "机制可概括为三步：离子屏蔽削弱排斥，盐析促使胶束脱水，界面能降低驱动单层排列。",
    "光谱结果显示，特征峰位保持不变，说明组装过程没有改变材料的化学骨架。",
    "综上，盐效应为构筑单层介孔薄膜提供了一条可重复的路径。",
    CAPTION,
    QUOTE,
]
MARKDOWN = "\n\n".join(PARAGRAPHS) + "\n"
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000100ffffffff0000000049454e44ae426082"
)


def _make_package(tmp_path: Path) -> Path:
    root = tmp_path / "article-package"
    (root / "images").mkdir(parents=True)
    (root / "article.md").write_text(MARKDOWN, encoding="utf-8")
    (root / "article.json").write_text(json.dumps({
        "schema_version": 1, "account_name": "成核生长", "editorial_slot": 1,
        "article_type": "literature_translation", "editorial_pillar_id": "literature_manuscript",
        "publication_status": "PUBLISHED", "appmsgid": APPMSGID, "article_id": ARTICLE_ID,
        "title": SYNTHETIC_TITLE, "published_at": "2026-11-25T08:00:00+08:00",
        "canonical_url": None, "canonical_url_verified": False,
    }, ensure_ascii=False), encoding="utf-8")
    (root / "images.json").write_text(json.dumps({"images": [
        {"image_id": "IMG01", "file": "images/IMG01.png", "caption": CAPTION,
         "context": CAPTION, "image_aspect": 1.0},
        {"image_id": "IMG02", "file": "images/IMG02.png", "caption": CAPTION,
         "context": CAPTION, "image_aspect": 1.0},
    ]}, ensure_ascii=False), encoding="utf-8")
    for name in ("IMG01.png", "IMG02.png"):
        (root / "images" / name).write_bytes(_PNG)
    return root


def _paragraph_index(text: str) -> int:
    matches = [item["paragraph_index"] for item in build_paragraph_index(MARKDOWN)
               if text in item["text"]]
    assert len(matches) == 1, (text, matches)
    return matches[0]


def _legal_output() -> dict:
    claims = [
        ("C1", "传统组装容易形成多层堆叠。", PARAGRAPHS[1]),
        ("C2", "氯化钾帮助稳定胶束并驱动横向铺展。", PARAGRAPHS[2]),
        ("C3", "结构尺寸由显微图像定量给出。", PARAGRAPHS[3]),
        ("C4", "结构在热循环后几乎原样恢复。", PARAGRAPHS[4]),
        ("C5", "机制包含离子屏蔽、盐析与界面能降低。", PARAGRAPHS[5]),
        ("C6", "光谱结果说明化学骨架未改变。", PARAGRAPHS[6]),
    ]
    claim_data = [
        {"claim_id": cid, "statement": statement,
         "source_ref": {"paragraph_index": _paragraph_index(excerpt)}}
        for cid, statement, excerpt in claims
    ]
    spoken = [
        "合成薄膜为何总是层层堆叠，难以形成真正的单层？",
        "研究者向水相加入氯化钾，稳定胶束并驱动界面横向铺展。",
        "显微图像给出尺寸：横向约二点五微米，孔径约十三纳米，厚度仅四纳米。",
        "升温之后薄膜形貌不变，冷却之后结构几乎原样恢复。",
        "机制分三步：离子屏蔽削弱排斥，盐析促使胶束脱水，界面能降低驱动单层排列。",
        "光谱结果显示特征峰位不变，说明化学骨架没有改变。",
        "盐效应为单层介孔薄膜提供了一条可重复的构筑路径。",
    ]
    # Pad only this synthetic fixture until the calibrated Han budget is met.
    while len(_CJK_RE.findall("".join(spoken))) < 222:
        spoken[-1] += "仍需重复验证。"
    assert 222 <= len(_CJK_RE.findall("".join(spoken))) <= 235

    kinds = ["hook", "image", "stat", "compare", "mechanism", "quote", "takeaway"]
    claim_ids = [item["claim_id"] for item in claim_data]
    units, beats = [], []
    for index, (text, kind) in enumerate(zip(spoken, kinds)):
        unit_id, beat_id = f"U{index + 1:02d}", f"B{index + 1:02d}"
        refs = [claim_ids[min(index, len(claim_ids) - 1)]]
        if index >= 2:
            refs.append(claim_ids[index - 2])
        units.append({
            "unit_id": unit_id, "spoken_text": text, "display_text": text,
            "claim_ids": refs, "visual_beat_id": beat_id, "pause_after_ms": 500,
        })
        beat = {"beat_id": beat_id, "unit_id": unit_id, "kind": kind,
                "headline": f"第{index + 1}段", "claim_ids": refs}
        if kind == "image":
            beat["image_ids"] = ["IMG01"]
        elif kind == "stat":
            beat["stat_value"] = "13"
            beat["stat_label"] = "平均孔径（纳米）"
        elif kind == "compare":
            beat["left"] = {"label": "升温", "detail": "形貌不变"}
            beat["right"] = {"label": "冷却", "detail": "原样恢复"}
        elif kind == "mechanism":
            beat["steps"] = ["离子屏蔽", "盐析脱水", "界面能降低"]
        elif kind == "quote":
            beat["quote"] = QUOTE
        beats.append(beat)
    return {
        "schema_version": 1,
        "summary_title": SYNTHETIC_TITLE,
        "channels_title": "盐调控单层薄膜",
        "core_thesis": "盐效应能够驱动单层薄膜的界面组装。",
        "thesis_claim_ids": ["C2"],
        "claims": claim_data,
        "speech_units": units,
        "beats": beats,
    }


def _validate(output: dict, package, *, article_id=ARTICLE_ID, sha=None):
    return validate_planner_output(
        output, article_id=article_id,
        article_sha256=sha or package["markdown_sha256"],
        image_ids=set(package["images"]),
    )


def test_legal_output_without_metadata_echo_passes_and_adapts(tmp_path: Path) -> None:
    package = load_article_package(_make_package(tmp_path))
    output = _legal_output()
    assert "article_id" not in output and "source_article_sha256" not in output
    validated = _validate(output, package)
    assert validated["article_id"] == ARTICLE_ID
    summary = adapt_planner_output(validated, package=package, paragraphs=build_paragraph_index(package["markdown"]))
    assert summary["article_id"] == ARTICLE_ID
    assert summary["source_article_sha256"] == package["markdown_sha256"]


@pytest.mark.parametrize("key,value,expected", [
    ("article_id", ARTICLE_ID, None),
    ("article_id", "WRONG_0", "article_id echo"),
    ("source_article_sha256", "PLACEHOLDER", None),
    ("source_article_sha256", "0" * 64, "echo conflicts"),
])
def test_metadata_echo_is_checked_when_present(tmp_path: Path, key, value, expected) -> None:
    package = load_article_package(_make_package(tmp_path))
    output = _legal_output()
    if key == "source_article_sha256" and value == "PLACEHOLDER":
        value = package["markdown_sha256"]
    output[key] = value
    if expected:
        with pytest.raises(PlannerContractError, match=expected):
            _validate(output, package)
    else:
        validated = _validate(output, package)
        assert validated["article_id"] == ARTICLE_ID
        summary = adapt_planner_output(validated, package=package, paragraphs=build_paragraph_index(package["markdown"]))
        assert summary["article_id"] == ARTICLE_ID
        assert summary["source_article_sha256"] == package["markdown_sha256"]


@pytest.mark.parametrize("mutate", [
    lambda o: o.pop("summary_title"),
    lambda o: o.update({"unexpected": True}),
    lambda o: o["claims"][0].update({"statement": ""}),
    lambda o: o["speech_units"][0].update({"claim_ids": ["NOPE"]}),
    lambda o: o["speech_units"][0].update({"visual_beat_id": "NOPE"}),
    lambda o: o["beats"][0].update({"kind": "unknown"}),
    lambda o: o["beats"][1].update({"image_ids": ["NOPE"]}),
    lambda o: o["beats"][2].update({"stat_value": ""}),
    lambda o: o["beats"][4].update({"steps": ["only one"]}),
    lambda o: o["speech_units"][0].update({"spoken_text": "短"}),
])
def test_invalid_planner_outputs_fail(tmp_path: Path, mutate) -> None:
    package = load_article_package(_make_package(tmp_path))
    output = _legal_output()
    mutate(output)
    with pytest.raises(PlannerContractError):
        _validate(output, package)


def test_missing_paragraph_index_fails_in_adapter(tmp_path: Path) -> None:
    package = load_article_package(_make_package(tmp_path))
    output = _legal_output()
    output["claims"][0]["source_ref"]["paragraph_index"] = 99999
    validated = _validate(output, package)
    with pytest.raises(PlannerContractError, match="paragraph_index"):
        adapt_planner_output(validated, package=package, paragraphs=build_paragraph_index(package["markdown"]))


def test_failed_model_shapes_are_rejected(tmp_path: Path) -> None:
    package = load_article_package(_make_package(tmp_path))
    hy4_shape = {
        "account_name": "成核生长", "source_title": "标题", "spoken_text": "长旁白",
        "speech_units": [{"unit_id": "SU1", "spoken_text": "旁白", "claims": [], "visual_beat": {}}],
        "constraints_check": {},
    }
    hungerg_shape = {
        "account_name": "成核生长", "source_files": [],
        "speech_units": [{"unit_id": 1, "spoken_text": "旁白", "source_excerpt": "摘录",
                          "visual_beat": {"image_id": "IMG01"}}],
    }
    for output in (hy4_shape, hungerg_shape):
        with pytest.raises(PlannerContractError):
            _validate(output, package)


def test_prompt_matches_contract() -> None:
    from wechat_video.daily_pipelines import _literature_prompt

    prompt = _literature_prompt({"article_id": ARTICLE_ID}, "0" * 64, [])
    assert '"schema_version":1' in prompt
    assert "source_ref" in prompt and "paragraph_index" in prompt
    assert "visual_beat_id" in prompt
    assert "source_excerpt" not in prompt
    assert "Do NOT output article_id" in prompt


def test_paragraph_index_is_deterministic_and_excerpt_is_exact(tmp_path: Path) -> None:
    root = _make_package(tmp_path)
    markdown = (root / "article.md").read_text(encoding="utf-8")
    first = build_paragraph_index(markdown)
    assert build_paragraph_index(markdown) == first
    assert len({item["paragraph_index"] for item in first}) == len(first)
    assert all(item["text"] in markdown for item in first)
