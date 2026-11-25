"""Read-only adapter from WeChat_control daily-run artifacts to Video article packages.

This module never opens a browser, reads credentials, or calls WeChat APIs. It only
reads completed local run artifacts and materializes a validated copy under Video's
own runtime directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .article_source import validate_canonical_article_url


class UpstreamArticleError(ValueError):
    """An upstream Slot 1 run lacks a consistent published-article evidence chain."""


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_PATH_KEYS = {
    "path", "file", "file_path", "local_path", "local_file", "source_path",
    "original_path", "asset_path", "absolute_path",
}
_URL_KEYS = {"url", "cdn_url", "image_url", "src", "remote_url", "original_url"}
_CONTEXT_KEYS = {"caption", "context", "alt", "description"}
_URL_RE = re.compile(r"https://mp\.weixin\.qq\.com/[^\s\"'<>]+", re.IGNORECASE)
_ALBUM_RE = re.compile(r"https://mp\.weixin\.qq\.com/mp/appmsgalbum[^\s\"'<>]*", re.IGNORECASE)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpstreamArticleError(f"Cannot read {path.name}: {exc}") from exc


def _walk(value: Any, path: str = "$"):
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield child_path, key, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield child_path, str(index), child
            yield from _walk(child, child_path)


def _strings(value: Any) -> list[str]:
    return [str(item) for _, _, item in _walk(value) if isinstance(item, str)]


def _values_for_key(value: Any, key_name: str) -> list[tuple[str, Any]]:
    wanted = key_name.casefold()
    return [(path, item) for path, key, item in _walk(value) if key.casefold() == wanted]


def _unique_string(values: list[Any], label: str) -> str:
    normalized = {str(value).strip() for value in values if str(value).strip()}
    if len(normalized) != 1:
        raise UpstreamArticleError(f"{label} is missing or ambiguous: {sorted(normalized)!r}")
    return next(iter(normalized))


def _scalar_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _scalar_strings(child)


def _extract_urls(value: Any, pattern: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    for text in _scalar_strings(value):
        for match in pattern.findall(text):
            url = match.rstrip(".,);]}，。；")
            found.add(url)
    return found


def _optional_unique(values: list[Any], label: str) -> str | None:
    normalized = {str(value).strip() for value in values if str(value).strip()}
    if len(normalized) > 1:
        raise UpstreamArticleError(f"{label} is ambiguous: {sorted(normalized)!r}")
    return next(iter(normalized), None)


def _record_values(record: Any, *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(
            str(value).strip()
            for _, value in _values_for_key(record, key)
            if str(value).strip()
        )
    return values


def _video_evidence_identity_matches(
    directory: Path,
    *,
    article_id: str,
    appmsgid: str,
    title: str,
    markdown_sha256: str,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    manifest_path = directory / "article_summary_manifest.json"
    source_path = directory / "source_record.json"
    if not manifest_path.is_file() or not source_path.is_file():
        return False, {}, {}
    try:
        manifest = _read_json(manifest_path)
        source = _read_json(source_path)
    except UpstreamArticleError:
        return False, {}, {}

    matched_records = 0
    for record in (manifest, source):
        identifiers = _record_values(record, "article_id", "source_article_id")
        appmsgids = _record_values(record, "appmsgid", "source_appmsgid")
        titles = _record_values(record, "article_title", "title", "source_article_title")
        hashes = _record_values(
            record,
            "source_article_sha256",
            "article_markdown_sha256",
            "source_article_markdown_sha256",
        )
        if identifiers and any(value != article_id for value in identifiers):
            return False, {}, {}
        if appmsgids and any(value != appmsgid for value in appmsgids):
            return False, {}, {}
        if titles and any(value != title for value in titles):
            return False, {}, {}
        if hashes and any(value.casefold() != markdown_sha256.casefold() for value in hashes):
            return False, {}, {}
        if (
            article_id in identifiers
            and appmsgid in appmsgids
            and title in titles
            and markdown_sha256.casefold() in {value.casefold() for value in hashes}
        ):
            matched_records += 1
    return matched_records >= 1, manifest, source


def _find_video_publication_evidence(
    evidence_root: Path,
    *,
    article_id: str,
    appmsgid: str,
    title: str,
    markdown_sha256: str,
) -> dict[str, Any]:
    root = evidence_root.resolve()
    if not root.is_dir():
        raise UpstreamArticleError(f"Video publication evidence directory does not exist: {root}")
    matched: list[dict[str, Any]] = []
    for verification_path in sorted(root.rglob("url_verification_evidence.json")):
        directory = verification_path.parent
        companions = {
            "verification_path": verification_path,
            "preflight_path": directory / "upload_preflight_report.json",
            "probe_path": directory / "article_read_count_probe.json",
        }
        if not all(Path(path).is_file() for key, path in companions.items() if key != "verification_path"):
            continue
        identity_ok, manifest, source = _video_evidence_identity_matches(
            directory,
            article_id=article_id,
            appmsgid=appmsgid,
            title=title,
            markdown_sha256=markdown_sha256,
        )
        if not identity_ok:
            continue
        try:
            verification = _read_json(companions["verification_path"])
            preflight = _read_json(companions["preflight_path"])
            probe = _read_json(companions["probe_path"])
        except UpstreamArticleError:
            continue
        matched.append({
            "directory": directory,
            "verification_path": companions["verification_path"],
            "preflight_path": companions["preflight_path"],
            "probe_path": companions["probe_path"],
            "verification": verification,
            "preflight": preflight,
            "probe": probe,
            "manifest": manifest,
            "source_record": source,
        })
    if not matched:
        raise UpstreamArticleError(
            "No matching Video production evidence bundle under "
            f"{root}; expected url_verification_evidence.json, upload_preflight_report.json, "
            "article_read_count_probe.json, article_summary_manifest.json and source_record.json "
            "bound to this exact article_id/appmsgid/title/Markdown SHA-256."
        )
    if len(matched) > 1:
        directories = [str(item["directory"]) for item in matched]
        raise UpstreamArticleError(
            f"Multiple Video production evidence bundles match this article; refusing ambiguous provenance: {directories}"
        )
    return matched[0]


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("\u3000", " "))


def _prepared_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in ("prepared_articles", "articles", "items", "records"):
            records = value.get(key)
            if isinstance(records, list):
                return [item for item in records if isinstance(item, dict)]
        return [value]
    raise UpstreamArticleError("prepared_articles.json must contain an article list or object.")


def _find_slot1_article(records: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = []
    for record in records:
        article_type = (
            record.get("taxonomy_pillar_id")
            or record.get("article_type")
            or record.get("type")
        )
        pillar = record.get("pillar_id") or record.get("editorial_pillar_id")
        if (
            str(article_type or "") == "literature_translation"
            and str(pillar or "") == "literature_manuscript"
        ):
            eligible.append(record)
    if len(eligible) != 1:
        raise UpstreamArticleError(
            "prepared_articles.json must contain exactly one Slot 1 "
            "literature_translation/literature_manuscript record."
        )
    return eligible[0]


def _attribute_values(value: Any, attribute: str) -> list[str]:
    escaped = re.escape(attribute)
    pattern = re.compile(rf"{escaped}\s*=\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)
    values = [
        str(item).strip()
        for _, item in _values_for_key(value, attribute)
        if str(item).strip()
    ]
    for text in _strings(value):
        values.extend(match.group(1) for match in pattern.finditer(text))
    return values


def _published_time(
    verification: Any,
    provenance: Any,
    probe: Any,
    *,
    metadata_url: str | None,
    expected_biz_id: str,
    verified_at_fallback: str,
) -> tuple[str, str, str | None, str, str, str]:
    """Validate the recorded public URL and derive the formal instant from the paired public ct probe.

    Evidence is stored in the matching Video production output directory, not
    beside the upstream WeChat_control daily-run files.
    """
    def published_article_urls(value: Any) -> set[str]:
        return {
            url for url in _extract_urls(value, _URL_RE)
            if urlparse(url).hostname == "mp.weixin.qq.com"
            and (urlparse(url).path == "/s" or urlparse(url).path.startswith("/s/"))
        }

    verification_urls = published_article_urls(verification)
    if len(verification_urls) != 1:
        raise UpstreamArticleError(
            "url_verification_evidence.json must record exactly one public mp.weixin.qq.com/s article URL."
        )
    canonical_url = validate_canonical_article_url(next(iter(verification_urls)))

    metadata_url_value = str(metadata_url or "").strip()
    if metadata_url_value:
        if validate_canonical_article_url(metadata_url_value) != canonical_url:
            raise UpstreamArticleError(
                "Video article_summary_manifest/source_record canonical_url differs from url_verification_evidence.json."
            )

    provenance_article_urls = published_article_urls(provenance)
    if provenance_article_urls and provenance_article_urls != {canonical_url}:
        raise UpstreamArticleError(
            "upload_preflight_report.url_provenance identifies a different public article URL."
        )
    probe_article_urls = published_article_urls(probe)
    if probe_article_urls and probe_article_urls != {canonical_url}:
        raise UpstreamArticleError(
            "article_read_count_probe.json identifies a different public article URL."
        )
    provenance_album_urls = _extract_urls(provenance, _ALBUM_RE)
    if not provenance_article_urls and not metadata_url_value and not provenance_album_urls:
        raise UpstreamArticleError(
            "The recorded article URL has no independent binding in url_provenance or the matching Video source manifest."
        )

    album_urls = _extract_urls(provenance, _ALBUM_RE) | _extract_urls(verification, _ALBUM_RE)
    album_url = _optional_unique(sorted(album_urls), "official album page URL")
    canonical_query = parse_qs(urlparse(canonical_url).query)
    album_query = parse_qs(urlparse(album_url).query) if album_url else {}
    canonical_biz = str((canonical_query.get("__biz") or [""])[0])
    album_biz = str((album_query.get("__biz") or [""])[0])
    observed_biz_values = {value for value in (canonical_biz, album_biz) if value}
    if not expected_biz_id or expected_biz_id not in observed_biz_values:
        raise UpstreamArticleError(
            f"Neither the recorded article URL nor album URL confirms expected account __biz={expected_biz_id!r}."
        )
    if any(value != expected_biz_id for value in observed_biz_values):
        raise UpstreamArticleError(
            f"Recorded public URL/album identity contains conflicting __biz values: {sorted(observed_biz_values)!r}."
        )

    ct_values: list[tuple[str, int]] = []
    for path, value in _values_for_key(probe, "ct"):
        if isinstance(value, bool):
            continue
        try:
            numeric = int(str(value).strip())
        except (TypeError, ValueError):
            continue
        if numeric > 0:
            ct_values.append((path, numeric))
    unique_ct = {value for _, value in ct_values}
    if len(unique_ct) != 1:
        raise UpstreamArticleError(
            "The paired Video article_read_count_probe.json must contain exactly one unambiguous positive ct."
        )
    ct = next(iter(unique_ct))
    canonical_ct = (canonical_query.get("ct") or [None])[0]
    if canonical_ct is not None and str(canonical_ct) != str(ct):
        raise UpstreamArticleError("The article URL ct does not match article_read_count_probe.json ct.")

    published_at = datetime.fromtimestamp(ct, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    ct_paths = sorted({path for path, value in ct_values})
    ct_path = "$.ct" if "$.ct" in ct_paths else ct_paths[0]

    query_mid = str((canonical_query.get("mid") or album_query.get("mid") or [""])[0])
    query_idx = str((canonical_query.get("idx") or album_query.get("idx") or [""])[0])
    recorded_mid = _optional_unique(
        _attribute_values(verification, "data-msgid")
        + _record_values(verification, "data_msgid", "album_mid", "mid"),
        "official album mid",
    )
    recorded_idx = _optional_unique(
        _attribute_values(verification, "data-itemidx")
        + _record_values(verification, "data_itemidx", "album_item_index", "itemidx", "idx"),
        "official album item index",
    )
    album_mid = recorded_mid or query_mid or None
    item_index = recorded_idx or query_idx or None
    if query_mid and recorded_mid and query_mid != recorded_mid:
        raise UpstreamArticleError("Recorded data-msgid does not match the article URL mid.")
    if query_idx and recorded_idx and query_idx != recorded_idx:
        raise UpstreamArticleError("Recorded data-itemidx does not match the article URL idx.")
    if item_index and item_index != "1":
        raise UpstreamArticleError(f"Expected Slot 1 article URL idx=1, observed {item_index!r}.")

    verification_url_paths = [
        path for path, key, value in _walk(verification)
        if isinstance(value, str) and any(url in value for url in verification_urls)
    ]
    field_path = verification_url_paths[0] if verification_url_paths else "url_verification_evidence.json: recorded URL"
    verified_at_values = _record_values(provenance, "verified_at", "observed_at", "recorded_at")
    verified_at_values += _record_values(verification, "verified_at", "observed_at", "recorded_at")
    verified_at = _optional_unique(verified_at_values, "URL verification timestamp") or verified_at_fallback

    return published_at, canonical_url, album_url, ct_path, json.dumps({
        "ct": ct,
        "ct_binding": (
            "paired_video_output_evidence_bound_by_article_id_appmsgid_title_and_markdown_sha256"
        ),
        "album_mid": album_mid,
        "album_item_index": item_index,
        "field_path": field_path,
        "verified_at": verified_at,
    }, ensure_ascii=False), verified_at


def _resolve_local_asset(raw_path: str, run_dir: Path, data_root: Path) -> Path | None:
    candidate = Path(raw_path)
    options = [candidate] if candidate.is_absolute() else [run_dir / candidate, data_root / candidate]
    for option in options:
        try:
            resolved = option.resolve()
            if (
                resolved.is_file()
                and resolved.suffix.casefold() in _IMAGE_SUFFIXES
                and resolved.is_relative_to(data_root.resolve())
            ):
                return resolved
        except OSError:
            continue
    return None


def _local_image_assets(
    manifest: Any,
    *,
    run_dir: Path,
    data_root: Path,
    markdown: str,
) -> list[dict[str, Any]]:
    normalized_markdown = _normalized_text(markdown)
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for _, _, value in _walk(manifest):
        if not isinstance(value, dict):
            continue
        path_values = [
            str(value.get(key)).strip()
            for key in _PATH_KEYS
            if isinstance(value.get(key), str) and str(value.get(key)).strip()
        ]
        if not path_values:
            continue
        source_path = next(
            (resolved for raw in path_values if (resolved := _resolve_local_asset(raw, run_dir, data_root))),
            None,
        )
        if source_path is None or source_path in seen:
            continue
        text_values = [
            str(value.get(key)).strip()
            for key in _CONTEXT_KEYS
            if isinstance(value.get(key), str) and str(value.get(key)).strip()
        ]
        context = next(
            (item for item in text_values if _normalized_text(item) in normalized_markdown),
            "",
        )
        if not context:
            continue
        source_url = next(
            (
                str(value.get(key)).strip()
                for key in _URL_KEYS
                if isinstance(value.get(key), str) and str(value.get(key)).strip().startswith("https://")
            ),
            None,
        )
        expected_sha = str(value.get("sha256") or "").strip().casefold()
        if expected_sha and _sha256_bytes(source_path.read_bytes()).casefold() != expected_sha:
            continue
        try:
            from PIL import Image
            with Image.open(source_path) as image:
                width, height = image.size
                image.verify()
            if width <= 0 or height <= 0:
                continue
        except Exception:
            continue
        seen.add(source_path)
        found.append({
            "source_path": source_path,
            "asset_root": data_root.resolve(),
            "source_url": source_url,
            "context": context,
            "image_aspect": round(width / height, 6),
            "sha256": expected_sha or _sha256_bytes(source_path.read_bytes()),
        })
    return found


def discover_upstream_literature_runs(
    daily_runs_root: Path,
    *,
    publication_evidence_root: Path,
    account_key: str,
    account_name: str,
    expected_biz_id: str,
    target_date: date,
    timezone_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Join upstream Slot 1 run data to its identity-matched Video output evidence."""
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    root = daily_runs_root.resolve()
    evidence_root = publication_evidence_root.resolve()
    if not root.is_dir():
        return [], [{"path": str(root), "reason": "upstream_daily_runs_directory_missing"}]
    if not evidence_root.is_dir():
        return [], [{
            "path": str(evidence_root),
            "reason": "video_publication_evidence_directory_missing",
        }]

    data_root = root.parent.resolve()
    for date_dir in sorted(root.iterdir()):
        if not date_dir.is_dir():
            continue
        account_dir = date_dir / account_key
        if not account_dir.is_dir():
            continue
        for run_dir in sorted(account_dir.iterdir()):
            if not run_dir.is_dir() or not (run_dir / "slot1.md").is_file():
                continue
            try:
                slot1_path = run_dir / "slot1.md"
                slot1_bytes = slot1_path.read_bytes()
                markdown_sha = _sha256_bytes(slot1_bytes)
                markdown = slot1_bytes.decode("utf-8")
                manifest = _read_json(run_dir / "slot1.manifest.json")
                prepared_doc = _read_json(run_dir / "prepared_articles.json")
                delivery = _read_json(run_dir / "delivery_result.json")
                review = _read_json(run_dir / "review_state.json")
                assets_manifest = _read_json(run_dir / "uploaded_assets_manifest.json")

                manifest_hash = str(manifest.get("output_sha256") or "").casefold()
                if manifest_hash != markdown_sha:
                    raise UpstreamArticleError("slot1.manifest.json output_sha256 does not match exact slot1.md bytes.")
                review_slots = review.get("slots") if isinstance(review.get("slots"), dict) else {}
                review_slot = review_slots.get("1", review_slots.get(1))
                review_hash = str((review_slot or {}).get("article_sha256") or "").casefold()
                if review_hash != markdown_sha:
                    raise UpstreamArticleError("review_state.json slots.1.article_sha256 does not match slot1.md.")

                records = _prepared_records(prepared_doc)
                prepared = _find_slot1_article(records)
                md_body = prepared.get("md_body")
                if not isinstance(md_body, str) or not md_body:
                    raise UpstreamArticleError("prepared_articles.json Slot 1 md_body is missing.")
                if md_body.encode("utf-8") != slot1_bytes:
                    raise UpstreamArticleError("prepared_articles.json md_body is not byte-identical to slot1.md.")
                title = str(prepared.get("title") or "").strip()
                h1 = re.search(r"(?m)^#\s+(.+?)\s*$", markdown)
                if not title or not h1 or h1.group(1).strip() != title:
                    raise UpstreamArticleError("prepared article title does not match the exact slot1.md H1.")

                article_type = str(
                    prepared.get("taxonomy_pillar_id")
                    or prepared.get("article_type")
                    or prepared.get("type")
                    or ""
                )
                pillar_id = str(prepared.get("pillar_id") or prepared.get("editorial_pillar_id") or "")
                if article_type != "literature_translation" or pillar_id != "literature_manuscript":
                    raise UpstreamArticleError("Slot 1 taxonomy does not match literature_translation/literature_manuscript.")

                appmsgid = _unique_string(
                    [value for _, value in _values_for_key(delivery, "appmsgid")],
                    "delivery_result.appmsgid",
                )
                delivered_accounts = [
                    str(value).strip()
                    for _, value in (
                        _values_for_key(delivery, "account_name")
                        + _values_for_key(delivery, "account")
                    )
                    if str(value).strip()
                ]
                accepted_accounts = {account_name, account_key}
                if not delivered_accounts or any(value not in accepted_accounts for value in delivered_accounts):
                    raise UpstreamArticleError(
                        f"delivery_result account/account_name must identify {account_name!r} "
                        f"or its configured key {account_key!r}; observed {delivered_accounts!r}."
                    )

                evidence = _find_video_publication_evidence(
                    evidence_root,
                    article_id=f"{appmsgid}_0",
                    appmsgid=appmsgid,
                    title=title,
                    markdown_sha256=markdown_sha,
                )
                verification = evidence["verification"]
                preflight = evidence["preflight"]
                probe = evidence["probe"]
                provenance = preflight.get("url_provenance") if isinstance(preflight, dict) else None
                metadata_url = (
                    evidence["source_record"].get("canonical_url")
                    or evidence["manifest"].get("canonical_url")
                )
                verification_path = Path(evidence["verification_path"])
                fallback_verified_at = datetime.fromtimestamp(
                    verification_path.stat().st_mtime,
                    tz=timezone.utc,
                ).isoformat(timespec="seconds").replace("+00:00", "Z")
                published_at, canonical_url, album_url, ct_path, time_details, verified_at = _published_time(
                    verification,
                    provenance,
                    probe,
                    metadata_url=str(metadata_url or "") or None,
                    expected_biz_id=expected_biz_id,
                    verified_at_fallback=fallback_verified_at,
                )
                parsed_published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                try:
                    from zoneinfo import ZoneInfo
                    local_date = parsed_published.astimezone(ZoneInfo(timezone_name)).date()
                except Exception:
                    if timezone_name != "Asia/Shanghai":
                        raise
                    from datetime import timedelta
                    local_date = parsed_published.astimezone(timezone(timedelta(hours=8))).date()
                if local_date != target_date:
                    continue

                article_id = f"{appmsgid}_0"
                video_image_assets = _local_image_assets(
                    evidence["manifest"].get("image_manifest") or {},
                    run_dir=evidence["directory"],
                    data_root=evidence_root,
                    markdown=markdown,
                )
                upstream_image_assets = _local_image_assets(
                    assets_manifest,
                    run_dir=run_dir,
                    data_root=data_root,
                    markdown=markdown,
                )
                image_assets = video_image_assets or upstream_image_assets
                image_asset_source = (
                    "matching_video_production_output"
                    if video_image_assets
                    else "upstream_uploaded_assets_manifest"
                )
                candidates.append({
                    "source_run_dir": run_dir,
                    "source_run_id": run_dir.name,
                    "source_account_key": account_key,
                    "article_id": article_id,
                    "appmsgid": appmsgid,
                    "title": title,
                    "published_at": published_at,
                    "local_date": local_date.isoformat(),
                    "markdown_sha256": markdown_sha,
                    "canonical_url": canonical_url,
                    "album_url": album_url,
                    "url_verified_at": verified_at,
                    "publication_time_field_path": ct_path,
                    "publication_time_details": json.loads(time_details),
                    "publication_evidence_dir": evidence["directory"],
                    "prepared_article": prepared,
                    "image_assets": image_assets,
                    "image_asset_source": image_asset_source,
                    "verified_video_image_count": len(video_image_assets),
                    "data_root": data_root,
                    "evidence_root": evidence_root,
                })
            except (UpstreamArticleError, OSError, UnicodeDecodeError, ValueError, TypeError, AttributeError, KeyError, IndexError) as exc:
                rejected.append({"path": str(run_dir), "reason": str(exc)})

    candidates.sort(
        key=lambda item: (
            datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00")).timestamp(),
            str(item["source_run_id"]),
        ),
        reverse=True,
    )
    by_article_id: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_article_id.setdefault(str(candidate["article_id"]), []).append(candidate)
    unique_candidates: list[dict[str, Any]] = []
    for article_id, matches in by_article_id.items():
        hashes = {str(item["markdown_sha256"]) for item in matches}
        if len(hashes) != 1:
            rejected.extend({
                "path": str(item["source_run_dir"]),
                "reason": f"conflicting_upstream_runs_for_article_id:{article_id}",
            } for item in matches)
            continue
        unique_candidates.append(matches[0])
        for duplicate in matches[1:]:
            rejected.append({
                "path": str(duplicate["source_run_dir"]),
                "reason": f"duplicate_upstream_run_same_article:{article_id}",
            })
    unique_candidates.sort(
        key=lambda item: (
            datetime.fromisoformat(str(item["published_at"]).replace("Z", "+00:00")).timestamp(),
            str(item["article_id"]),
        ),
        reverse=True,
    )
    return unique_candidates, rejected


def materialize_upstream_article_package(candidate: dict[str, Any], package_root: Path) -> Path:
    """Create an immutable Video-local package from one validated upstream run."""
    package_root = package_root.resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    article_id = str(candidate["article_id"])
    run_id = str(candidate["source_run_id"])
    safe_article_id = re.sub(r"[^A-Za-z0-9_-]", "_", article_id)
    safe_run_id = re.sub(r"[^A-Za-z0-9_-]", "_", run_id)
    destination = package_root / safe_article_id / safe_run_id
    markdown_source = Path(candidate["source_run_dir"]) / "slot1.md"
    source_bytes = markdown_source.read_bytes()
    source_hash = _sha256_bytes(source_bytes)
    if source_hash != str(candidate["markdown_sha256"]):
        raise UpstreamArticleError("Upstream slot1.md changed after discovery; refusing materialization.")

    if destination.exists():
        existing_article = json.loads((destination / "article.json").read_text(encoding="utf-8"))
        existing_hash = _sha256_bytes((destination / "article.md").read_bytes())
        if existing_article.get("article_id") == article_id and existing_hash == source_hash:
            return destination
        raise UpstreamArticleError(f"Existing Video package conflicts with this source run; not overwriting: {destination}")

    article = candidate["prepared_article"]
    published_at = str(candidate["published_at"])
    time_details = dict(candidate["publication_time_details"])
    article_json = {
        "schema_version": 1,
        "account_name": "成核生长",
        "editorial_slot": 1,
        "article_type": "literature_translation",
        "editorial_pillar_id": "literature_manuscript",
        "publication_status": "PUBLISHED",
        "appmsgid": str(candidate["appmsgid"]),
        "article_id": article_id,
        "title": str(candidate["title"]),
        "published_at": published_at,
        "canonical_url": str(candidate["canonical_url"]),
        "canonical_url_verified": True,
        "url_provenance": {
            "endpoint": str(candidate.get("album_url") or candidate["canonical_url"]),
            "field_path": str(time_details.get("field_path") or "url_verification_evidence.json: recorded URL"),
            "verified_at": str(candidate["url_verified_at"]),
            "read_only": True,
            "evidence_directory": str(candidate["publication_evidence_dir"]),
        },
        "publication_time_provenance": {
            "source_file": "article_read_count_probe.json",
            "field_path": str(candidate["publication_time_field_path"]),
            "raw_ct": time_details.get("ct"),
            "interpretation": "Unix epoch seconds read from the public WeChat article page ct field",
            "read_only": True,
        },
        "official_album_entry": {
            "page_url": candidate.get("album_url"),
            "data_msgid": time_details.get("album_mid"),
            "data_itemidx": time_details.get("album_item_index"),
            "note": "data_msgid is the official album namespace and is not the delivery appmsgid",
        },
        "source_provenance": {
            "upstream_project": "WeChat_control",
            "source_account_key": str(candidate["source_account_key"]),
            "source_run_id": run_id,
            "source_run_dir": str(candidate["source_run_dir"]),
            "video_publication_evidence_dir": str(candidate["publication_evidence_dir"]),
            "video_image_source": str(candidate.get("image_asset_source") or ""),
            "slot1_markdown_sha256": source_hash,
            "doi": article.get("doi"),
            "bundle_path": article.get("bundle_path"),
            "file_id": article.get("file_id"),
            "cover_name": article.get("cover_name"),
            "micro_tags": article.get("micro_tags"),
        },
    }

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{safe_run_id}.", dir=destination.parent))
    try:
        (temporary / "article.md").write_bytes(source_bytes)
        images_dir = temporary / "images"
        image_records: list[dict[str, Any]] = []
        for index, asset in enumerate(candidate.get("image_assets") or [], start=1):
            source_path = Path(asset["source_path"]).resolve()
            asset_root = Path(asset.get("asset_root") or candidate["data_root"]).resolve()
            if not source_path.is_file() or not source_path.is_relative_to(asset_root):
                continue
            expected_sha = str(asset.get("sha256") or "").casefold()
            if expected_sha and _sha256_bytes(source_path.read_bytes()).casefold() != expected_sha:
                continue
            image_id = f"IMG{index:02d}"
            filename = f"{image_id}{source_path.suffix.casefold()}"
            images_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, images_dir / filename)
            image_records.append({
                "image_id": image_id,
                "file": f"images/{filename}",
                "image_aspect": float(asset["image_aspect"]),
                "caption": str(asset["context"]),
                "context": str(asset["context"]),
                "source_cdn_url": asset.get("source_url"),
                "source_local_path": str(source_path),
            })
        (temporary / "images.json").write_text(
            json.dumps({"images": image_records}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (temporary / "article.json").write_text(
            json.dumps(article_json, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            os.rename(temporary, destination)
        except FileExistsError:
            existing_article = json.loads((destination / "article.json").read_text(encoding="utf-8"))
            existing_hash = _sha256_bytes((destination / "article.md").read_bytes())
            if existing_article.get("article_id") != article_id or existing_hash != source_hash:
                raise UpstreamArticleError(f"Concurrent package creation produced a conflicting directory: {destination}")
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return destination
