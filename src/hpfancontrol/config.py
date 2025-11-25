"""Configuration dataclasses and YAML loader."""

from __future__ import annotations

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml


DEFAULT_CONFIG_PATHS: Sequence[Path] = (
    Path("/etc/hpfancontrol.yaml"),
    Path("/etc/hpfancontrol/config.yaml"),
    Path("./hpfancontrol.yaml"),
    Path("./fancontrol.yaml"),
)

DEFAULT_SENSOR_PATHS = [
    "/sys/class/hwmon/hwmon0/temp1_input",
    "/sys/class/thermal/thermal_zone0/temp",
]


@dataclass(slots=True)
class CurvePoint:
    """Single coordinate in a fan curve."""

    temperature: float
    percent: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.percent <= 100.0:
            raise ValueError("Fan percent must stay between 0 and 100")
        if self.temperature < -40.0:
            raise ValueError("Temperature points look invalid")


@dataclass(slots=True)
class ApiConfig:
    """How to reach the HP iLO Redfish endpoint."""

    base_url: str
    username: str
    password: str | None = None
    password_file: str | None = None
    password_env: str = "HPFANCONTROL_PASSWORD"
    path: str = "/redfish/v1/Chassis/1/Thermal"
    timeout: float = 10.0
    verify_ssl: bool = True

    def resolved_password(self) -> str:
        if self.password:
            return self.password
        if self.password_file:
            return Path(self.password_file).expanduser().read_text(encoding="utf-8").strip()
        if self.password_env:
            env_val = os.getenv(self.password_env)
            if env_val:
                return env_val
        raise RuntimeError(
            "API password missing. Set password, password_file, or password_env."
        )


@dataclass(slots=True)
class SensorConfig:
    """Where CPU temperature readings should be sourced from."""

    paths: list[str] = field(default_factory=lambda: list(DEFAULT_SENSOR_PATHS))
    scale: float | None = 1000.0
    average_samples: int = 1
    fallback_command: list[str] | None = None


@dataclass(slots=True)
class ControllerSettings:
    """Loop tuning parameters."""

    curve: str = "balanced"
    poll_seconds: float = 5.0
    min_percent: float = 10.0
    max_percent: float = 100.0
    min_step: float = 2.0
    startup_boost_percent: float = 40.0
    startup_boost_seconds: float = 10.0
    emergency_temperature: float = 85.0
    emergency_percent: float = 100.0
    log_every_n_samples: int = 6


@dataclass(slots=True)
class DaemonConfig:
    """Complete configuration consumed by the daemon."""

    api: ApiConfig
    controller: ControllerSettings
    sensors: SensorConfig
    custom_curves: dict[str, list[CurvePoint]] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "DaemonConfig":
        return cls(
            api=_parse_api(data.get("api", {})),
            controller=_parse_controller(data.get("controller", {})),
            sensors=_parse_sensors(data.get("sensors", {})),
            custom_curves=_parse_curve_map(data.get("curves", {})),
        )


def load_config(path: str | os.PathLike[str] | None = None) -> DaemonConfig:
    """Load YAML configuration, defaulting to known search locations."""

    config_path = _resolve_config_path(path)
    if not config_path:
        raise FileNotFoundError("No configuration file found. Create hpfancontrol.yaml.")
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return DaemonConfig.from_mapping(data)


def _resolve_config_path(custom_path: str | os.PathLike[str] | None) -> Path | None:
    if custom_path:
        candidate = Path(custom_path).expanduser()
        return candidate if candidate.exists() else None
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate
    return None


def _parse_api(data: dict[str, Any]) -> ApiConfig:
    if "base_url" not in data or "username" not in data:
        raise ValueError("api.base_url and api.username are required")
    return ApiConfig(
        base_url=data["base_url"],
        username=data["username"],
        password=data.get("password"),
        password_file=data.get("password_file"),
        password_env=data.get("password_env", "HPFANCONTROL_PASSWORD"),
        path=data.get("path", "/redfish/v1/Chassis/1/Thermal"),
        timeout=float(data.get("timeout", 10.0)),
        verify_ssl=bool(data.get("verify_ssl", True)),
    )


def _parse_controller(data: dict[str, Any]) -> ControllerSettings:
    return ControllerSettings(
        curve=data.get("curve", "balanced"),
        poll_seconds=float(data.get("poll_seconds", data.get("poll_interval", 5.0))),
        min_percent=float(data.get("min_percent", 10.0)),
        max_percent=float(data.get("max_percent", 100.0)),
        min_step=float(data.get("min_step", data.get("change_threshold", 2.0))),
        startup_boost_percent=float(data.get("startup_boost_percent", 40.0)),
        startup_boost_seconds=float(data.get("startup_boost_seconds", 10.0)),
        emergency_temperature=float(data.get("emergency_temperature", 85.0)),
        emergency_percent=float(data.get("emergency_percent", 100.0)),
        log_every_n_samples=int(data.get("log_every_n_samples", 6)),
    )


def _parse_sensors(data: dict[str, Any]) -> SensorConfig:
    paths = data.get("files") or data.get("paths") or None
    if paths is not None and not isinstance(paths, Iterable):
        raise TypeError("sensors.paths must be an iterable of filesystem paths")
    command = data.get("fallback_command")
    if isinstance(command, str):
        command = shlex.split(command)
    if "scale" in data:
        scale_value = data.get("scale")
        scale = None if scale_value is None else float(scale_value)
    else:
        scale = 1000.0
    return SensorConfig(
        paths=list(paths) if paths else list(DEFAULT_SENSOR_PATHS),
        scale=scale,
        average_samples=int(data.get("average_samples", 1)),
        fallback_command=command,
    )


def _parse_curve_map(data: dict[str, Any]) -> dict[str, list[CurvePoint]]:
    curves: dict[str, list[CurvePoint]] = {}
    for name, raw_points in data.items():
        curves[name.lower()] = [_point_from(item) for item in raw_points]
    return curves


def _point_from(item: dict[str, Any]) -> CurvePoint:
    if "temp" in item:
        temp = item["temp"]
    else:
        temp = item["temperature"]
    percent = item.get("percent", item.get("fan"))
    if percent is None:
        raise ValueError("Curve points require a 'percent' value")
    return CurvePoint(float(temp), float(percent))

