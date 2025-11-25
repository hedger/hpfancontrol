# HP Fan Control

Python daemon that keeps HP ProLiant chassis fans in check from inside a Proxmox LXC container. It reads CPU temperature files bind-mounted from the host, evaluates a fan curve (preset or custom), then sends `Oem.Hpe.FanPercentMinimum` PATCH requests to the iLO Redfish endpoint—the same command already verified manually.

## Features

- Built-in `quiet`, `balanced`, and `performance` curves plus arbitrary custom curves in YAML
- Tunable polling interval, duty limits, startup boost, optional temperature smoothing, and emergency override
- Works from unprivileged LXCs with read-only hwmon mounts
- `--once` testing mode and long-running daemon mode

## Installation (inside the LXC)

```bash
python3 -m venv /opt/hpfancontrol/.venv
source /opt/hpfancontrol/.venv/bin/activate
pip install --upgrade pip
pip install .
cp hpfancontrol.yaml.example /etc/hpfancontrol.yaml
chmod 600 /etc/hpfancontrol.yaml
```

Populate `/etc/hpfancontrol.yaml` with your iLO details and preferred curve. Keep credentials in `password_file` or `HPFANCONTROL_PASSWORD` instead of inline YAML.

Deploy the bundled sample configuration anywhere (add `--force` to overwrite):

```bash
hp-fancontrol --init-config /etc/hpfancontrol.yaml
```

## Built-in fan curves

| Name | Curve (°C → %) |
| --- | --- |
| `quiet` | 25→18, 40→28, 55→45, 70→65, 80→80 |
| `balanced` | 25→20, 40→35, 55→55, 70→75, 80→90 |
| `performance` | 20→35, 35→55, 50→75, 65→95, 75→100 |

Add more curves under the `curves` mapping (example below) and select them via `controller.curve`.

## Example configuration

```yaml
api:
  base_url: "https://hp.h.nanode.su"
  username: "fan"
  password_file: "/etc/hpfancontrol/ilo_password"
  verify_ssl: true
  timeout: 5

controller:
  curve: balanced
  poll_seconds: 5
  min_percent: 15
  max_percent: 100
  min_step: 3
  filter_window: 3  # moving average window (set to 1 to disable)
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
  average_mode: ema  # mean | ema
  ema_alpha: 0.3     # only used when average_mode=ema
  # fallback_command: "sensors -u | awk '/temp1_input/ {print $2; exit}'"

curves:
  custom-loud:
    - { temperature: 30, percent: 40 }
    - { temperature: 60, percent: 75 }
    - { temperature: 75, percent: 100 }
```

Successful Redfish responses contain `Base.1.18.Success`, identical to the manually verified `curl` call.

## Making host CPU temperature available in the LXC

1. On the Proxmox host note the container ID (CTID) and edit `/etc/pve/lxc/<CTID>.conf`.
2. Bind the relevant sysfs trees read-only (adjust paths as needed):
   ```
   lxc.mount.entry: /sys/class/hwmon sys/class/hwmon none bind,ro,0 0
   lxc.mount.entry: /sys/devices/platform/coretemp.0 sys/devices/platform/coretemp.0 none bind,ro,0 0
   ```
3. Permit read access to the hwmon character devices (replace the major if your hwmon nodes differ—check with `stat`):
   ```
   lxc.cgroup2.devices.allow: c 242:* r
   ```
4. Restart the container: `pct stop <CTID> && pct start <CTID>`.
5. Inside the container confirm values exist: `cat /sys/class/hwmon/hwmon*/temp1_input`.

If sysfs cannot be mounted, install `lm-sensors` inside the guest and configure `fallback_command` to emit a Celsius value per invocation. When noisy readings cause fan hunting, increase `average_samples` for per-read smoothing and raise `controller.filter_window` to average the last N polling cycles (set to 1 to disable).

## Daemonizing on Alpine Linux (OpenRC)

`/etc/init.d/hpfancontrol`:

```sh
#!/sbin/openrc-run

command="/opt/hpfancontrol/.venv/bin/hp-fancontrol"
command_args="--config /etc/hpfancontrol.yaml"
command_user="fanctl:fanctl"
pidfile="/run/hpfancontrol.pid"
name="HP Fan Control"
command_background=yes

depend() {
	need net
	use dns logger
}

start_pre() {
	checkpath --directory --owner "${command_user}" --mode 0750 /run
}
```

Enable it and add to default runlevel:

```bash
chmod +x /etc/init.d/hpfancontrol
rc-update add hpfancontrol default
rc-service hpfancontrol start
```

`command_background=yes` makes OpenRC's start-stop-daemon keep the Python process in the background without needing it to fork itself. Adjust the virtualenv path or service account to match your deployment.

## Running

- Single iteration for validation:
  ```bash
  HPFANCONTROL_LOG=DEBUG hp-fancontrol --once --config /etc/hpfancontrol.yaml
  ```
- Continuous daemon (default loop):
  ```bash
  hp-fancontrol --config /etc/hpfancontrol.yaml
  ```

Logs follow `%(asctime)s %(levelname)s %(name)s: %(message)s`; change verbosity with `--log-level` or the `HPFANCONTROL_LOG` environment variable.

### systemd unit example (inside the container)

`/etc/systemd/system/hpfancontrol.service`:

```
[Unit]
Description=HP Fan Control
After=network-online.target

[Service]
ExecStart=/opt/hpfancontrol/.venv/bin/hp-fancontrol --config /etc/hpfancontrol.yaml
WorkingDirectory=/opt/hpfancontrol
Restart=on-failure
Environment=HPFANCONTROL_LOG=INFO

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
systemctl daemon-reload
systemctl enable --now hpfancontrol.service
```

## Troubleshooting

- Run with `--log-level DEBUG` to see sensor readings and HTTP responses.
- Validate the container can hit iLO with the original curl command (matching credentials used in the YAML file).
- Ensure the password file is readable only by root to prevent iLO credential leaks.
