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


def _extract_urls(value: Any, pattern: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    for text in _strings(value):
        for match in pattern.findall(text):
            url = match.rstrip(".,);]}，。；")
            found.add(url)
    return found


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
    pattern = re.compile(rf"{escaped}\\s*=\\s*[\"']?([A-Za-z0-9_-]+)", re.IGNORECASE)
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
    title: str,
    expected_biz_id: str,
) -> tuple[str, str, str, str, str]:
    verification_text = "\n".join(_strings(verification))
    provenance_text = "\n".join(_strings(provenance))
    probe_text = "\n".join(_strings(probe))

    if "appmsgalbum" not in verification_text.casefold():
        raise UpstreamArticleError("Publication evidence does not identify the official appmsgalbum page.")
    if "data-link" not in verification_text.casefold() or "li.album__list-item" not in verification_text:
        raise UpstreamArticleError("Publication evidence lacks li.album__list-item[data-link].")
    if "data-link" not in provenance_text.casefold() or "appmsgalbum" not in provenance_text.casefold():
        raise UpstreamArticleError("upload_preflight_report.url_provenance does not bind data-link to appmsgalbum.")
    if title not in verification_text:
        raise UpstreamArticleError("Official album evidence does not contain the exact prepared-article title.")

    observed_urls = _extract_urls(verification, _URL_RE)
    provenance_urls = _extract_urls(provenance, _URL_RE)
    probe_urls = _extract_urls(probe, _URL_RE)
    common = observed_urls & provenance_urls & probe_urls
    article_urls = {
        url for url in common
        if urlparse(url).hostname == "mp.weixin.qq.com"
        and (urlparse(url).path == "/s" or urlparse(url).path.startswith("/s/"))
    }
    if len(article_urls) != 1:
        raise UpstreamArticleError(
            "The album data-link, upload preflight provenance, and public read-count probe "
            "do not identify exactly one identical published article URL."
        )
    canonical_url = validate_canonical_article_url(next(iter(article_urls)))

    album_urls = _extract_urls(verification, _ALBUM_RE) | _extract_urls(provenance, _ALBUM_RE)
    if not album_urls:
        raise UpstreamArticleError("The official album page URL is absent from the recorded evidence.")
    album_url = sorted(album_urls)[0]
    album_query = parse_qs(urlparse(album_url).query)
    observed_biz = str((album_query.get("__biz") or [""])[0])
    if not expected_biz_id or observed_biz != expected_biz_id:
        raise UpstreamArticleError(
            f"Official album __biz mismatch: expected {expected_biz_id!r}, observed {observed_biz!r}."
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
        raise UpstreamArticleError("article_read_count_probe.json must contain exactly one unambiguous positive ct.")
    ct = next(iter(unique_ct))
    canonical_ct = (parse_qs(urlparse(canonical_url).query).get("ct") or [None])[0]
    if canonical_ct is not None and str(canonical_ct) != str(ct):
        raise UpstreamArticleError("The article URL ct does not match article_read_count_probe.json ct.")

    published = datetime.fromtimestamp(ct, tz=timezone.utc).astimezone(
        timezone.utc
    )
    # The caller converts the absolute instant to its configured local timezone.
    published_at = published.isoformat(timespec="seconds").replace("+00:00", "Z")
    ct_path = _unique_string([path for path, value in ct_values], "ct field path")
    album_mid = _unique_string(
        _attribute_values(verification, "data-msgid"),
        "official album data-msgid",
    )
    item_index = _unique_string(
        _attribute_values(verification, "data-itemidx"),
        "official album data-itemidx",
    )
    if item_index != "1":
        raise UpstreamArticleError(f"Expected Slot 1 album item data-itemidx=1, observed {item_index!r}.")

    field_paths = [
        str(value) for _, value in _walk(provenance)
        if isinstance(value, str) and "data-link" in value.casefold()
    ]
    field_path = field_paths[0] if field_paths else "li.album__list-item[data-link]"
    return published_at, canonical_url, album_url, ct_path, json.dumps({
        "ct": ct,
        "album_mid": album_mid,
        "album_item_index": item_index,
        "field_path": field_path,
    }, ensure_ascii=False)


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
            "source_url": source_url,
            "context": context,
            "image_aspect": round(width / height, 6),
        })
    return found


def discover_upstream_literature_runs(
    daily_runs_root: Path,
    *,
    account_key: str,
    account_name: str,
    expected_biz_id: str,
    target_date: date,
    timezone_name: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Find published Slot 1 articles from existing daily-run output, read-only."""
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    root = daily_runs_root.resolve()
    if not root.is_dir():
        return [], [{"path": str(root), "reason": "upstream_daily_runs_directory_missing"}]

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
                verification = _read_json(run_dir / "url_verification_evidence.json")
                preflight = _read_json(run_dir / "upload_preflight_report.json")
                probe = _read_json(run_dir / "article_read_count_probe.json")
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
                raw_markdown = prepared.get("raw_markdown")
                if not isinstance(md_body, str) or not md_body:
                    raise UpstreamArticleError("prepared_articles.json Slot 1 md_body is missing.")
                if md_body.encode("utf-8") != slot1_bytes:
                    raise UpstreamArticleError("prepared_articles.json md_body is not byte-identical to slot1.md.")
                if isinstance(raw_markdown, str) and raw_markdown.encode("utf-8") != slot1_bytes:
                    raise UpstreamArticleError("prepared_articles.json raw_markdown differs from slot1.md.")
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
                    str(value).strip() for _, value in _values_for_key(delivery, "account_name")
                    if str(value).strip()
                ]
                if not delivered_accounts or any(value != account_name for value in delivered_accounts):
                    raise UpstreamArticleError("delivery_result account_name does not match the configured target account.")

                published_at, canonical_url, album_url, ct_path, time_details = _published_time(
                    verification,
                    preflight.get("url_provenance") if isinstance(preflight, dict) else None,
                    probe,
                    title=title,
                    expected_biz_id=expected_biz_id,
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
                    "publication_time_field_path": ct_path,
                    "publication_time_details": json.loads(time_details),
                    "prepared_article": prepared,
                    "image_assets": _local_image_assets(
                        assets_manifest, run_dir=run_dir, data_root=data_root, markdown=markdown
                    ),
                    "data_root": data_root,
                })
            except (UpstreamArticleError, OSError, UnicodeDecodeError, ValueError) as exc:
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
        "appmsgid": article_id.rsplit("_", 1)[0],
        "article_id": article_id,
        "title": str(candidate["title"]),
        "published_at": published_at,
        "canonical_url": str(candidate["canonical_url"]),
        "canonical_url_verified": True,
        "url_provenance": {
            "endpoint": str(candidate["album_url"]),
            "field_path": "li.album__list-item[data-link] (data-itemidx=1)",
            "verified_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "read_only": True,
        },
        "publication_time_provenance": {
            "source_file": "article_read_count_probe.json",
            "field_path": str(candidate["publication_time_field_path"]),
            "raw_ct": time_details.get("ct"),
            "interpretation": "Unix epoch seconds read from the public WeChat article page ct field",
            "read_only": True,
        },
        "official_album_entry": {
            "page_url": str(candidate["album_url"]),
            "data_msgid": str(time_details.get("album_mid") or ""),
            "data_itemidx": str(time_details.get("album_item_index") or ""),
            "note": "data_msgid is the official album namespace and is not the delivery appmsgid",
        },
        "source_provenance": {
            "upstream_project": "WeChat_control",
            "source_account_key": str(candidate["source_account_key"]),
            "source_run_id": run_id,
            "source_run_dir": str(candidate["source_run_dir"]),
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
            if not source_path.is_file() or not source_path.is_relative_to(Path(candidate["data_root"]).resolve()):
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
