from __future__ import annotations

import shutil
import tarfile
import urllib.request
from pathlib import Path


MODEL_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "tts-models/vits-melo-tts-zh_en.tar.bz2"
)
MODEL_DIR_NAME = "vits-melo-tts-zh_en"


def _valid_model_dir(path: Path) -> bool:
    return all(
        (path / name).is_file()
        for name in ("model.onnx", "lexicon.txt", "tokens.txt")
    ) and (path / "model.onnx").stat().st_size > 100_000_000


def download_model(project_root: Path, timeout_seconds: int = 900) -> Path:
    model_parent = project_root / "assets" / "models"
    model_parent.mkdir(parents=True, exist_ok=True)
    target = model_parent / MODEL_DIR_NAME
    if _valid_model_dir(target):
        return target

    archive = model_parent / f"{MODEL_DIR_NAME}.tar.bz2"
    if archive.exists():
        archive.unlink()

    request = urllib.request.Request(
        MODEL_URL,
        headers={"User-Agent": "WeChat-Video-Slice-A/0.1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response, archive.open("wb") as out:
            total = int(response.headers.get("Content-Length", "0") or 0)
            written = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                out.write(block)
                written += len(block)
                if written > 700 * 1024 * 1024:
                    raise RuntimeError("TTS 模型压缩包异常过大，已停止下载。")
        if archive.stat().st_size < 50 * 1024 * 1024:
            raise RuntimeError("TTS 模型压缩包下载不完整（文件过小）。")
    except Exception:
        archive.unlink(missing_ok=True)
        raise

    root = model_parent.resolve()
    try:
        with tarfile.open(archive, mode="r:bz2") as tar:
            members = tar.getmembers()
            for member in members:
                resolved = (root / member.name).resolve()
                if root not in resolved.parents and resolved != root:
                    raise RuntimeError("模型压缩包包含越界路径，拒绝解压。")
                if member.issym() or member.islnk():
                    raise RuntimeError("模型压缩包包含链接条目，拒绝解压。")
            tar.extractall(root)
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        archive.unlink(missing_ok=True)

    if not _valid_model_dir(target):
        raise RuntimeError(
            "模型文件解压后未通过完整性检查；请删除 assets/models 下的模型目录后重试。"
        )
    return target
