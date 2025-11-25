"""Fan curve utilities and built-in presets."""

from __future__ import annotations

from dataclasses import dataclass

from .config import CurvePoint


PRESET_CURVES: dict[str, list[CurvePoint]] = {
    "quiet": [
        CurvePoint(25, 18),
        CurvePoint(40, 28),
        CurvePoint(55, 45),
        CurvePoint(70, 65),
        CurvePoint(80, 80),
    ],
    "balanced": [
        CurvePoint(25, 20),
        CurvePoint(40, 35),
        CurvePoint(55, 55),
        CurvePoint(70, 75),
        CurvePoint(80, 90),
    ],
    "performance": [
        CurvePoint(20, 35),
        CurvePoint(35, 55),
        CurvePoint(50, 75),
        CurvePoint(65, 95),
        CurvePoint(75, 100),
    ],
}


@dataclass(slots=True)
class Curve:
    """Interpolates fan percent for a given temperature."""

    points: list[CurvePoint]

    def __post_init__(self) -> None:
        if not self.points:
            raise ValueError("Curve requires at least one point")
        self.points.sort(key=lambda point: point.temperature)

    def percent_for_temp(self, temperature: float) -> float:
        ordered = self.points
        if temperature <= ordered[0].temperature:
            return ordered[0].percent
        if temperature >= ordered[-1].temperature:
            return ordered[-1].percent
        for left, right in zip(ordered, ordered[1:]):
            if left.temperature <= temperature <= right.temperature:
                span = right.temperature - left.temperature
                if span == 0:
                    return right.percent
                ratio = (temperature - left.temperature) / span
                return left.percent + ratio * (right.percent - left.percent)
        return ordered[-1].percent


def resolve_curve(name: str, custom: dict[str, list[CurvePoint]] | None = None) -> Curve:
    """Return a curve by name, falling back to built-ins."""

    lowered = name.lower()
    if custom and lowered in custom:
        return Curve(list(custom[lowered]))
    preset = PRESET_CURVES.get(lowered)
    if not preset:
        raise ValueError(f"Unknown curve '{name}'")
    return Curve(list(preset))


def describe_curves(custom: dict[str, list[CurvePoint]] | None = None) -> dict[str, list[tuple[float, float]]]:
    """Return serialisable curve information for documentation."""

    data: dict[str, list[tuple[float, float]]] = {}
    for name, points in PRESET_CURVES.items():
        data[name] = [(point.temperature, point.percent) for point in points]
    if custom:
        for name, points in custom.items():
            data[name] = [(point.temperature, point.percent) for point in points]
    return data

