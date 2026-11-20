"""Project-local tool discovery.

All rendering tools are resolved from ``config/tools.local.json`` (relative to
the project root) before falling back to PATH. This keeps Slice A from
accidentally using an unrelated global FFmpeg or TeX installation.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


CONFIG_RELATIVE_PATH = Path("config") / "tools.local.json"

_COMMAND_KEYS: dict[str, tuple[str, ...]] = {
    "ffmpeg": ("ffmpeg", "ffmpeg"),
    "ffprobe": ("ffmpeg", "ffprobe"),
    "latex": ("miktex", "latex"),
    "dvisvgm": ("miktex", "dvisvgm"),
    "kpsewhich": ("miktex", "kpsewhich"),
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_tools_config(root: Path | None = None) -> dict[str, Any]:
    root = root or project_root()
    path = root / CONFIG_RELATIVE_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"无法读取项目工具配置 {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"项目工具配置根节点必须是对象: {path}")
    return data


def configured_path(*keys: str, root: Path | None = None) -> Path | None:
    node: Any = load_tools_config(root)
    for key in keys:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if node is None:
        return None
    root = root or project_root()
    path = Path(str(node))
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def _require_file(path: Path, command: str) -> str:
    if not path.is_file():
        raise RuntimeError(
            f"项目工具配置指向的 {command} 不存在：{path}。"
            "请检查 config/tools.local.json 与项目内工具安装。"
        )
    return str(path)


def resolve_command(command: str, root: Path | None = None) -> str:
    """Return an absolute command path, preferring the project-local tool."""
    keys = _COMMAND_KEYS.get(command)
    if keys:
        path = configured_path(*keys, root=root)
        if path is not None:
            return _require_file(path, command)
    found = shutil.which(command)
    if found:
        return found
    raise RuntimeError(f"未找到工具 {command}，且项目工具配置未提供路径。")


def tool_bin_dirs(root: Path | None = None) -> list[str]:
    dirs: list[str] = []
    for keys in (("ffmpeg", "bin_dir"), ("miktex", "bin_dir")):
        path = configured_path(*keys, root=root)
        if path is not None and path.is_dir():
            dirs.append(str(path))
    return dirs


def tool_env(root: Path | None = None) -> dict[str, str]:
    """Environment for Manim/TeX/FFmpeg subprocesses (process-local only)."""
    env = os.environ.copy()
    dirs = tool_bin_dirs(root)
    if dirs:
        env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    return env


def tool_path_for_bat(root: Path | None = None) -> str:
    return os.pathsep.join(tool_bin_dirs(root))


def model_root(root: Path | None = None) -> Path:
    configured = configured_path("tts_model", "root", root=root)
    if configured is not None:
        return configured
    return (root or project_root()) / "assets" / "models" / "vits-piper-en_US-lessac-medium"


def legacy_model_root(root: Path | None = None) -> Path:
    configured = configured_path("tts_model_zh", "root", root=root)
    if configured is not None:
        return configured
    return (root or project_root()) / "assets" / "models" / "vits-melo-tts-zh_en"


def describe_tools(root: Path | None = None) -> dict[str, Any]:
    report: dict[str, Any] = {"project_root": str(root or project_root())}
    for name, keys in (
        ("latex", ("miktex", "latex")),
        ("dvisvgm", ("miktex", "dvisvgm")),
        ("kpsewhich", ("miktex", "kpsewhich")),
        ("ffmpeg", ("ffmpeg", "ffmpeg")),
        ("ffprobe", ("ffmpeg", "ffprobe")),
    ):
        path = configured_path(*keys, root=root)
        report[name] = {"path": str(path) if path else None, "present": bool(path and path.is_file())}
    report["model"] = {
        "path": str(model_root(root)),
        "present": _model_files_present(model_root(root)),
    }
    report["model_zh"] = {
        "path": str(legacy_model_root(root)),
        "present": _model_files_present(legacy_model_root(root)),
    }
    return report


def _model_files_present(path: Path) -> bool:
    if (path / "espeak-ng-data").is_dir() and any(path.glob("*.onnx")):
        return (path / "tokens.txt").is_file()
    return all((path / name).is_file() for name in ("model.onnx", "lexicon.txt", "tokens.txt"))
