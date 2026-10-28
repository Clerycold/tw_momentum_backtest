"""Wait for the running downloader, resume it if it died, then run pytest and the dev backtest."""
import subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DONE = ROOT / "data" / "raw" / "DOWNLOAD_DONE"
LOG = ROOT / "logs" / "pipeline.log"
pid = sys.argv[1] if len(sys.argv) > 1 else None


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def alive(p):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {p}"], capture_output=True, text=True).stdout
    return str(p) in out


log(f"waiting for downloader pid={pid}")
while pid and alive(pid) and not DONE.exists():
    time.sleep(120)
for attempt in range(3):
    if DONE.exists():
        break
    log(f"downloader not done; resuming (attempt {attempt + 1})")
    with open(ROOT / "logs" / "download.err", "a") as err:
        subprocess.run([sys.executable, "scripts/download_all.py"], cwd=ROOT, stderr=err)
if not DONE.exists():
    log("download failed 3 times; stopping")
    sys.exit(1)

log("download done; running pytest")
with open(ROOT / "logs" / "pytest.log", "w", encoding="utf-8") as f:
    rc = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT).returncode
log(f"pytest rc={rc}")
if rc != 0:
    sys.exit(1)
log("running run_dev.py")
with open(ROOT / "logs" / "run_dev.log", "w", encoding="utf-8") as f:
    rc = subprocess.run([sys.executable, "scripts/run_dev.py"], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"}).returncode
log(f"run_dev rc={rc}; PIPELINE_FINISHED")
