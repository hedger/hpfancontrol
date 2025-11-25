"""HTTP client for the HP iLO Redfish fan controls."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .config import ApiConfig

LOG = logging.getLogger(__name__)


class FanCommandError(RuntimeError):
	"""Raised when the controller cannot update the fan settings."""


class RedfishFanClient:
	"""Minimal PATCH client for the HP OEM fan endpoint."""

	def __init__(self, config: ApiConfig) -> None:
		self._config = config
		self._session = requests.Session()
		self._url = f"{config.base_url.rstrip('/')}{config.path}"
		self._auth = (config.username, config.resolved_password())

	def set_min_percent(self, percent: float) -> dict[str, Any]:
		value = int(round(percent))
		payload = {"Oem": {"Hpe": {"FanPercentMinimum": value}}}
		LOG.debug("Posting fan percent %d to %s", value, self._url)
		response = self._session.patch(
			self._url,
			json=payload,
			timeout=self._config.timeout,
			verify=self._config.verify_ssl,
			auth=self._auth,
			headers={"content-type": "application/json"},
		)
		if not response.ok:
			raise FanCommandError(
				f"Fan update failed: {response.status_code} {response.text}"
			)
		try:
			data = response.json()
		except ValueError as exc:  # noqa: PERF203
			raise FanCommandError("Fan update response was not JSON") from exc
		_log_extended_info(data)
		return data

	def close(self) -> None:
		self._session.close()


def _log_extended_info(data: dict[str, Any]) -> None:
	info = data.get("@Message.ExtendedInfo") or []
	for entry in info:
		if entry.get("MessageId", "").endswith("Success"):
			LOG.debug("iLO success: %s", entry)
		else:
			LOG.warning("iLO message: %s", entry)
