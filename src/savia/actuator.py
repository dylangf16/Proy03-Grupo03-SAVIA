"""Actuator models for the SAVIA system.

These classes mirror the UML diagram (`Actuador` and its subclasses) but in
English. Every actuator keeps an on/off ``state`` and exposes
``activate()``/``deactivate()``.
"""

from __future__ import annotations


class Actuator:
    """Base class for every actuator (UML: ``Actuador``).

    Attributes
    ----------
    name:
        Human readable identifier used in logs and notifications.
    state:
        ``True`` when the actuator is active, ``False`` otherwise.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.state: bool = False

    def activate(self) -> None:
        """Turn the actuator on (UML: ``activar()``)."""
        self.state = True

    def deactivate(self) -> None:
        """Turn the actuator off (UML: ``desactivar()``)."""
        self.state = False

    def __str__(self) -> str:
        return f"{self.name}={'ON' if self.state else 'OFF'}"


class WaterPump(Actuator):
    """Irrigation water pump (UML: ``BombaAgua``)."""

    def __init__(self, name: str = "water_pump") -> None:
        super().__init__(name)


class Led(Actuator):
    """Status LED (UML: ``Led``). Adds a configurable color."""

    def __init__(self, name: str = "led", color: str = "green") -> None:
        super().__init__(name)
        self.color = color

    def change_color(self, color: str) -> None:
        """Set a new LED color (UML: ``cambiarColor()``)."""
        self.color = color

    def __str__(self) -> str:
        return f"{self.name}({self.color})={'ON' if self.state else 'OFF'}"


class Buzzer(Actuator):
    """Audible alarm (UML: ``Buzzer``)."""

    def __init__(self, name: str = "buzzer") -> None:
        super().__init__(name)

    def emit_alert(self) -> None:
        """Start the alarm (UML: ``emitirAlerta()``)."""
        self.activate()

    def stop(self) -> None:
        """Silence the alarm (UML: ``detener()``)."""
        self.deactivate()
