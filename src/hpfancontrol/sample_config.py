"""Helper to deploy the bundled sample configuration."""

from __future__ import annotations

from pathlib import Path

SAMPLE_CONFIG = """# Example HP fan control configuration
api:
  base_url: "https://hp.h.nanode.su"
  username: "fan"
  # Prefer storing secrets in a file with 0600 permissions
  password_file: "/etc/hpfancontrol/ilo_password"
  verify_ssl: true
  timeout: 5
  path: "/redfish/v1/Chassis/1/Thermal"

controller:
  curve: balanced
  poll_seconds: 5
  min_percent: 15
  max_percent: 100
  min_step: 3
  filter_window: 3
  startup_boost_percent: 40
  startup_boost_seconds: 10
  emergency_temperature: 85
  emergency_percent: 100

sensors:
  paths:
    - "/sys/class/hwmon/hwmon*/temp1_input"
    - "/sys/class/thermal/thermal_zone*/temp"
  scale: 1000
  average_samples: 3
  # fallback_command: "sensors -u | awk '/temp1_input/ {print $2; exit}'"

curves:
  quiet-custom:
    - { temperature: 25, percent: 20 }
    - { temperature: 50, percent: 45 }
    - { temperature: 70, percent: 70 }
    - { temperature: 80, percent: 85 }
"""


def write_sample_config(destination: str | Path, overwrite: bool = False) -> Path:
    """Write the bundled sample configuration to *destination*."""

    dest = Path(destination).expanduser()
    if dest.exists() and not overwrite:
        raise FileExistsError(
            f"Refusing to overwrite existing file: {dest}. Pass overwrite=True or --force."
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(SAMPLE_CONFIG, encoding="utf-8")
    return dest
