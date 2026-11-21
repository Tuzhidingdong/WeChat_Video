"""Safe, local-only WeChat Channels draft uploader.

This module drives only the visible official Channels Assistant website through a
project-owned Edge profile and Playwright CDP. It never uses private platform APIs,
never reads/writes the user's normal Edge profile, and contains no publish action.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from .channels_metadata import build_channels_metadata, validate_channels_metadata
from .topic_approval import TopicApprovalError, verify_fact_card_approval


class UploadBlockedError(RuntimeError):
    """A safety or precondition gate prevents upload."""


class UploadUnknownError(RuntimeError):
    """The save outcome is uncertain; reconcile, never upload again."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UploadBlockedError(f"Required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise UploadBlockedError(f"Invalid JSON file: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise UploadBlockedError(f"Expected a JSON object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normal_path(value: str | Path) -> str:
    return os.path.normcase(str(Path(value).expanduser().resolve()))


def _relative_config_path(project_root: Path, value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else project_root / candidate


def _load_config(project_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    config = _read_json(project_root / "config" / "channels_upload.json")
    if config.get("schema_version") != 1:
        raise UploadBlockedError("Unsupported config/channels_upload.json schema_version.")
    safety = config.get("safety", {})
    required_safety = {
        "allow_publish": False,
        "allow_schedule": False,
        "allow_delete": False,
        "allow_overwrite": False,
        "cdp_host": "127.0.0.1",
    }
    for key, expected in required_safety.items():
        if safety.get(key) != expected:
            raise UploadBlockedError(
                f"Unsafe Channels config: safety.{key} must be {expected!r}; refusing to run."
            )

    selectors_path = _relative_config_path(
        project_root, str(config.get("selectors_file", "config/selectors.yaml"))
    )
    try:
        import yaml
    except ImportError as exc:
        raise UploadBlockedError(
            "PyYAML is not installed in the project .venv. Run Setup_Slice_A.bat to install upload dependencies."
        ) from exc
    try:
        selectors = yaml.safe_load(selectors_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise UploadBlockedError(f"Missing selector config: {selectors_path}") from exc
    except yaml.YAMLError as exc:
        raise UploadBlockedError(f"Invalid selector YAML: {exc}") from exc
    if not isinstance(selectors, dict):
        raise UploadBlockedError("config/selectors.yaml must contain a YAML mapping.")
    return config, selectors


def _find_edge_executable(config: dict[str, Any]) -> Path:
    configured = config.get("edge_executable")
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(str(configured)).expanduser())
    on_path = shutil.which("msedge") or shutil.which("msedge.exe")
    if on_path:
        candidates.append(Path(on_path))
    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.name.casefold() == "msedge.exe":
            return resolved
    raise UploadBlockedError(
        "Microsoft Edge executable was not found. Set edge_executable in config/channels_upload.json."
    )


def _load_psutil():
    try:
        import psutil
    except ImportError as exc:
        raise UploadBlockedError(
            "psutil is not installed in the project .venv. Run Setup_Slice_A.bat."
        ) from exc
    return psutil


def _process_cmdline(process: Any) -> list[str]:
    try:
        return [str(item) for item in process.cmdline()]
    except Exception as exc:
        raise UploadBlockedError(
            f"Cannot inspect Edge process command line safely: {type(exc).__name__}."
        ) from exc


def _uses_profile(command: list[str], profile_dir: Path) -> bool:
    expected = _normal_path(profile_dir)
    for index, item in enumerate(command):
        value = item.strip().strip('"')
        if value.casefold().startswith("--user-data-dir="):
            value = value.split("=", 1)[1].strip('"')
            if _normal_path(value) == expected:
                return True
        elif value.casefold() == "--user-data-dir" and index + 1 < len(command):
            if _normal_path(command[index + 1].strip('"')) == expected:
                return True
    return False


def _profile_processes(profile_dir: Path) -> list[int]:
    psutil = _load_psutil()
    matches: list[int] = []
    try:
        processes = psutil.process_iter(["pid", "name", "cmdline"])
        for process in processes:
            try:
                name = str(process.info.get("name") or "").casefold()
                if name not in {"msedge.exe", "msedge"}:
                    continue
                command = [str(x) for x in (process.info.get("cmdline") or [])]
                if _uses_profile(command, profile_dir):
                    matches.append(int(process.info["pid"]))
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                continue
            except psutil.AccessDenied:
                continue
    except Exception as exc:
        raise UploadBlockedError(
            f"Cannot enumerate Edge processes safely: {type(exc).__name__}."
        ) from exc
    return sorted(set(matches))


def _listener_pid(port: int) -> int:
    psutil = _load_psutil()
    try:
        connections = psutil.net_connections(kind="tcp")
    except Exception as exc:
        raise UploadBlockedError(
            f"Cannot inspect the local CDP listener process: {type(exc).__name__}."
        ) from exc
    pids = {
        int(connection.pid)
        for connection in connections
        if connection.pid
        and connection.status == psutil.CONN_LISTEN
        and getattr(connection.laddr, "port", None) == port
    }
    if len(pids) != 1:
        raise UploadBlockedError(
            f"CDP port {port} must map to exactly one listener process; found {sorted(pids)}."
        )
    return next(iter(pids))


def _process_details(pid: int) -> dict[str, Any]:
    psutil = _load_psutil()
    try:
        process = psutil.Process(pid)
        return {
            "pid": int(pid),
            "executable": str(Path(process.exe()).resolve()),
            "command_line": _process_cmdline(process),
            "creation_time": float(process.create_time()),
        }
    except Exception as exc:
        raise UploadBlockedError(
            f"Cannot verify Edge process {pid}: {type(exc).__name__}."
        ) from exc


def _cdp_version(port: int) -> dict[str, Any]:
    url = f"http://127.0.0.1:{port}/json/version"
    try:
        with urlopen(url, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise UploadBlockedError(
            f"Dedicated Edge CDP endpoint is not responding on loopback port {port}."
        ) from exc
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "")
    parsed = urlparse(websocket_url)
    if parsed.scheme != "ws" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise UploadBlockedError("Edge returned a non-loopback CDP websocket URL; refusing to connect.")
    if parsed.port is None:
        raise UploadBlockedError("Edge CDP websocket URL has no port.")
    if parsed.port != port:
        raise UploadBlockedError("Edge CDP websocket port does not match the recorded loopback port.")
    return {
        "browser_version": str(payload.get("Browser") or ""),
        "websocket_url": websocket_url,
    }


def _validate_existing_session(
    project_root: Path,
    config: dict[str, Any],
    session_path: Path,
    profile_dir: Path,
) -> tuple[dict[str, Any], str]:
    session = _read_json(session_path)
    if session.get("schema_version") != 1:
        raise UploadBlockedError("Unsupported edge_session.json schema_version.")
    if session.get("user_data_dir_fingerprint") != hashlib.sha256(
        _normal_path(profile_dir).encode("utf-8")
    ).hexdigest():
        raise UploadBlockedError("Recorded Edge profile fingerprint does not match the project profile.")
    if _normal_path(session.get("user_data_dir", "")) != _normal_path(profile_dir):
        raise UploadBlockedError("Recorded Edge user-data directory does not match configuration.")
    port = int(session.get("remote_debugging_port", 0))
    if not 1 <= port <= 65535:
        raise UploadBlockedError("Recorded Edge CDP port is invalid.")
    endpoint = _cdp_version(port)
    pid = _listener_pid(port)
    details = _process_details(pid)
    if int(session.get("edge_pid", -1)) != pid:
        raise UploadBlockedError("The process owning the CDP port differs from edge_session.json.")
    if abs(float(session.get("process_creation_time", -1)) - details["creation_time"]) > 1.0:
        raise UploadBlockedError("Edge process creation time changed; possible PID reuse.")
    if _normal_path(details["executable"]) != _normal_path(session.get("edge_executable", "")):
        raise UploadBlockedError("Edge executable identity does not match edge_session.json.")
    if not _uses_profile(details["command_line"], profile_dir):
        raise UploadBlockedError("CDP listener process is not using the dedicated project Edge profile.")
    joined = " ".join(details["command_line"])
    if f"--remote-debugging-port={port}" not in joined:
        raise UploadBlockedError("CDP listener command line does not contain its recorded port.")
    if "--remote-debugging-address=127.0.0.1" not in joined:
        raise UploadBlockedError("Edge CDP is not explicitly bound to 127.0.0.1.")
    session["edge_version"] = endpoint["browser_version"]
    session["last_verified_at"] = _now()
    _write_json_atomic(session_path, session)
    return session, endpoint["websocket_url"]


def _choose_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def ensure_edge_session(
    project_root: Path,
    *,
    open_url: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Reuse a fully verified dedicated Edge session, or safely launch one."""
    project_root = project_root.resolve()
    config, _ = _load_config(project_root)
    profile_dir = _relative_config_path(project_root, config["edge_profile_dir"]).resolve()
    session_path = _relative_config_path(project_root, config["session_file"])
    profile_dir.mkdir(parents=True, exist_ok=True)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    if session_path.is_file():
        try:
            return _validate_existing_session(project_root, config, session_path, profile_dir)
        except UploadBlockedError:
            active = _profile_processes(profile_dir)
            if active:
                raise UploadBlockedError(
                    "The dedicated Edge profile is still owned by process(es) "
                    f"{active}, but its recorded CDP session is invalid. Do not start a second Edge. "
                    "Close/restart this dedicated profile manually, then retry."
                )

    active = _profile_processes(profile_dir)
    if active:
        raise UploadBlockedError(
            f"Dedicated Edge profile is already in use by process(es) {active}, "
            "but no verified session is available. Refusing to launch another instance."
        )

    executable = _find_edge_executable(config)
    port = _choose_port()
    args = [
        str(executable),
        f"--user-data-dir={profile_dir}",
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        open_url or str(config["create_url"]),
    ]
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0
        )
    try:
        subprocess.Popen(
            args,
            cwd=str(project_root),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise UploadBlockedError(f"Could not launch the dedicated Edge process: {exc}") from exc

    deadline = time.monotonic() + int(config.get("edge_start_timeout_seconds", 30))
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            endpoint = _cdp_version(port)
            pid = _listener_pid(port)
            details = _process_details(pid)
            if not _uses_profile(details["command_line"], profile_dir):
                raise UploadBlockedError("CDP listener is not the dedicated Edge profile process.")
            joined = " ".join(details["command_line"])
            if f"--remote-debugging-port={port}" not in joined or "--remote-debugging-address=127.0.0.1" not in joined:
                raise UploadBlockedError("Edge command line does not prove loopback-only CDP.")
            session = {
                "schema_version": 1,
                "edge_executable": details["executable"],
                "edge_pid": pid,
                "process_creation_time": details["creation_time"],
                "user_data_dir": str(profile_dir),
                "user_data_dir_fingerprint": hashlib.sha256(
                    _normal_path(profile_dir).encode("utf-8")
                ).hexdigest(),
                "remote_debugging_port": port,
                "remote_debugging_address": "127.0.0.1",
                "edge_version": endpoint["browser_version"],
                "session_started_at": _now(),
                "last_verified_at": _now(),
            }
            _write_json_atomic(session_path, session)
            return session, endpoint["websocket_url"]
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise UploadBlockedError(
        "Dedicated Edge did not expose a verifiable loopback CDP endpoint within "
        f"{config.get('edge_start_timeout_seconds', 30)} seconds. "
        f"Last check: {last_error}"
    )


def _connect_playwright(websocket_url: str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise UploadBlockedError(
            "Playwright is not installed in the project .venv. Run Setup_Slice_A.bat."
        ) from exc
    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.connect_over_cdp(websocket_url, timeout=15_000)
        contexts = browser.contexts
        if not contexts:
            raise UploadBlockedError("Dedicated Edge has no persistent browser context.")
        return playwright, browser, contexts[0]
    except Exception:
        playwright.stop()
        raise


def open_channels_session(project_root: Path, *, wait_login_seconds: int = 5) -> dict[str, Any]:
    """Open the official creator page in a dedicated Edge profile for manual login."""
    project_root = project_root.resolve()
    config, selectors = _load_config(project_root)
    session, websocket_url = ensure_edge_session(project_root, open_url=str(config["create_url"]))
    playwright, browser, context = _connect_playwright(websocket_url)
    try:
        page = context.new_page()
        page.goto(str(config["create_url"]), wait_until="domcontentloaded", timeout=60_000)
        verified = _wait_for_account_identity(
            page,
            str(config["account_name"]),
            selectors,
            wait_seconds=max(0, int(wait_login_seconds)),
        )
        return {
            "session_pid": session["edge_pid"],
            "session_profile": session["user_data_dir"],
            "edge_version": session["edge_version"],
            "page_url": page.url,
            "account_verified": verified,
            "manual_login_required": not verified,
            "message": (
                "Account identity verified."
                if verified
                else "Edge is open. Scan the QR code/login manually, then rerun channels-inspect."
            ),
        }
    finally:
        # Stop only the Playwright driver. Never close the persistent context or Edge.
        playwright.stop()


def _body_text(page: Any) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=5_000))
    except Exception:
        return ""


def _wait_for_account_identity(
    page: Any,
    expected_name: str,
    selectors: dict[str, Any],
    *,
    wait_seconds: int,
) -> bool:
    parsed = urlparse(page.url)
    if parsed.hostname and not parsed.hostname.endswith("weixin.qq.com"):
        raise UploadBlockedError(f"Unexpected website host for Channels operation: {parsed.hostname}")
    account_cfg = selectors.get("account_identity", {}) or {}
    selector = account_cfg.get("selector")
    exact_text = str(account_cfg.get("exact_text") or expected_name)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            if selector:
                loc = page.locator(str(selector))
                if loc.count() and loc.first.is_visible():
                    actual = loc.first.inner_text().strip()
                    if actual == expected_name or expected_name in actual:
                        return True
            loc = page.get_by_text(exact_text, exact=True)
            if loc.count():
                for index in range(min(loc.count(), 8)):
                    if loc.nth(index).is_visible():
                        return True
        except Exception:
            pass
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(1_000)


def _ensure_account_identity(
    page: Any,
    expected_name: str,
    selectors: dict[str, Any],
    *,
    wait_seconds: int,
) -> None:
    if _wait_for_account_identity(
        page, expected_name, selectors, wait_seconds=wait_seconds
    ):
        return
    body = _body_text(page)
    if any(token in body for token in ("扫码登录", "微信登录", "请登录", "登录后")):
        raise UploadBlockedError(
            "The dedicated Channels session is not logged in. Scan the QR code in the open Edge window, "
            "confirm the intended account, then rerun this command."
        )
    raise UploadBlockedError(
        f"Could not verify the intended Channels account identity {expected_name!r}. "
        "No upload was attempted."
    )


def _visible_locator(page: Any, selector_list: Any):
    if not isinstance(selector_list, list):
        selector_list = [selector_list] if selector_list else []
    for selector in selector_list:
        try:
            locator = page.locator(str(selector))
            count = locator.count()
            for index in range(min(count, 8)):
                candidate = locator.nth(index)
                if candidate.is_visible():
                    return candidate
        except Exception:
            continue
    return None


def _video_file_input(page: Any, selectors: dict[str, Any]):
    selectors_list = selectors.get("video_file_input", ["input[type='file'][accept*='video']", "input[type='file']"])
    for selector in selectors_list:
        try:
            locator = page.locator(str(selector))
            count = locator.count()
            if not count:
                continue
            candidates = [locator.nth(index) for index in range(min(count, 8))]
            video_inputs = [
                item for item in candidates
                if any(token in str(item.get_attribute("accept") or "").casefold()
                       for token in ("video", "mp4"))
            ]
            if len(video_inputs) == 1:
                return video_inputs[0]
            if len(video_inputs) > 1:
                raise UploadBlockedError(
                    "More than one video file input is present; refusing ambiguous selection."
                )
            if len(candidates) == 1:
                return candidates[0]
        except UploadBlockedError:
            raise
        except Exception:
            continue
    raise UploadBlockedError(
        "Could not identify exactly one video upload input. Inspect the page and adjust config/selectors.yaml."
    )


def _fill_field(page: Any, selectors: dict[str, Any], key: str, value: str) -> None:
    locator = _visible_locator(page, selectors.get(key, []))
    if locator is None:
        raise UploadBlockedError(
            f"Could not locate the {key} field using config/selectors.yaml; no save action was taken."
        )
    locator.fill(value, timeout=10_000)
    try:
        actual = locator.input_value(timeout=3_000)
    except Exception:
        actual = locator.inner_text(timeout=3_000)
    if str(actual).strip() != value.strip():
        raise UploadBlockedError(f"The {key} field did not retain the exact supplied text.")


def _draft_save_button(page: Any, selectors: dict[str, Any]):
    for name in selectors.get("draft_save_button_text", ["存草稿", "保存草稿"]):
        try:
            locator = page.get_by_role("button", name=str(name), exact=True)
            if locator.count() == 1 and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
        try:
            locator = page.get_by_text(str(name), exact=True)
            if locator.count() == 1 and locator.first.is_visible():
                return locator.first
        except Exception:
            continue
    return None


def _preview_ready(page: Any, selectors: dict[str, Any]) -> bool:
    locator = _visible_locator(page, selectors.get("preview_selectors", ["video"]))
    if locator is None:
        return False
    try:
        tag = str(locator.evaluate("(el) => el.tagName.toLowerCase()"))
        if tag == "video":
            return bool(
                locator.evaluate(
                    "(el) => Boolean(el.currentSrc || el.src) && el.readyState >= 1"
                )
            )
        return True
    except Exception:
        return False


def _wait_upload_ready(
    page: Any,
    selectors: dict[str, Any],
    *,
    timeout_seconds: int,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    errors = [str(x) for x in selectors.get("upload_error_texts", [])]
    while time.monotonic() < deadline:
        body = _body_text(page)
        matched_error = next((item for item in errors if item and item in body), None)
        if matched_error:
            raise UploadBlockedError(f"Channels upload page reported an error: {matched_error}")
        button = _draft_save_button(page, selectors)
        button_ready = button is not None and button.is_enabled()
        preview_ready = _preview_ready(page, selectors)
        if button_ready and preview_ready:
            return
        page.wait_for_timeout(1_000)
    raise UploadBlockedError(
        "Upload did not reach the required state (preview ready + draft-save control enabled). "
        "No save action was taken; inspect the still-open Edge tab."
    )


def _select_draft_tab(page: Any, selectors: dict[str, Any]) -> None:
    for name in selectors.get("draft_tab_text", ["草稿箱", "草稿"]):
        try:
            locator = page.get_by_text(str(name), exact=True)
            if locator.count() == 1 and locator.first.is_visible():
                locator.first.click(timeout=5_000)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue
    body = _body_text(page)
    if not any(token in body for token in ("草稿箱", "草稿")):
        raise UploadBlockedError(
            "Could not verify the draft-list view. Inspect the account UI and adjust config/selectors.yaml."
        )


def _draft_snapshot(page: Any, selectors: dict[str, Any]) -> dict[str, Any]:
    ready_selector = selectors.get("draft_list_ready_selector")
    if ready_selector:
        page.locator(str(ready_selector)).wait_for(state="visible", timeout=15_000)
    _select_draft_tab(page, selectors)
    body = _body_text(page)
    if not any(token in body for token in ("草稿箱", "草稿")):
        raise UploadBlockedError("The page does not identify itself as the draft list.")
    entries: list[str] = []
    for selector in selectors.get("draft_row_selectors", []):
        try:
            rows = page.locator(str(selector))
            count = rows.count()
            if count:
                entries = [
                    re.sub(r"\s+", " ", rows.nth(index).inner_text(timeout=2_000)).strip()
                    for index in range(min(count, 500))
                ]
                entries = [item for item in entries if item]
                if entries:
                    break
        except Exception:
            continue
    if not entries:
        # A compact line snapshot is a fallback, not evidence of an individual
        # new draft. Verification below still requires an identifiable row.
        entries = [
            re.sub(r"\s+", " ", line).strip()
            for line in body.splitlines()
            if line.strip()
        ][:500]
    return {"captured_at": _now(), "url": page.url, "entries": entries}


def _matching_draft_entries(
    snapshot: dict[str, Any],
    title: str,
    selectors: dict[str, Any],
) -> list[str]:
    status_words = [str(x) for x in selectors.get("draft_status_texts", ["草稿"])]
    matches = []
    for entry in snapshot.get("entries", []):
        text = str(entry)
        if title in text and any(status in text for status in status_words):
            matches.append(text)
    return matches


def _job_path(project_root: Path, config: dict[str, Any], job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", job_id):
        raise UploadBlockedError("Invalid job_id; only letters, digits, dot, underscore and hyphen are allowed.")
    return _relative_config_path(project_root, config["jobs_dir"]) / f"{job_id}.json"


def _save_job(path: Path, record: dict[str, Any]) -> None:
    record["updated_at"] = _now()
    _write_json_atomic(path, record)


def _approval_record(
    project_root: Path,
    config: dict[str, Any],
    run_dir: Path,
) -> tuple[dict[str, Any], Path]:
    approval_path = _relative_config_path(
        project_root, config["approvals_dir"]
    ) / f"{run_dir.name}.json"
    approval = _read_json(approval_path)
    if approval.get("schema_version") != 1:
        raise UploadBlockedError("Unsupported local approval record schema.")
    if approval.get("fact_card_approved") is not True or approval.get("video_accepted") is not True:
        raise UploadBlockedError("Both Fact Card and video must have explicit user approval before upload.")
    for filename, key in (
        ("final.mp4", "video_sha256"),
        ("fact_card.json", "fact_card_sha256"),
        ("source_record.json", "source_record_sha256"),
        ("qa_report.json", "qa_report_sha256"),
        ("channels_draft.json", "channels_metadata_sha256"),
    ):
        path = run_dir / filename
        if not path.is_file() or _sha256(path) != approval.get(key):
            raise UploadBlockedError(
                f"Approved artifact changed or is missing ({filename}); review and approve the run again."
            )
    return approval, approval_path


def approve_run(
    project_root: Path,
    run_dir: Path,
    *,
    approved_by: str,
    confirmation: str | None = None,
    input_fn=input,
) -> dict[str, Any]:
    """Record an explicit local human review of the Fact Card and complete MP4."""
    project_root = project_root.resolve()
    run_dir = run_dir.resolve()
    output_root = (project_root / "outputs").resolve()
    if not run_dir.is_relative_to(output_root):
        raise UploadBlockedError("Only a generated run directory under project outputs/ can be approved.")
    if not approved_by.strip():
        raise UploadBlockedError("approved_by must not be empty.")

    final_mp4 = run_dir / "final.mp4"
    card_path = run_dir / "fact_card.json"
    source_path = run_dir / "source_record.json"
    qa_path = run_dir / "qa_report.json"
    for path in (final_mp4, card_path, source_path, qa_path):
        if not path.is_file():
            raise UploadBlockedError(f"Cannot approve an incomplete review package: missing {path.name}.")
    if final_mp4.stat().st_size < 100_000:
        raise UploadBlockedError("final.mp4 is unexpectedly small; refusing to approve.")
    card = _read_json(card_path)
    sources = _read_json(source_path)
    qa = _read_json(qa_path)
    if not card.get("claims") or not sources.get("sources"):
        raise UploadBlockedError("Fact Card claims and source records must both be present.")
    if qa.get("overall_status") != "PASS":
        raise UploadBlockedError(
            f"Only a strict QA PASS can be approved for upload; got {qa.get('overall_status')!r}."
        )
    duration = float(qa.get("video_summary", {}).get("duration_seconds") or 0.0)
    if not 45.0 <= duration <= 90.0:
        raise UploadBlockedError(f"Video duration {duration:.2f}s is outside the safe 45–90s upload gate.")

    fact_card_id = str(card.get("fact_card_id") or "").strip()
    if not fact_card_id:
        raise UploadBlockedError("Fact Card has no fact_card_id.")
    config, _ = _load_config(project_root)
    script = _read_json(run_dir / "script.json")
    metadata_path = run_dir / "channels_draft.json"
    expected_metadata = build_channels_metadata(
        card,
        script,
        run_dir.name,
        account_name=str(config["account_name"]),
        tags=list(config.get("default_tags", [])),
    )
    if metadata_path.is_file():
        metadata = _read_json(metadata_path)
        if metadata != expected_metadata:
            raise UploadBlockedError(
                "channels_draft.json differs from the exact approved Fact Card-derived metadata. "
                "Do not upload edited copy; update channels_title/Fact Card and explicitly re-approve the card."
            )
    else:
        metadata = expected_metadata
        _write_json_atomic(metadata_path, metadata)
    validate_channels_metadata(
        metadata,
        min_title_chars=int(config.get("title_min_chars", 6)),
        max_title_chars=int(config.get("title_max_chars", 16)),
        max_description_chars=int(config.get("description_max_chars", 1000)),
    )
    approval_phrase = f"APPROVE {fact_card_id}"
    print("\n即将记录本地人工审核批准：")
    print(f"Fact Card：{fact_card_id} — {card.get('title', '')}")
    print(f"科学问题：{card.get('scientific_question', '')}")
    for claim in card.get("claims", []):
        print(f"- {claim.get('claim_id', '')}: {claim.get('statement', '')}")
    print(f"视频：{final_mp4}")
    print(f"时长：{duration:.2f}s；QA：PASS")
    print(f"视频号短标题：{metadata['title']}")
    print(f"视频号描述：{metadata['description']}")
    print("请先实际观看完整视频并审阅 Fact Card、来源记录及待上传文案。")
    response = confirmation if confirmation is not None else input_fn(
        f"确认你已批准科学内容和成片？输入 {approval_phrase}："
    )
    if response.strip() != approval_phrase:
        raise UploadBlockedError("Approval phrase did not match; no approval record was written.")

    record = {
        "schema_version": 1,
        "job_id": run_dir.name,
        "fact_card_id": fact_card_id,
        "fact_card_approved": True,
        "video_accepted": True,
        "approved_by": approved_by.strip(),
        "approved_at": _now(),
        "video_sha256": _sha256(final_mp4),
        "fact_card_sha256": _sha256(card_path),
        "source_record_sha256": _sha256(source_path),
        "qa_report_sha256": _sha256(qa_path),
        "channels_metadata_sha256": _sha256(metadata_path),
        "qa_status": qa["overall_status"],
        "duration_seconds": duration,
        "approval_scope": "this exact review package only",
    }
    approval_path = _relative_config_path(
        project_root, config["approvals_dir"]
    ) / f"{run_dir.name}.json"
    if approval_path.exists():
        previous = _read_json(approval_path)
        if all(previous.get(key) == record.get(key) for key in (
            "video_sha256", "fact_card_sha256", "source_record_sha256",
            "qa_report_sha256", "channels_metadata_sha256"
        )):
            raise UploadBlockedError("This exact run already has an approval record.")
        raise UploadBlockedError("An approval record already exists for this run ID; resolve it manually.")
    _write_json_atomic(approval_path, record)
    return record


def _validate_run_for_upload(
    project_root: Path,
    run_dir: Path,
    config: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    project_root = project_root.resolve()
    run_dir = run_dir.resolve()
    if not run_dir.is_relative_to((project_root / "outputs").resolve()):
        raise UploadBlockedError("Upload source must be a generated run under project outputs/.")
    final_mp4 = run_dir / "final.mp4"
    if not final_mp4.is_file() or final_mp4.stat().st_size < 100_000:
        raise UploadBlockedError("final.mp4 is missing or unexpectedly small.")
    qa = _read_json(run_dir / "qa_report.json")
    if qa.get("overall_status") != "PASS":
        raise UploadBlockedError(
            f"Upload is blocked unless qa_report.json is strict PASS; got {qa.get('overall_status')!r}."
        )
    card_path = run_dir / "fact_card.json"
    source_path = run_dir / "source_record.json"
    card = _read_json(card_path)
    script = _read_json(run_dir / "script.json")
    try:
        approval = verify_fact_card_approval(project_root, card_path, source_path)
    except TopicApprovalError as exc:
        raise UploadBlockedError(str(exc)) from exc
    if approval is None:
        # Backward-compatible, stricter one-off approval remains available;
        # daily automation uses a one-time hash-bound Fact Card approval.
        try:
            approval, _ = _approval_record(project_root, config, run_dir)
        except UploadBlockedError as exc:
            raise UploadBlockedError(
                "This Fact Card has not been approved. Run approve-fact-card once before daily draft production."
            ) from exc
    metadata_path = run_dir / "channels_draft.json"
    if metadata_path.is_file():
        metadata = _read_json(metadata_path)
    else:
        metadata = build_channels_metadata(
            card,
            script,
            run_dir.name,
            account_name=str(config["account_name"]),
            tags=list(config.get("default_tags", [])),
        )
        _write_json_atomic(metadata_path, metadata)
    validate_channels_metadata(metadata)
    if metadata.get("job_id") != run_dir.name:
        raise UploadBlockedError("channels_draft.json job_id does not match the output directory.")
    if metadata.get("account_name") != config.get("account_name"):
        raise UploadBlockedError("Draft metadata account does not match configured target account.")
    if len(str(metadata["title"])) > int(config.get("title_max_chars", 16)):
        raise UploadBlockedError("Draft title exceeds the configured platform character limit.")
    if len(str(metadata["title"])) < int(config.get("title_min_chars", 6)):
        raise UploadBlockedError("Draft title is shorter than the configured platform minimum.")
    if len(str(metadata["description"])) > int(config.get("description_max_chars", 1000)):
        raise UploadBlockedError("Draft description exceeds the configured platform character limit.")
    return metadata, qa, approval


def _existing_session_only(project_root: Path) -> tuple[dict[str, Any], str]:
    config, _ = _load_config(project_root)
    session_path = _relative_config_path(project_root, config["session_file"])
    profile_dir = _relative_config_path(project_root, config["edge_profile_dir"]).resolve()
    if not session_path.is_file():
        raise UploadBlockedError("No recorded dedicated Edge session exists. Run channels-session first.")
    return _validate_existing_session(project_root, config, session_path, profile_dir)


def upload_run_to_channels(project_root: Path, run_dir: Path) -> dict[str, Any]:
    """Upload one approved, QA-passed video and save it as an unpublished draft."""
    project_root = project_root.resolve()
    run_dir = run_dir.resolve()
    config, selectors = _load_config(project_root)
    metadata, qa, approval = _validate_run_for_upload(project_root, run_dir, config)
    job_id = run_dir.name
    job_path = _job_path(project_root, config, job_id)
    if job_path.exists():
        existing = _read_json(job_path)
        state = str(existing.get("state", ""))
        if state == "DRAFT_SAVED":
            raise UploadBlockedError("This job already has a verified draft; duplicate upload is blocked.")
        if state in {"SAVE_REQUESTED", "UPLOAD_UNKNOWN", "UPLOADING", "PREPARED"}:
            raise UploadUnknownError(
                f"This job is already in state {state}. Reconcile it with channels-reconcile; do not upload again."
            )
        raise UploadBlockedError(
            f"This job already has an upload state ({state}); manual reconciliation is required before another attempt."
        )

    job: dict[str, Any] = {
        "schema_version": 1,
        "job_id": job_id,
        "state": "CREATED",
        "title": metadata["title"],
        "video_path": str((run_dir / "final.mp4").resolve()),
        "video_sha256": _sha256(run_dir / "final.mp4"),
        "approval_by": approval["approved_by"],
        "approval_at": approval["approved_at"],
        "qa_status": qa["overall_status"],
        "created_at": _now(),
        "save_click_count": 0,
        "pre_upload_snapshot": None,
        "verified_draft": None,
        "automatic_publication": False,
    }
    _save_job(job_path, job)

    session, websocket_url = ensure_edge_session(
        project_root, open_url=str(config["create_url"])
    )
    playwright, browser, context = _connect_playwright(websocket_url)
    try:
        create_page = context.new_page()
        create_page.goto(
            str(config["create_url"]),
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        _ensure_account_identity(
            create_page,
            str(config["account_name"]),
            selectors,
            wait_seconds=int(config.get("login_wait_seconds", 180)),
        )

        draft_page = context.new_page()
        draft_page.goto(
            str(config["draft_list_url"]),
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        _ensure_account_identity(
            draft_page,
            str(config["account_name"]),
            selectors,
            wait_seconds=0,
        )
        before = _draft_snapshot(draft_page, selectors)
        if _matching_draft_entries(before, str(metadata["title"]), selectors):
            job["state"] = "BLOCKED_DUPLICATE_TITLE"
            job["pre_upload_snapshot"] = before
            _save_job(job_path, job)
            raise UploadBlockedError(
                "A draft with the same title already exists. Refusing to create a possible duplicate."
            )
        job["pre_upload_snapshot"] = before
        job["state"] = "PREPARED"
        job["edge_session_pid"] = session["edge_pid"]
        job["draft_list_url"] = before["url"]
        _save_job(job_path, job)

        create_page.bring_to_front()
        video_input = _video_file_input(create_page, selectors)
        job["state"] = "UPLOADING"
        job["upload_started_at"] = _now()
        _save_job(job_path, job)
        video_input.set_input_files(str((run_dir / "final.mp4").resolve()), timeout=30_000)

        _wait_upload_ready(
            create_page,
            selectors,
            timeout_seconds=int(config.get("upload_timeout_seconds", 1800)),
        )
        _fill_field(create_page, selectors, "title_input", str(metadata["title"]))
        _fill_field(create_page, selectors, "description_input", str(metadata["description"]))

        button = _draft_save_button(create_page, selectors)
        if button is None or not button.is_enabled():
            raise UploadBlockedError("The draft-save control is not visible and enabled.")
        # Record intent before the single click. A crash from this point onward
        # is treated as uncertain and can only be reconciled from the draft list.
        job["state"] = "SAVE_REQUESTED"
        job["save_requested_at"] = _now()
        job["save_click_count"] = 1
        _save_job(job_path, job)
        try:
            button.click(timeout=10_000)
        except Exception as exc:
            job["state"] = "UPLOAD_UNKNOWN"
            job["save_click_error"] = type(exc).__name__
            _save_job(job_path, job)
            raise UploadUnknownError(
                "The save-draft action may have been submitted. Reconcile the draft list; do not click save again."
            ) from exc

        attempts = int(config.get("draft_verify_attempts", 5))
        interval = int(config.get("draft_verify_interval_seconds", 2))
        verified: list[str] = []
        after: dict[str, Any] | None = None
        for attempt in range(attempts):
            draft_page.reload(wait_until="domcontentloaded", timeout=60_000)
            after = _draft_snapshot(draft_page, selectors)
            verified = _matching_draft_entries(after, str(metadata["title"]), selectors)
            if verified:
                break
            if attempt + 1 < attempts:
                draft_page.wait_for_timeout(interval * 1000)

        if len(verified) != 1:
            job["state"] = "UPLOAD_UNKNOWN"
            job["post_upload_snapshot"] = after
            job["verification_matches"] = len(verified)
            _save_job(job_path, job)
            raise UploadUnknownError(
                "The draft save was clicked once, but the new unpublished draft could not be uniquely "
                "verified. The upload will not be repeated. Inspect the open Edge draft list."
            )

        before_entries = set(before.get("entries", []))
        if verified[0] in before_entries:
            job["state"] = "UPLOAD_UNKNOWN"
            job["post_upload_snapshot"] = after
            _save_job(job_path, job)
            raise UploadUnknownError("The matching draft was already present in the pre-upload snapshot.")

        job["state"] = "DRAFT_SAVED"
        job["post_upload_snapshot"] = after
        job["verified_draft"] = {
            "title": metadata["title"],
            "row_text": verified[0],
            "verified_at": _now(),
            "draft_list_url": after["url"] if after else None,
        }
        job["automatic_publication"] = False
        _save_job(job_path, job)
        draft_page.bring_to_front()
        return {
            "state": job["state"],
            "job_id": job_id,
            "title": metadata["title"],
            "account_name": config["account_name"],
            "verified_draft": job["verified_draft"],
            "edge_pid": session["edge_pid"],
            "automatic_publication": False,
        }
    except UploadUnknownError:
        raise
    except Exception as exc:
        if job.get("state") in {"SAVE_REQUESTED", "UPLOAD_UNKNOWN"}:
            job["state"] = "UPLOAD_UNKNOWN"
            job["last_error_type"] = type(exc).__name__
        elif job.get("state") not in {"DRAFT_SAVED", "BLOCKED_DUPLICATE_TITLE"}:
            job["state"] = "FAILED_BEFORE_SAVE"
            job["last_error_type"] = type(exc).__name__
            job["last_error"] = str(exc)[:500]
        _save_job(job_path, job)
        raise
    finally:
        # The persistent Edge process/context is intentionally left alive.
        playwright.stop()


def reconcile_upload(project_root: Path, job_id: str) -> dict[str, Any]:
    """Read the draft list and reconcile an uncertain upload; never resubmit."""
    project_root = project_root.resolve()
    config, selectors = _load_config(project_root)
    job_path = _job_path(project_root, config, job_id)
    job = _read_json(job_path)
    if job.get("state") == "DRAFT_SAVED":
        return {
            "state": "DRAFT_SAVED",
            "job_id": job_id,
            "verified_draft": job.get("verified_draft"),
            "message": "Already verified; no upload action was performed.",
        }
    if job.get("state") not in {"SAVE_REQUESTED", "UPLOAD_UNKNOWN", "UPLOADING", "PREPARED"}:
        raise UploadBlockedError(
            f"Job state {job.get('state')!r} is not eligible for read-only reconciliation."
        )
    before = job.get("pre_upload_snapshot")
    if not isinstance(before, dict):
        raise UploadUnknownError("No pre-upload draft snapshot is stored; manual inspection is required.")

    session, websocket_url = _existing_session_only(project_root)
    playwright, browser, context = _connect_playwright(websocket_url)
    try:
        page = context.new_page()
        page.goto(str(config["draft_list_url"]), wait_until="domcontentloaded", timeout=60_000)
        _ensure_account_identity(page, str(config["account_name"]), selectors, wait_seconds=0)
        after = _draft_snapshot(page, selectors)
        matches = _matching_draft_entries(after, str(job.get("title") or ""), selectors)
        prior = _matching_draft_entries(before, str(job.get("title") or ""), selectors)
        if len(matches) == 1 and not prior:
            job["state"] = "DRAFT_SAVED"
            job["post_upload_snapshot"] = after
            job["verified_draft"] = {
                "title": job.get("title"),
                "row_text": matches[0],
                "verified_at": _now(),
                "draft_list_url": after["url"],
                "reconciled_read_only": True,
            }
            _save_job(job_path, job)
            page.bring_to_front()
            return {
                "state": "DRAFT_SAVED",
                "job_id": job_id,
                "verified_draft": job["verified_draft"],
                "automatic_publication": False,
            }
        job["state"] = "UPLOAD_UNKNOWN"
        job["post_upload_snapshot"] = after
        job["verification_matches"] = len(matches)
        _save_job(job_path, job)
        raise UploadUnknownError(
            "Read-only reconciliation found no unique new draft. No second upload or save click was made. "
            "Inspect the account manually before taking any further action."
        )
    finally:
        playwright.stop()


def latest_qa_pass_run(project_root: Path) -> Path:
    """Choose the newest complete, strict-QA-PASS output for explicit review."""
    outputs = (project_root.resolve() / "outputs")
    candidates: list[Path] = []
    if not outputs.is_dir():
        raise UploadBlockedError("No outputs/ directory exists.")
    for run_dir in outputs.iterdir():
        if not run_dir.is_dir():
            continue
        try:
            qa = _read_json(run_dir / "qa_report.json")
            if (
                qa.get("overall_status") == "PASS"
                and (run_dir / "final.mp4").is_file()
                and (run_dir / "fact_card.json").is_file()
                and (run_dir / "source_record.json").is_file()
                and (run_dir / "script.json").is_file()
            ):
                candidates.append(run_dir)
        except UploadBlockedError:
            continue
    if not candidates:
        raise UploadBlockedError("No complete output with strict QA PASS is available under outputs/.")
    return max(candidates, key=lambda item: item.stat().st_mtime)


def approve_latest_run(
    project_root: Path,
    *,
    approved_by: str,
    confirmation: str | None = None,
    input_fn=input,
) -> dict[str, Any]:
    run_dir = latest_qa_pass_run(project_root)
    print(f"Selected latest QA-passed run: {run_dir}")
    return approve_run(
        project_root,
        run_dir,
        approved_by=approved_by,
        confirmation=confirmation,
        input_fn=input_fn,
    )


def upload_latest_approved_run(project_root: Path) -> dict[str, Any]:
    """Upload the newest strict-QA-PASS output whose Fact Card has one-time approval."""
    project_root = project_root.resolve()
    outputs = project_root / "outputs"
    config, _ = _load_config(project_root)
    if not outputs.is_dir():
        raise UploadBlockedError("No outputs/ directory exists.")
    # Snapshot the existing run order before validation: validating a legacy
    # output may create its deterministic channels_draft.json and change mtime.
    ordered_runs = sorted(
        (item for item in outputs.iterdir() if item.is_dir()),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for run_dir in ordered_runs:
        try:
            _validate_run_for_upload(project_root, run_dir, config)
        except (UploadBlockedError, TopicApprovalError, FileNotFoundError, ValueError):
            continue
        return upload_run_to_channels(project_root, run_dir)
    raise UploadBlockedError(
        "No output has both strict QA PASS and a valid approved Fact Card. "
        "Approve the Fact Card once with approve-fact-card, then generate a normal (non-review-sample) video."
    )


def inspect_channels_ui(project_root: Path) -> dict[str, Any]:
    """Return a sanitized inventory of visible controls to tune selectors locally."""
    project_root = project_root.resolve()
    config, selectors = _load_config(project_root)
    session, websocket_url = ensure_edge_session(project_root, open_url=str(config["create_url"]))
    playwright, browser, context = _connect_playwright(websocket_url)
    try:
        page = context.new_page()
        page.goto(str(config["create_url"]), wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(1_000)
        body = _body_text(page)
        account_verified = _wait_for_account_identity(
            page, str(config["account_name"]), selectors, wait_seconds=0
        )
        buttons = []
        try:
            loc = page.get_by_role("button")
            for index in range(min(loc.count(), 100)):
                item = loc.nth(index)
                if item.is_visible():
                    text = re.sub(r"\s+", " ", item.inner_text()).strip()
                    if text:
                        buttons.append(text[:100])
        except Exception:
            pass
        textboxes = []
        try:
            loc = page.get_by_role("textbox")
            for index in range(min(loc.count(), 100)):
                item = loc.nth(index)
                if item.is_visible():
                    textboxes.append({
                        "placeholder": item.get_attribute("placeholder"),
                        "aria_label": item.get_attribute("aria-label"),
                        "role": item.get_attribute("role"),
                    })
        except Exception:
            pass
        files = []
        try:
            loc = page.locator("input[type='file']")
            for index in range(min(loc.count(), 20)):
                item = loc.nth(index)
                files.append({"accept": item.get_attribute("accept"), "multiple": item.get_attribute("multiple")})
        except Exception:
            pass
        login_hint = any(token in body for token in ("扫码登录", "微信登录", "请登录", "登录后"))
        return {
            "account_verified": account_verified,
            "manual_login_required": not account_verified and login_hint,
            "page_url": page.url,
            "page_title": page.title(),
            "visible_buttons": buttons,
            "visible_textboxes": textboxes,
            "file_inputs": files,
            "session_pid": session["edge_pid"],
            "session_profile": session["user_data_dir"],
            "note": "No upload, save, publish or delete action was performed.",
        }
    finally:
        playwright.stop()
