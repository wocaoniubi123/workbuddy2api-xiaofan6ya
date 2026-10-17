from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = json.loads((ROOT / "desktop/version.json").read_text(encoding="utf-8"))
VERSION = METADATA["version"]
REPOSITORY = METADATA["repository"]
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"


def app_dir() -> Path:
    """EXE 所在目录：Windows 桌面版所有数据、日志、缓存都落在这里。

    PyInstaller onefile 下 `__file__` 指向 `%TEMP%\\_MEIxxxx` 解包目录（退出即删），
    不能用来定位数据目录；`sys.executable` 才是用户双击的那个 EXE。
    源码运行时取仓库根目录，与「EXE 旁边」等价。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return ROOT


def data_dir() -> Path:
    path = Path(os.environ.get("WORKBUDDY_DESKTOP_DATA") or app_dir())
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"数据目录不可写：{path}，请把 EXE 放到有写权限的文件夹") from exc
    return path


def atomic_json(path: Path, value: dict) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)
