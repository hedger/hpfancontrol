"""Daemon entry point and CLI wiring."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
from pathlib import Path
from typing import Sequence

from .client import RedfishFanClient
from .config import load_config
from .controller import FanController
from .curves import resolve_curve
from .sample_config import write_sample_config
from .sensors import SensorReader


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and start the controller."""

    args = _parse_args(argv)
    _configure_logging(args.log_level)
    if args.init_config:
        return _handle_init_config(args.init_config, args.force)

    config = load_config(args.config)
    controller = _build_controller(config)

    if args.once:
        try:
            controller.run_once()
        finally:
            controller.close()
        return 0

    stop_event = threading.Event()
    _install_signal_handlers(stop_event)
    try:
        controller.run(stop_event)
    finally:
        controller.close()
    return 0


def _build_controller(config):
    from .config import DaemonConfig  # noqa: WPS433 (local import to avoid cycle)

    if not isinstance(config, DaemonConfig):
        raise TypeError("load_config must return DaemonConfig")

    client = RedfishFanClient(config.api)
    sensor = SensorReader(config.sensors)
    curve = resolve_curve(config.controller.curve, config.custom_curves)
    return FanController(client, sensor, config.controller, curve)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HP fan control daemon")
    parser.add_argument(
        "-c",
        "--config",
        help="Path to hpfancontrol YAML configuration",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read temperature and perform a single update",
    )
    parser.add_argument(
        "--init-config",
        metavar="PATH",
        help="Write the sample configuration to PATH and exit",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow overwriting files when used with --init-config",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("HPFANCONTROL_LOG", "INFO"),
        help="Python logging level (default: INFO)",
    )
    return parser.parse_args(argv)


def _configure_logging(level_name: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level_name.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def _handler(signum, _frame):  # noqa: ANN001
        logging.getLogger(__name__).info("Received signal %s, stopping", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def _handle_init_config(path: str, overwrite: bool) -> int:
    dest = Path(path).expanduser()
    try:
        write_sample_config(dest, overwrite=overwrite)
    except FileExistsError as exc:
        logging.getLogger(__name__).error("%s", exc)
        return 1
    logging.getLogger(__name__).info("Sample configuration written to %s", dest)
    return 0
