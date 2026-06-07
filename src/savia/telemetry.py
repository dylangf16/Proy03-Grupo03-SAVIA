"""Telemetry receiver for the SAVIA system.

Object-oriented rewrite of ``sketch_may29a/telemetry_receiver.py``: an HTTP
server that listens for JSON telemetry posted by the ESP32/Arduino device on
``POST /telemetry`` and exposes each payload as a :class:`TelemetryReading`.

A user-supplied callback receives every reading, so the rest of the system
(sensors, controller, notifications) can react to incoming data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable, Optional


@dataclass
class TelemetryReading:
    """A single telemetry payload received from the device."""

    timestamp: str
    device: str
    distance_cm: Optional[float] = None
    lux: Optional[float] = None
    white: Optional[float] = None
    soil_raw_adc: Optional[int] = None
    soil_moisture_pct: Optional[float] = None
    soil_do: Optional[int] = None
    uptime_ms: Optional[int] = None

    @classmethod
    def from_payload(cls, payload: dict) -> "TelemetryReading":
        """Build a reading from a decoded JSON payload."""
        return cls(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            device=payload.get("device", "unknown"),
            distance_cm=payload.get("distance_cm"),
            lux=payload.get("lux"),
            white=payload.get("white"),
            soil_raw_adc=payload.get("soil_raw_adc"),
            soil_moisture_pct=payload.get("soil_moisture_pct"),
            soil_do=payload.get("soil_do"),
            uptime_ms=payload.get("uptime_ms"),
        )

    def has_measurements(self) -> bool:
        """True when at least one of the main sensor fields is present."""
        return any(
            v is not None
            for v in (self.lux, self.distance_cm, self.soil_moisture_pct)
        )

    def __str__(self) -> str:
        return (
            f"[{self.timestamp}] device={self.device} "
            f"lux={self.lux} white={self.white} "
            f"distance_cm={self.distance_cm} "
            f"soil_moisture_pct={self.soil_moisture_pct} "
            f"soil_raw_adc={self.soil_raw_adc} soil_do={self.soil_do} "
            f"uptime_ms={self.uptime_ms}"
        )


# Type of the callback invoked for every received reading.
ReadingCallback = Callable[[TelemetryReading], None]


class Telemetry:
    """HTTP server that receives telemetry and dispatches it to a callback.

    Parameters
    ----------
    host, port:
        Address to bind the HTTP server to.
    path:
        URL path accepted for telemetry POSTs.
    on_reading:
        Optional callback invoked with each :class:`TelemetryReading`. When not
        provided, readings are printed to the console (legacy behavior).
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5000,
        path: str = "/telemetry",
        on_reading: Optional[ReadingCallback] = None,
    ) -> None:
        self.host = host
        self.port = port
        self.path = path
        self.on_reading = on_reading or self._default_print
        self.last_reading: Optional[TelemetryReading] = None
        self._server: Optional[HTTPServer] = None

    @staticmethod
    def _default_print(reading: TelemetryReading) -> None:
        if reading.has_measurements():
            print(reading)
        else:
            print(f"[{reading.timestamp}] device={reading.device} (no measurements)")

    def handle_reading(self, reading: TelemetryReading) -> None:
        """Store and dispatch a freshly received reading."""
        self.last_reading = reading
        self.on_reading(reading)

    def _make_handler(self):
        telemetry = self

        class TelemetryHandler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):  # noqa: N802 - keep stdlib name
                # Silence default HTTP logs to keep the console clean.
                return

            def do_POST(self):  # noqa: N802 - required stdlib method name
                if self.path != telemetry.path:
                    self.send_response(404)
                    self.end_headers()
                    self.wfile.write(b"Not Found")
                    return

                content_length = int(self.headers.get("Content-Length", "0"))
                raw_body = self.rfile.read(content_length)

                try:
                    payload = json.loads(raw_body.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"Invalid JSON")
                    return

                telemetry.handle_reading(TelemetryReading.from_payload(payload))

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

        return TelemetryHandler

    def serve_forever(self) -> None:
        """Start the server and block until interrupted."""
        self._server = HTTPServer((self.host, self.port), self._make_handler())
        print(f"Listening on http://{self.host}:{self.port}{self.path}")
        print("Press Ctrl+C to exit")
        try:
            self._server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping server...")
        finally:
            self._server.server_close()


def main() -> None:
    Telemetry().serve_forever()


if __name__ == "__main__":
    main()
