"""
Publishes the jobboard_common wheel to CodeArtifact.
Run once before the first pipeline execution.

Works on Windows, macOS, and Linux (no bash required).

Usage:
  python scripts/publish-common-lib.py [domain] [repo]

Defaults to domain=jobboard-cicd, repo=jobboard-internal
"""

import os
import sys
import shutil
import subprocess
import tempfile
import venv
from pathlib import Path


def run(cmd, **kwargs):
    print(f"  > {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, check=True, **kwargs)
    return result


def main():
    domain = sys.argv[1] if len(sys.argv) > 1 else "jobboard-cicd"
    repo   = sys.argv[2] if len(sys.argv) > 2 else "jobboard-internal"
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    script_dir = Path(__file__).resolve().parent
    lib_dir    = script_dir.parent / "app" / "lib" / "jobboard_common"
    out_dir    = Path(tempfile.gettempdir()) / "jobboard-common-dist"
    venv_dir   = Path(tempfile.gettempdir()) / "jobboard-publish-venv"

    # ---------- build ----------
    print("\n==> Building jobboard-common wheel...")
    if out_dir.exists():
        shutil.rmtree(out_dir)

    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    venv.create(str(venv_dir), with_pip=True)

    # Locate pip and python inside the venv (path differs on Windows vs Unix)
    if sys.platform == "win32":
        venv_python = venv_dir / "Scripts" / "python.exe"
        venv_pip    = venv_dir / "Scripts" / "pip.exe"
    else:
        venv_python = venv_dir / "bin" / "python"
        venv_pip    = venv_dir / "bin" / "pip"

    run([str(venv_pip), "install", "--quiet", "build", "twine"])
    run([str(venv_python), "-m", "build", "--wheel",
         "--outdir", str(out_dir), str(lib_dir)])

    # ---------- authenticate twine ----------
    print(f"\n==> Logging twine into CodeArtifact domain={domain} repo={repo} region={region}...")
    run(["aws", "codeartifact", "login",
         "--tool", "twine",
         "--domain", domain,
         "--repository", repo,
         "--region", region])

    # ---------- upload ----------
    print("\n==> Publishing wheel...")
    wheels = list(out_dir.glob("*.whl"))
    if not wheels:
        print("ERROR: no .whl file found in", out_dir, file=sys.stderr)
        sys.exit(1)

    if sys.platform == "win32":
        twine = venv_dir / "Scripts" / "twine.exe"
    else:
        twine = venv_dir / "bin" / "twine"

    run([str(twine), "upload", "--repository", "codeartifact"] + [str(w) for w in wheels])

    # ---------- verify ----------
    print("\n==> Done. Installed versions:")
    run(["aws", "codeartifact", "list-package-versions",
         "--domain", domain,
         "--repository", repo,
         "--package", "jobboard-common",
         "--format", "pypi",
         "--query", "versions[*].{version:version,status:status}",
         "--output", "table",
         "--region", region])


if __name__ == "__main__":
    main()
