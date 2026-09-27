"""Run the private API and public Streamlit UI in one deployable container."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    env = os.environ.copy()
    api_port = env.get("OPSPILOT_INTERNAL_API_PORT", "8000")
    env["OPSPILOT_API_URL"] = f"http://127.0.0.1:{api_port}"
    env.setdefault("APP_ENV", "development")
    env["DATABASE_PATH"] = env.get("DATABASE_PATH", "/tmp/trustmesh/trustmesh.sqlite3")
    env.setdefault("DATA_DIR", "/app/data")
    port = env.get("PORT", "8080")

    api = subprocess.Popen([
        sys.executable, "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1", "--port", api_port,
    ], env=env)
    ui = None

    def shutdown(signum=None, frame=None):
        del signum, frame
        for process in (ui, api):
            if process and process.poll() is None:
                process.terminate()
        for process in (ui, api):
            if process and process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if api.poll() is not None:
            raise RuntimeError(f"TrustMesh API exited during startup (code {api.returncode})")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{api_port}/health", timeout=2) as response:
                if response.status == 200:
                    break
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    else:
        shutdown()
        raise RuntimeError("TrustMesh API did not become healthy within 60 seconds")

    ui = subprocess.Popen([
        sys.executable, "-m", "streamlit", "run", "frontend/streamlit_app.py",
        "--server.address=0.0.0.0", f"--server.port={port}",
        "--server.headless=true", "--browser.gatherUsageStats=false",
    ], env=env)
    while True:
        if api.poll() is not None or ui.poll() is not None:
            api_code = api.poll()
            ui_code = ui.poll()
            shutdown()
            return api_code if api_code not in (None, 0) else (ui_code or 0)
        time.sleep(1)


if __name__ == "__main__":
    raise SystemExit(main())
