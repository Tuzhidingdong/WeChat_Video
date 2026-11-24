"""Safe, local-only WeChat Channels draft uploader.

Automated uploads use a project-owned headless Edge profile through Playwright CDP.
A headed session is reserved for explicit manual QR login. The module never uses
private platform APIs, never reads/writes the user's normal Edge profile, and
contains no publish action.
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
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from .article_source import build_article_channels_metadata
from .channels_metadata import build_channels_metadata_for_run_dir, validate_channels_metadata
from .topic_approval import TopicApprovalError, verify_fact_card_approval


class UploadBlockedError(RuntimeError):
    """A safety or precondition gate prevents upload."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


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


def _is_headless_command(command: list[str]) -> bool:
    """Return whether an Edge command line explicitly enables headless mode."""
    return any(
        item.strip().strip('"').casefold() == "--headless"
        or item.strip().strip('"').casefold().startswith("--headless=")
        for item in command
    )


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
    *,
    expected_headless: bool,
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
    if bool(session.get("headless", False)) != expected_headless:
        raise UploadBlockedError("Recorded Edge session headless mode does not match configuration.")
    if _is_headless_command(details["command_line"]) != expected_headless:
        mode = "headless" if expected_headless else "headed"
        raise UploadBlockedError(
            f"Dedicated Edge process is not running in the required {mode} mode."
        )
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
    headless: bool | None = None,
) -> tuple[dict[str, Any], str]:
    """Reuse a verified dedicated Edge session, or launch in the requested mode."""
    project_root = project_root.resolve()
    config, _ = _load_config(project_root)
    headless_mode = bool(config.get("headless", False) if headless is None else headless)
    profile_dir = _relative_config_path(project_root, config["edge_profile_dir"]).resolve()
    session_path = _relative_config_path(project_root, config["session_file"])
    profile_dir.mkdir(parents=True, exist_ok=True)
    session_path.parent.mkdir(parents=True, exist_ok=True)

    if session_path.is_file():
        try:
            return _validate_existing_session(
                project_root, config, session_path, profile_dir,
                expected_headless=headless_mode,
            )
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
    ]
    if headless_mode:
        args.append("--headless=new")
    else:
        args.append("--new-window")
    args.append(open_url or str(config["create_url"]))
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
            if _is_headless_command(details["command_line"]) != headless_mode:
                raise UploadBlockedError("Edge process did not start in the requested browser mode.")
            session = {
                "schema_version": 1,
                "headless": headless_mode,
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
    # Manual QR login needs a visible window. Automated uploads remain headless.
    session, websocket_url = ensure_edge_session(
        project_root, open_url=str(config["create_url"]), headless=False
    )
    playwright, browser, context = _connect_playwright(websocket_url)
    try:
        page = context.new_page()
        page.goto(str(config["create_url"]), wait_until="domcontentloaded", timeout=60_000)
        expected_name = str(config["account_name"])
        verified = _wait_for_account_identity(
            page,
            expected_name,
            selectors,
            wait_seconds=max(0, int(wait_login_seconds)),
        )
        login_required = not verified and _login_required_hint(page)
        return {
            "session_pid": session["edge_pid"],
            "session_profile": session["user_data_dir"],
            "edge_version": session["edge_version"],
            "headless": bool(session.get("headless", False)),
            "page_url": page.url,
            "account_verified": verified,
            "manual_login_required": login_required,
            "message": (
                "Account identity verified."
                if verified
                else (
                    "A login prompt is visible. Complete manual login in the dedicated Edge window, "
                    "then rerun channels-inspect."
                    if login_required
                    else (
                        f"The page is open, but account identity {expected_name!r} is not yet verified. "
                        "No upload action is allowed."
                    )
                )
            ),
        }
    finally:
        # Stop only the Playwright driver. Never close the persistent context or Edge.
        playwright.stop()


def _body_text(page: Any) -> str:
    """Read body text directly in each frame's own execution context."""
    chunks: list[str] = []
    expression = """() => {
        const body = document.body;
        return body ? String(body.innerText || body.textContent || '').trim() : '';
    }"""
    for frame in _frame_contexts(page):
        try:
            value = str(frame.evaluate(expression)).strip()
        except Exception:
            continue
        if value and value not in chunks:
            chunks.append(value)
    return "\n".join(chunks)

def _login_required_hint(page: Any) -> bool:
    """Return true only for an explicit, high-confidence login prompt."""
    body = _body_text(page)
    explicit_prompts = (
        "扫码登录",
        "微信登录",
        "请登录",
        "立即登录",
        "登录后继续",
        "登录以继续",
    )
    return any(token in body for token in explicit_prompts)


def _account_identity_evidence(frame: Any, expected_name: str) -> list[dict[str, Any]]:
    """Find only visible DOM evidence for the configured account identity.

    The scan is restricted to the configured account name in visible text,
    accessible attributes, image alt text, or CSS pseudo-element content. It
    accepts a match only in the lower-left account area or on a semantically
    account-related element. No form values, cookies, storage, or page-wide
    text dumps are collected.
    """
    expression = r"""(expectedName) => {
        /* __CHANNELS_ACCOUNT_IDENTITY_SCAN__ */
        const marker = "__CHANNELS_ACCOUNT_IDENTITY_SCAN__";
        const expected = String(expectedName || "").replace(/\s+/g, " ").trim();
        if (!expected) return [];
        const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const visible = (element) => {
            if (!element || element.hidden) return false;
            const rect = element.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
            for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (style.display === "none" || style.visibility === "hidden" ||
                    style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                    return false;
                }
            }
            return true;
        };
        const matches = [];
        const elements = Array.from(document.querySelectorAll("body *"));
        for (const element of elements) {
            if (!visible(element)) continue;
            const rect = element.getBoundingClientRect();
            const directText = Array.from(element.childNodes)
                .filter(node => node.nodeType === Node.TEXT_NODE)
                .map(node => normalize(node.nodeValue))
                .filter(Boolean);
            const candidates = directText.map(value => ["visible_text", value]);
            for (const attr of ["aria-label", "title", "alt"]) {
                const value = normalize(element.getAttribute(attr));
                if (value) candidates.push([attr, value]);
            }
            for (const pseudo of ["::before", "::after"]) {
                const value = normalize(window.getComputedStyle(element, pseudo).content)
                    .replace(/^["']|["']$/g, "");
                if (value && value !== "none" && value !== "normal") {
                    candidates.push(["pseudo_text", value]);
                }
            }
            const matched = candidates.find(([, value]) => value.includes(expected));
            if (!matched) continue;

            // The headless platform shell renders the authenticated account
            // nickname in this explicit WeChat surface rather than the headed
            // lower-left account panel. Accept only an exact configured-name
            // match on the observed h2.finder-nickname node.
            const finderNicknameSurface =
                element.tagName.toLowerCase() === "h2" &&
                Boolean(element.classList && element.classList.contains("finder-nickname")) &&
                normalize(element.innerText || element.textContent) === expected;
            const semanticHint = [
                element.getAttribute("role"),
                element.getAttribute("aria-label"),
                element.getAttribute("title"),
                element.getAttribute("id"),
                typeof element.className === "string" ? element.className : ""
            ].join(" ");
            const semanticAccountSurface = finderNicknameSurface ||
                /(account|profile|avatar|user|账号|用户|个人中心)/i.test(semanticHint);
            const lowerLeft =
                rect.left <= window.innerWidth * 0.45 &&
                rect.top >= window.innerHeight * 0.50;
            if (!lowerLeft && !semanticAccountSurface) continue;

            matches.push({
                tag: element.tagName.toLowerCase(),
                evidence_type: matched[0],
                matched_value: matched[1].slice(0, 80),
                region: lowerLeft ? "lower_left" : "semantic_account_surface",
                semantic_account_surface: semanticAccountSurface,
                identity_surface: finderNicknameSurface ? "finder_nickname" :
                    (semanticAccountSurface ? "semantic_account_surface" : "lower_left"),
                role: element.getAttribute("role") || "",
                viewport_width: Math.round(window.innerWidth),
                viewport_height: Math.round(window.innerHeight),
                device_pixel_ratio: Number(window.devicePixelRatio || 1),
                left: Math.round(rect.left),
                top: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height)
            });
            if (matches.length >= 8) break;
        }
        return matches;
    }"""
    try:
        raw = frame.evaluate(expression, expected_name)
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    evidence: list[dict[str, Any]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        region = str(item.get("region") or "")
        if region != "lower_left" and item.get("semantic_account_surface") is not True:
            continue
        evidence.append({
            "tag": str(item.get("tag") or "")[:24],
            "evidence_type": str(item.get("evidence_type") or "")[:24],
            "matched_value": str(item.get("matched_value") or "")[:80],
            "region": region,
            "identity_surface": str(item.get("identity_surface") or "")[:40],
            "role": str(item.get("role") or "")[:40],
            "viewport_width": int(item.get("viewport_width") or 0),
            "viewport_height": int(item.get("viewport_height") or 0),
            "device_pixel_ratio": float(item.get("device_pixel_ratio") or 1),
            "left": int(item.get("left") or 0),
            "top": int(item.get("top") or 0),
            "width": int(item.get("width") or 0),
            "height": int(item.get("height") or 0),
        })
    return evidence


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
    deadline = time.monotonic() + max(0, wait_seconds)
    while True:
        for frame in _frame_contexts(page):
            try:
                if _account_identity_evidence(frame, expected_name):
                    return True
                if selector:
                    candidates = _visible_element_handles(frame, str(selector), limit=8)
                    for candidate in candidates:
                        actual = candidate.inner_text().strip()
                        if actual == expected_name or expected_name in actual:
                            return True
                # Do not accept an arbitrary page mention as account identity.
                # Only the configured selector or semantically recognized
                # account surfaces above are authoritative.
            except Exception:
                continue
        if time.monotonic() >= deadline:
            return False
        page.wait_for_timeout(500)


def _account_identity_diagnostics(page: Any, expected_name: str) -> dict[str, Any]:
    """Capture privacy-safe per-frame evidence when the intended account cannot be verified.

    Only the configured account name's presence/count and matching visible DOM
    nodes are recorded. Arbitrary page text, form values, cookies and storage
    are never collected.
    """
    expression = r"""(expectedName) => {
        /* __CHANNELS_ACCOUNT_IDENTITY_DIAGNOSTICS__ */
        const expected = String(expectedName || "").replace(/\s+/g, " ").trim();
        const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const visible = (element) => {
            if (!element || element.hidden) return false;
            const rect = element.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
            for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (style.display === "none" || style.visibility === "hidden" ||
                    style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                    return false;
                }
            }
            return true;
        };
        const bodyText = normalize(document.body ? document.body.innerText : "");
        const matches = [];
        let visibleMatchCount = 0;
        for (const element of Array.from(document.querySelectorAll("body *"))) {
            if (!visible(element)) continue;
            const rect = element.getBoundingClientRect();
            const directText = Array.from(element.childNodes)
                .filter(node => node.nodeType === Node.TEXT_NODE)
                .map(node => normalize(node.nodeValue))
                .filter(Boolean);
            const candidates = directText.map(value => ["visible_text", value]);
            for (const attr of ["aria-label", "title", "alt"]) {
                const value = normalize(element.getAttribute(attr));
                if (value) candidates.push([attr, value]);
            }
            for (const pseudo of ["::before", "::after"]) {
                const value = normalize(window.getComputedStyle(element, pseudo).content)
                    .replace(/^["']|["']$/g, "");
                if (value && value !== "none" && value !== "normal") {
                    candidates.push(["pseudo_text", value]);
                }
            }
            const match = candidates.find(([, value]) => value.includes(expected));
            if (!match) continue;
            visibleMatchCount += 1;
            const finderNicknameNode =
                element.tagName.toLowerCase() === "h2" &&
                Boolean(element.classList && element.classList.contains("finder-nickname")) &&
                normalize(element.innerText || element.textContent) === expected;
            const semantic = [
                element.getAttribute("role"),
                element.getAttribute("aria-label"),
                element.getAttribute("title"),
                element.id,
                typeof element.className === "string" ? element.className : ""
            ].join(" ");
            if (matches.length < 12) matches.push({
                tag: element.tagName.toLowerCase(),
                evidence_type: match[0],
                matched_value: String(match[1]).slice(0, 80),
                role: element.getAttribute("role") || "",
                id: String(element.id || "").slice(0, 100),
                class_name: String(typeof element.className === "string" ? element.className : "").slice(0, 160),
                semantic_account_surface: finderNicknameNode || /(account|profile|avatar|user|账号|用户|个人中心)/i.test(semantic),
                finder_nickname_node: finderNicknameNode,
                lower_left: rect.left <= window.innerWidth * 0.45 &&
                    rect.top >= window.innerHeight * 0.50,
                rect: {
                    x: Math.round(rect.left), y: Math.round(rect.top),
                    width: Math.round(rect.width), height: Math.round(rect.height)
                }
            });
        }
        return {
            body_contains_expected_name: Boolean(expected && bodyText.includes(expected)),
            viewport: {
                width: Math.round(window.innerWidth),
                height: Math.round(window.innerHeight),
                device_pixel_ratio: Number(window.devicePixelRatio || 1),
                scroll_x: Math.round(window.scrollX || 0),
                scroll_y: Math.round(window.scrollY || 0)
            },
            visible_matching_node_count: visibleMatchCount,
            visible_matching_nodes: matches
        };
    }""";
    result: dict[str, Any] = {
        "stage": "account_identity",
        "expected_account_name": str(expected_name),
        "page_url": str(getattr(page, "url", "")),
        "login_prompt_detected": False,
        "frames": [],
        "captured_at": _now(),
    }
    try:
        result["page_title"] = str(page.title())[:160]
    except Exception as exc:
        result["page_title_error"] = type(exc).__name__
    try:
        result["login_prompt_detected"] = _login_required_hint(page)
    except Exception as exc:
        result["login_prompt_error"] = type(exc).__name__

    for frame in _frame_contexts(page):
        item: dict[str, Any] = {
            "frame_url": str(getattr(frame, "url", ""))[:300],
            "ready_state": None,
            "verified_identity_evidence": [],
        }
        try:
            item["ready_state"] = str(frame.evaluate("() => document.readyState") or "")
        except Exception as exc:
            item["ready_state_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        try:
            item["verified_identity_evidence"] = _account_identity_evidence(
                frame, expected_name
            )
        except Exception as exc:
            item["identity_evidence_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        try:
            raw = frame.evaluate(expression, expected_name)
            if isinstance(raw, dict):
                item.update(raw)
            else:
                item["diagnostic_scan_error"] = "unexpected result type"
        except Exception as exc:
            item["diagnostic_scan_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        result["frames"].append(item)
    return result


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
    diagnostics = _account_identity_diagnostics(page, expected_name)
    if diagnostics.get("login_prompt_detected"):
        message = (
            "The dedicated Channels session is not logged in. Scan the QR code in the open Edge window, "
            "confirm the intended account, then rerun this command."
        )
    else:
        message = (
            f"Could not verify the intended Channels account identity {expected_name!r}. "
            "The sanitized per-frame identity diagnostics were saved to the upload job. "
            "No upload was attempted."
        )
    raise UploadBlockedError(message, diagnostics=diagnostics)


def _ensure_draft_list_account_identity(
    page: Any,
    config: dict[str, Any],
    selectors: dict[str, Any],
) -> None:
    """Wait for the draft-list SPA to render before verifying its account identity."""
    wait_seconds = max(1, int(config.get("ui_ready_timeout_seconds", 15)))
    _ensure_account_identity(
        page,
        str(config["account_name"]),
        selectors,
        wait_seconds=wait_seconds,
    )


def _frame_contexts(page: Any) -> list[Any]:
    """Return the top frame followed by child frames, without duplicates."""
    try:
        frames = list(page.frames)
    except Exception:
        return [page]
    main_frame = getattr(page, "main_frame", None)
    ordered: list[Any] = []
    if main_frame is not None:
        ordered.append(main_frame)
    ordered.extend(frame for frame in frames if frame is not main_frame)
    return ordered or [page]


_DOM_VISIBLE_ELEMENT_SCAN = r"""(payload) => {
    /* __CHANNELS_VISIBLE_ELEMENT_SCAN__ */
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const isVisible = (element) => {
        if (!element || element.hidden) return false;
        const rect = element.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) return false;
        for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
            const style = window.getComputedStyle(node);
            if (style.display === "none" || style.visibility === "hidden" ||
                style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                return false;
            }
        }
        return true;
    };
    const labelInfo = (element) => {
        const visibleText = normalize(element.innerText || element.textContent || "");
        const ariaLabel = normalize(element.getAttribute("aria-label") || "");
        return {
            visible_text: visibleText,
            aria_label: ariaLabel,
            label: visibleText || ariaLabel,
            label_source: visibleText ? "visible_text" : (ariaLabel ? "aria_label" : "none")
        };
    };
    const selector = String(payload.selector || "");
    const exactText = payload.exact_text == null ? null : normalize(payload.exact_text);
    const containsText = payload.contains_text == null ? null : normalize(payload.contains_text);
    const visibleElements = Array.from(document.querySelectorAll(selector)).filter(isVisible);
    const matches = visibleElements.filter((element) => {
        if (exactText === null && containsText === null) return true;
        const actual = labelInfo(element).label;
        if (exactText !== null && actual !== exactText) return false;
        if (containsText !== null && !actual.includes(containsText)) return false;
        return true;
    });
    const clip = (value, size) => String(value == null ? "" : value).slice(0, size);
    const attributesOf = (element) => {
        const out = {};
        const attrs = element && element.attributes ? Array.from(element.attributes) : [];
        for (const attr of attrs) {
            const name = String(attr.name || "").slice(0, 64);
            if (name) out[name] = clip(attr.value, 240);
        }
        return out;
    };
    const hrefPath = (element) => {
        try {
            const raw = element && element.getAttribute
                ? element.getAttribute("href") : "";
            if (!raw) return "";
            return new URL(raw, location.href).pathname || "";
        } catch (_) { return ""; }
    };
    const navigationHrefOf = (element) => {
        const own = String(element.getAttribute("href") || "");
        if (own) return hrefPath(element);
        for (let node = element.parentElement; node && node.nodeType === 1;
             node = node.parentElement) {
            const path = hrefPath(node);
            if (path) return path;
        }
        return "";
    };
    const ancestorsOf = (element) => {
        const out = [];
        let node = element.parentElement;
        for (let depth = 0; node && node.nodeType === 1 && depth < 6;
             depth += 1, node = node.parentElement) {
            out.push({
                tag: node.tagName.toLowerCase(),
                id: clip(node.id, 120),
                class_name: clip(typeof node.className === "string" ? node.className : "", 240),
                role: clip(node.getAttribute("role") || "", 80),
                href: hrefPath(node),
                attributes: attributesOf(node)
            });
        }
        return out;
    };
    const rectOf = (element) => {
        const rect = element.getBoundingClientRect();
        return {
            x: Math.round(rect.left), y: Math.round(rect.top),
            w: Math.round(rect.width), h: Math.round(rect.height)
        };
    };
    const limit = Math.max(1, Math.min(64, Number(payload.limit || 8)));
    const describe = (element, visible_index) => {
        const info = labelInfo(element);
        return {
            visible_index,
            tag: element.tagName.toLowerCase(),
            text: info.visible_text.slice(0, 160),
            aria_label: info.aria_label.slice(0, 160),
            matched_label: info.label.slice(0, 160),
            label_source: info.label_source,
            disabled: Boolean(element.disabled) ||
                element.getAttribute("aria-disabled") === "true",
            /* Structural evidence for the semantic creator-entry rule.
               Class, id, data, aria, href and ancestor attributes are captured
               for diagnosis and for proving a navigation target. Geometry
               (rect) is captured ONLY to de-duplicate repeated scans of the
               same DOM node; it is never used to choose which button to click. */
            attributes: attributesOf(element),
            outer_html: clip(element.outerHTML || "", 600),
            href: navigationHrefOf(element),
            ancestors: ancestorsOf(element),
            rect: rectOf(element)
        };
    };
    return {
        match_count: matches.length,
        items: matches.slice(0, limit).map((element, visible_index) =>
            describe(element, visible_index)
        ),
        observed_items: payload.include_observed === true
            ? visibleElements.slice(0, limit).map((element, index) => describe(element, index))
            : []
    };
}""";

_DOM_VISIBLE_ELEMENT_HANDLE = r"""(payload) => {
    /* __CHANNELS_VISIBLE_ELEMENT_HANDLE__ */
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const isVisible = (element) => {
        if (!element || element.hidden) return false;
        const rect = element.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) return false;
        for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
            const style = window.getComputedStyle(node);
            if (style.display === "none" || style.visibility === "hidden" ||
                style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                return false;
            }
        }
        return true;
    };
    const labelOf = (element) => {
        const visibleText = normalize(element.innerText || element.textContent || "");
        const ariaLabel = normalize(element.getAttribute("aria-label") || "");
        return visibleText || ariaLabel;
    };
    const selector = String(payload.selector || "");
    const exactText = payload.exact_text == null ? null : normalize(payload.exact_text);
    const containsText = payload.contains_text == null ? null : normalize(payload.contains_text);
    const matches = Array.from(document.querySelectorAll(selector)).filter((element) => {
        if (!isVisible(element)) return false;
        if (exactText === null && containsText === null) return true;
        const actual = labelOf(element);
        if (exactText !== null && actual !== exactText) return false;
        if (containsText !== null && !actual.includes(containsText)) return false;
        return true;
    });
    return matches[Number(payload.visible_index)] || null;
}""";


def _visible_element_handles(
    page: Any,
    selector: str,
    *,
    limit: int = 8,
    exact_text: str | None = None,
    contains_text: str | None = None,
    bind_retries: int = 5,
    retry_delay_ms: int = 250,
) -> list[Any]:
    """Return ElementHandles found by DOM evaluation, never frame Locator queries.

    Channels embeds creator and management applications in cross-origin frames.
    CDP Locator queries have returned zero nodes in those frames even when a
    same-frame querySelectorAll sees the live controls. Resolve each candidate
    in its own execution context, then perform trusted Playwright ElementHandle
    actions on that exact node.

    The management SPA re-renders its navigation while it animates, so a node
    seen by the read-only scan can change or become invisible before it is
    bound. A transient bind failure re-scans a bounded number of times; nothing
    is clicked until a fresh, stable, visible handle is bound. Persistent
    failures still fail closed with the original diagnostic message.
    """
    found: list[Any] = []
    payload = {
        "selector": str(selector),
        "exact_text": exact_text,
        "contains_text": contains_text,
        "limit": int(limit),
    }
    attempts = max(1, int(bind_retries))
    for frame in _frame_contexts(page):
        frame_url = str(getattr(frame, "url", ""))[:180]
        last_error: str | None = None
        last_error_kind = "bind"
        for attempt in range(attempts):
            transient = False
            try:
                inventory = frame.evaluate(_DOM_VISIBLE_ELEMENT_SCAN, payload)
            except Exception as exc:
                # The WeChat management SPA raises a benign LogicError from its
                # own code ("此报错可以忽略，iframe主动中断主应用代码...") that
                # Playwright surfaces through evaluate. A fresh scan normally
                # succeeds, so treat it as transient and only fail if it persists.
                last_error = (
                    f"Could not inspect selector {selector!r} inside frame "
                    f"{frame_url}: {type(exc).__name__}: {str(exc)[:160]}"
                )
                last_error_kind = "scan"
                transient = True
            if not transient and (
                not isinstance(inventory, dict)
                or not isinstance(inventory.get("items"), list)
            ):
                last_error = f"DOM scan returned an invalid result for selector {selector!r}."
                last_error_kind = "scan"
                transient = True
            if not transient:
                match_count = int(inventory.get("match_count") or 0)
                if match_count > limit:
                    raise UploadBlockedError(
                        f"Too many visible DOM matches ({match_count}) for selector {selector!r}; refusing an ambiguous action."
                    )
                batch: list[Any] = []
                for item in inventory["items"]:
                    if not isinstance(item, dict):
                        continue
                    handle_payload = dict(payload)
                    handle_payload["visible_index"] = int(item.get("visible_index", -1))
                    try:
                        handle = frame.evaluate_handle(
                            _DOM_VISIBLE_ELEMENT_HANDLE, handle_payload
                        )
                        candidate = handle.as_element()
                        if candidate is None or not candidate.is_visible():
                            raise ValueError("the candidate changed or became invisible")
                    except Exception as exc:
                        last_error = f"{type(exc).__name__}: {str(exc)[:160]}"
                        last_error_kind = "bind"
                        transient = True
                        break
                    batch.append(candidate)
                if not transient:
                    found.extend(batch)
                    last_error = None
                    break
            if attempt + 1 < attempts:
                page.wait_for_timeout(max(0, int(retry_delay_ms)))
        if last_error is not None:
            if last_error_kind == "scan":
                raise UploadBlockedError(last_error)
            raise UploadBlockedError(
                f"Could not bind the inspected DOM candidate in frame "
                f"{frame_url}: {last_error}"
            )
    return found


def _visible_element_handle(page: Any, selector_list: Any):
    """Return one visible ElementHandle from configured selectors, if unique."""
    if not isinstance(selector_list, list):
        selector_list = [selector_list] if selector_list else []
    for selector in selector_list:
        candidates = _visible_element_handles(page, str(selector), limit=16)
        if len(candidates) > 1:
            raise UploadBlockedError(
                f"More than one visible element matched the configured field selector {selector!r}."
            )
        if candidates:
            return candidates[0]
    return None

_CHANNELS_HOST = "channels.weixin.qq.com"
_DEFAULT_CREATE_FORM_PATH = "/micro/content/post/create"
# The post-card creator entry is a navigation control: its function is proven
# by the creation route it targets, never by its position, index or a guessed
# CSS class. Both the SPA create route and the embedded form route are accepted.
_DEFAULT_CREATE_NAV_TARGETS = (
    "/platform/post/create",
    "/micro/content/post/create",
)
# Real production DOM (upload job 20261122_192030_critical_nucleus) proved the
# two same-name buttons are distinct creation entries rendered in two UI states:
#   header entry:  button -> .weui-desktop-btn_wrp -> .post ->
#                  .post-list-header -> .post-list -> .finder-card
#   empty-state:   button -> .weui-desktop-btn_wrp -> .option ->
#                  .none-post -> .post-list -> .finder-card
# Both share identical markup and have no URL-bearing attribute (Vue click
# handler), so an href-based rule alone can never qualify them. Ancestor class
# tokens are used ONLY as positive structural proof of the create action, in
# this explicit priority order: the persistent list-header action wins over
# the empty-state action when both are mounted. A card token is required so a
# same-name button elsewhere in the page can never qualify.
_DEFAULT_CREATE_ENTRY_CONTEXTS = (
    "post-list-header",
    "none-post",
)
_DEFAULT_POST_CARD_CONTEXTS = (
    "post-list",
    "finder-card",
)


def _normalized_url_path(value: Any) -> str:
    """Return the path of an absolute URL or a leading-slash path, else ''."""
    text = str(value or "").strip()
    if not text or ("://" not in text and not text.startswith("/")):
        return ""
    try:
        parsed = urlparse(text)
    except Exception:
        return ""
    path = parsed.path or ("" if "://" in text else text)
    if not path:
        return ""
    path = re.sub(r"/+", "/", path).rstrip("/")
    return path or "/"


def _creator_entry_navigation_target(
    item: dict[str, Any], target_paths: list[str],
) -> dict[str, str] | None:
    """Prove a button is the creator entry from its structural navigation target.

    Only URL-bearing attributes (the element's own href / an ancestor anchor's
    href / data-* or aria-* values that carry a URL or path) can prove this.
    Class names, coordinates, DOM order and array index are deliberately not
    consulted: they cannot prove what the control does.
    """
    values: list[Any] = []
    own_href = item.get("href")
    if own_href:
        values.append(own_href)
    url_attribute_tokens = ("href", "url", "route", "target", "link", "path")

    def collect_url_values(attributes: dict[str, Any]) -> None:
        for key, value in attributes.items():
            lowered = str(key).casefold()
            if any(token in lowered for token in url_attribute_tokens):
                values.append(value)
            elif _normalized_url_path(value):
                # A data-*/aria-* value that is itself a URL/path also proves
                # the navigation target, regardless of the attribute name.
                values.append(value)

    collect_url_values(item.get("attributes") or {})
    for ancestor in item.get("ancestors") or []:
        ancestor_href = ancestor.get("href")
        if ancestor_href:
            values.append(ancestor_href)
        collect_url_values(ancestor.get("attributes") or {})

    targets = [
        path for path in (_normalized_url_path(target) for target in target_paths)
        if path
    ]
    for value in values:
        path = _normalized_url_path(value)
        if not path:
            continue
        for target in targets:
            if (
                path == target
                or path.endswith("/" + target.lstrip("/"))
                or path.startswith(target + "/")
            ):
                return {
                    "navigation_target": str(value)[:200],
                    "matched_route": target,
                }
    return None


def _creator_entry_structural_context(
    item: dict[str, Any],
    entry_contexts: list[str],
    card_contexts: list[str],
) -> dict[str, Any] | None:
    """Prove a same-name button is the create action from its ancestor structure.

    The rule is built only from ancestor class tokens observed in the real
    production DOM. A candidate must first prove it lives inside the post-card
    content list, then match one of the configured create-entry contexts. The
    context priority (its index in ``entry_contexts``) is used solely to pick a
    single winner when two proven creation entries are mounted at once; it is
    never used by itself to click a button. Geometry, DOM order and array index
    remain unused. Returns ``None`` when the structure does not prove the role.
    """
    ancestors = item.get("ancestors") or []
    tokens: set[str] = set()
    for ancestor in ancestors:
        if not isinstance(ancestor, dict):
            continue
        class_name = str(ancestor.get("class_name") or "")
        tokens.update(token for token in class_name.split() if token)
    if not any(token in tokens for token in card_contexts):
        return None
    for rank, context in enumerate(entry_contexts):
        if context and context in tokens:
            return {"context": context, "rank": rank}
    return None


def _creator_candidate_identity(item: dict[str, Any]) -> tuple[Any, ...]:
    """Identity used only to de-duplicate repeated scans of the SAME node.

    The structural signature is combined with the element's rect so that two
    genuinely distinct buttons (even with identical markup) are kept apart,
    while the same button re-observed through another CDP page/frame revisit
    collapses to one candidate. Geometry is never used to pick a winner.
    """
    structure = {
        "tag": str(item.get("tag") or ""),
        "text": str(item.get("text") or ""),
        "attributes": item.get("attributes") or {},
        "href": str(item.get("href") or ""),
        "ancestors": item.get("ancestors") or [],
    }
    try:
        payload = json.dumps(structure, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    except Exception:
        digest = hashlib.sha256(repr(structure).encode("utf-8", "replace")).hexdigest()[:20]
    rect = item.get("rect") or {}
    return (digest, rect.get("x"), rect.get("y"), rect.get("w"), rect.get("h"))


def _target_frame_observations(page: Any, frame_path: str, limit: int = 24) -> list[dict[str, Any]]:
    """Capture sanitized, structure-rich observations for every target frame."""
    observations: list[dict[str, Any]] = []
    for frame in _frame_contexts(page):
        parsed = urlparse(str(getattr(frame, "url", "")))
        if (
            parsed.hostname != _CHANNELS_HOST
            or parsed.path.rstrip("/") != frame_path.rstrip("/")
        ):
            continue
        try:
            inventory = frame.evaluate(
                _DOM_VISIBLE_ELEMENT_SCAN,
                {
                    "selector": "button, [role='button']",
                    "limit": limit,
                    "include_observed": True,
                },
            )
            ready_state = frame.evaluate("() => document.readyState")
            observations.append({
                "frame_url": str(getattr(frame, "url", "")),
                "ready_state": str(ready_state or ""),
                "visible_button_count": int(
                    inventory.get("match_count", 0)
                ) if isinstance(inventory, dict) else None,
                "visible_buttons": (
                    inventory.get("observed_items", [])[:limit]
                    if isinstance(inventory, dict) else []
                ),
            })
        except Exception as exc:
            observations.append({
                "frame_url": str(getattr(frame, "url", "")),
                "diagnostic_error": f"{type(exc).__name__}: {str(exc)[:180]}",
            })
    return observations


def _collect_creator_entry_candidates(
    page: Any,
    frame_path: str,
    button_text: str,
    target_paths: list[str],
    entry_contexts: list[str],
    card_contexts: list[str],
    limit: int,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """Scan only the target frame and return de-duplicated structural candidates."""
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    duplicates_removed = 0
    scan_errors: list[str] = []
    payload = {
        "selector": "button, [role='button']",
        "exact_text": button_text,
        "contains_text": None,
        "limit": int(limit),
        "include_observed": False,
    }
    for frame in _frame_contexts(page):
        parsed = urlparse(str(getattr(frame, "url", "")))
        if (
            parsed.hostname != _CHANNELS_HOST
            or parsed.path.rstrip("/") != frame_path.rstrip("/")
        ):
            continue
        frame_url = str(getattr(frame, "url", ""))
        try:
            inventory = frame.evaluate(_DOM_VISIBLE_ELEMENT_SCAN, payload)
        except Exception as exc:
            scan_errors.append(f"{type(exc).__name__}: {str(exc)[:180]}")
            continue
        if not isinstance(inventory, dict) or not isinstance(inventory.get("items"), list):
            scan_errors.append("invalid same-frame DOM scan result")
            continue
        match_count = int(inventory.get("match_count") or 0)
        if match_count > limit:
            raise UploadBlockedError(
                f"Too many visible exact '{button_text}' buttons ({match_count}) in "
                f"frame {frame_path}; refusing an ambiguous action."
            )
        for item in inventory["items"]:
            if not isinstance(item, dict):
                continue
            identity = _creator_candidate_identity(item)
            if identity in seen:
                duplicates_removed += 1
                continue
            seen.add(identity)
            handle_payload = dict(payload)
            handle_payload["visible_index"] = int(item.get("visible_index", -1))
            try:
                handle = frame.evaluate_handle(_DOM_VISIBLE_ELEMENT_HANDLE, handle_payload)
                element = handle.as_element()
                if element is None or not element.is_visible():
                    raise ValueError("the candidate changed or became invisible")
            except Exception as exc:
                scan_errors.append(
                    f"Could not bind candidate in {frame_url[:180]}: "
                    f"{type(exc).__name__}: {str(exc)[:160]}"
                )
                continue
            navigation = _creator_entry_navigation_target(item, target_paths)
            structural = _creator_entry_structural_context(
                item, entry_contexts, card_contexts
            )
            candidates.append({
                "handle": element,
                "metadata": item,
                "navigation_target": navigation["navigation_target"] if navigation else None,
                "matched_route": navigation["matched_route"] if navigation else None,
                "entry_context": structural["context"] if structural else None,
                "entry_context_rank": structural["rank"] if structural else None,
                "enabled": bool(element.is_enabled()),
            })
    return candidates, scan_errors, duplicates_removed


def _sanitized_creator_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip ElementHandles from candidate records for JSON-safe diagnostics."""
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        metadata = candidate["metadata"]
        result.append({
            "tag": str(metadata.get("tag") or ""),
            "text": str(metadata.get("text") or ""),
            "aria_label": str(metadata.get("aria_label") or ""),
            "disabled": bool(metadata.get("disabled")),
            "enabled": bool(candidate["enabled"]),
            "rect": metadata.get("rect") or {},
            "attributes": metadata.get("attributes") or {},
            "outer_html": str(metadata.get("outer_html") or ""),
            "href": str(metadata.get("href") or ""),
            "ancestors": metadata.get("ancestors") or [],
            "navigation_target": candidate["navigation_target"],
            "matched_route": candidate["matched_route"],
            "entry_context": candidate.get("entry_context"),
            "entry_context_rank": candidate.get("entry_context_rank"),
        })
    return result


def _creator_entry_diagnostics(
    *,
    button_text: str,
    frame_path: str,
    target_paths: list[str],
    entry_contexts: list[str],
    card_contexts: list[str],
    candidates: list[dict[str, Any]],
    duplicates_removed: int,
    frame_count: int,
    frame_urls: list[str],
    frame_observations: list[dict[str, Any]],
    scan_errors: list[str],
) -> dict[str, Any]:
    return {
        "expected_button_label": button_text,
        "expected_frame_path": frame_path,
        "expected_navigation_targets": list(target_paths),
        "expected_entry_contexts": list(entry_contexts),
        "expected_card_contexts": list(card_contexts),
        "matching_frame_count": frame_count,
        "unique_candidate_count": len(candidates),
        "qualifying_candidate_count": sum(
            1 for item in candidates if item["navigation_target"] or item.get("entry_context")
        ),
        "duplicate_scan_records_removed": duplicates_removed,
        "creator_entry_candidates": _sanitized_creator_candidates(candidates),
        "current_frame_urls": frame_urls,
        "frame_observations": frame_observations,
        "scan_errors": scan_errors[-3:],
        "captured_at": _now(),
    }


def _wait_for_creator_form_frame(page: Any, selectors: dict[str, Any]):
    """Wait until the creation form frame actually mounts after the CTA click."""
    form_path = str(
        selectors.get("creator_form_frame_path") or _DEFAULT_CREATE_FORM_PATH
    )
    timeout_seconds = max(
        0.0, float(selectors.get("creator_form_ready_timeout_seconds", 15))
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        for frame in _frame_contexts(page):
            parsed = urlparse(str(getattr(frame, "url", "")))
            if (
                parsed.hostname == _CHANNELS_HOST
                and parsed.path.rstrip("/") == form_path.rstrip("/")
            ):
                return frame
        if time.monotonic() >= deadline:
            frame_urls = [
                str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
            ]
            raise UploadBlockedError(
                f"The creator form frame {form_path} did not mount after activating "
                "the creator entry. No video was selected or uploaded; no save or "
                "publication action was taken.",
                diagnostics={
                    "expected_creator_form_frame_path": form_path,
                    "current_frame_urls": frame_urls,
                    "captured_at": _now(),
                },
            )
        page.wait_for_timeout(400)


def _open_create_view(
    page: Any,
    config: dict[str, Any],
    selectors: dict[str, Any],
) -> None:
    """Mount the creator SPA through a structurally-proven post-card entry.

    Same-name buttons in post-card.html are not distinguishable by text, index,
    DOM order or coordinates. The entry is positively identified when its
    captured DOM structure either proves a navigation target to the creation
    route (own href, ancestor anchor href, or a URL-bearing data-*/aria-* value)
    or matches a configured create-entry ancestor context inside the post card
    (the real WeChat SPA uses JS click handlers with no URL attribute). Re-scans
    of the same node (multiple CDP pages / frame revisits) are
    de-duplicated by a structural signature plus geometry; geometry is used
    only for identity, never to choose a button. If exactly one unique, enabled,
    visible, navigation-proven entry remains, it is clicked once and the
    creator form frame is awaited. Otherwise the workflow fails closed with
    full candidate/ancestor diagnostics. Locator APIs are avoided: they have
    returned zero nodes for this cross-origin iframe over CDP.
    """
    platform_url = str(
        config.get("platform_url") or "https://channels.weixin.qq.com/platform"
    )
    parsed_platform = urlparse(platform_url)
    if (
        parsed_platform.scheme != "https"
        or parsed_platform.hostname != _CHANNELS_HOST
        or parsed_platform.path.rstrip("/") != "/platform"
        or parsed_platform.query
        or parsed_platform.fragment
    ):
        raise UploadBlockedError(
            "platform_url must be the exact official Channels /platform shell URL."
        )

    page.goto(platform_url, wait_until="domcontentloaded", timeout=60_000)
    settle_ms = max(0, int(config.get("ui_settle_ms", 750)))
    if settle_ms:
        page.wait_for_timeout(settle_ms)
    _ensure_account_identity(
        page,
        str(config["account_name"]),
        selectors,
        wait_seconds=max(1, int(config.get("ui_ready_timeout_seconds", 15))),
    )

    frame_path = str(
        selectors.get("create_nav_frame_path")
        or "/micro/content/iframe/post-card.html"
    )
    button_text = str(selectors.get("create_nav_button_text") or "发表视频").strip()
    if not button_text:
        raise UploadBlockedError("The creator-entry button text is not configured.")

    configured_targets = selectors.get("create_nav_target_paths")
    if not configured_targets:
        target_paths = list(_DEFAULT_CREATE_NAV_TARGETS)
    elif isinstance(configured_targets, str):
        target_paths = [configured_targets]
    else:
        target_paths = [str(item) for item in configured_targets if str(item).strip()]

    def _configured_contexts(key: str, defaults: tuple[str, ...]) -> list[str]:
        configured = selectors.get(key)
        if not configured:
            return list(defaults)
        if isinstance(configured, str):
            configured = [configured]
        return [str(item).strip() for item in configured if str(item).strip()]

    entry_contexts = _configured_contexts(
        "create_nav_entry_contexts", _DEFAULT_CREATE_ENTRY_CONTEXTS
    )
    card_contexts = _configured_contexts(
        "create_nav_card_contexts", _DEFAULT_POST_CARD_CONTEXTS
    )

    timeout_seconds = max(
        0.0, float(selectors.get("create_nav_timeout_seconds", 15))
    )
    deadline = time.monotonic() + timeout_seconds
    last_scan_errors: list[str] = []

    def failure_diagnostics(candidates, duplicates_removed, frame_count, frame_urls):
        return _creator_entry_diagnostics(
            button_text=button_text,
            frame_path=frame_path,
            target_paths=target_paths,
            entry_contexts=entry_contexts,
            card_contexts=card_contexts,
            candidates=candidates,
            duplicates_removed=duplicates_removed,
            frame_count=frame_count,
            frame_urls=frame_urls,
            frame_observations=_target_frame_observations(page, frame_path),
            scan_errors=last_scan_errors,
        )

    while True:
        candidates, scan_errors, duplicates_removed = _collect_creator_entry_candidates(
            page,
            frame_path,
            button_text,
            target_paths,
            entry_contexts,
            card_contexts,
            limit=32,
        )
        last_scan_errors = (last_scan_errors + scan_errors)[-3:]
        qualifying = [
            item for item in candidates
            if item["navigation_target"] or item.get("entry_context")
        ]
        matching_frame_count = sum(
            1
            for frame in _frame_contexts(page)
            if urlparse(str(getattr(frame, "url", ""))).hostname == _CHANNELS_HOST
            and urlparse(str(getattr(frame, "url", ""))).path.rstrip("/")
            == frame_path.rstrip("/")
        )
        frame_urls = [
            str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
        ]

        # An explicit navigation target outranks a structural context. Two such
        # entries remain genuinely ambiguous and still fail closed.
        navigation_proven = [
            item for item in qualifying if item["navigation_target"]
        ]
        chosen = None
        if len(navigation_proven) > 1:
            raise UploadBlockedError(
                f"More than one visible exact '{button_text}' button in frame "
                f"{frame_path} proves a creator-entry navigation target; refusing "
                "an ambiguous click.",
                diagnostics=failure_diagnostics(
                    candidates, duplicates_removed, matching_frame_count, frame_urls
                ),
            )
        if navigation_proven:
            chosen = navigation_proven[0]
        elif len(qualifying) > 1:
            # Both buttons are proven creation entries (real SPA shape). The
            # configured context priority picks the single primary action; a
            # tie at the same priority stays ambiguous and fails closed.
            best_rank = min(
                int(item["entry_context_rank"])
                for item in qualifying
                if item.get("entry_context_rank") is not None
            )
            winners = [
                item for item in qualifying
                if item.get("entry_context_rank") == best_rank
            ]
            if len(winners) != 1:
                raise UploadBlockedError(
                    f"More than one visible exact '{button_text}' button in frame "
                    f"{frame_path} matches the same highest-priority create-entry "
                    "context; refusing an ambiguous click.",
                    diagnostics=failure_diagnostics(
                        candidates, duplicates_removed, matching_frame_count, frame_urls
                    ),
                )
            chosen = winners[0]
        elif len(qualifying) == 1:
            chosen = qualifying[0]

        if chosen is not None:
            if not chosen["enabled"]:
                raise UploadBlockedError(
                    f"The structurally-identified '{button_text}' creator entry in "
                    f"frame {frame_path} is disabled; refusing to click.",
                    diagnostics=failure_diagnostics(
                        candidates, duplicates_removed, matching_frame_count, frame_urls
                    ),
                )
            diagnostics = lambda: failure_diagnostics(
                candidates, duplicates_removed, matching_frame_count, frame_urls
            )
            try:
                # ElementHandle.click sends a real browser input action while
                # retaining the node resolved in the frame's own execution context.
                chosen["handle"].click(timeout=10_000)
            except Exception as exc:
                native_click_error = f"{type(exc).__name__}: {str(exc)[:400]}"
                # A real mouse click can be rejected for this button because it
                # sits off-viewport inside a cross-origin iframe. Before using
                # any other activation, prove the first click did not already
                # open the form so a second activation can never happen.
                form_path = str(
                    selectors.get("creator_form_frame_path") or _DEFAULT_CREATE_FORM_PATH
                )
                already_mounted = any(
                    urlparse(str(getattr(frame, "url", ""))).hostname == _CHANNELS_HOST
                    and urlparse(str(getattr(frame, "url", ""))).path.rstrip("/")
                    == form_path.rstrip("/")
                    for frame in _frame_contexts(page)
                )
                if already_mounted:
                    _wait_for_creator_form_frame(page, selectors)
                    return
                # One DOM click event on the same bound node is an equivalent
                # activation and does not depend on viewport geometry.
                try:
                    chosen["handle"].evaluate("(element) => element.click()")
                except Exception as dom_exc:
                    info = diagnostics()
                    info["native_click_error"] = native_click_error
                    info["dom_click_error"] = (
                        f"{type(dom_exc).__name__}: {str(dom_exc)[:400]}"
                    )
                    raise UploadBlockedError(
                        "The unique visible creator-entry button could not be activated.",
                        diagnostics=info,
                    ) from dom_exc
            _wait_for_creator_form_frame(page, selectors)
            return

        if time.monotonic() >= deadline:
            raise UploadBlockedError(
                f"Could not identify a unique, structurally-proven '{button_text}' "
                f"creator entry in frame {frame_path}. No same-name button proved a "
                "navigation target or a create-entry ancestor context; refusing an "
                f"ambiguous or guessed click. Unique same-name candidates: {len(candidates)}; "
                f"matching frames: {matching_frame_count}; current frame URLs: {frame_urls}. "
                "Sanitized target-frame button diagnostics were saved to the upload job. "
                "No video was selected or uploaded; no save or publication action was taken.",
                diagnostics=failure_diagnostics(
                    candidates, duplicates_removed, matching_frame_count, frame_urls
                ),
            )
        page.wait_for_timeout(400)

def _video_file_input(page: Any, selectors: dict[str, Any]):
    """Find the unique video-upload input across all live page frames.

    File inputs are commonly visually hidden and may omit an accept
    attribute. Inspect sanitized DOM metadata in each frame, prefer explicit
    video MIME/extensions or video-specific labels, and never fall back to an
    arbitrary input when multiple candidates remain.
    """
    selectors_list = selectors.get(
        "video_file_input",
        ["input[type='file'][accept*='video']", "input[type='file']"],
    )
    if not isinstance(selectors_list, list):
        selectors_list = [str(selectors_list)] if selectors_list else []
    selectors_list = [str(item) for item in selectors_list if str(item).strip()]
    timeout_seconds = max(
        0.0, float(selectors.get("video_file_input_timeout_seconds", 15))
    )
    deadline = time.monotonic() + timeout_seconds
    last_diagnostics: list[dict[str, Any]] = []

    scan_expression = r"""(preferredSelectors) => {
        /* __CHANNELS_VIDEO_FILE_INPUT_SCAN__ */
        const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const isVisible = (element) => {
            const rect = element.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
            for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (style.display === "none" || style.visibility === "hidden" ||
                    style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                    return false;
                }
            }
            return true;
        };
        return Array.from(document.querySelectorAll("input[type='file']")).map((element, index) => {
            const labels = Array.from(element.labels || []).map((label) =>
                normalize(label.innerText || label.textContent)
            ).filter(Boolean);
            const context = [];
            let node = element.parentElement;
            for (let depth = 0; node && depth < 4; depth += 1, node = node.parentElement) {
                const text = normalize(node.innerText || node.textContent);
                if (text && text.length <= 240 && !context.includes(text)) context.push(text);
            }
            const matchedSelectors = [];
            for (const selector of preferredSelectors) {
                try {
                    if (element.matches(selector)) matchedSelectors.push(selector);
                } catch (_) {}
            }
            return {
                index,
                accept: element.getAttribute("accept") || "",
                name: element.getAttribute("name") || "",
                id: element.id || "",
                class_name: typeof element.className === "string" ? element.className : "",
                aria_label: element.getAttribute("aria-label") || "",
                title: element.getAttribute("title") || "",
                data_testid: element.getAttribute("data-testid") || "",
                labels,
                context_text: context,
                visible: isVisible(element),
                matched_selectors: matchedSelectors
            };
        });
    }"""

    def candidate_score(item: dict[str, Any]) -> tuple[int, str] | None:
        accept = str(item.get("accept") or "").casefold()
        identity = " ".join(
            str(item.get(key) or "")
            for key in ("name", "id", "class_name", "aria_label", "title", "data_testid")
        ).casefold()
        labels = " ".join(str(value) for value in item.get("labels", [])).casefold()
        contexts = [str(value) for value in item.get("context_text", [])]
        context = " ".join(contexts[:2]).casefold()
        video_terms = (
            "视频", "video", "mp4", "quicktime", "m4v", "webm", "mpeg",
            ".avi", ".mov", ".mkv", ".wmv", ".flv", ".3gp",
        )
        image_terms = ("image/", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
        accept_is_video = any(term in accept for term in video_terms)
        accept_is_image_only = (
            any(term in accept for term in image_terms) and not accept_is_video
        )
        if accept_is_image_only:
            return None
        if accept_is_video:
            return 100, "video_accept"
        configured_specific_match = any(
            str(selector).strip() not in {"input[type='file']", "input[type='file'][accept*='video']"}
            for selector in item.get("matched_selectors", [])
        )
        if configured_specific_match:
            return 95, "configured_specific_selector"
        if any(term in identity for term in video_terms):
            return 90, "video_identity_attribute"
        if any(term in labels for term in ("视频", "video")):
            return 85, "video_label"
        if any(term in context for term in ("视频", "video")):
            return 75, "video_container_context"
        if not accept:
            return 10, "single_or_remaining_untyped_file_input"
        return 5, "generic_file_accept"

    while True:
        candidates: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        for frame in _frame_contexts(page):
            raw_frame_url = str(getattr(frame, "url", ""))
            parsed_frame_url = urlparse(raw_frame_url)
            frame_url = (
                f"{parsed_frame_url.scheme}://{parsed_frame_url.netloc}{parsed_frame_url.path}"
                if parsed_frame_url.scheme and parsed_frame_url.netloc
                else raw_frame_url[:240]
            )
            try:
                raw_items = frame.evaluate(scan_expression, selectors_list)
                if not isinstance(raw_items, list):
                    raise ValueError("DOM scan did not return a list.")
                diagnostics.append({
                    "frame_url": frame_url,
                    "file_input_count": len(raw_items),
                    "scan_error": None,
                })
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    scored = candidate_score(raw)
                    if scored is None:
                        continue
                    score, reason = scored
                    candidates.append({
                        "frame": frame,
                        "frame_url": frame_url,
                        "index": int(raw.get("index", -1)),
                        "score": score,
                        "reason": reason,
                        "metadata": raw,
                    })
            except Exception as exc:
                diagnostics.append({
                    "frame_url": frame_url,
                    "file_input_count": None,
                    "scan_error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })

        last_diagnostics = diagnostics
        # A single candidate is not sufficient evidence if another
        # frame could not be inspected: that frame may contain a competing
        # file control. Retry while the creator UI settles, then fail closed.
        all_frames_scanned = all(item.get("scan_error") is None for item in diagnostics)
        if candidates and all_frames_scanned:
            highest = max(item["score"] for item in candidates)
            best = [item for item in candidates if item["score"] == highest]
            if len(best) == 1:
                selected = best[0]
                frame = selected["frame"]
                index = selected["index"]
                try:
                    if index < 0:
                        raise UploadBlockedError(
                            "The selected video file input has an invalid DOM index."
                        )
                    # Bind the inspected node in its own frame execution
                    # context. This avoids the observed CDP issue where
                    # cross-origin iframe locators report zero nodes even
                    # though querySelectorAll inside that frame sees them.
                    handle = frame.evaluate_handle(
                        "(index) => document.querySelectorAll(\"input[type='file']\")[index] || null",
                        index,
                    )
                    candidate = handle.as_element()
                    if candidate is None:
                        raise UploadBlockedError(
                            "The selected video file input changed after DOM inspection."
                        )
                    attribute_pairs = (
                        ("accept", "accept"),
                        ("name", "name"),
                        ("id", "id"),
                        ("class_name", "class"),
                        ("aria_label", "aria-label"),
                        ("title", "title"),
                        ("data_testid", "data-testid"),
                    )
                    for metadata_key, attribute_name in attribute_pairs:
                        current_value = str(candidate.get_attribute(attribute_name) or "")
                        expected_value = str(
                            selected["metadata"].get(metadata_key) or ""
                        )
                        if current_value != expected_value:
                            raise UploadBlockedError(
                                "The video file input changed after DOM inspection; refusing to upload."
                            )
                    return candidate
                except UploadBlockedError:
                    raise
                except Exception as exc:
                    raise UploadBlockedError(
                        "The unique video file input was identified in the DOM but could not be "
                        f"bound to a DOM element handle ({type(exc).__name__})."
                    ) from exc

        if time.monotonic() >= deadline:
            summaries = []
            for item in candidates:
                metadata = item["metadata"]
                summaries.append({
                    "frame_url": item["frame_url"],
                    "index": item["index"],
                    "accept": str(metadata.get("accept") or "")[:100],
                    "name": str(metadata.get("name") or "")[:80],
                    "id": str(metadata.get("id") or "")[:80],
                    "aria_label": str(metadata.get("aria_label") or "")[:80],
                    "labels": [str(value)[:80] for value in metadata.get("labels", [])[:3]],
                    "reason": item["reason"],
                    "score": item["score"],
                })
            raise UploadBlockedError(
                "Could not identify exactly one unambiguous video upload input across the page frames. "
                f"Candidate summary: {summaries}; frame scan summary: {last_diagnostics}. "
                "No video file was selected or uploaded."
            )

        page.wait_for_timeout(500)


def _fill_field(page: Any, selectors: dict[str, Any], key: str, value: str) -> None:
    handle = _visible_element_handle(page, selectors.get(key, []))
    if handle is None:
        raise UploadBlockedError(
            f"Could not locate the {key} field in any page frame using config/selectors.yaml; "
            "no save action was taken."
        )
    try:
        handle.fill(value, timeout=10_000)
    except Exception as exc:
        raise UploadBlockedError(
            f"The {key} field was found in its frame DOM but could not be filled: "
            f"{type(exc).__name__}: {str(exc)[:200]}."
        ) from exc
    # ElementHandle.input_value has a timeout, but ElementHandle.inner_text does
    # NOT (only Locator.inner_text does). Passing timeout there raises TypeError,
    # so use the correct signatures and fall back to a frame-local DOM read for
    # contenteditable surfaces that have no input value.
    actual: Any = None
    try:
        actual = handle.input_value(timeout=3_000)
    except Exception:
        try:
            actual = handle.inner_text()
        except Exception:
            try:
                actual = handle.evaluate(
                    "(element) => element.innerText || element.textContent || ''"
                )
            except Exception:
                actual = None
    if actual is None:
        raise UploadBlockedError(
            f"The {key} field was filled but its value could not be read back; "
            "no save action was taken."
        )
    if str(actual).strip() != value.strip():
        raise UploadBlockedError(f"The {key} field did not retain the exact supplied text.")

def _draft_save_button_with_info(page: Any, selectors: dict[str, Any]) -> dict[str, Any] | None:
    """Locate ONE draft-save button and return it with full DOM diagnostics.

    The same-frame DOM scan is used deliberately: this project has observed
    cross-origin CDP Locator queries returning zero nodes while querySelectorAll
    in that frame sees the live controls. The returned handle is freshly bound
    at call time, so callers must invoke this immediately before acting - do not
    cache the handle across file writes or long waits, because the creator SPA
    re-renders and invalidates previously bound nodes.
    """
    names = selectors.get("draft_save_button_text", ["存草稿", "保存草稿"])
    if not isinstance(names, list):
        names = [str(names)] if names else []
    names = [str(item).strip() for item in names if str(item).strip()]
    for name in names:
        matches: list[dict[str, Any]] = []
        for frame in _frame_contexts(page):
            frame_url = str(getattr(frame, "url", ""))[:240]
            payload = {
                "selector": "button, [role='button']",
                "exact_text": name,
                "contains_text": None,
                "limit": 32,
            }
            try:
                inventory = frame.evaluate(_DOM_VISIBLE_ELEMENT_SCAN, payload)
            except Exception:
                continue
            if not isinstance(inventory, dict) or not isinstance(inventory.get("items"), list):
                continue
            for item in inventory["items"]:
                if not isinstance(item, dict):
                    continue
                handle_payload = dict(payload)
                handle_payload["visible_index"] = int(item.get("visible_index", -1))
                try:
                    handle = frame.evaluate_handle(
                        _DOM_VISIBLE_ELEMENT_HANDLE, handle_payload
                    )
                    element = handle.as_element()
                    if element is None or not element.is_visible():
                        continue
                except Exception:
                    continue
                matches.append({
                    "handle": element,
                    "frame_url": frame_url,
                    "text": str(item.get("text") or ""),
                    "attributes": item.get("attributes") or {},
                    "outer_html": str(item.get("outer_html") or "")[:400],
                    "rect": item.get("rect") or {},
                    "disabled": bool(item.get("disabled")),
                    "enabled": bool(element.is_enabled()),
                })
        if len(matches) > 1:
            raise UploadBlockedError(
                f"More than one visible exact '{name}' draft-save button exists across "
                "the page frames; refusing an ambiguous save."
            )
        if len(matches) == 1:
            return matches[0]
    return None


def _draft_save_button(page: Any, selectors: dict[str, Any]):
    """Find one semantic draft-save button using same-frame DOM inspection."""
    target = _draft_save_button_with_info(page, selectors)
    return target["handle"] if target is not None else None


def _click_draft_save_once(
    page: Any,
    selectors: dict[str, Any],
    job: dict[str, Any],
    job_path: Path,
) -> None:
    """Rebind and click the save control exactly once, recording full evidence.

    There is deliberately NO secondary activation on failure (no second
    Playwright click, no DOM element.click(), no dispatchEvent, no coordinate
    click): a failed call may already have submitted the save, so any retry
    risks a duplicate request. A raised exception always leaves the job in
    UPLOAD_UNKNOWN for a single read-only reconciliation.
    """
    target = _draft_save_button_with_info(page, selectors)
    if target is None:
        raise UploadBlockedError(
            "No visible draft-save button was found; no save was attempted."
        )
    button = target["handle"]
    if not target["enabled"] or not button.is_enabled():
        raise UploadBlockedError(
            "The draft-save button is disabled; no save was attempted."
        )

    diagnostics: dict[str, Any] = {
        "control": "draft_save",
        "frame_url": target["frame_url"],
        "tag": "button",
        "text": target["text"],
        "class": str(target["attributes"].get("class") or ""),
        "attributes": target["attributes"],
        "outer_html_excerpt": target["outer_html"],
        "rect": target["rect"],
        "visible": True,
        "enabled": True,
        "page_url_before": str(getattr(page, "url", "")),
        "frame_urls_before": [
            str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
        ],
        "binding": "fresh_same_frame_element_handle",
    }
    job["save_button_diagnostics"] = diagnostics
    job["state"] = "SAVE_REQUESTED"
    job["save_requested_at"] = _now()
    job["save_click_attempted"] = True
    job["save_click_attempted_at"] = _now()
    # Kept for schema compatibility: number of recorded click ATTEMPTS, not a
    # server-side confirmation that the save request was received.
    job["save_click_count"] = 1
    _save_job(job_path, job)

    try:
        button.click(timeout=10_000)
    except Exception as exc:
        job["state"] = "UPLOAD_UNKNOWN"
        job["save_click_returned"] = False
        job["save_click_error_type"] = type(exc).__name__
        job["save_click_error_message"] = str(exc)[:1200]
        job["save_click_traceback"] = traceback.format_exc()[-6000:]
        job["save_page_url_after"] = str(getattr(page, "url", ""))
        job["save_frame_urls_after"] = [
            str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
        ]
        job["save_failed_at"] = _now()
        _save_job(job_path, job)
        raise UploadUnknownError(
            "The save-draft click raised an exception. The save may or may not have "
            "been submitted; exactly one read-only reconciliation is allowed. No "
            "secondary click, upload or save was performed."
        ) from exc

    job["save_click_returned"] = True
    job["save_click_returned_at"] = _now()
    job["save_page_url_after"] = str(getattr(page, "url", ""))
    job["save_frame_urls_after"] = [
        str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
    ]
    _save_job(job_path, job)

_SAVE_BUTTON_STATE_JS = r"""(element) => {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  return {
    text: String(element.innerText || '').replace(/\s+/g, ' ').trim(),
    className: String(element.className || ''),
    disabled: element.getAttribute('disabled'),
    ariaDisabled: element.getAttribute('aria-disabled'),
    rect: {
      x: Math.round(rect.left), y: Math.round(rect.top),
      w: Math.round(rect.width), h: Math.round(rect.height)
    },
    pointerEvents: style.pointerEvents,
    cursor: style.cursor,
    opacity: style.opacity,
    visibility: style.visibility,
    connected: element.isConnected
  };
}"""

_SAVE_BUTTON_HIT_JS = r"""(point) => {
  const hit = document.elementFromPoint(point.x, point.y);
  const button = hit && hit.closest ? hit.closest('button, [role=button]') : null;
  return {
    hitTag: hit ? hit.tagName.toLowerCase() : null,
    hitClass: hit ? String(hit.className || '').slice(0, 200) : null,
    buttonText: button ? String(button.innerText || '').replace(/\s+/g, ' ').trim() : null,
    buttonClass: button ? String(button.className || '') : null,
    buttonOuterHTML: button ? String(button.outerHTML || '').slice(0, 240) : null
  };
}"""


def _wait_for_stable_save_button(
    page: Any,
    selectors: dict[str, Any],
    *,
    stable_checks: int = 4,
    poll_ms: int = 250,
    timeout_seconds: float = 10.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-scan until the unique save button is stable across a quiet window."""
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    previous = None
    streak = 0
    last_target: dict[str, Any] | None = None
    last_state: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        target = _draft_save_button_with_info(page, selectors)
        if target is not None:
            try:
                state = target["handle"].evaluate(_SAVE_BUTTON_STATE_JS)
            except Exception:
                state = None
            if isinstance(state, dict) and state.get("connected"):
                rect = state.get("rect") or {}
                signature = (
                    str(state.get("text") or ""),
                    str(state.get("className") or ""),
                    str(state.get("disabled")),
                    str(state.get("ariaDisabled")),
                    rect.get("x"), rect.get("y"), rect.get("w"), rect.get("h"),
                )
                streak = streak + 1 if signature == previous else 1
                previous = signature
                last_target, last_state = target, state
                if streak >= max(2, int(stable_checks)):
                    return target, state
        else:
            streak = 0
            previous = None
        page.wait_for_timeout(max(0, int(poll_ms)))
    raise UploadBlockedError(
        "The unique draft-save button never reached a stable state; no click was attempted."
    )


def _verify_browser_mouse_target(
    page: Any,
    target: dict[str, Any],
    selectors: dict[str, Any],
) -> dict[str, Any]:
    """Prove the computed main-viewport point really lands on the save button."""
    form_path = str(
        selectors.get("creator_form_frame_path") or _DEFAULT_CREATE_FORM_PATH
    )
    frame = next(
        (
            item for item in _frame_contexts(page)
            if urlparse(str(getattr(item, "url", ""))).path.rstrip("/")
            == form_path.rstrip("/")
        ),
        None,
    )
    if frame is None:
        raise UploadBlockedError("The creator form frame is gone; refusing to click.")

    button = target["handle"]
    # Playwright's bounding_box() is already relative to the MAIN frame viewport
    # and accounts for nested iframes and CSS scaling.
    box = button.bounding_box()
    if not isinstance(box, dict) or not box or float(box.get("width") or 0) <= 0 or float(box.get("height") or 0) <= 0:
        raise UploadBlockedError("The save button has no usable viewport bounding box.")
    center_x = float(box["x"]) + float(box["width"]) / 2.0
    center_y = float(box["y"]) + float(box["height"]) / 2.0
    viewport = page.evaluate("() => ({w: innerWidth, h: innerHeight})")
    if not isinstance(viewport, dict):
        raise UploadBlockedError("Could not read the main viewport size.")
    if not (0 <= center_x <= float(viewport.get("w") or 0) and 0 <= center_y <= float(viewport.get("h") or 0)):
        raise UploadBlockedError(
            f"The save button center ({center_x:.1f}, {center_y:.1f}) is outside the main viewport."
        )

    # Verify the same point inside the creator frame hits the SAME button.
    frame_rect = button.evaluate(
        "(el) => { const r = el.getBoundingClientRect(); "
        "return {x: r.left, y: r.top, w: r.width, h: r.height}; }"
    )
    frame_point = {
        "x": float(frame_rect["x"]) + float(frame_rect["w"]) / 2.0,
        "y": float(frame_rect["y"]) + float(frame_rect["h"]) / 2.0,
    }
    hit = frame.evaluate(_SAVE_BUTTON_HIT_JS, frame_point)
    if not isinstance(hit, dict):
        raise UploadBlockedError("The frame hit-test returned no result.")
    hit_text = str(hit.get("buttonText") or "")
    save_texts = [str(item).strip() for item in selectors.get("draft_save_button_text", ["存草稿", "保存草稿"])]
    if hit_text not in save_texts:
        raise UploadBlockedError(
            f"The viewport point does not hit the draft-save button (hit button text {hit_text!r})."
        )
    if any(token in hit_text for token in ("发表", "发布", "群发", "定时")):
        raise UploadBlockedError("The viewport point targets a publication control; refusing.")
    return {
        "x": center_x,
        "y": center_y,
        "viewport": viewport,
        "bounding_box": box,
        "frame_rect": frame_rect,
        "frame_point": frame_point,
        "hit_test": hit,
        "frame_url": str(getattr(frame, "url", "")),
    }


def _click_draft_save_by_browser_mouse_once(
    page: Any,
    selectors: dict[str, Any],
    job: dict[str, Any],
    job_path: Path,
) -> None:
    """Click the unique save button ONCE with real browser mouse input.

    Playwright's ``page.mouse.click`` dispatches a trusted browser input event,
    matching the human click that was proven to save successfully. It does not
    depend on an ElementHandle surviving Playwright's actionability/scroll
    phase, which is exactly what invalidated ``ElementHandle.click``. There is
    no fallback of any kind after this single call.
    """
    # Bring the button into view with a read-only DOM scroll. This is NOT a
    # click and cannot submit the form. The auto-scroll previously performed
    # inside ElementHandle.click was the window in which the SPA replaced the
    # node; doing it explicitly first lets the following quiet-window re-scan
    # bind the final, stable node.
    initial = _draft_save_button_with_info(page, selectors)
    if initial is None:
        raise UploadBlockedError("No visible draft-save button was found; no save was attempted.")
    try:
        initial["handle"].evaluate(
            "(element) => element.scrollIntoView({block: 'center', inline: 'center'})"
        )
    except Exception as exc:
        raise UploadBlockedError(
            f"The save button could not be scrolled into view ({type(exc).__name__}); no click was attempted."
        ) from exc
    page.wait_for_timeout(400)

    target, state = _wait_for_stable_save_button(page, selectors)
    if not target["enabled"] or not target["handle"].is_enabled():
        raise UploadBlockedError("The draft-save button is not enabled; no click was attempted.")
    class_name = str(state.get("className") or "")
    if (
        state.get("disabled") is not None
        or str(state.get("ariaDisabled") or "").lower() == "true"
        or "disabled" in class_name.lower()
        or str(state.get("pointerEvents") or "") == "none"
        or str(state.get("cursor") or "") == "not-allowed"
    ):
        raise UploadBlockedError(
            "The draft-save button is in a disabled-looking state; no click was attempted."
        )
    point = _verify_browser_mouse_target(page, target, selectors)

    form_path = str(
        selectors.get("creator_form_frame_path") or _DEFAULT_CREATE_FORM_PATH
    )
    if urlparse(str(target["frame_url"])).path.rstrip("/") != form_path.rstrip("/"):
        raise UploadBlockedError("The save button is not in the creator form frame.")

    diagnostics: dict[str, Any] = {
        "control": "draft_save",
        "method": "page_mouse_click_real_browser_input",
        "frame_url": target["frame_url"],
        "text": target["text"],
        "class": str(target["attributes"].get("class") or ""),
        "attributes": target["attributes"],
        "outer_html_excerpt": target["outer_html"],
        "state": state,
        "viewport_point": point,
        "page_url_before": str(getattr(page, "url", "")),
        "frame_urls_before": [
            str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
        ],
    }
    job["save_button_diagnostics"] = diagnostics
    job["state"] = "SAVE_REQUESTED"
    job["save_requested_at"] = _now()
    job["save_click_attempted"] = True
    job["save_click_attempted_at"] = _now()
    job["save_click_count"] = 1
    _save_job(job_path, job)

    try:
        page.mouse.click(point["x"], point["y"])
    except Exception as exc:
        job["state"] = "UPLOAD_UNKNOWN"
        job["save_click_returned"] = False
        job["save_click_error_type"] = type(exc).__name__
        job["save_click_error_message"] = str(exc)[:1200]
        job["save_click_traceback"] = traceback.format_exc()[-6000:]
        job["save_failed_at"] = _now()
        _save_job(job_path, job)
        raise UploadUnknownError(
            "The single browser-mouse save click raised an exception. The save may or "
            "may not have been submitted; only one read-only reconciliation is allowed."
        ) from exc

    job["save_click_returned"] = True
    job["save_click_returned_at"] = _now()
    job["save_page_url_after"] = str(getattr(page, "url", ""))
    job["save_frame_urls_after"] = [
        str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
    ]
    _save_job(job_path, job)


# Read-only monitor used by the human-takeover save checkpoint. The listeners
# only record; they never preventDefault/stopPropagation, never dispatch events,
# never click and never submit a form. This is derived from the real 2026-11-22
# session where a human mouse click produced five isTrusted events on the exact
# "保存草稿" button and a POST .../post/post_draft returned 201.
MANUAL_SAVE_MONITOR_JS = r"""() => {
  if (window.__CHANNELS_MANUAL_SAVE_MONITOR__) return 'already_installed';
  window.__CHANNELS_MANUAL_SAVE_EVENTS__ = [];
  window.__CHANNELS_MANUAL_SAVE_MUTATIONS__ = [];
  const summary = (el) => {
    if (!el || el.nodeType !== 1) return null;
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName.toLowerCase(),
      id: el.id || '',
      className: String(el.className || '').slice(0, 240),
      innerText: String(el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120),
      disabled: el.getAttribute('disabled'),
      ariaDisabled: el.getAttribute('aria-disabled'),
      rect: {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)},
      connected: el.isConnected
    };
  };
  const record = (e) => {
    const target = e.target;
    const nearest = target && target.closest ? target.closest('button, [role=button]') : null;
    let hit = null;
    try { hit = document.elementFromPoint(e.clientX, e.clientY); } catch (_) {}
    window.__CHANNELS_MANUAL_SAVE_EVENTS__.push({
      ts: new Date().toISOString(),
      type: e.type,
      isTrusted: e.isTrusted,
      target: summary(target),
      composedPath: (e.composedPath ? e.composedPath() : []).slice(0, 8).map(summary),
      nearestButton: summary(nearest),
      clientX: e.clientX,
      clientY: e.clientY,
      hitElement: summary(hit),
      href: location.href
    });
    if (window.__CHANNELS_MANUAL_SAVE_EVENTS__.length > 300) {
      window.__CHANNELS_MANUAL_SAVE_EVENTS__.shift();
    }
  };
  ['pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click'].forEach((type) => {
    document.addEventListener(type, record, true);
  });
  const observer = new MutationObserver((records) => {
    for (const change of records) {
      const nodes = [].concat(
        Array.from(change.addedNodes || []),
        Array.from(change.removedNodes || [])
      );
      const relevant = nodes.some((node) =>
        node.nodeType === 1 && String(node.innerText || '').indexOf('保存草稿') !== -1
      ) || (change.type === 'attributes' && change.target &&
            String(change.target.innerText || '').indexOf('保存草稿') !== -1);
      if (!relevant) continue;
      window.__CHANNELS_MANUAL_SAVE_MUTATIONS__.push({
        ts: new Date().toISOString(),
        type: change.type,
        attributeName: change.attributeName || null,
        target: summary(change.target),
        added: nodes.filter((node) => node.nodeType === 1).slice(0, 3).map(summary),
        removed: Array.from(change.removedNodes || [])
          .filter((node) => node.nodeType === 1).slice(0, 3).map(summary)
      });
      if (window.__CHANNELS_MANUAL_SAVE_MUTATIONS__.length > 300) {
        window.__CHANNELS_MANUAL_SAVE_MUTATIONS__.shift();
      }
    }
  });
  observer.observe(document, {
    subtree: true, childList: true, attributes: true, attributeOldValue: true
  });
  window.__CHANNELS_MANUAL_SAVE_OBSERVER__ = observer;
  window.__CHANNELS_MANUAL_SAVE_MONITOR__ = true;
  return 'installed';
}"""


def install_manual_save_monitor(page: Any, selectors: dict[str, Any]) -> dict[str, Any]:
    """Install read-only mouse/DOM monitors in the real creator frame.

    No click is performed here. The human operator is expected to click the
    save button in the visible browser while this monitor records the trusted
    event chain.
    """
    form_path = str(
        selectors.get("creator_form_frame_path") or _DEFAULT_CREATE_FORM_PATH
    )
    for frame in _frame_contexts(page):
        parsed = urlparse(str(getattr(frame, "url", "")))
        if (
            parsed.hostname != _CHANNELS_HOST
            or parsed.path.rstrip("/") != form_path.rstrip("/")
        ):
            continue
        result = frame.evaluate(MANUAL_SAVE_MONITOR_JS)
        return {
            "installed": True,
            "frame_url": str(getattr(frame, "url", "")),
            "result": str(result),
        }
    raise UploadBlockedError(
        f"The creator form frame {form_path} is not mounted; no monitor was installed."
    )


def read_manual_save_monitor(page: Any, selectors: dict[str, Any]) -> dict[str, Any]:
    """Read the bounded, read-only traces recorded by the manual-save monitor."""
    form_path = str(
        selectors.get("creator_form_frame_path") or _DEFAULT_CREATE_FORM_PATH
    )
    for frame in _frame_contexts(page):
        parsed = urlparse(str(getattr(frame, "url", "")))
        if (
            parsed.hostname != _CHANNELS_HOST
            or parsed.path.rstrip("/") != form_path.rstrip("/")
        ):
            continue
        events = frame.evaluate("() => window.__CHANNELS_MANUAL_SAVE_EVENTS__ || []")
        mutations = frame.evaluate(
            "() => window.__CHANNELS_MANUAL_SAVE_MUTATIONS__ || []"
        )
        return {
            "frame_url": str(getattr(frame, "url", "")),
            "events": events if isinstance(events, list) else [],
            "mutations": mutations if isinstance(mutations, list) else [],
        }
    raise UploadBlockedError(
        f"The creator form frame {form_path} is not mounted; no trace could be read."
    )


def summarize_manual_save_click(
    events: list[dict[str, Any]], mutations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize a human click from captured traces without inventing events."""
    trusted_clicks = [
        item for item in events
        if isinstance(item, dict)
        and item.get("type") == "click"
        and item.get("isTrusted") is True
    ]
    button_of = lambda item: (item or {}).get("nearestButton") or (item or {}).get("target") or {}
    target_texts = [str(button_of(item).get("innerText") or "") for item in trusted_clicks]
    hit_texts = [
        str(((item or {}).get("hitElement") or {}).get("innerText") or "")
        for item in trusted_clicks
    ]
    phases = ("pointerdown", "pointerup", "click")
    phase_nodes = {
        phase: [
            str(button_of(item).get("className") or "")
            for item in events
            if isinstance(item, dict) and item.get("type") == phase
        ]
        for phase in phases
    }
    same_node_across_phases = all(
        len(phase_nodes[phase]) == len(trusted_clicks)
        and (not trusted_clicks or phase_nodes[phase] == phase_nodes["click"])
        for phase in phases
    )
    return {
        "trusted_click_count": len(trusted_clicks),
        "target_buttons": target_texts,
        "hit_elements": hit_texts,
        "same_node_across_pointer_phases": same_node_across_phases,
        "mutation_count": len(mutations),
        "save_button_clicked": any("保存草稿" in text for text in target_texts),
    }


def _preview_ready(page: Any, selectors: dict[str, Any]) -> bool:
    """Check preview readiness inside each frame without Locator queries."""
    selector_list = selectors.get("preview_selectors", ["video"])
    if not isinstance(selector_list, list):
        selector_list = [selector_list] if selector_list else []
    expression = r"""(selector) => {
        const isVisible = (element) => {
            if (!element || element.hidden) return false;
            const rect = element.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
            for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (style.display === "none" || style.visibility === "hidden" ||
                    style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                    return false;
                }
            }
            return true;
        };
        let elements = [];
        try { elements = Array.from(document.querySelectorAll(String(selector || ""))); }
        catch (_) { return false; }
        return elements.some((element) => {
            if (!isVisible(element)) return false;
            if (element.tagName.toLowerCase() === "video") {
                return Boolean(element.currentSrc || element.src) && element.readyState >= 1;
            }
            return true;
        });
    }"""
    for frame in _frame_contexts(page):
        for selector in selector_list:
            try:
                if frame.evaluate(expression, str(selector)):
                    return True
            except Exception:
                continue
    return False


class _LocatorInputNotFound(Exception):
    """The legacy frame Locator lookup saw no video input; try the DOM path."""


def _video_file_input_locator(page: Any, selectors: dict[str, Any]):
    """Return the single video file input as an auto-rebinding Playwright Locator.

    This is the lookup that worked in the historically successful upload runs.
    Locators re-resolve their node on every action, unlike an ElementHandle that
    is bound once and can become detached when the SPA re-renders. Uniqueness is
    still enforced across every frame; an ambiguous result fails closed.
    """
    configured = selectors.get(
        "video_file_input",
        ["input[type='file'][accept*='video']", "input[type='file']"],
    )
    if not isinstance(configured, list):
        configured = [str(configured)] if configured else []
    configured = [str(item).strip() for item in configured if str(item).strip()]
    video_terms = ("video", "mp4")
    for selector in configured:
        candidates: list[Any] = []
        for frame in _frame_contexts(page):
            try:
                locator = frame.locator(selector)
                candidates.extend(
                    locator.nth(index)
                    for index in range(min(locator.count(), 8))
                )
            except Exception:
                continue
        video_inputs = [
            item for item in candidates
            if any(
                token in str(item.get_attribute("accept") or "").casefold()
                for token in video_terms
            )
        ]
        if len(video_inputs) > 1:
            raise UploadBlockedError(
                "More than one video file input is present across the page frames; "
                "refusing ambiguous selection."
            )
        if len(video_inputs) == 1:
            return video_inputs[0]
        if len(candidates) == 1:
            return candidates[0]
    raise _LocatorInputNotFound(
        "Could not identify exactly one video upload input with a stable Locator."
    )


def _set_video_file(
    page: Any,
    selectors: dict[str, Any],
    video_path: str,
    *,
    retries: int = 5,
    retry_delay_ms: int = 300,
) -> None:
    """Select the generated MP4 with the proven auto-rebinding Locator path.

    ElementHandles obtained by the DOM scan have repeatedly detached before
    ``set_input_files`` in this SPA, while Locators (the historically successful
    method) re-resolve the node at action time. The DOM-handle path is kept only
    as a fallback for environments where frame Locators return zero nodes.
    """
    try:
        locator = _video_file_input_locator(page, selectors)
        locator.set_input_files(video_path, timeout=30_000)
        return
    except UploadBlockedError:
        raise
    except Exception:
        # Fall through to the same-frame DOM handle path below.
        pass

    attempts = max(1, int(retries))
    last_detach_error: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            page.wait_for_timeout(max(0, int(retry_delay_ms)))
        video_input = _video_file_input(page, selectors)
        try:
            video_input.set_input_files(video_path, timeout=30_000)
            return
        except Exception as exc:
            if "detached" not in str(exc).casefold():
                raise
            last_detach_error = exc
    assert last_detach_error is not None
    raise UploadBlockedError(
        "The video file input became detached repeatedly and no file was selected. "
        "No upload was performed."
    ) from last_detach_error


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


_DRAFT_LIST_DOM_SCAN = r"""/* __CHANNELS_DRAFT_LIST_DOM_SCAN__ */ (config) => {
    const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
    const isVisible = (element) => {
        if (!element || element.hidden) return false;
        const rect = element.getBoundingClientRect();
        if (!rect || rect.width <= 0 || rect.height <= 0) return false;
        for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
            const style = window.getComputedStyle(node);
            if (style.display === "none" || style.visibility === "hidden" ||
                style.visibility === "collapse" || Number.parseFloat(style.opacity || "1") === 0) {
                return false;
            }
        }
        return true;
    };
    const query = (selector) => {
        try {
            return Array.from(document.querySelectorAll(String(selector || "")));
        } catch (_) {
            return [];
        }
    };
    const roots = query(config.root_selector);
    const activeTabs = query(config.active_tab_selector).filter(isVisible);
    const headers = query(config.header_selector).filter(isVisible);
    const containers = query(config.body_selector);
    const body = containers.length === 1 ? containers[0] : null;
    const rowTexts = body
        ? Array.from(body.children)
            .filter(isVisible)
            .map((child) => normalize(child.innerText || child.textContent || ""))
            .filter(Boolean)
        : [];
    return {
        root_count: roots.length,
        root_visible_count: roots.filter(isVisible).length,
        active_tab_texts: activeTabs.map((element) => normalize(element.innerText || element.textContent || "")),
        header_texts: headers.map((element) => normalize(element.innerText || element.textContent || "")),
        body_count: containers.length,
        body_visible: body ? isVisible(body) : false,
        body_child_count: body ? body.children.length : 0,
        row_texts: rowTexts
    };
}"""


def _draft_count(text: str) -> int | None:
    """Parse the count from the verified draft-list tab/header label."""
    match = re.search(r"草稿箱\s*[（(]\s*(\d+)\s*[）)]", str(text))
    return int(match.group(1)) if match else None


def _draft_list_dom_state(
    frame: Any,
    selectors: dict[str, Any],
) -> dict[str, Any] | None:
    """Read draft-manager evidence inside its own frame execution context.

    Playwright locators can return zero for live cross-origin iframe DOMs over
    CDP even while document.querySelectorAll() sees the nodes. Keep the read
    inside the target frame and return only the small, visible DOM evidence
    needed for view validation and row matching.
    """
    config = {
        "root_selector": str(selectors.get("draft_list_root_selector") or ""),
        "active_tab_selector": str(selectors.get("draft_list_active_tab_selector") or ""),
        "header_selector": str(selectors.get("draft_list_header_selector") or ""),
        "body_selector": str(selectors.get("draft_list_body_selector") or ""),
    }
    if not all(config.values()):
        return None
    try:
        result = frame.evaluate(_DRAFT_LIST_DOM_SCAN, config)
    except Exception:
        return None
    if not isinstance(result, dict):
        return None
    return result


def _draft_list_view_evidence(
    page: Any,
    selectors: dict[str, Any],
) -> dict[str, Any] | None:
    """Return strong DOM evidence that the dedicated DraftListManager view is active.

    The left navigation always contains the text '草稿箱', even on the normal
    video-management page. It is therefore not evidence of the current view.
    """
    page_path = str(selectors.get("draft_list_path") or "/platform/post/draftListManager")
    shell_path = str(selectors.get("draft_list_parent_shell_path") or "/platform")
    frame_path = str(
        selectors.get("draft_list_frame_path")
        or "/micro/content/post/draftListManager"
    )
    parsed_page = urlparse(str(getattr(page, "url", "")))
    if parsed_page.hostname != "channels.weixin.qq.com":
        return None
    normalized_page_path = parsed_page.path.rstrip("/") or "/"
    if normalized_page_path == page_path.rstrip("/"):
        page_route_mode = "direct_draft_route"
    elif normalized_page_path == shell_path.rstrip("/"):
        # Some Channels SPA/headless sessions retain the platform shell URL
        # while the dedicated draft manager is loaded in its own child frame.
        # This is only a route-shell allowance: all frame and DraftListManager
        # DOM checks below remain mandatory.
        page_route_mode = "platform_shell_with_verified_draft_frame"
    else:
        return None

    for frame in _frame_contexts(page):
        parsed_frame = urlparse(str(getattr(frame, "url", "")))
        if parsed_frame.hostname != "channels.weixin.qq.com":
            continue
        if parsed_frame.path.rstrip("/") != frame_path.rstrip("/"):
            continue
        state = _draft_list_dom_state(frame, selectors)
        if state is None:
            continue

        if state.get("root_count") != 1 or state.get("root_visible_count") != 1:
            continue
        if state.get("body_count") != 1:
            continue

        active_texts = [
            re.sub(r"\s+", " ", str(text)).strip()
            for text in state.get("active_tab_texts", [])
            if _draft_count(str(text)) is not None
        ]
        header_texts = [
            re.sub(r"\s+", " ", str(text)).strip()
            for text in state.get("header_texts", [])
            if _draft_count(str(text)) is not None
        ]
        active_counts = {
            count for count in (_draft_count(text) for text in active_texts)
            if count is not None
        }
        header_counts = {
            count for count in (_draft_count(text) for text in header_texts)
            if count is not None
        }
        if len(active_counts) != 1 or len(header_counts) != 1:
            continue
        if active_counts != header_counts or len(active_texts) != 1 or len(header_texts) != 1:
            continue

        return {
            "frame": frame,
            "page_path": parsed_page.path,
            "page_route_mode": page_route_mode,
            "frame_path": parsed_frame.path,
            "active_tab_text": active_texts[0],
            "header_text": header_texts[0],
            "draft_count": next(iter(active_counts)),
            "list_container_present": True,
            "list_container_visible": bool(state.get("body_visible")),
            "row_texts": [
                re.sub(r"\s+", " ", str(item)).strip()
                for item in state.get("row_texts", [])
                if str(item).strip()
            ],
            "row_child_count": int(state.get("body_child_count") or 0),
        }
    return None


def _wait_for_draft_list_view(
    page: Any,
    selectors: dict[str, Any],
) -> dict[str, Any]:
    """Wait for the exact draft manager route and its view-specific DOM signals."""
    timeout_seconds = max(0, int(selectors.get("draft_list_ready_timeout_seconds", 15)))
    deadline = time.monotonic() + timeout_seconds
    while True:
        evidence = _draft_list_view_evidence(page, selectors)
        if evidence is not None:
            return evidence
        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(500)

    frame_urls = [
        str(getattr(frame, "url", "")) for frame in _frame_contexts(page)
    ]
    raise UploadBlockedError(
        "The page could not be verified as the dedicated draft manager. "
        "Expected page path '/platform/post/draftListManager' or the exact "
        "platform shell '/platform' with child frame path "
        "'/micro/content/post/draftListManager', DraftListManager root, selected "
        "'草稿箱 (n)' tab/header, and the draft-list body container. "
        f"Current page URL: {getattr(page, 'url', '')}; frame URLs: {frame_urls}"
    )


def _click_draft_list_nav_entry(
    page: Any,
    selectors: dict[str, Any],
) -> None:
    """Open DraftListManager through the platform's own SPA navigation.

    Directly loading /platform/post/draftListManager can update the iframe URL
    without mounting the list application. The official platform exposes this
    view under the left-side Content Management menu, so navigate through that
    visible entry and still require the dedicated frame/DOM proof afterwards.
    """
    entry_selectors = [
        str(item)
        for item in selectors.get("draft_list_nav_entry_selectors", [])
        if str(item).strip()
    ]
    parent_selectors = [
        str(item)
        for item in selectors.get("draft_list_nav_parent_selectors", [])
        if str(item).strip()
    ]
    if not entry_selectors or not parent_selectors:
        raise UploadBlockedError(
            "Draft-list navigation selectors are missing from config/selectors.yaml."
        )

    entry_text = str(selectors.get("draft_list_nav_entry_text") or "草稿箱").strip()

    def visible_entry():
        for selector in entry_selectors:
            matches = _visible_element_handles(
                page, selector, limit=12, contains_text=entry_text
            )
            if len(matches) > 1:
                raise UploadBlockedError(
                    "More than one visible DraftListManager navigation entry exists; "
                    "refusing an ambiguous click."
                )
            if len(matches) == 1:
                return matches[0]
        return None

    def click_entry(entry: Any) -> None:
        try:
            entry.click(timeout=10_000)
        except Exception as exc:
            raise UploadBlockedError(
                "The visible DraftListManager navigation entry could not be clicked."
            ) from exc

    # The submenu may already be expanded (for example after a prior read).
    entry = visible_entry()
    if entry is not None:
        click_entry(entry)
        return

    timeout_seconds = max(
        0, int(selectors.get("draft_list_nav_timeout_seconds", 20))
    )
    deadline = time.monotonic() + timeout_seconds
    while True:
        found_parent = False
        for selector in parent_selectors:
            for parent in _visible_element_handles(page, selector, limit=12):
                found_parent = True
                try:
                    parent.hover(timeout=2_000)
                except Exception:
                    continue
                # The platform submenu is animated after its parent is hovered.
                page.wait_for_timeout(400)
                entry = visible_entry()
                if entry is not None:
                    click_entry(entry)
                    return

        if time.monotonic() >= deadline:
            break
        page.wait_for_timeout(400 if not found_parent else 250)

    raise UploadBlockedError(
        "Could not open the DraftListManager from the visible Content Management "
        "navigation. No upload or save action was attempted."
    )


def _open_draft_list_view(
    page: Any,
    config: dict[str, Any],
    selectors: dict[str, Any],
) -> None:
    """Navigate from the authenticated platform shell into DraftListManager."""
    platform_url = str(
        config.get("platform_url") or "https://channels.weixin.qq.com/platform"
    )
    parsed = urlparse(platform_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "channels.weixin.qq.com"
        or parsed.path.rstrip("/") != "/platform"
        or parsed.query
        or parsed.fragment
    ):
        raise UploadBlockedError(
            "platform_url must be the exact official Channels /platform shell URL."
        )

    page.goto(platform_url, wait_until="domcontentloaded", timeout=60_000)
    settle_ms = max(0, int(config.get("ui_settle_ms", 750)))
    if settle_ms:
        page.wait_for_timeout(settle_ms)
    _ensure_draft_list_account_identity(page, config, selectors)
    _click_draft_list_nav_entry(page, selectors)
    # URL changes alone are not accepted: the existing strict frame and DOM
    # evidence remains the only proof that the dedicated draft view is active.
    _wait_for_draft_list_view(page, selectors)


def _draft_snapshot(page: Any, selectors: dict[str, Any]) -> dict[str, Any]:
    """Read the actual draft list only after its dedicated view is positively identified."""
    evidence = _wait_for_draft_list_view(page, selectors)
    entries = list(evidence["row_texts"])
    if evidence["draft_count"] > 0 and not entries:
        timeout_seconds = max(
            0, int(selectors.get("draft_list_rows_timeout_seconds", 15))
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(500)
            refreshed = _draft_list_dom_state(evidence["frame"], selectors)
            if refreshed is None or refreshed.get("body_count") != 1:
                continue
            entries = [
                re.sub(r"\s+", " ", str(item)).strip()
                for item in refreshed.get("row_texts", [])
                if str(item).strip()
            ]
            if entries:
                evidence["list_container_visible"] = bool(
                    refreshed.get("body_visible")
                )
                evidence["row_child_count"] = int(
                    refreshed.get("body_child_count") or 0
                )
                break

        if not entries:
            raise UploadBlockedError(
                "The draft manager reports "
                f"{evidence['draft_count']} draft(s), but the confirmed draft-list body "
                "contains no readable rows after waiting. Refusing to treat an unreadable "
                "list as empty."
            )

    return {
        "captured_at": _now(),
        "url": page.url,
        "frame_urls": [str(getattr(item, "url", "")) for item in _frame_contexts(page)],
        "view_type": "draft_list",
        "view_verified": True,
        "view_evidence": {
            "page_path": evidence["page_path"],
            "page_route_mode": evidence["page_route_mode"],
            "frame_path": evidence["frame_path"],
            "active_tab_text": evidence["active_tab_text"],
            "header_text": evidence["header_text"],
            "list_container_present": evidence["list_container_present"],
            "list_container_visible": evidence["list_container_visible"],
        },
        "draft_count": evidence["draft_count"],
        "entries": entries,
    }


def _matching_draft_entries(
    snapshot: dict[str, Any],
    title: str,
    selectors: dict[str, Any],
) -> list[str]:
    """Match one row per title occurrence in the verified draft-list context."""
    verified_draft_view = (
        snapshot.get("view_type") == "draft_list"
        and snapshot.get("view_verified") is True
    )
    status_words = [str(x) for x in selectors.get("draft_status_texts", ["草稿"])]
    matches: list[str] = []
    for entry in snapshot.get("entries", []):
        text = str(entry)
        if title not in text:
            continue
        if verified_draft_view:
            # Membership in the independently verified DraftListManager is
            # itself draft-state evidence; row text need not repeat '草稿'.
            matches.append(text)
        elif any(status in text for status in status_words):
            matches.append(text)
    return matches

def _matching_new_draft_rows(
    snapshot: dict[str, Any],
    before_snapshot: dict[str, Any],
    title: str,
    description: str,
    selectors: dict[str, Any],
) -> list[str]:
    """Match the ONE newly created row using the joint evidence available.

    WeChat Channels renders the description (not the short title) as the draft
    list preview text. A title-only row match therefore rejects every real
    save. A row qualifies only when it is genuinely new relative to the
    pre-upload snapshot AND either the title or a distinctive normalized slice
    of the description appears in it, inside a verified DraftListManager.
    """
    if not (
        snapshot.get("view_type") == "draft_list"
        and snapshot.get("view_verified") is True
    ):
        return []
    before_entries = {str(item) for item in before_snapshot.get("entries", [])}
    normalize = lambda value: " ".join(str(value or "").split())
    description_signature = normalize(description)[:60]
    matched: list[str] = []
    for entry in snapshot.get("entries", []):
        text = str(entry)
        if text in before_entries:
            continue
        if title and title in text:
            matched.append(text)
            continue
        if description_signature and description_signature in normalize(text):
            matched.append(text)
    return list(dict.fromkeys(matched))


def _safe_failed_before_upload(job: dict[str, Any]) -> bool:
    """A failed job is retryable only when set_input_files was never entered."""
    return (
        str(job.get("state") or "") == "FAILED_BEFORE_SAVE"
        and not job.get("upload_started_at")
        and int(job.get("save_click_count") or 0) == 0
        and job.get("verified_draft") is None
    )


def _resolve_upload_job_identity(
    project_root: Path,
    config: dict[str, Any],
    source_run_id: str,
) -> tuple[str, int]:
    """Allocate an auditable upload-attempt ID without bypassing uncertain jobs.

    The first attempt keeps the historical job ID equal to the output directory.
    A later attempt may reuse the same QA-passed media only when every earlier
    attempt for that source run is explicitly FAILED_BEFORE_SAVE and proves that
    set_input_files was never entered and the save control was never clicked.
    Any UPLOADING/SAVE_REQUESTED/UPLOAD_UNKNOWN or other non-retryable state
    blocks the whole source run.
    """
    original_path = _job_path(project_root, config, source_run_id)
    if not original_path.exists():
        return source_run_id, 1

    original = _read_json(original_path)
    if not _safe_failed_before_upload(original):
        state = str(original.get("state") or "")
        if state in {"SAVE_REQUESTED", "UPLOAD_UNKNOWN", "UPLOADING", "PREPARED"}:
            raise UploadUnknownError(
                f"Source run {source_run_id} has an existing {state} job; "
                "reconcile it before any further upload attempt."
            )
        raise UploadBlockedError(
            f"Source run {source_run_id} already has a non-retryable upload job "
            f"({state}); refusing another attempt."
        )

    for attempt in range(2, 100):
        suffix = f".upload_attempt_{attempt:02d}"
        prefix = source_run_id[: max(1, 120 - len(suffix))]
        candidate_id = f"{prefix}{suffix}"
        candidate_path = _job_path(project_root, config, candidate_id)
        if not candidate_path.exists():
            return candidate_id, attempt

        previous = _read_json(candidate_path)
        if _safe_failed_before_upload(previous):
            continue

        state = str(previous.get("state") or "")
        if state in {"SAVE_REQUESTED", "UPLOAD_UNKNOWN", "UPLOADING", "PREPARED"}:
            raise UploadUnknownError(
                f"Upload attempt {candidate_id} is in state {state}; "
                "reconcile it before any further upload attempt."
            )
        raise UploadBlockedError(
            f"Upload attempt {candidate_id} is non-retryable ({state}); "
            "refusing to bypass its recorded state."
        )

    raise UploadBlockedError(
        f"Source run {source_run_id} has reached the maximum number of recorded upload attempts."
    )


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
    try:
        expected_metadata = build_channels_metadata_for_run_dir(
            card,
            script,
            run_dir,
            account_name=str(config["account_name"]),
            tags=list(config.get("default_tags", [])),
        )
    except ValueError as exc:
        raise UploadBlockedError(f"Fact Card-derived Channels metadata is invalid: {exc}") from exc
    if metadata_path.is_file():
        metadata = _read_json(metadata_path)
        if metadata != expected_metadata:
            raise UploadBlockedError(
                "channels_draft.json differs from the Fact Card-derived metadata for this run."
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

    # Literature-reading videos use their own source-excerpt and article-identity
    # contract. The unsupported WeChat extended-link feature is intentionally not
    # part of this path; the original account name is rendered in the final outro.
    manifest_path = run_dir / "article_summary_manifest.json"
    if manifest_path.is_file():
        manifest = _read_json(manifest_path)
        source_path = run_dir / "source_record.json"
        summary_path = run_dir / "summary.json"
        content_qa_path = run_dir / "content_qa_report.json"
        for path in (source_path, summary_path, content_qa_path):
            if not path.is_file():
                raise UploadBlockedError(
                    f"Literature upload package is incomplete; missing {path.name}."
                )
        source = _read_json(source_path)
        summary = _read_json(summary_path)
        content_qa = _read_json(content_qa_path)
        if manifest.get("content_type") != "article_summary":
            raise UploadBlockedError("Unrecognized article-summary manifest content_type.")
        if source.get("source_type") != "published_wechat_article":
            raise UploadBlockedError("Literature upload source_record is not a published WeChat article.")
        if str(manifest.get("article_id") or "") != str(source.get("article_id") or ""):
            raise UploadBlockedError("Article manifest and source record identify different articles.")
        if str(summary.get("article_id") or "") != str(source.get("article_id") or ""):
            raise UploadBlockedError("Article summary is not bound to the source article ID.")
        if (
            str(source.get("article_markdown_sha256") or "")
            != str(manifest.get("source_article_sha256") or "")
            or str(summary.get("source_article_sha256") or "")
            != str(manifest.get("source_article_sha256") or "")
        ):
            raise UploadBlockedError("Manifest, article source and summary hashes do not agree.")
        required_content_checks = {
            "source_article_sha256_matched": True,
            "all_claims_have_exact_source_excerpt": True,
            "all_claims_referenced": True,
            "all_visual_beats_have_narration": True,
            "outro_cta_rendered": True,
            "audio_timeline_validation": True,
            "scene_layout_qa": "PASS",
            "technical_qa": "PASS",
        }
        failed = [
            key for key, expected in required_content_checks.items()
            if content_qa.get(key) != expected
        ]
        if content_qa.get("upload_eligible") is not True or failed:
            raise UploadBlockedError(
                "Literature content QA is not eligible for draft upload; failed checks: "
                + (", ".join(failed) if failed else "upload_eligible is not true")
            )
        if qa.get("overall_status") != "PASS":
            raise UploadBlockedError("Literature video technical QA is not strict PASS.")
        try:
            expected_metadata = build_article_channels_metadata(
                source,
                summary,
                run_dir.name,
            )
        except ValueError as exc:
            raise UploadBlockedError(f"Article-derived Channels metadata is invalid: {exc}") from exc
        metadata_path = run_dir / "channels_draft.json"
        if not metadata_path.is_file():
            raise UploadBlockedError("Literature package is missing channels_draft.json.")
        metadata = _read_json(metadata_path)
        if metadata != expected_metadata:
            raise UploadBlockedError(
                "channels_draft.json differs from the deterministic source-article metadata."
            )
        validate_channels_metadata(
            metadata,
            min_title_chars=int(config.get("title_min_chars", 6)),
            max_title_chars=int(config.get("title_max_chars", 16)),
            max_description_chars=int(config.get("description_max_chars", 1000)),
        )
        if metadata.get("job_id") != run_dir.name:
            raise UploadBlockedError("Literature draft metadata job_id does not match its output directory.")
        if metadata.get("account_name") != config.get("account_name"):
            raise UploadBlockedError("Literature draft metadata account does not match configured target account.")
        return metadata, qa, {
            "approval_type": "standing_user_draft_only_authorization",
            "approved_by": None,
            "approved_at": None,
            "channels_title": None,
        }

    # Fact Card / science-popularization path retains the existing governed
    # Fact Card validation and metadata derivation.
    card_path = run_dir / "fact_card.json"
    source_path = run_dir / "source_record.json"
    script_path = run_dir / "script.json"
    for path in (card_path, source_path, script_path):
        if not path.is_file():
            raise UploadBlockedError(f"Science-popularization package is incomplete; missing {path.name}.")
    card = _read_json(card_path)
    source_doc = _read_json(source_path)
    script = _read_json(script_path)
    approval: dict[str, Any] = {
        "approval_type": "standing_user_draft_only_authorization",
        "approved_by": None,
        "approved_at": None,
        "channels_title": None,
    }
    try:
        topic_approval = verify_fact_card_approval(project_root, card_path, source_path)
    except TopicApprovalError:
        topic_approval = None
    if topic_approval is not None:
        approval["channels_title"] = topic_approval.get("channels_title")
    metadata_path = run_dir / "channels_draft.json"
    metadata_card = dict(card)
    if approval.get("channels_title") and not metadata_card.get("channels_title"):
        metadata_card["channels_title"] = approval["channels_title"]
    try:
        expected_metadata = build_channels_metadata_for_run_dir(
            metadata_card,
            script,
            run_dir,
            account_name=str(config["account_name"]),
            tags=list(config.get("default_tags", [])),
        )
    except ValueError as exc:
        raise UploadBlockedError(f"Fact Card-derived Channels metadata is invalid: {exc}") from exc
    if metadata_path.is_file():
        metadata = _read_json(metadata_path)
        if metadata != expected_metadata:
            raise UploadBlockedError(
                "channels_draft.json differs from the Fact Card-derived metadata. "
                "Do not upload edited copy; update channels_title or the source Fact Card, then regenerate the package."
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
    return _validate_existing_session(
        project_root, config, session_path, profile_dir,
        expected_headless=bool(config.get("headless", False)),
    )


def _finalize_draft_verification(
    job: dict[str, Any],
    job_path: Path,
    *,
    after: dict[str, Any] | None,
    verified: list[str],
    verification_history: list[Any],
    title: str,
) -> None:
    """Record the new draft row, but do not mark an article-linked job complete until link readback passes."""
    if len(verified) != 1:
        job["state"] = "UPLOAD_UNKNOWN"
        job["post_upload_snapshot"] = after
        observed_counts = [
            int(item["match_count"])
            for item in verification_history
            if isinstance(item, dict) and "match_count" in item
        ]
        job["verification_matches"] = observed_counts[-1] if observed_counts else 0
        job["verification_max_matches"] = max(observed_counts, default=0)
        _save_job(job_path, job)
        raise UploadUnknownError(
            "The draft save was clicked once, but the new unpublished draft could not be uniquely "
            "verified before the read-back timeout. No upload or save retry was attempted. "
            "Inspect the target account's 草稿箱 and use the manual-review command to record the result."
        )

    job["post_upload_snapshot"] = after
    job["verified_draft"] = {
        "title": title,
        "row_text": verified[0],
        "verified_at": _now(),
        "draft_list_url": after["url"] if after else None,
    }
    job["save_action"] = {
        "control": "draft_save",
        "click_count": int(job.get("save_click_count", 0)),
        "persistence_confirmation": "unique title match in DraftListManager",
        "mobile_app_visibility": "not_verified_by_desktop_browser",
    }
    job["automatic_publication"] = False

    link_check = job.get("extended_link_persistence") or {}
    if job.get("extended_link_required") is True and link_check.get("state") != "PERSISTED_AND_READ_BACK":
        job["state"] = "BLOCKED_LINK_NOT_PERSISTED"
        job["blocking_reason"] = (
            "The unpublished video draft row exists, but the required official-account article link "
            "has not been verified after reopening the draft editor."
        )
        job["extended_link_persistence"] = {
            **link_check,
            "readback_verified": False,
            "required_state": "PERSISTED_AND_READ_BACK",
        }
        _save_job(job_path, job)
        return

    job["state"] = "DRAFT_SAVED"
    _save_job(job_path, job)


def upload_run_to_channels(project_root: Path, run_dir: Path) -> dict[str, Any]:
    """Upload one strict-QA-passed video as an unpublished draft under standing user authorization."""
    project_root = project_root.resolve()
    run_dir = run_dir.resolve()
    config, selectors = _load_config(project_root)
    metadata, qa, approval = _validate_run_for_upload(project_root, run_dir, config)
    source_run_id = run_dir.name
    job_id, upload_attempt = _resolve_upload_job_identity(
        project_root, config, source_run_id
    )
    job_path = _job_path(project_root, config, job_id)

    job: dict[str, Any] = {
        "schema_version": 1,
        "job_id": job_id,
        "source_run_id": source_run_id,
        "upload_attempt": upload_attempt,
        "content_type": str(metadata.get("content_type") or "science_popularization"),
        "extended_link_required": metadata.get("extended_link_required") is True,
        "extended_link_persistence": (
            {
                "state": "NOT_ATTEMPTED",
                "readback_verified": False,
                "required_state": "PERSISTED_AND_READ_BACK",
            }
            if metadata.get("extended_link_required") is True
            else {"state": "NOT_REQUIRED", "readback_verified": True}
        ),
        "state": "CREATED",
        "title": metadata["title"],
        "description": metadata["description"],
        "video_path": str((run_dir / "final.mp4").resolve()),
        "video_sha256": _sha256(run_dir / "final.mp4"),
        "approval_type": approval["approval_type"],
        "approval_by": approval.get("approved_by"),
        "approval_at": approval.get("approved_at"),
        "authorization_basis": "standing_user_instruction_draft_only",
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
        _open_create_view(create_page, config, selectors)
        # A CTA click alone does not prove the creator form is mounted. Confirm
        # the actual video input before moving on to the draft-list baseline.
        video_input = _video_file_input(create_page, selectors)
        job["creator_form_ready_at"] = _now()
        job["creator_form_file_input_confirmed"] = True
        _save_job(job_path, job)

        draft_page = context.new_page()
        _open_draft_list_view(draft_page, config, selectors)
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

        # The upload page stays in the background; automated Edge is headless.
        job["state"] = "UPLOADING"
        job["upload_started_at"] = _now()
        _save_job(job_path, job)
        _set_video_file(
            create_page,
            selectors,
            str((run_dir / "final.mp4").resolve()),
        )

        _wait_upload_ready(
            create_page,
            selectors,
            timeout_seconds=int(config.get("upload_timeout_seconds", 1800)),
        )
        _fill_field(create_page, selectors, "title_input", str(metadata["title"]))
        _fill_field(create_page, selectors, "description_input", str(metadata["description"]))

        # Real browser mouse input on the verified viewport point. This is the
        # mechanism proven to produce an isTrusted click and a 201 save response
        # in the real 2026-11-22 session; ElementHandle.click was proven to fail
        # because the SPA replaces the node during Playwright's scroll phase.
        _click_draft_save_by_browser_mouse_once(create_page, selectors, job, job_path)

        job["draft_verification_started_at"] = _now()
        after, verified, verification_history, verification_elapsed = (
            _verify_new_draft_after_save(
                draft_page,
                config,
                selectors,
                title=str(metadata["title"]),
                description=str(metadata["description"]),
                before_snapshot=before,
            )
        )
        job["draft_verification"] = {
            "started_at": job["draft_verification_started_at"],
            "finished_at": _now(),
            "timeout_seconds": int(config.get("draft_verify_timeout_seconds", 90)),
            "poll_interval_seconds": float(
                config.get("draft_verify_poll_interval_seconds", 3)
            ),
            "elapsed_seconds": verification_elapsed,
            "navigation_count": 1,
            "samples": verification_history,
        }

        _finalize_draft_verification(
            job,
            job_path,
            after=after,
            verified=verified,
            verification_history=verification_history,
            title=str(metadata["title"]),
        )
        return {
            "state": job["state"],
            "job_id": job_id,
            "source_run_id": source_run_id,
            "upload_attempt": upload_attempt,
            "title": metadata["title"],
            "account_name": config["account_name"],
            "verified_draft": job["verified_draft"],
            "save_action": job["save_action"],
            "extended_link_persistence": job.get("extended_link_persistence"),
            "blocking_reason": job.get("blocking_reason"),
            "mobile_app_visibility_verified": False,
            "edge_pid": session["edge_pid"],
            "headless": bool(session.get("headless", config.get("headless", False))),
            "authorization_basis": "standing_user_instruction_draft_only",
            "automatic_publication": False,
        }
    except UploadUnknownError:
        raise
    except Exception as exc:
        diagnostics = getattr(exc, "diagnostics", None)
        if isinstance(diagnostics, dict):
            if diagnostics.get("stage") == "account_identity":
                job["account_identity_diagnostics"] = diagnostics
            else:
                job["creator_navigation_diagnostics"] = diagnostics
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


def _verify_new_draft_after_save(
    page: Any,
    config: dict[str, Any],
    selectors: dict[str, Any],
    *,
    title: str,
    before_snapshot: dict[str, Any],
    description: str = "",
) -> tuple[dict[str, Any] | None, list[str], list[dict[str, Any]], float]:
    """Read back a just-saved draft without repeatedly remounting the SPA.

    The upload/save action has already happened exactly once before this helper
    is called. This helper only navigates to DraftListManager once, then polls
    its already-mounted DOM until a unique new row appears or the deadline is
    reached. It never clicks the save control or resubmits media.
    """
    timeout_seconds = max(1.0, float(config.get("draft_verify_timeout_seconds", 90)))
    poll_interval_seconds = max(
        0.5, float(config.get("draft_verify_poll_interval_seconds", 3))
    )
    initial_settle_seconds = max(
        0.0, float(config.get("draft_verify_initial_settle_seconds", 3))
    )
    started = time.monotonic()
    deadline = started + timeout_seconds
    history: list[dict[str, Any]] = []
    after: dict[str, Any] | None = None
    matches: list[str] = []
    before_entries = set(str(item) for item in before_snapshot.get("entries", []))
    # A same-title row in the pre-upload snapshot is never eligible to be
    # reinterpreted as a newly-saved draft, even if its timestamp or row text
    # changes between reads.
    preexisting_title_matches = [
        str(item)
        for item in before_snapshot.get("entries", [])
        if title in str(item)
    ]

    if initial_settle_seconds:
        remaining = max(0.0, deadline - time.monotonic())
        wait_seconds = min(initial_settle_seconds, remaining)
        if wait_seconds > 0:
            page.wait_for_timeout(int(wait_seconds * 1000))

    # One SPA navigation refreshes the server-backed draft list after Save.
    # Do not navigate again during polling: repeated remounts can interrupt the
    # platform's asynchronous list loading and make a successful save invisible.
    direct_refresh_done = False
    try:
        _open_draft_list_view(page, config, selectors)
    except Exception as exc:
        history.append({
            "captured_at": _now(),
            "read_error": f"{type(exc).__name__}: {str(exc)[:240]}",
            "navigation": "single_refresh_failed",
        })
        direct_refresh_done = True
        try:
            page.goto(
                str(config.get("draft_list_url") or ""),
                wait_until="domcontentloaded", timeout=60_000,
            )
            page.wait_for_timeout(1000)
        except Exception as refresh_exc:
            history.append({
                "captured_at": _now(),
                "read_error": f"direct_refresh: {type(refresh_exc).__name__}: {str(refresh_exc)[:240]}",
            })

    while True:
        try:
            after = _draft_snapshot(page, selectors)
            if not direct_refresh_done and not (
                isinstance(after, dict)
                and after.get("view_type") == "draft_list"
                and after.get("view_verified") is True
            ):
                # The SPA menu can leave the list frame unmounted. A single
                # direct read-only reload of the official route is enough to
                # refresh the server-backed list; never retry the save action.
                direct_refresh_done = True
                page.goto(
                    str(config.get("draft_list_url") or ""),
                    wait_until="domcontentloaded", timeout=60_000,
                )
                page.wait_for_timeout(1000)
                after = _draft_snapshot(page, selectors)
            if description:
                matches = _matching_new_draft_rows(
                    after, before_snapshot, title, description, selectors
                )
            else:
                matches = _matching_draft_entries(after, title, selectors)
            new_matches = [item for item in matches if item not in before_entries]
            history.append({
                "captured_at": _now(),
                "draft_count": after.get("draft_count"),
                "match_count": len(matches),
                "new_match_count": len(new_matches),
                "preexisting_title_match_count": len(preexisting_title_matches),
                "matching_rows": matches[:5],
                "view_evidence": after.get("view_evidence", {}),
            })
            if (
                not preexisting_title_matches
                and len(matches) == 1
                and len(new_matches) == 1
            ):
                elapsed = max(0.0, time.monotonic() - started)
                return after, matches, history, round(elapsed, 3)
        except Exception as exc:
            history.append({
                "captured_at": _now(),
                "read_error": f"{type(exc).__name__}: {str(exc)[:240]}",
            })

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        wait_seconds = min(poll_interval_seconds, remaining)
        page.wait_for_timeout(max(1, int(wait_seconds * 1000)))

    elapsed = max(0.0, time.monotonic() - started)
    # Never return a prior or ambiguous match as a successful verification.
    # The full sample history retains the observed counts for diagnosis.
    return after, [], history, round(elapsed, 3)


def reconcile_upload(project_root: Path, job_id: str) -> dict[str, Any]:
    """Read the draft list and reconcile an uncertain upload; never resubmit."""
    project_root = project_root.resolve()
    config, selectors = _load_config(project_root)
    job_path = _job_path(project_root, config, job_id)
    job = _read_json(job_path)
    if job.get("state") in {"DRAFT_SAVED", "MANUALLY_CONFIRMED_DRAFT"}:
        return {
            "state": job.get("state"),
            "job_id": job_id,
            "verified_draft": job.get("verified_draft"),
            "manual_review": job.get("manual_review"),
            "message": "Already confirmed; no browser, upload, or save action was performed.",
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
        job["draft_reconciliation_started_at"] = _now()
        after, matches, history, elapsed = _verify_new_draft_after_save(
            page,
            config,
            selectors,
            title=str(job.get("title") or ""),
            description=str(job.get("description") or ""),
            before_snapshot=before,
        )
        job["draft_reconciliation"] = {
            "started_at": job["draft_reconciliation_started_at"],
            "finished_at": _now(),
            "timeout_seconds": int(config.get("draft_verify_timeout_seconds", 90)),
            "elapsed_seconds": elapsed,
            "navigation_count": 1,
            "samples": history,
            "read_only": True,
        }
        if after is not None and len(matches) == 1:
            job["state"] = "DRAFT_SAVED"
            job["post_upload_snapshot"] = after
            job["verified_draft"] = {
                "title": job.get("title"),
                "row_text": matches[0],
                "verified_at": _now(),
                "draft_list_url": after["url"],
                "reconciled_read_only": True,
                "verification_method": "read_only_draft_list_polling",
            }
            _save_job(job_path, job)
            return {
                "state": "DRAFT_SAVED",
                "job_id": job_id,
                "verified_draft": job["verified_draft"],
                "draft_reconciliation": job["draft_reconciliation"],
                "automatic_publication": False,
                "upload_or_save_retried": False,
            }
        job["state"] = "UPLOAD_UNKNOWN"
        job["post_upload_snapshot"] = after
        observed_counts = [
            int(item["match_count"])
            for item in history
            if isinstance(item, dict) and "match_count" in item
        ]
        job["verification_matches"] = observed_counts[-1] if observed_counts else 0
        job["verification_max_matches"] = max(observed_counts, default=0)
        _save_job(job_path, job)
        raise UploadUnknownError(
            "Read-only reconciliation found no unique new draft within the verification window. "
            "No upload or save click was performed. Inspect the account manually; do not retry the upload."
        )
    finally:
        playwright.stop()


def record_manual_review(
    project_root: Path,
    job_id: str,
    *,
    result: str,
    reviewed_by: str,
    confirmation: str,
    row_text: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Append a user-attested review of an uncertain draft without browser actions."""
    project_root = project_root.resolve()
    config, _ = _load_config(project_root)
    job_path = _job_path(project_root, config, job_id)
    job = _read_json(job_path)

    if job.get("state") not in {"UPLOAD_UNKNOWN", "MANUAL_REVIEW_NOT_FOUND"}:
        raise UploadBlockedError(
            f"Job state {job.get('state')!r} is not eligible for manual review recording."
        )
    if int(job.get("save_click_count", 0)) != 1:
        raise UploadBlockedError(
            "Manual review recording requires an uncertain job with exactly one recorded Save click."
        )
    reviewer = str(reviewed_by or "").strip()
    if not reviewer:
        raise UploadBlockedError("reviewed_by must identify the person who inspected the account.")

    normalized_result = str(result).strip().casefold()
    expected_confirmation = {
        "draft-found": f"CONFIRM CHANNELS DRAFT FOUND {job_id}",
        "not-found": f"CONFIRM CHANNELS DRAFT NOT FOUND {job_id}",
    }
    if normalized_result not in expected_confirmation:
        raise UploadBlockedError("result must be exactly 'draft-found' or 'not-found'.")
    if str(confirmation).strip() != expected_confirmation[normalized_result]:
        raise UploadBlockedError(
            f"Manual review confirmation did not match. Required phrase: {expected_confirmation[normalized_result]}"
        )

    title = str(job.get("title") or "").strip()
    row = str(row_text or "").strip()
    review_note = str(note or "").strip()
    if normalized_result == "draft-found":
        if not row or title not in row:
            raise UploadBlockedError(
                "For draft-found, row_text must be copied from 草稿箱 and contain the exact job title."
            )
        recorded_result = "draft_found_by_user"
        next_state = "MANUALLY_CONFIRMED_DRAFT"
    else:
        if not review_note:
            raise UploadBlockedError(
                "For not-found, note is required to record what was checked."
            )
        recorded_result = "not_found_at_review_time"
        next_state = "MANUAL_REVIEW_NOT_FOUND"

    event = {
        "result": recorded_result,
        "reviewed_at": _now(),
        "reviewed_by": reviewer,
        "account_name": str(config.get("account_name") or ""),
        "checked_area": "草稿箱",
        "title": title,
        "row_text": row if normalized_result == "draft-found" else None,
        "note": review_note,
        "confirmation_phrase": expected_confirmation[normalized_result],
        "no_browser_or_upload_action": True,
    }
    history = job.get("manual_reviews")
    if not isinstance(history, list):
        history = []
    history.append(event)
    job["manual_reviews"] = history
    job["manual_review"] = event
    job["state"] = next_state
    if normalized_result == "draft-found":
        job["verified_draft"] = {
            "title": title,
            "row_text": row,
            "verified_at": event["reviewed_at"],
            "verification_method": "manual_user_attestation",
            "reviewed_by": reviewer,
            "checked_area": "草稿箱",
            "mobile_app_visibility": "not_verified",
        }
    job["automatic_publication"] = False
    _save_job(job_path, job)
    return {
        "state": next_state,
        "job_id": job_id,
        "manual_review": event,
        "verified_draft": job.get("verified_draft"),
        "save_click_count": int(job.get("save_click_count", 0)),
        "upload_or_save_retried": False,
        "same_job_retry_allowed": False,
        "note": (
            "A user-reported absence is time-scoped and does not prove that the prior save request "
            "was never processed. The job remains blocked from another upload."
            if normalized_result == "not-found"
            else "This is a manual user attestation, not an automated DraftListManager read-back."
        ),
        "automatic_publication": False,
    }


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
    """Upload the newest strict-QA-PASS output under standing draft-only authorization."""
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
        "No complete output with strict QA PASS and valid Channels metadata is available under outputs/. "
    )



def _inspect_frame_controls(frame: Any, frame_url: str) -> dict[str, Any]:
    """Read visible creator controls directly from a frame's DOM.

    The inspector is deliberately read-only and does not read input values.
    Direct DOM evaluation avoids losing the entire inventory when a single
    Playwright locator/role query behaves differently in the embedded SPA.
    """
    expression = r"""() => {
        const isVisible = (element) => {
            if (!element || element.hidden) return false;
            const rect = element.getBoundingClientRect();
            if (!rect || rect.width <= 0 || rect.height <= 0) return false;
            for (let node = element; node && node.nodeType === 1; node = node.parentElement) {
                const style = window.getComputedStyle(node);
                if (style.display === "none" ||
                    style.visibility === "hidden" ||
                    style.visibility === "collapse" ||
                    Number.parseFloat(style.opacity || "1") === 0) {
                    return false;
                }
            }
            return true;
        };
        const normalize = (value) => String(value || "").replace(/\s+/g, " ").trim();
        const allButtons = Array.from(document.querySelectorAll("button, [role='button']"));
        const visibleButtons = allButtons.filter(isVisible).map((element) => ({
            tag: element.tagName.toLowerCase(),
            text: normalize(element.innerText || element.textContent),
            aria_label: normalize(element.getAttribute("aria-label") || "")
        }));
        const fieldSelector =
            "input[type='text'], input:not([type]), textarea, [contenteditable], [role='textbox']";
        const allFields = Array.from(document.querySelectorAll(fieldSelector));
        const visibleFields = allFields.filter(isVisible).map((element) => ({
            tag: element.tagName.toLowerCase(),
            placeholder: element.getAttribute("placeholder"),
            data_placeholder: element.getAttribute("data-placeholder"),
            aria_label: element.getAttribute("aria-label"),
            contenteditable: element.getAttribute("contenteditable"),
            role: element.getAttribute("role")
        }));
        const allFiles = Array.from(document.querySelectorAll("input[type='file']"));
        const fileInputs = allFiles.map((element) => ({
            accept: element.getAttribute("accept"),
            multiple: element.getAttribute("multiple"),
            visible: isVisible(element)
        }));
        return {
            ready_state: document.readyState,
            counts: {
                buttons_total: allButtons.length,
                buttons_visible: visibleButtons.length,
                textboxes_total: allFields.length,
                textboxes_visible: visibleFields.length,
                file_inputs_total: allFiles.length,
                file_inputs_visible: allFiles.filter(isVisible).length
            },
            buttons: visibleButtons,
            textboxes: visibleFields,
            file_inputs: fileInputs
        };
    }"""
    raw = frame.evaluate(expression)
    if not isinstance(raw, dict):
        raise ValueError("Frame DOM inspection returned an unexpected result.")

    buttons: list[dict[str, str]] = []
    for item in raw.get("buttons", []) or []:
        if not isinstance(item, dict):
            continue
        label = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
        aria_label = re.sub(
            r"\s+", " ", str(item.get("aria_label") or "")
        ).strip()
        if label or aria_label:
            buttons.append({
                "tag": str(item.get("tag") or "")[:24],
                "text": (label or aria_label)[:120],
                "aria_label": aria_label[:120],
                "label_source": "visible_text" if label else "aria_label",
                "frame_url": frame_url,
            })

    textboxes: list[dict[str, Any]] = []
    for item in raw.get("textboxes", []) or []:
        if not isinstance(item, dict):
            continue
        details = dict(item)
        details["frame_url"] = frame_url
        textboxes.append(details)

    files: list[dict[str, Any]] = []
    for item in raw.get("file_inputs", []) or []:
        if not isinstance(item, dict):
            continue
        details = dict(item)
        details["frame_url"] = frame_url
        files.append(details)

    counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
    return {
        "url": frame_url,
        "ready_state": str(raw.get("ready_state") or ""),
        "control_counts": {
            key: int(counts.get(key, 0) or 0)
            for key in (
                "buttons_total",
                "buttons_visible",
                "textboxes_total",
                "textboxes_visible",
                "file_inputs_total",
                "file_inputs_visible",
            )
        },
        "visible_buttons": buttons,
        "visible_textboxes": textboxes,
        "file_inputs": files,
    }


def _collect_ui_inventory(
    page: Any,
    *,
    timeout_seconds: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    """Collect each frame independently and wait briefly for the creator form."""
    deadline = time.monotonic() + max(0, timeout_seconds)
    while True:
        frames = _frame_contexts(page)
        frame_inventory: list[dict[str, Any]] = []
        buttons: list[dict[str, str]] = []
        textboxes: list[dict[str, Any]] = []
        files: list[dict[str, Any]] = []
        seen_buttons: set[tuple[str, str]] = set()
        seen_textboxes: set[tuple[str, str, str]] = set()

        for frame in frames:
            frame_url = str(getattr(frame, "url", ""))
            try:
                inventory = _inspect_frame_controls(frame, frame_url)
            except Exception as exc:
                frame_inventory.append({
                    "url": frame_url,
                    "ready_state": "",
                    "control_counts": {
                        "buttons_total": 0,
                        "buttons_visible": 0,
                        "textboxes_total": 0,
                        "textboxes_visible": 0,
                        "file_inputs_total": 0,
                        "file_inputs_visible": 0,
                    },
                    "visible_buttons": [],
                    "visible_textboxes": [],
                    "file_inputs": [],
                    "inspection_error": f"{type(exc).__name__}: {str(exc)[:160]}",
                })
                continue

            frame_buttons: list[str] = []
            for item in inventory["visible_buttons"]:
                label = str(item["text"])
                key = (frame_url, label)
                if key not in seen_buttons:
                    seen_buttons.add(key)
                    buttons.append(item)
                    frame_buttons.append(label)
            frame_textboxes: list[dict[str, Any]] = []
            for item in inventory["visible_textboxes"]:
                identity = (
                    frame_url,
                    str(item.get("tag") or ""),
                    str(
                        item.get("placeholder")
                        or item.get("data_placeholder")
                        or item.get("aria_label")
                        or item.get("role")
                        or ""
                    ),
                )
                if identity not in seen_textboxes:
                    seen_textboxes.add(identity)
                    textboxes.append(item)
                    frame_textboxes.append(item)
            frame_files = inventory["file_inputs"]
            files.extend(frame_files)
            frame_inventory.append({
                "url": frame_url,
                "ready_state": inventory["ready_state"],
                "control_counts": inventory["control_counts"],
                "visible_buttons": frame_buttons,
                "visible_textboxes": frame_textboxes,
                "file_inputs": frame_files,
            })

        # A creator form may legitimately distribute its controls across
        # the top document and embedded frames; readiness is page-wide.
        totals = {
            key: sum(item["control_counts"][key] for item in frame_inventory)
            for key in (
                "buttons_visible",
                "textboxes_visible",
                "file_inputs_total",
            )
        }
        controls_ready = (
            totals["buttons_visible"] > 0
            and totals["textboxes_visible"] > 0
            and totals["file_inputs_total"] > 0
        )
        if controls_ready or time.monotonic() >= deadline:
            return frame_inventory, buttons, textboxes, files, controls_ready
        page.wait_for_timeout(400)


def inspect_channels_ui(project_root: Path) -> dict[str, Any]:
    """Return a sanitized, read-only inventory of visible controls across frames."""
    project_root = project_root.resolve()
    config, selectors = _load_config(project_root)
    session, websocket_url = ensure_edge_session(
        project_root, open_url=str(config["create_url"])
    )
    playwright, browser, context = _connect_playwright(websocket_url)
    try:
        page = context.new_page()
        # Inspect the stable shell and its SPA creator-entry control. A
        # direct /platform/post/create deep link may fall back to this shell.
        page.goto(
            str(config.get("platform_url") or "https://channels.weixin.qq.com/platform"),
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        settle_ms = max(0, int(config.get("ui_settle_ms", 750)))
        if settle_ms:
            page.wait_for_timeout(settle_ms)

        ready_timeout = max(0, int(config.get("ui_ready_timeout_seconds", 15)))
        expected_name = str(config["account_name"])
        account_verified = _wait_for_account_identity(
            page,
            expected_name,
            selectors,
            wait_seconds=ready_timeout,
        )
        account_identity_diagnostics = (
            _account_identity_diagnostics(page, expected_name)
            if not account_verified else None
        )
        account_identity_evidence: list[dict[str, Any]] = []
        for frame in _frame_contexts(page):
            for item in _account_identity_evidence(frame, expected_name):
                details = dict(item)
                details["frame_url"] = str(getattr(frame, "url", ""))
                account_identity_evidence.append(details)
        (
            frame_inventory,
            buttons,
            textboxes,
            files,
            controls_ready,
        ) = _collect_ui_inventory(page, timeout_seconds=ready_timeout)

        login_required = not account_verified and _login_required_hint(page)
        return {
            "account_verified": account_verified,
            "manual_login_required": login_required,
            "account_identity_evidence": account_identity_evidence,
            "account_identity_diagnostics": account_identity_diagnostics,
            "page_url": page.url,
            "page_title": page.title(),
            "frame_count": len(frame_inventory),
            "frames": frame_inventory,
            "controls_ready": controls_ready,
            "visible_buttons": buttons,
            "visible_textboxes": textboxes,
            "file_inputs": files,
            "ui_ready_timeout_seconds": ready_timeout,
            "session_pid": session["edge_pid"],
            "session_profile": session["user_data_dir"],
            "note": (
                "Read-only DOM inventory across all frames. Input values were not read; "
                "no upload, fill, save, publish or delete action was performed."
            ),
        }
    finally:
        # The persistent Edge process/context is intentionally left alive.
        playwright.stop()
