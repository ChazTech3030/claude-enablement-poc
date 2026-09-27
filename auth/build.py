"""Package the auth Lambdas for arm64 (plan 8.1, Packaging). Output: auth/dist/{auth_request,auth_verify}.zip

Vendors `cryptography` as a manylinux aarch64 wheel so packaging works from Windows, macOS or Linux.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIST = HERE / "dist"
PY = "3.13"
FUNCTIONS = {"auth_request": [], "auth_verify": ["cryptography>=43"]}


def main() -> None:
    DIST.mkdir(exist_ok=True)
    for fn, deps in FUNCTIONS.items():
        stage = DIST / f"_{fn}"
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir()
        if deps:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(stage),
                 "--platform", "manylinux2014_aarch64", "--implementation", "cp", "--python-version", PY,
                 "--only-binary=:all:", *deps],
                check=True,
            )
        shutil.copy(HERE / "lambda" / fn / "handler.py", stage / "handler.py")
        shutil.copy(HERE / "lambda" / "common" / "authcommon.py", stage / "authcommon.py")
        target = DIST / f"{fn}.zip"
        target.unlink(missing_ok=True)
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(stage.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts:
                    info = zipfile.ZipInfo(str(f.relative_to(stage)).replace("\\", "/"), date_time=(2026, 1, 1, 0, 0, 0))
                    info.external_attr = 0o644 << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, f.read_bytes())
        shutil.rmtree(stage)
        print(f"{target} ({target.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
