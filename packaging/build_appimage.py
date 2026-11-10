"""Build dist/repopull-<version>-x86_64.AppImage with a bundled Python and PySide6."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from pathlib import Path

try:
    from trim_appdir import IMAGE_SIZE_CEILING, TrimError, trim_appdir
except ImportError:  # imported by tests instead of executed as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from trim_appdir import IMAGE_SIZE_CEILING, TrimError, trim_appdir

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "build" / "appimage"
CACHE = ROOT / "build" / "downloads"
RUNTIME_VARIABLES = ("APPDIR", "APPIMAGE", "ARGV0", "OWD")


def run(*args: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True, env=env)


def download(item: dict[str, str]) -> Path:
    """Fetch a pinned build input and verify its SHA-256."""
    path = CACHE / item["name"]
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".part")
        request = urllib.request.Request(
            item["url"], headers={"Accept": "application/octet-stream"}
        )
        with urllib.request.urlopen(request, timeout=180) as source:
            with temporary.open("wb") as target:
                shutil.copyfileobj(source, target)
        temporary.replace(path)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != item["sha256"]:
        raise SystemExit(
            f"Checksum mismatch: {path}. Remove it and review downloads.json."
        )
    return path


def main() -> None:
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise SystemExit("Build on Linux x86_64.")

    # A terminal inside another AppImage passes these on; both python-appimage
    # and appimagetool would otherwise run from the wrong folder.
    for key in RUNTIME_VARIABLES:
        os.environ.pop(key, None)
    os.environ["APPIMAGE_EXTRACT_AND_RUN"] = "1"

    BUILD.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    try:
        import python_appimage  # noqa: F401
    except ImportError:
        raise SystemExit(
            "python-appimage is not installed. Run `make appimage`."
        ) from None

    downloads = json.loads((PACKAGING / "downloads.json").read_text())
    binaries = {key: download(value) for key, value in downloads.items()}
    for binary in binaries.values():
        binary.chmod(0o755)

    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "version"
    ]

    wheel_dir = BUILD / "wheels"
    wheel_dir.mkdir(exist_ok=True)
    run(
        sys.executable,
        "-m",
        "pip",
        "wheel",
        "--no-deps",
        "--wheel-dir",
        str(wheel_dir),
        str(ROOT),
    )
    wheels = sorted(wheel_dir.glob(f"repopull-{version}-*.whl"))
    if not wheels:
        raise SystemExit("The repopull wheel was not built.")
    wheel = wheels[-1]

    with tempfile.TemporaryDirectory(prefix="stage-", dir=BUILD) as staging:
        stage = Path(staging)
        recipe = stage / "repopull"
        recipe.mkdir()
        shutil.copy2(PACKAGING / "repopull.desktop", recipe)
        shutil.copy2(PACKAGING / "repopull.png", recipe / "repopull.png")
        requirements = (
            PACKAGING / "runtime-requirements.txt"
        ).read_text().strip()
        (recipe / "requirements.txt").write_text(
            f"{requirements}\n{wheel}\n", encoding="utf-8"
        )

        run(
            sys.executable,
            "-m",
            "python_appimage",
            "build",
            "app",
            "--base-image",
            str(binaries["python"]),
            "--no-packaging",
            str(recipe),
            cwd=stage,
        )

        candidates = sorted(path for path in stage.glob("repopull*x86_64") if path.is_dir())
        if not candidates:
            raise SystemExit(f"python-appimage produced no AppDir in {stage}")
        appdir = candidates[0]

        # pip records the local wheel path here; it must not ship in a public
        # build because it exposes the builder's home layout.
        for direct_url in appdir.glob(
            "opt/python*/lib/python*/site-packages/repopull-*.dist-info/direct_url.json"
        ):
            direct_url.unlink(missing_ok=True)

        apprun = appdir / "AppRun"
        apprun.unlink(missing_ok=True)
        shutil.copy2(PACKAGING / "AppRun", apprun)
        apprun.chmod(0o755)

        share = appdir / "usr" / "share" / "repopull"
        share.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            PACKAGING / "default-config.toml", share / "config.toml"
        )

        asset_dir = ROOT / "src" / "repopull" / "gui" / "assets"
        for size in (16, 22, 24, 32, 48, 64, 128, 256, 512):
            source = asset_dir / f"repopull-{size}.png"
            if not source.is_file():
                continue
            target = (
                appdir
                / "usr"
                / "share"
                / "icons"
                / "hicolor"
                / f"{size}x{size}"
                / "apps"
                / "repopull.png"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

        try:
            trimmed = trim_appdir(appdir)
        except TrimError as exc:
            raise SystemExit(f"AppDir trim failed: {exc}") from exc
        print(
            f"Trimmed AppDir to {trimmed.appdir_bytes / 1_000_000:.1f} MB "
            f"({trimmed.kept_bindings} bindings, "
            f"{trimmed.kept_libraries} Qt libraries)"
        )

        notices = appdir / "usr" / "share" / "doc" / "repopull"
        notices.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PACKAGING / "THIRD_PARTY_NOTICES.md", notices)
        licenses = notices / "licenses"
        licenses.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            PACKAGING / "licenses" / "LGPL-3.0.txt",
            licenses / "LGPL-3.0.txt",
        )
        shutil.copy2(ROOT / "LICENSE", notices / "LICENSE")
        notices.chmod(0o755)
        licenses.chmod(0o755)
        for path in (
            notices / "THIRD_PARTY_NOTICES.md",
            licenses / "LGPL-3.0.txt",
            notices / "LICENSE",
        ):
            path.chmod(0o644)

        output = ROOT / "dist"
        output.mkdir(exist_ok=True)
        image = output / f"repopull-{version}-x86_64.AppImage"
        staged_image = stage / image.name
        os.environ["ARCH"] = "x86_64"
        os.environ["VERSION"] = version
        run(
            str(binaries["tool"]),
            "--appimage-extract-and-run",
            "--runtime-file",
            str(binaries["runtime"]),
            "--comp",
            "zstd",
            "--no-appstream",
            str(appdir),
            str(staged_image),
            cwd=stage,
        )
        size = staged_image.stat().st_size
        if size > IMAGE_SIZE_CEILING:
            raise SystemExit(
                f"{image.name} is {size / 1_000_000:.1f} MB, above the "
                f"{IMAGE_SIZE_CEILING / 1_000_000:.0f} MB ceiling. Review "
                "packaging/trim_appdir.py or raise the ceiling deliberately."
            )
        staged_image.replace(image)
        image.chmod(0o755)

    smoke_home = BUILD / "smoke-home"
    # A previous build's root-state file would make the smoke test refuse the
    # root after a remount, so each build starts with a clean home.
    shutil.rmtree(smoke_home, ignore_errors=True)
    smoke_env = dict(
        os.environ,
        QT_QPA_PLATFORM="offscreen",
        XDG_CONFIG_HOME=str(smoke_home),
    )

    smoke_args = [str(image), "--appimage-extract-and-run", "--smoke-test"]
    dev_config = ROOT / "config.toml"
    if dev_config.is_file():
        dev = tomllib.loads(dev_config.read_text())
        dev_root = dev.get("root")
        if isinstance(dev_root, str) and dev_root:
            smoke_args.extend(["--root", dev_root])

    smoke = subprocess.run(
        smoke_args,
        capture_output=True,
        text=True,
        timeout=180,
        env=smoke_env,
    )
    if smoke.returncode != 0:
        raise SystemExit(
            f"AppImage smoke test failed:\n{smoke.stdout}\n{smoke.stderr}"
        )
    print(smoke.stdout.strip())

    cli = subprocess.run(
        [str(image), "--appimage-extract-and-run", "--cli", "version"],
        capture_output=True,
        text=True,
        timeout=120,
        env=smoke_env,
    )
    if cli.returncode != 0:
        raise SystemExit(f"AppImage CLI test failed:\n{cli.stdout}\n{cli.stderr}")
    print(cli.stdout.strip())

    with image.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    (output / "SHA256SUMS.txt").write_text(f"{digest}  {image.name}\n")
    print(f"Built {image} ({size / 1_000_000:.1f} MB)")


if __name__ == "__main__":
    main()
