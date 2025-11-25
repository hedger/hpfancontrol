"""Temperature sensor discovery and reading utilities."""

from __future__ import annotations

import glob
import logging
from pathlib import Path
import subprocess
from typing import Iterable

from .config import SensorConfig

LOG = logging.getLogger(__name__)


class SensorReadError(RuntimeError):
    """Raised when no temperature value can be obtained."""


class SensorReader:
    """Read CPU temperature according to the configured sources."""

    def __init__(self, config: SensorConfig) -> None:
        self._config = config
        self._ema_value: float | None = None

    def read_celsius(self) -> float:
        values: list[float] = []
        for _ in range(max(1, self._config.average_samples)):
            value = self._read_once()
            values.append(value)
        if not values:
            raise SensorReadError("No CPU temperature sources were readable")
        sample = sum(values) / len(values)
        return self._apply_filter(sample)

    def _read_once(self) -> float:
        for path in _iter_sensor_paths(self._config.paths):
            value = _read_path(path, self._config.scale)
            if value is not None:
                return value
        if self._config.fallback_command:
            return self._read_from_command()
        raise SensorReadError("Unable to read CPU temperature from configured sources")

    def _read_from_command(self) -> float:
        result = subprocess.run(
            self._config.fallback_command,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SensorReadError(
                f"Temperature command failed ({result.returncode}): {result.stderr.strip()}"
            )
        try:
            value = float(result.stdout.strip())
        except ValueError as exc:  # noqa: PERF203
            raise SensorReadError("Fallback command output was not a float") from exc
        LOG.debug("Read %.2f°C from fallback command", value)
        return value

    def _apply_filter(self, sample: float) -> float:
        mode = (self._config.average_mode or "mean").lower()
        if mode == "ema":
            alpha = self._config.ema_alpha or 0.5
            if not 0 < alpha <= 1:
                LOG.warning("Invalid ema_alpha %.3f; defaulting to 0.5", alpha)
                alpha = 0.5
            if self._ema_value is None:
                self._ema_value = sample
            else:
                self._ema_value = alpha * sample + (1 - alpha) * self._ema_value
            LOG.debug("EMA filtered temp %.2f°C (alpha %.2f)", self._ema_value, alpha)
            return self._ema_value
        return sample


def _iter_sensor_paths(patterns: Iterable[str]) -> Iterable[str]:
    for pattern in patterns:
        # Allow either literal files or glob-style paths.
        matches = glob.glob(pattern)
        if not matches:
            yield pattern
        for match in sorted(matches):
            yield match


def _read_path(path: str, scale: float | None) -> float | None:
    try:
        raw = Path(path).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except PermissionError as exc:  # noqa: PERF203
        LOG.debug("Permission denied for sensor %s: %s", path, exc)
        return None
    try:
        value = float(raw)
    except ValueError:
        LOG.debug("Sensor %s returned non-float data: %s", path, raw)
        return None
    if scale:
        value /= scale
    elif value > 200:
        value /= 1000.0
    LOG.debug("Read %.2f°C from %s", value, path)
    return value
