'''Wave-1 live probe: start two uvicorn servers and assert the auth contract.'''
import os
import subprocess
import sys
import time

import httpx

PY = sys.executable
API_DIR = r"c:\MIHA\Agentic_Mess\services\api"
ENV_BASE = {
    **os.environ,
    "HARNESS_DATABASE_URL": "postgresql+psycopg://harness:harness@localhost:15432/harness",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def wait_healthy(port: int) -> None:
    for _ in range(120):
        try:
            if httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=2).status_code == 200:
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"server on {port} never became healthy")


def start(port: int, token: str) -> subprocess.Popen:
    env = dict(ENV_BASE)
    if token:
        env["HARNESS_API_TOKEN"] = token
    proc = subprocess.Popen(
        [PY, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=API_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_healthy(port)
    return proc


def main() -> int:
    failures: list[str] = []

    # A: default local mode — auth disabled
    a = start(8020, "")
    try:
        code = httpx.get("http://127.0.0.1:8020/api/projects", timeout=10).status_code
        print(f"A default-mode /api/projects no token -> {code} (expect 200)")
        if code != 200:
            failures.append("A: default mode should be open")
    finally:
        a.terminate()
        a.wait(timeout=10)

    # B: token mode — auth enforced
    token = "w1-live-probe-token"
    b = start(8021, token)
    try:
        base = "http://127.0.0.1:8021"
        code_health = httpx.get(f"{base}/healthz", timeout=10).status_code
        print(f"B token-mode /healthz no token -> {code_health} (expect 200)")
        if code_health != 200:
            failures.append("B: healthz must stay public")
        r = httpx.get(f"{base}/api/projects", timeout=10)
        print(f"B token-mode /api/projects no token -> {r.status_code} (expect 401)")
        if r.status_code != 401:
            failures.append("B: unauthenticated request was NOT rejected")
        r = httpx.get(
            f"{base}/api/projects",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        print(f"B token-mode /api/projects valid token -> {r.status_code} (expect 200)")
        if r.status_code != 200:
            failures.append("B: valid token was not accepted")
        r = httpx.get(
            f"{base}/api/projects", headers={"Authorization": "Bearer wrong"}, timeout=10
        )
        print(f"B token-mode /api/projects invalid token -> {r.status_code} (expect 401)")
        if r.status_code != 401:
            failures.append("B: invalid token was not rejected")
    finally:
        b.terminate()
        b.wait(timeout=10)

    if failures:
        print("WAVE1-LIVE-FAIL:", failures)
        return 1
    print("WAVE1-LIVE-PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
