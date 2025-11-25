"""Core controller loop implementation."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

from .client import FanCommandError, RedfishFanClient
from .config import ControllerSettings
from .curves import Curve
from .sensors import SensorReadError, SensorReader

LOG = logging.getLogger(__name__)


class FanController:
    """Poll sensors and post updates to the iLO fan endpoint."""

    def __init__(
        self,
        client: RedfishFanClient,
        sensor: SensorReader,
        settings: ControllerSettings,
        curve: Curve,
    ) -> None:
        self._client = client
        self._sensor = sensor
        self._settings = settings
        self._curve = curve
        self._last_percent: float | None = None
        self._iterations = 0
        self._startup_deadline = (
            time.monotonic() + settings.startup_boost_seconds
            if settings.startup_boost_seconds > 0
            else 0.0
        )
        self._filter = TemperatureFilter(settings.filter_window)

    def run(self, stop_event: threading.Event | None = None) -> None:
        """Run the fan loop until stop_event is set."""

        try:
            while not stop_event or not stop_event.is_set():
                started = time.monotonic()
                self._tick()
                _wait_for_next(started, self._settings.poll_seconds, stop_event)
        finally:
            self._client.close()

    def run_once(self) -> None:
        """Perform a single control loop iteration."""

        self._tick()

    def _tick(self) -> None:
        try:
            raw_temperature = self._sensor.read_celsius()
        except SensorReadError as exc:
            LOG.warning("No temperature reading: %s", exc)
            return

        temperature = self._filter.apply(raw_temperature)

        percent = self._compute_percent(temperature)
        self._iterations += 1

        if self._iterations % max(1, self._settings.log_every_n_samples) == 0:
            if temperature != raw_temperature:
                LOG.info(
                    "CPU %.1f°C (raw %.1f°C), target %.1f%%",
                    temperature,
                    raw_temperature,
                    percent,
                )
            else:
                LOG.info("CPU %.1f°C, target %.1f%%", temperature, percent)

        if not self._should_apply(percent):
            return

        try:
            self._client.set_min_percent(percent)
            self._last_percent = percent
            LOG.info("Updated fan minimum to %.1f%%", percent)
        except FanCommandError as exc:
            LOG.warning("Unable to update fan speed: %s", exc)

    def _compute_percent(self, temperature: float) -> float:
        if self._startup_deadline and time.monotonic() < self._startup_deadline:
            percent = max(self._settings.startup_boost_percent, self._settings.min_percent)
        else:
            percent = self._curve.percent_for_temp(temperature)
        percent = max(self._settings.min_percent, min(percent, self._settings.max_percent))
        if temperature >= self._settings.emergency_temperature:
            percent = max(percent, self._settings.emergency_percent)
        return float(int(round(percent)))

    def _should_apply(self, percent: float) -> bool:
        if self._last_percent is None:
            return True
        return abs(percent - self._last_percent) >= self._settings.min_step

    def close(self) -> None:
        self._client.close()


def _wait_for_next(
    started_at: float, poll_interval: float, stop_event: threading.Event | None
) -> None:
    elapsed = time.monotonic() - started_at
    sleep_for = max(0.0, poll_interval - elapsed)
    if stop_event:
        stop_event.wait(timeout=sleep_for)
    else:
        time.sleep(sleep_for)


class TemperatureFilter:
    """Simple moving average smoothing for temperature readings."""

    def __init__(self, window: int) -> None:
        self._window = max(1, int(window))
        self._values: deque[float] = deque(maxlen=self._window)

    def apply(self, value: float) -> float:
        if self._window == 1:
            return value
        self._values.append(value)
        if len(self._values) == 0:
            return value
        return sum(self._values) / len(self._values)
