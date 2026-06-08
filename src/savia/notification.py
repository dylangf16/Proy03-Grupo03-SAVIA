"""Notification model for the SAVIA system.

Mirrors the UML diagram (``Notificacion`` and the ``TipoAlerta`` enum) but in
English. A :class:`Notification` couples a human readable ``message`` with an
:class:`AlertType` and knows how to ``send()`` itself.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Callable, Optional


class AlertType(Enum):
    """Kind of alert a notification carries (UML: ``TipoAlerta``)."""

    RIEGO = "RIEGO"  # Irrigation related (soil moisture / pump).
    LUZ = "LUZ"  # Light related (illuminance out of range).
    TANQUE = "TANQUE"  # Water tank level related.


# Type of the sink invoked to actually deliver a notification.
NotificationSink = Callable[["Notification"], None]


class Notification:
    """A message addressed to the user (UML: ``Notificacion``).

    Attributes
    ----------
    message:
        Human readable text shown to the user (UML: ``mensaje``).
    type:
        Category of the alert (UML: ``tipo: TipoAlerta``).
    timestamp:
        Moment the notification was created.
    sent:
        ``True`` once :meth:`send` has been called.
    """

    def __init__(self, message: str, type: AlertType) -> None:
        self.message = message
        self.type = type
        self.timestamp = datetime.now()
        self.sent = False

    def send(self, sink: Optional[NotificationSink] = None) -> None:
        """Deliver the notification (UML: ``enviar()``).

        The optional ``sink`` lets the caller (typically :class:`Application`)
        decide how the message is delivered. When omitted, the notification is
        printed to the console.
        """
        if sink is not None:
            sink(self)
        else:
            print(str(self))
        self.sent = True

    def __str__(self) -> str:
        stamp = self.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        return f"[{stamp}] {self.type.value}: {self.message}"
