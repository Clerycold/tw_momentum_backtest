"""Detached OOS pipeline: FinMind download (resumable, retried) -> official records -> pytest -> run_oos."""
import os, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DONE = ROOT / "data" / "raw" / "DOWNLOAD_OOS_DONE"
LOG = ROOT / "logs" / "pipeline_oos.log"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def run(args, out):
    with open(ROOT / "logs" / out, "a", encoding="utf-8") as f:
        return subprocess.run([sys.executable, *args], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, env=ENV).returncode


log("start")
for attempt in range(5):
    if DONE.exists():
        break
    log(f"download attempt {attempt + 1}")
    run(["scripts/download_oos.py"], "download_oos.err")
if not DONE.exists():
    log("download failed; stopping"); sys.exit(1)
log(f"official records rc={run(['scripts/fetch_official_actions.py', '2022', '2026'], 'official_oos.log')}")
rc = run(["-m", "pytest", "-q", "tests"], "pytest_oos.log")
log(f"pytest rc={rc}")
if rc:
    sys.exit(1)
log(f"run_oos rc={run(['scripts/run_oos.py'], 'run_oos.log')}; PIPELINE_FINISHED")
