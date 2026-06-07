"""Sensor models for the SAVIA system.

These classes mirror the UML diagram (`Sensores` and its subclasses) but in
English. Each sensor holds its latest reading (`value`) and exposes
`read_sensor()` to retrieve it. Values are normally fed from the telemetry
payloads received from the ESP32/Arduino device (see ``telemetry.py``).
"""

from __future__ import annotations


class Sensor:
    """Base class for every sensor (UML: ``Sensores``).

    Attributes
    ----------
    name:
        Human readable identifier used in logs and notifications.
    value:
        Latest reading. ``None`` until the first measurement arrives.
    unit:
        Measurement unit, only used for display purposes.
    """

    def __init__(self, name: str, unit: str = "") -> None:
        self.name = name
        self.value: float | None = None
        self.unit = unit

    def read_sensor(self) -> float | None:
        """Return the latest stored reading (UML: ``leerSensor()``)."""
        return self.value

    def update(self, value: float | None) -> float | None:
        """Store a new reading coming from telemetry and return it."""
        if value is not None:
            self.value = float(value)
        return self.value

    def __str__(self) -> str:
        if self.value is None:
            return f"{self.name}=n/a"
        return f"{self.name}={self.value:.1f}{self.unit}"


class SoilMoistureSensor(Sensor):
    """Soil humidity sensor (UML: ``SensorHumedad``).

    Reads a raw ADC value and converts it to a moisture percentage using the
    same air/water calibration as the firmware.
    """

    def __init__(
        self,
        name: str = "soil_moisture",
        air_value: int = 760,
        water_value: int = 390,
    ) -> None:
        super().__init__(name, unit="%")
        self.air_value = air_value
        self.water_value = water_value
        self.raw_value: int | None = None

    def raw_to_percent(self, raw: int) -> float:
        """Convert a raw ADC reading to a 0-100 moisture percentage."""
        if self.air_value == self.water_value:
            return -1.0
        pct = (self.air_value - raw) * 100.0 / (self.air_value - self.water_value)
        return max(0.0, min(100.0, pct))

    def update_from_raw(self, raw: int) -> float:
        """Store a raw ADC reading and derive the moisture percentage."""
        self.raw_value = int(raw)
        return self.update(self.raw_to_percent(self.raw_value)) or -1.0


class LightSensor(Sensor):
    """Ambient light sensor (UML: ``SensorLuz``). Stores illuminance in lux."""

    def __init__(self, name: str = "light") -> None:
        super().__init__(name, unit=" lux")
        self.white: float | None = None

    def update(self, value: float | None, white: float | None = None) -> float | None:
        if white is not None:
            self.white = float(white)
        return super().update(value)


class UltrasonicSensor(Sensor):
    """Ultrasonic water-level sensor (UML: ``SensorUS``).

    Stores the measured distance in centimeters and classifies the tank level.
    """

    FULL = "FULL"
    MID = "MID"
    EMPTY = "EMPTY"
    UNKNOWN = "UNKNOWN"

    def __init__(
        self,
        name: str = "water_level",
        full_max_cm: float = 7.0,
        mid_max_cm: float = 11.0,
    ) -> None:
        super().__init__(name, unit=" cm")
        self.full_max_cm = full_max_cm
        self.mid_max_cm = mid_max_cm

    def classify_level(self) -> str:
        """Map the latest distance reading to a tank level."""
        if self.value is None or self.value < 0.0:
            return self.UNKNOWN
        if self.value <= self.full_max_cm:
            return self.FULL
        if self.value >= self.mid_max_cm:
            return self.EMPTY
        return self.MID
