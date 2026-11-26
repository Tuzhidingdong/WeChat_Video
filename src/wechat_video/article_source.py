"""Validated hand-off contract for published WeChat articles and one-minute summaries.

The Video project consumes an exported, non-secret article package. It never opens
or reuses the WeChat_control browser profile. Article URLs are accepted only when
their provenance records an observed published-article response field.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse


class ArticleSourceError(ValueError):
    """A published-article package or summary fails evidence validation."""


ALLOWED_BEAT_KINDS = {
    "hook", "image", "stat", "compare", "mechanism", "quote", "takeaway"
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ArticleSourceError(f"Missing article package file: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ArticleSourceError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise ArticleSourceError(f"{path.name} must contain a JSON object.")
    return value


def _safe_child(root: Path, relative: str, *, must_exist: bool = True) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise ArticleSourceError(f"Article asset path escapes the package: {relative!r}")
    if must_exist and not candidate.is_file():
        raise ArticleSourceError(f"Article asset is missing: {relative!r}")
    return candidate


def validate_canonical_article_url(value: Any) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "mp.weixin.qq.com"
        or parsed.username
        or parsed.password
        or not (parsed.path == "/s" or parsed.path.startswith("/s/"))
    ):
        raise ArticleSourceError(
            "canonical_url must be the observed HTTPS mp.weixin.qq.com/s article URL."
        )
    forbidden = {"token", "access_token", "auth", "code", "pass_ticket"}
    if any(key.casefold() in forbidden for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        raise ArticleSourceError("canonical_url contains an authentication-related query parameter.")
    return url


def load_article_package(article_dir: Path) -> dict[str, Any]:
    root = article_dir.resolve()
    if not root.is_dir():
        raise ArticleSourceError(f"Article package directory does not exist: {root}")
    article = _read_json(root / "article.json")
    if article.get("schema_version") != 1:
        raise ArticleSourceError("article.json schema_version must be 1.")
    if article.get("account_name") != "成核生长":
        raise ArticleSourceError("Article package account_name must be exactly '成核生长'.")
    # Map the upstream editorial taxonomy without conflating article type and pillar:
    # prepared_articles.json uses type=literature_translation and
    # pillar_id=literature_manuscript for the Slot 1 reading series.
    if (
        article.get("editorial_slot") != 1
        or article.get("article_type") != "literature_translation"
        or article.get("editorial_pillar_id") != "literature_manuscript"
    ):
        raise ArticleSourceError(
            "Only a published Slot 1 article with article_type=literature_translation "
            "and editorial_pillar_id=literature_manuscript is eligible."
        )
    if str(article.get("publication_status", "")).upper() != "PUBLISHED":
        raise ArticleSourceError("Only an already-published WeChat article may be summarized.")
    article_id = str(article.get("article_id") or "").strip()
    title = str(article.get("title") or "").strip()
    published_at = str(article.get("published_at") or "").strip()
    if not article_id or not title or not published_at:
        raise ArticleSourceError("article.json requires article_id, title, and published_at.")
    try:
        from datetime import datetime
        datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ArticleSourceError("published_at must be an ISO-8601 timestamp.") from exc

    raw_url = str(article.get("canonical_url") or "").strip()
    if article.get("canonical_url_verified") is True:
        if not raw_url:
            raise ArticleSourceError("A verified canonical_url value is required when canonical_url_verified is true.")
        url = validate_canonical_article_url(raw_url)
        provenance = article.get("url_provenance")
        if not isinstance(provenance, dict):
            raise ArticleSourceError("url_provenance must record the observed URL source.")
        for field in ("endpoint", "field_path", "verified_at"):
            if not str(provenance.get(field) or "").strip():
                raise ArticleSourceError(f"url_provenance.{field} is required.")
        endpoint_query = parse_qsl(urlparse(str(provenance["endpoint"])).query, keep_blank_values=True)
        if any(key.casefold() in {"token", "access_token", "auth", "code", "pass_ticket"} for key, _ in endpoint_query):
            raise ArticleSourceError("url_provenance.endpoint must not contain authentication parameters.")
        if provenance.get("read_only") is not True:
            raise ArticleSourceError("Article URL provenance must explicitly record a read-only lookup.")
    elif article.get("canonical_url_verified") is False and not raw_url:
        # A missing URL does not block a local video preview. It will still block
        # any future upload/link-mounting path, which is separately fail-closed.
        url = None
        provenance = None
    else:
        raise ArticleSourceError(
            "A supplied canonical URL must be verified; omit the URL and set "
            "canonical_url_verified=false for local-preview-only production."
        )

    markdown_path = _safe_child(root, "article.md")
    markdown = markdown_path.read_text(encoding="utf-8")
    if len(markdown.strip()) < 300:
        raise ArticleSourceError("article.md is too short for a source-grounded one-minute summary.")
    images_doc = _read_json(root / "images.json")
    image_records = images_doc.get("images")
    if image_records is None and isinstance(images_doc, list):
        image_records = images_doc
    if not isinstance(image_records, list):
        raise ArticleSourceError("images.json must be a list or an object with an images list.")
    images: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(image_records):
        if not isinstance(item, dict):
            raise ArticleSourceError(f"images.json entry {index} must be an object.")
        image_id = str(item.get("image_id") or item.get("id") or "").strip()
        relative = str(item.get("file") or item.get("path") or "").strip()
        if (
            not image_id
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", image_id)
            or not relative
            or image_id in images
        ):
            raise ArticleSourceError(
                f"images.json entry {index} needs a safe unique image_id and file."
            )
        asset_path = _safe_child(root, relative)
        if asset_path.suffix.casefold() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise ArticleSourceError(f"Unsupported article image type: {relative}")
        try:
            aspect = float(item.get("image_aspect", item.get("imageAspect", 0)))
        except (TypeError, ValueError):
            aspect = 0
        if aspect <= 0:
            raise ArticleSourceError(f"Image {image_id} must include a positive image_aspect.")
        images[image_id] = {
            **item,
            "image_id": image_id,
            "file": relative,
            "resolved_path": asset_path,
            "image_aspect": aspect,
        }

    return {
        "root": root,
        "article": {**article, "canonical_url": url, "canonical_url_verified": url is not None, "url_provenance": provenance},
        "markdown": markdown,
        "markdown_path": markdown_path,
        "markdown_sha256": sha256_file(markdown_path),
        "images": images,
    }


def _normalize_source_text(value: str) -> str:
    value = value.replace("\u3000", " ")
    return re.sub(r"\s+", "", value)


def _cjk_count(value: str) -> int:
    return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", value))


def _validate_normalized_rect(region: Any, *, field_name: str, beat_id: str) -> None:
    if not isinstance(region, dict):
        raise ArticleSourceError(f"{beat_id} {field_name} entries must be normalized rectangle objects.")
    try:
        x, y = float(region["x"]), float(region["y"])
        width, height = float(region["width"]), float(region["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ArticleSourceError(
            f"{beat_id} {field_name} requires numeric x, y, width and height."
        ) from exc
    if (
        x < 0 or y < 0 or width <= 0 or height <= 0
        or x + width > 1 or y + height > 1
    ):
        raise ArticleSourceError(
            f"{beat_id} {field_name} must stay inside the normalized source-image bounds."
        )


def validate_article_summary(
    package: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    article = package["article"]
    if summary.get("schema_version") != 1:
        raise ArticleSourceError("summary.json schema_version must be 1.")
    if str(summary.get("article_id") or "") != str(article["article_id"]):
        raise ArticleSourceError("summary.json article_id does not match article.json.")
    if str(summary.get("source_article_sha256") or "").casefold() != package["markdown_sha256"]:
        raise ArticleSourceError("summary.json source_article_sha256 does not match article.md.")
    if not str(summary.get("summary_title") or "").strip():
        raise ArticleSourceError("summary_title is required.")
    channels_title = str(summary.get("channels_title") or "").strip()
    if not 6 <= len(channels_title) <= 16:
        raise ArticleSourceError("channels_title must contain 6–16 characters.")
    thesis = str(summary.get("core_thesis") or "").strip()
    if not thesis:
        raise ArticleSourceError("core_thesis is required.")

    claims = summary.get("claims")
    if not isinstance(claims, list) or not claims:
        raise ArticleSourceError("summary.json must contain evidence-linked claims.")
    claim_map: dict[str, dict[str, str]] = {}
    source_text = _normalize_source_text(package["markdown"])
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ArticleSourceError(f"Claim {index} must be an object.")
        claim_id = str(claim.get("claim_id") or "").strip()
        statement = str(claim.get("statement") or "").strip()
        excerpt = str(claim.get("source_excerpt") or "").strip()
        if not claim_id or claim_id in claim_map or not statement or len(excerpt) < 8:
            raise ArticleSourceError(f"Claim {index} needs unique claim_id, statement, and source_excerpt.")
        if _normalize_source_text(excerpt) not in source_text:
            raise ArticleSourceError(
                f"Claim {claim_id} source_excerpt is not an exact excerpt from article.md."
            )
        claim_map[claim_id] = {"statement": statement, "source_excerpt": excerpt}

    thesis_claim_ids = summary.get("thesis_claim_ids")
    if (
        not isinstance(thesis_claim_ids, list)
        or not thesis_claim_ids
        or not set(str(x) for x in thesis_claim_ids).issubset(claim_map)
    ):
        raise ArticleSourceError("core_thesis must reference one or more valid thesis_claim_ids.")

    units = summary.get("speech_units")
    beats = summary.get("beats")
    if not isinstance(units, list) or not 5 <= len(units) <= 8:
        raise ArticleSourceError("A one-minute summary must contain 5–8 speech_units.")
    if not isinstance(beats, list) or len(beats) != len(units):
        raise ArticleSourceError("There must be exactly one visual beat for each speech unit.")

    unit_map: dict[str, dict[str, Any]] = {}
    spoken_parts: list[str] = []
    for index, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise ArticleSourceError(f"speech_units[{index}] must be an object.")
        unit_id = str(unit.get("unit_id") or "").strip()
        spoken = str(unit.get("spoken_text") or "").strip()
        display = str(unit.get("display_text") or spoken).strip()
        refs = [str(x) for x in (unit.get("claim_ids") or [])]
        if (
            not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", unit_id)
            or unit_id in unit_map
            or not spoken
            or not display
        ):
            raise ArticleSourceError(f"speech_units[{index}] requires a safe unique unit_id and spoken/display text.")
        if not refs or not set(refs).issubset(claim_map):
            raise ArticleSourceError(f"{unit_id} references missing or empty claim_ids.")
        try:
            requested_pause = int(unit.get("pause_after_ms", 500))
        except (TypeError, ValueError) as exc:
            raise ArticleSourceError(f"{unit_id} pause_after_ms must be an integer.") from exc
        if requested_pause < 0 or requested_pause > 1000:
            raise ArticleSourceError(f"{unit_id} pause_after_ms must be between 0 and 1000 ms.")
        # Enforce a deliberate comprehension gap between visual beats.
        pause = max(450, requested_pause)
        visual_ids = unit.get("visual_trigger_ids") or []
        if not isinstance(visual_ids, list) or not visual_ids:
            raise ArticleSourceError(f"{unit_id} must include visual_trigger_ids.")
        normalized = {
            **unit,
            "unit_id": unit_id,
            "spoken_text": spoken,
            "display_text": display,
            "raw_text": str(unit.get("raw_text") or spoken),
            "claim_ids": refs,
            "visual_trigger_ids": [str(x) for x in visual_ids],
            "pause_after_ms": pause,
            "requested_pause_after_ms": requested_pause,
        }
        unit_map[unit_id] = normalized
        spoken_parts.append(spoken)

    spoken_text = "".join(spoken_parts)
    cjk_total = _cjk_count(spoken_text)
    if not 150 <= cjk_total <= 360:
        raise ArticleSourceError(
            f"Spoken script has {cjk_total} Chinese characters; expected 150–360 for a one-minute cut."
        )

    referenced_claims = {claim_id for unit in units for claim_id in unit_map[str(unit["unit_id"])]["claim_ids"]}
    if set(claim_map) - referenced_claims:
        raise ArticleSourceError("Every evidence claim must be referenced by at least one spoken unit.")
    beat_ids: set[str] = set()
    seen_kinds: list[str] = []
    used_images: set[str] = set()
    for index, beat in enumerate(beats):
        if not isinstance(beat, dict):
            raise ArticleSourceError(f"beats[{index}] must be an object.")
        beat_id = str(beat.get("beat_id") or "").strip()
        unit_id = str(beat.get("unit_id") or "").strip()
        kind = str(beat.get("kind") or "").strip()
        if not beat_id or beat_id in beat_ids or unit_id not in unit_map:
            raise ArticleSourceError(f"beats[{index}] needs a unique beat_id and valid unit_id.")
        if kind not in ALLOWED_BEAT_KINDS:
            raise ArticleSourceError(f"Unsupported article beat kind: {kind!r}.")
        if beat_id not in unit_map[unit_id]["visual_trigger_ids"]:
            raise ArticleSourceError(f"{unit_id} must reference its matching beat_id in visual_trigger_ids.")
        claim_refs = [str(x) for x in (beat.get("claim_ids") or unit_map[unit_id]["claim_ids"])]
        if (
            not claim_refs
            or not set(claim_refs).issubset(claim_map)
            or not set(claim_refs).issubset(set(unit_map[unit_id]["claim_ids"]))
        ):
            raise ArticleSourceError(f"{beat_id} has invalid claim_ids for its spoken unit.")
        if not str(beat.get("headline") or "").strip():
            raise ArticleSourceError(f"{beat_id} needs a headline.")
        if kind == "image":
            image_ids = beat.get("image_ids")
            if not isinstance(image_ids, list) or not 1 <= len(image_ids) <= 2:
                raise ArticleSourceError(f"{beat_id} image beat must reference one or two original article images.")
            for image_id in image_ids:
                image_id = str(image_id)
                if image_id not in package["images"]:
                    raise ArticleSourceError(f"{beat_id} references unknown article image {image_id!r}.")
                image_record = package["images"][image_id]
                image_context = str(image_record.get("context") or image_record.get("caption") or "").strip()
                if not image_context or _normalize_source_text(image_context) not in source_text:
                    raise ArticleSourceError(
                        f"Image {image_id!r} has no verified caption/context in article.md."
                    )
                if image_id in used_images:
                    raise ArticleSourceError(f"Article image {image_id!r} is reused in multiple beats.")
                used_images.add(image_id)

            selected_image_ids = {str(image_id) for image_id in image_ids}
            for field_name in ("focus_regions", "display_crop_regions"):
                mapping = beat.get(field_name) or {}
                if not isinstance(mapping, dict):
                    raise ArticleSourceError(
                        f"{beat_id} {field_name} must map image IDs to normalized rectangles."
                    )
                unknown_ids = set(str(key) for key in mapping) - selected_image_ids
                if unknown_ids:
                    raise ArticleSourceError(
                        f"{beat_id} {field_name} references images not selected by this beat: {sorted(unknown_ids)}."
                    )
                for image_id, region in mapping.items():
                    _validate_normalized_rect(
                        region, field_name=f"{field_name}[{image_id}]", beat_id=beat_id
                    )

            axis_labels = beat.get("axis_labels_zh") or {}
            if not isinstance(axis_labels, dict):
                raise ArticleSourceError(
                    f"{beat_id} axis_labels_zh must map image IDs to x/y label objects."
                )
            unknown_axis_ids = set(str(key) for key in axis_labels) - selected_image_ids
            if unknown_axis_ids:
                raise ArticleSourceError(
                    f"{beat_id} axis_labels_zh references images not selected by this beat: {sorted(unknown_axis_ids)}."
                )
            for image_id, labels in axis_labels.items():
                if not isinstance(labels, dict) or set(labels) - {"x", "y"}:
                    raise ArticleSourceError(
                        f"{beat_id} axis_labels_zh[{image_id}] may contain only x and y labels."
                    )
                for axis, label in labels.items():
                    if not isinstance(label, str) or not label.strip() or len(label.strip()) > 40:
                        raise ArticleSourceError(
                            f"{beat_id} axis_labels_zh[{image_id}].{axis} must be a concise 1–40 character label."
                        )
        elif beat.get("image_ids"):
            raise ArticleSourceError(f"{beat_id}: image_ids are only supported by image beats.")
        if kind == "quote":
            quote = str(beat.get("quote") or beat.get("body") or "").strip()
            if not quote or _normalize_source_text(quote) not in source_text:
                raise ArticleSourceError(f"{beat_id} quote is not an exact excerpt from article.md.")
        if kind == "compare" and not (
            isinstance(beat.get("left"), dict) and isinstance(beat.get("right"), dict)
        ):
            raise ArticleSourceError(f"{beat_id} compare beat requires left and right objects.")
        if kind == "mechanism":
            steps = beat.get("steps")
            if not isinstance(steps, list) or not 2 <= len(steps) <= 4:
                raise ArticleSourceError(f"{beat_id} mechanism beat requires 2–4 steps.")
        if kind == "stat":
            stat_value = str(beat.get("stat_value") or "").strip()
            if not stat_value:
                raise ArticleSourceError(f"{beat_id} stat beat requires stat_value.")
            numbers = re.findall(r"\d+(?:\.\d+)?", stat_value)
            if numbers and any(number not in package["markdown"] for number in numbers):
                raise ArticleSourceError(
                    f"{beat_id} includes a numeric value not found in the source article."
                )
        beat_ids.add(beat_id)
        seen_kinds.append(kind)

    unit_ids = set(unit_map)
    if {str(beat.get("unit_id")) for beat in beats} != unit_ids:
        raise ArticleSourceError("Every speech unit must map to exactly one visual beat.")
    if len(seen_kinds) >= 5 and all(kind == seen_kinds[0] for kind in seen_kinds):
        raise ArticleSourceError("The visual plan must vary its scene types.")
    for start in range(len(seen_kinds) - 2):
        if seen_kinds[start] == seen_kinds[start + 1] == seen_kinds[start + 2]:
            raise ArticleSourceError("Three consecutive article beats may not use the same visual type.")

    return {
        **summary,
        "speech_units": [unit_map[str(unit["unit_id"])] for unit in units],
        "beats": beats,
        "claim_map": claim_map,
        "spoken_cjk_characters": cjk_total,
    }


def build_article_channels_metadata(
    article: dict[str, Any],
    summary: dict[str, Any],
    job_id: str,
) -> dict[str, Any]:
    """Build draft metadata without the unsupported WeChat extended-article link."""
    title = str(summary.get("channels_title") or "").strip()
    thesis = str(summary.get("core_thesis") or "").strip()
    article_title = str(article.get("title") or "").strip()
    if not thesis or not article_title:
        raise ArticleSourceError("Article-summary metadata requires a thesis and source article title.")
    description = (
        f"{thesis}\n\n"
        f"原文：{article_title}\n\n"
        "#成核生长 #文献精读 #科学研究"
    )
    if not 6 <= len(title) <= 16 or len(description) > 1000:
        raise ArticleSourceError("Article-summary Channels metadata fails title/description length limits.")
    # The video CTA is rendered into the final frame. WeChat's optional
    # extended-article link control is deliberately not used: link persistence
    # is unsupported/unreliable for this account and is not a release gate.
    # Any verified canonical URL remains in source_record.json only.
    return {
        "schema_version": 4,
        "content_type": "article_summary",
        "job_id": job_id,
        "account_name": "成核生长",
        "title": title,
        "description": description,
        "source_article_id": str(article.get("article_id") or ""),
        "source_appmsgid": str(article.get("appmsgid") or ""),
        "source_article_title": article_title,
        "source_cta_text": "更多详细解读见【成核生长】同名公众号",
        "extended_link_required": False,
        "extended_link": None,
        "extended_link_status": "NOT_REQUIRED_CTA_ONLY",
        "external_article_link_used": False,
        "automatic_publication": False,
    }
