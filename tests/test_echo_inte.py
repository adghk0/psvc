import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ECHO_SCRIPT = ROOT / "tests" / "echo_app.py"

def test_echo_and_graceful_exit():
    server = subprocess.Popen(
        [sys.executable, str(ECHO_SCRIPT), "server"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        time.sleep(0.5)

        client_input = "olleh\nexit\n"
        client_proc = subprocess.run(
            [sys.executable, str(ECHO_SCRIPT)],
            cwd=str(ROOT),
            input=client_input,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )

        client_out = client_proc.stdout
        client_err = client_proc.stderr

        print("=== client stdout ===")
        print(client_out)
        print("=== client stderr ===")
        print(client_err)

        server_out, server_err = server.communicate(timeout=10)

        print("=== server stdout ===")
        print(server_out)
        print("=== server stderr ===")
        print(server_err)

        assert client_proc.returncode == 0
        assert server.returncode == 0
        assert "olleh" in client_out or "olleh" in client_err
        assert "Status=Stopped" in server_out or "Status=Stopped" in server_err

    finally:
        if server.poll() is None:
            server.kill()
