"""Fixed stdio-to-Unix-socket transport for the agentic_dev MCP server."""

import socket
import sys
import threading
import time


def main() -> None:
    connection = socket.socket(socket.AF_UNIX)
    for attempt in range(50):
        try:
            connection.connect("/ipc/mcp.sock")
            break
        except (FileNotFoundError, ConnectionRefusedError):
            if attempt == 49:
                raise SystemExit("work server unavailable")
            time.sleep(0.1)

    def receive() -> None:
        with connection.makefile("rb") as incoming:
            for line in incoming:
                sys.stdout.buffer.write(line)
                sys.stdout.buffer.flush()

    reader = threading.Thread(target=receive, daemon=True)
    reader.start()
    try:
        for line in sys.stdin.buffer:
            connection.sendall(line)
    finally:
        connection.shutdown(socket.SHUT_WR)
        reader.join()
        connection.close()


if __name__ == "__main__":
    main()
