"""Console script entry point."""

from __future__ import annotations

from . import daemon


def main() -> int:
    """Delegate to daemon module."""

    return daemon.main()


if __name__ == "__main__":
    raise SystemExit(main())
