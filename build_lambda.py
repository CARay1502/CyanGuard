"""Build dist/cyanguard-lambda.zip for AWS Lambda (Python 3.12, x86_64).

Usage:  python build_lambda.py

Packages are downloaded as Linux builds, because Lambda runs on Linux and some
packages (like pydantic-core) contain compiled code that differs per platform.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD = ROOT / "build" / "lambda"
ZIP_PATH = ROOT / "dist" / "cyanguard-lambda.zip"


def main() -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    print("Installing Linux packages...")
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "-r", str(ROOT / "requirements-lambda.txt"),
            "--target", str(BUILD),
            "--platform", "manylinux2014_x86_64",
            "--implementation", "cp",
            "--python-version", "3.12",
            "--only-binary=:all:",
            "--quiet",
        ],
        check=True,
    )

    print("Copying app code...")
    shutil.copytree(ROOT / "app", BUILD / "app", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(ROOT / "lambda_handler.py", BUILD / "lambda_handler.py")

    print("Zipping...")
    ZIP_PATH.parent.mkdir(exist_ok=True)
    ZIP_PATH.unlink(missing_ok=True)
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                # as_posix() keeps forward slashes, which Lambda (Linux) requires.
                zf.write(path, path.relative_to(BUILD).as_posix())

    size_mb = ZIP_PATH.stat().st_size / 1_000_000
    print(f"Done: {ZIP_PATH.relative_to(ROOT)} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
