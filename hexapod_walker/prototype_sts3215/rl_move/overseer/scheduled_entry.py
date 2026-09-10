"""Private credential loading for the operating system's deterministic timer."""
import json
import os
from pathlib import Path
import stat


def main():
    from .scheduler import main as scheduler_main
    path = Path(os.environ['METAAGENT_CREDENTIAL_FILE']).expanduser()
    if path.exists():
        mode = path.stat()
        if mode.st_uid != os.getuid() or stat.S_IMODE(mode.st_mode) & 0o077:
            raise ValueError('Reviewer credential file must be owned by this user with mode 0600')
        with path.open('rb') as stream:
            raw = stream.read(16385)
        if len(raw) > 16384:
            raise ValueError('Reviewer credential file exceeds bounded size')
        for key, value in json.loads(raw).items():
            if key in {'ANTHROPIC_API_KEY', 'OPENAI_API_KEY'} and isinstance(value, str):
                os.environ[key] = value
    return scheduler_main(['tick'])


if __name__ == '__main__':
    raise SystemExit(main())
