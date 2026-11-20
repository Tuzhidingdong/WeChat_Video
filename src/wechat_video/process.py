from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence


class ExternalProcessError(RuntimeError):
    """Raised when an external tool fails or exceeds its timeout."""


def run_checked(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout_seconds: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [str(part) for part in args]
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ExternalProcessError(
            f"外部命令超时（{timeout_seconds}s）：{command[0]}\n"
            f"工作目录：{cwd or Path.cwd()}\n"
            f"部分输出：{exc.stderr or exc.stdout or ''}"
        ) from exc
    except OSError as exc:
        raise ExternalProcessError(
            f"无法启动外部命令：{command[0]}；{exc}"
        ) from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        if len(detail) > 6000:
            detail = detail[-6000:]
        raise ExternalProcessError(
            f"命令退出码 {result.returncode}：{command[0]}\n"
            f"工作目录：{cwd or Path.cwd()}\n{detail}"
        )
    return result
