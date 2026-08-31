"""Run the local browser control plane."""

from __future__ import annotations

import argparse
from pathlib import Path

from .web import create_server


def main() -> None:
    parser = argparse.ArgumentParser(description="JAWL VoiceCompanion Phase 1 server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--frontend", type=Path, default=None)
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.frontend)
    print(f"JAWL VoiceCompanion listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

