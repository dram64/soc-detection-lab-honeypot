"""Build ingest.zip and (optionally) geolite2-layer.zip for Lambda deployment.

Pure-Python replacement for the bash version of package_lambdas.sh — works
cross-platform without `zip` / `find` / Cygwin path translation.

Usage:
    python scripts/package_lambdas.py [--python-bin <path>]

The deps are downloaded with cross-target wheel flags so the resulting zip
is Lambda-runtime-compatible (cp313, manylinux2014_x86_64) regardless of the
interpreter used to run this script.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parents[1]
INGEST_BUILD = DASHBOARD / "infrastructure" / "terraform" / "modules" / "ingest" / "build"
AGGREGATOR_BUILD = DASHBOARD / "infrastructure" / "terraform" / "modules" / "aggregator" / "build"
API_BUILD = DASHBOARD / "infrastructure" / "terraform" / "modules" / "api" / "build"
INGEST_STAGE = INGEST_BUILD / "ingest-stage"
LAYER_STAGE = INGEST_BUILD / "geolite2-stage"
AGGREGATOR_STAGE = AGGREGATOR_BUILD / "aggregator-stage"
API_STAGE = API_BUILD / "api-stage"

INGEST_DEPS = ["pydantic", "boto3", "geoip2"]
AGGREGATOR_DEPS = ["pydantic", "boto3"]
API_DEPS = ["pydantic", "boto3"]
# Back-compat alias
DEPS = INGEST_DEPS


def _run(argv: list[str]) -> None:
    print("$", " ".join(str(a) for a in argv))
    subprocess.run(argv, check=True)


def _purge_caches(root: Path) -> None:
    for d in list(root.rglob("__pycache__")):
        if d.is_dir():
            shutil.rmtree(d)
    for d in list(root.rglob("tests")):
        if d.is_dir():
            shutil.rmtree(d)
    for f in list(root.rglob("*.pyc")):
        f.unlink()


def _zip_dir(stage: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                arcname = path.relative_to(stage).as_posix()
                zf.write(path, arcname)
    print(f"Built: {out} ({out.stat().st_size:,} bytes)")


def _build_function_zip(
    *,
    python_bin: str,
    stage: Path,
    deps: list[str],
    function_subpkg: str,
    out_zip: Path,
) -> None:
    """Vendor first-party code + cross-target wheels into stage/, zip to out_zip."""
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    (stage / "functions").mkdir()
    (stage / "functions" / "__init__.py").touch()
    shutil.copytree(
        DASHBOARD / "functions" / function_subpkg, stage / "functions" / function_subpkg
    )
    shutil.copytree(DASHBOARD / "functions" / "shared", stage / "functions" / "shared")

    _run(
        [
            python_bin,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(stage),
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.13",
            "--only-binary=:all:",
            "--upgrade",
            *deps,
        ]
    )

    _purge_caches(stage)
    _zip_dir(stage, out_zip)
    shutil.rmtree(stage)


def build_ingest_zip(python_bin: str) -> None:
    _build_function_zip(
        python_bin=python_bin,
        stage=INGEST_STAGE,
        deps=INGEST_DEPS,
        function_subpkg="ingest",
        out_zip=INGEST_BUILD / "ingest.zip",
    )


def build_aggregator_zip(python_bin: str) -> None:
    _build_function_zip(
        python_bin=python_bin,
        stage=AGGREGATOR_STAGE,
        deps=AGGREGATOR_DEPS,
        function_subpkg="aggregator",
        out_zip=AGGREGATOR_BUILD / "aggregator.zip",
    )


def build_api_zip(python_bin: str) -> None:
    _build_function_zip(
        python_bin=python_bin,
        stage=API_STAGE,
        deps=API_DEPS,
        function_subpkg="api",
        out_zip=API_BUILD / "api.zip",
    )


def build_layer_zip() -> None:
    geoip_dir = DASHBOARD / "functions" / "layers" / "geolite2"
    country = geoip_dir / "GeoLite2-Country.mmdb"
    asn = geoip_dir / "GeoLite2-ASN.mmdb"
    if not (country.exists() and asn.exists()):
        print(
            "Skipping GeoLite2 layer: .mmdb files not present. "
            f"Run download_geolite2.sh in {geoip_dir} first."
        )
        return
    if LAYER_STAGE.exists():
        shutil.rmtree(LAYER_STAGE)
    (LAYER_STAGE / "geolite2").mkdir(parents=True)
    shutil.copy(country, LAYER_STAGE / "geolite2" / country.name)
    shutil.copy(asn, LAYER_STAGE / "geolite2" / asn.name)
    _zip_dir(LAYER_STAGE, INGEST_BUILD / "geolite2-layer.zip")
    shutil.rmtree(LAYER_STAGE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python interpreter to invoke pip with (default: this interpreter).",
    )
    args = parser.parse_args()
    print(f"Using PYTHON_BIN={args.python_bin}")
    INGEST_BUILD.mkdir(parents=True, exist_ok=True)
    AGGREGATOR_BUILD.mkdir(parents=True, exist_ok=True)
    API_BUILD.mkdir(parents=True, exist_ok=True)
    build_ingest_zip(args.python_bin)
    build_aggregator_zip(args.python_bin)
    build_api_zip(args.python_bin)
    build_layer_zip()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
