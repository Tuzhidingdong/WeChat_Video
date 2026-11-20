from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from .tooling import legacy_model_root, model_root as configured_model_root


MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "tts-models/vits-melo-tts-zh_en.tar.bz2"
)
MODEL_DIR_NAME = "vits-melo-tts-zh_en"

EN_MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "tts-models/vits-piper-en_US-lessac-medium.tar.bz2"
)
EN_MODEL_DIR_NAME = "vits-piper-en_US-lessac-medium"
EN_MODEL_SIZE = 67_230_653
EN_MODEL_SHA256 = "9e3febfacf0abf4270172d2958bcec246032b7e88efc2720840cc80c93de334e"


def _valid_legacy_model_dir(path: Path) -> bool:
    return all(
        (path / name).is_file() for name in ("model.onnx", "lexicon.txt", "tokens.txt")
    ) and (path / "model.onnx").stat().st_size > 100_000_000


def _valid_en_model_dir(path: Path) -> bool:
    if not (path / "tokens.txt").is_file() or not (path / "espeak-ng-data").is_dir():
        return False
    return any(
        p.is_file() and p.stat().st_size > 10_000_000
        for p in path.glob("*.onnx")
        if "int8" not in p.name
    )


def _model_dir_valid(path: Path) -> bool:
    return _valid_en_model_dir(path) or _valid_legacy_model_dir(path)


def _download_and_extract(
    target: Path, url: str, archive_name: str, validator,
    *, expected_size: int | None = None, expected_sha256: str | None = None,
    timeout_seconds: int = 900,
) -> Path:
    target = target.resolve()
    model_parent = target.parent
    model_parent.mkdir(parents=True, exist_ok=True)
    if validator(target):
        return target

    archive = model_parent / archive_name
    if archive.exists():
        archive.unlink()

    request = urllib.request.Request(url, headers={"User-Agent": "WeChat-Video-Slice-A/0.2"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as out:
            written = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                out.write(block)
                written += len(block)
                if written > 700 * 1024 * 1024:
                    raise RuntimeError("TTS model archive is unexpectedly large; stopping.")
        if expected_size is not None and archive.stat().st_size != expected_size:
            raise RuntimeError(f"TTS model archive size mismatch: {archive.stat().st_size}")
        if expected_sha256 is not None:
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            if digest != expected_sha256:
                raise RuntimeError(f"TTS model archive SHA-256 mismatch: {digest}")
    except Exception:
        archive.unlink(missing_ok=True)
        raise

    root = model_parent.resolve()
    try:
        with tarfile.open(archive, mode="r:bz2") as tar:
            for member in tar.getmembers():
                resolved = (root / member.name).resolve()
                if root not in resolved.parents and resolved != root:
                    raise RuntimeError("Model archive contains an out-of-bounds path.")
                if member.issym() or member.islnk():
                    raise RuntimeError("Model archive contains a link entry.")
            tar.extractall(root)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        archive.unlink(missing_ok=True)

    if not validator(target):
        raise RuntimeError(f"Model extraction did not pass validation: {target}")
    return target


def download_model(project_root: Path, timeout_seconds: int = 900) -> Path:
    """Download the default (English Piper) Slice A voice."""
    return download_english_model(project_root, timeout_seconds=timeout_seconds)


def download_english_model(project_root: Path, timeout_seconds: int = 900) -> Path:
    return _download_and_extract(
        configured_model_root(project_root),
        EN_MODEL_URL,
        f"{EN_MODEL_DIR_NAME}.tar.bz2",
        _valid_en_model_dir,
        expected_size=EN_MODEL_SIZE,
        expected_sha256=EN_MODEL_SHA256,
        timeout_seconds=timeout_seconds,
    )


def download_chinese_model(project_root: Path, timeout_seconds: int = 900) -> Path:
    """Legacy rollback model; kept on disk but no longer the default voice."""
    return _download_and_extract(
        legacy_model_root(project_root),
        MODEL_URL,
        f"{MODEL_DIR_NAME}.tar.bz2",
        _valid_legacy_model_dir,
        timeout_seconds=timeout_seconds,
    )
