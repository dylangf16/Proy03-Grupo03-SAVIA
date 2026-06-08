"""Decision logic for the SAVIA system.

Mirrors the UML ``Controlador`` class: it *monitors* the sensors, *controls*
the actuators and *generates* notifications. The controller holds the
thresholds used to decide when to irrigate, warn about light or report a low
water tank.
"""

from __future__ import annotations

from typing import List

from .actuator import Buzzer, Led, WaterPump
from .notification import AlertType, Notification
from .sensor import LightSensor, SoilMoistureSensor, UltrasonicSensor


class Controller:
    """Evaluates sensor readings and drives actuators (UML: ``Controlador``).

    Parameters
    ----------
    soil, light, water:
        Sensors the controller monitors (UML: ``monitorea Sensores``).
    pump, led, buzzer:
        Actuators the controller drives (UML: ``controla Actuador``).
    Thresholds (UML attributes):
        ``humedad_min`` / ``humedad_max`` -- soil moisture percentage band.
        ``luz_min`` / ``luz_max`` -- ambient light band in lux.
        ``nivel_agua_min`` -- minimum acceptable tank level (cm of headroom).
    """

    def __init__(
        self,
        soil: SoilMoistureSensor,
        light: LightSensor,
        water: UltrasonicSensor,
        pump: WaterPump,
        led: Led,
        buzzer: Buzzer,
        humedad_min: float = 30.0,
        humedad_max: float = 70.0,
        luz_min: float = 200.0,
        luz_max: float = 10000.0,
        nivel_agua_min: float = 11.0,
    ) -> None:
        self.soil = soil
        self.light = light
        self.water = water
        self.pump = pump
        self.led = led
        self.buzzer = buzzer

        self.humedad_min = humedad_min
        self.humedad_max = humedad_max
        self.luz_min = luz_min
        self.luz_max = luz_max
        self.nivel_agua_min = nivel_agua_min

        # Notifications generated during the last evaluation cycle.
        self.notifications: List[Notification] = []

    # -- evaluation steps (UML: evaluarHumedad / evaluarLuz / evaluarNivelAgua)

    def evaluate_moisture(self) -> None:
        """Check soil moisture and irrigate if it dropped below the minimum.

        UML: ``evaluarHumedad()``.
        """
        value = self.soil.read_sensor()
        if value is None:
            return
        if value < self.humedad_min:
            self.irrigate()
            self._notify(
                AlertType.RIEGO,
                f"Humedad baja ({value:.0f}%) -- riego activado",
            )
        elif value >= self.humedad_max and self.pump.state:
            self.pump.deactivate()
            self._notify(
                AlertType.RIEGO,
                f"Humedad suficiente ({value:.0f}%) -- riego detenido",
            )

    def evaluate_light(self) -> None:
        """Check ambient light and warn when it is out of the desired band.

        UML: ``evaluarLuz()``.
        """
        value = self.light.read_sensor()
        if value is None:
            return
        if value < self.luz_min:
            self._notify(AlertType.LUZ, f"Poca luz ({value:.0f} lux)")
        elif value > self.luz_max:
            self._notify(AlertType.LUZ, f"Exceso de luz ({value:.0f} lux)")

    def evaluate_water_level(self) -> None:
        """Check the tank level and alert (buzzer + notification) if it is low.

        UML: ``evaluarNivelAgua()``. A larger distance means a lower water
        level, so the tank is low when the reading exceeds ``nivel_agua_min``.
        """
        value = self.water.read_sensor()
        if value is None or value < 0.0:
            return
        if value >= self.nivel_agua_min:
            self.buzzer.emit_alert()
            self._notify(
                AlertType.TANQUE,
                f"Nivel de agua bajo ({self.water.classify_level()})",
            )
        else:
            self.buzzer.stop()

    # -- actuation (UML: riego())

    def irrigate(self) -> None:
        """Activate the pump to water the plant (UML: ``riego()``)."""
        self.pump.activate()
        self.led.change_color("blue")
        self.led.activate()

    # -- orchestration

    def evaluate_all(self) -> List[Notification]:
        """Run the three evaluations and return the notifications produced."""
        self.notifications = []
        self.evaluate_moisture()
        self.evaluate_light()
        self.evaluate_water_level()
        return self.notifications

    def _notify(self, type: AlertType, message: str) -> None:
        """Generate a notification (UML: ``Controlador genera Notificacion``)."""
        self.notifications.append(Notification(message, type))
