"""Enable ``python -m agentcore`` as an alias for the ``agent`` CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
