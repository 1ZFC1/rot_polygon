#!/usr/bin/env python3
"""把旋转多边形工具打包成单个 exe（控制台程序，带问答）。

    python build_exe.py            # 生成 artifacts/rot_polygon/旋转多边形.exe
    python build_exe.py --onedir   # 文件夹版（排查用）

谱面库 rizChartFunction 会被编译进 exe；该库里的 advanced_font 需要 numpy/skimage，
本工具用不到，所以整块排除，exe 体积能压到十几 MB。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
LIB_SRC = TOOLS / "rizChartFunction_Library" / "src"
DIST = TOOLS.parent / "artifacts" / "rot_polygon"
BUILD = HERE / "build"
NAME = "旋转多边形"

EXCLUDES = [
    "numpy", "scipy", "skimage", "PIL", "Pillow", "matplotlib", "PIL.Image",
    "PyQt5", "tkinter", "pandas", "IPython", "pytest", "setuptools", "pip",
    "advanced_font",
]


def build_args(onefile: bool) -> list[str]:
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--noupx", "--console", "--log-level", "WARN",
        "--name", NAME,
        "--distpath", str(DIST), "--workpath", str(BUILD), "--specpath", str(BUILD),
        "--paths", str(HERE), "--paths", str(LIB_SRC),
        "--hidden-import", "rizChartFunction",
    ]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    if onefile:
        args.append("--onefile")
    args.append(str(HERE / "rot_polygon.py"))
    return args


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onedir", action="store_true")
    args = parser.parse_args()

    if not (LIB_SRC / "rizChartFunction" / "__init__.py").exists():
        print(f"缺少谱面库：{LIB_SRC}")
        return 2

    DIST.mkdir(parents=True, exist_ok=True)
    code = subprocess.run(build_args(not args.onedir), cwd=str(HERE)).returncode
    if code != 0:
        print("打包失败")
        return code

    if args.onedir:
        target = DIST / NAME
        print(f"\n[onedir] {target}")
    else:
        target = DIST / f"{NAME}.exe"
        print(f"\n[onefile] {target}  {target.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
