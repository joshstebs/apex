"""Run standalone tests in separate processes with synthetic configuration defaults."""

import argparse
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

from qa.offline import install_egress_guard


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", type=Path)
    args = parser.parse_args()
    if args.child:
        install_egress_guard()
        runpy.run_path(str(args.child), run_name="__main__")
        return

    with tempfile.TemporaryDirectory(prefix="apex-legacy-") as directory:
        failures = []
        paths = sorted(ROOT.glob("test_*.py"))
        if not paths:
            raise SystemExit("No standalone tests found")
        for path in paths:
            print(f"Running {path.name}", flush=True)
            env = {
                "PATH": os.environ.get("PATH", os.defpath),
                "HOME": directory,
                "DB_PATH": str(Path(directory) / f"{path.stem}.db"),
                "PYTHONUNBUFFERED": "1",
            }
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "qa.run_legacy", "--child", str(path)],
                    cwd=ROOT, env=env, timeout=90, check=False,
                )
                if result.returncode:
                    failures.append(path.name)
            except subprocess.TimeoutExpired:
                failures.append(path.name + " (timeout)")
        print(f"{len(paths) - len(failures)}/{len(paths)} scripts passed")
        if failures:
            raise SystemExit("Failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
