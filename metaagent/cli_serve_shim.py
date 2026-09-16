"""Named metaagent CLI; the HTTP service only exposes durable records."""
from __future__ import annotations
import argparse
import sys

def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] == 'serve':
        parser = argparse.ArgumentParser(description='Serve metaagent history and MCP; never schedule reviews')
        parser.add_argument('--host', default='127.0.0.1')
        parser.add_argument('--port', type=int, default=8768)
        parser.add_argument('--state-dir')
        args = parser.parse_args(values[1:])
        from pathlib import Path
        import uvicorn
        from rl_move.overseer.server import create_app
        app = create_app(state_dir=Path(args.state_dir) if args.state_dir else None)
        uvicorn.run(app, host=args.host, port=args.port, access_log=False)
        return 0
    from rl_move.overseer.__main__ import main as engine_main
    return engine_main(values)

if __name__ == '__main__':
    raise SystemExit(main())
