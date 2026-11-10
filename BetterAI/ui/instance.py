"""
Single-instance control.

The first Aria listens on a Unix socket. Launching Aria again (menu, autostart,
or the Ctrl+Alt+Space hotkey running `aria.sh --toggle`) doesn't start a second copy,
which would fight over the camera and mic. It sends a command to the running one instead:

    toggle  show/hide the text box (the hotkey)
    show    open the text box
    quit    shut Aria down
    capture open the quick capture box (Ctrl+Alt+N)
    ping    nothing; only checks that Aria is running (MyNotion's Start: she starts without the orb)
"""

import os
import socket
import threading

SOCKET_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", f"aria-{os.getuid()}.sock")
COMMANDS = ("toggle", "show", "quit", "capture", "ping")


def send(command: str) -> bool:
    """Send a command to a running Aria. Returns False if none is running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(SOCKET_PATH)
            s.sendall(command.encode())
        return True
    except OSError:
        return False


def listen(on_command):
    """Start the server in a daemon thread. on_command(cmd) is called from that thread."""
    if os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)  # left over from a crash (send() already failed, so nobody owns it)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCKET_PATH)
    os.chmod(SOCKET_PATH, 0o600)
    server.listen(4)

    def loop():
        while True:
            try:
                conn, _ = server.accept()
                with conn:
                    conn.settimeout(1.0)
                    cmd = conn.recv(64).decode(errors="ignore").strip()
                if cmd in COMMANDS:
                    on_command(cmd)
            except OSError:
                break

    threading.Thread(target=loop, daemon=True).start()
    return server


if __name__ == "__main__":
    # python -m ui.instance toggle  → exit 0 if a running Aria got it, 1 if none is running
    import sys
    sys.exit(0 if send(sys.argv[1] if len(sys.argv) > 1 else "show") else 1)
