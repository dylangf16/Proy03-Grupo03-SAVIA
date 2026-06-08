"""Application layer for the SAVIA system.

Mirrors the UML ``Aplicacion`` class: the façade the user interacts with. It
*queries/configures* the :class:`Controller`, *shows* sensor data and *sends*
the notifications the controller generates.
"""

from __future__ import annotations

from typing import List, Optional

from .controller import Controller
from .notification import Notification, NotificationSink


class Application:
    """User-facing façade over the controller (UML: ``Aplicacion``).

    Parameters
    ----------
    controller:
        The :class:`Controller` this application drives.
    notification_sink:
        Optional delivery function used by :meth:`send_notifications`. When
        omitted, notifications are printed to the console.
    """

    def __init__(
        self,
        controller: Controller,
        notification_sink: Optional[NotificationSink] = None,
    ) -> None:
        self.controller = controller
        self.notification_sink = notification_sink

    def show_data(self) -> str:
        """Return a readable snapshot of the current sensor readings.

        UML: ``mostrarDatos()``.
        """
        c = self.controller
        lines = [
            "=== SAVIA ===",
            f"Humedad : {c.soil}",
            f"Luz     : {c.light}",
            f"Tanque  : {c.water} ({c.water.classify_level()})",
            f"Bomba   : {c.pump}",
            f"LED     : {c.led}",
            f"Buzzer  : {c.buzzer}",
        ]
        report = "\n".join(lines)
        print(report)
        return report

    def send_notifications(self) -> List[Notification]:
        """Evaluate the controller and deliver the resulting notifications.

        UML: ``enviarNotificaciones()``.
        """
        notifications = self.controller.evaluate_all()
        for notification in notifications:
            notification.send(self.notification_sink)
        return notifications

    def adjust_thresholds(
        self,
        humedad_min: Optional[float] = None,
        humedad_max: Optional[float] = None,
        luz_min: Optional[float] = None,
        luz_max: Optional[float] = None,
        nivel_agua_min: Optional[float] = None,
    ) -> None:
        """Reconfigure the controller's thresholds (UML: ``ajustarUmbrales()``).

        Only the values explicitly provided are changed.
        """
        c = self.controller
        if humedad_min is not None:
            c.humedad_min = humedad_min
        if humedad_max is not None:
            c.humedad_max = humedad_max
        if luz_min is not None:
            c.luz_min = luz_min
        if luz_max is not None:
            c.luz_max = luz_max
        if nivel_agua_min is not None:
            c.nivel_agua_min = nivel_agua_min
