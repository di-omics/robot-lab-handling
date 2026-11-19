"""Read the current observation or make one command on a running local episode."""
import argparse
import json
import socket
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("action", nargs="?", help="One JSON object")
    args = parser.parse_args()
    request = json.loads(args.action) if args.action is not None else None
    latest = args.run / "latest.json"
    deadline = time.monotonic() + 90
    while not latest.exists() and time.monotonic() < deadline:
        time.sleep(.1)
    current = json.loads(latest.read_text())
    if request is None or "terminal" in current:
        print(json.dumps(current))
        return
    endpoint = (args.run / "socket.txt").read_text().strip()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(endpoint)
        client.sendall((json.dumps({"after": current["observation_index"], "action": request}) + "\n").encode())
        with client.makefile("rb") as incoming:
            result = incoming.readline()
    if not result:
        raise SystemExit("The server stopped before returning a reply; read latest.json before retrying.")
    print(result.decode().strip())


if __name__ == "__main__":
    main()
