"""SAVIA · servidor web "mi maceta".

Punto de entrada unico que:
  * sirve la interfaz web (``mimaceta.html`` + imagen de fondo),
  * recibe la telemetria del Arduino/ESP32 por ``POST /telemetry``
    (mismo contrato que ``src/sketch_may29a/telemetry_receiver.py``),
  * expone ``GET /api/state`` con los valores ya procesados que la
    interfaz consulta cada par de segundos para actualizarse en vivo.

Uso:
    python src/main.py            # escucha en http://localhost:5000
    python src/main.py --port 8000

El Arduino debe seguir enviando su POST a  http://<ip-del-pc>:5000/telemetry
"""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# --------------------------------------------------------------------------- #
# Configuracion / umbrales (reflejan src/savia/controller.py y el firmware)
# --------------------------------------------------------------------------- #
HOST = "0.0.0.0"
DEFAULT_PORT = 5000

# main.py vive en src/, los assets web estan en la raiz del repositorio.
REPO_ROOT = Path(__file__).resolve().parent.parent
HTML_FILE = REPO_ROOT / "interfaz_web/avance 1/mimaceta.html"
IMAGE_FILE = REPO_ROOT / "interfaz_web/imagen_cactus_bonito.jpeg"

# Mapeo de distancia (cm) -> porcentaje de tanque (limites de calibracion).
TANK_PCT_FULL_CM = 4.0    # <= 4 cm  => 100 %
TANK_PCT_EMPTY_CM = 14.0  # >= 14 cm =>   0 %

# Clasificacion discreta FULL / MID / EMPTY (coincide con el firmware).
WATER_FULL_MAX_CM = 5.0    # <= 5 cm  => FULL
WATER_EMPTY_MIN_CM = 13.0  # >= 13 cm => EMPTY

# Referencia para la barra de luz (1000 lux ~ barra llena).
LUX_FULL_REF = 1000.0

# Se considera "sin conexion" si no llega telemetria en este tiempo.
STALE_AFTER_S = 10.0

# Intervalo de riego automatico mostrado en el contador (segundos).
AUTO_IRRIGATION_INTERVAL_S = 2 * 3600 + 5 * 60 + 38  # 2 h 5 min 38 s


# --------------------------------------------------------------------------- #
# Estado compartido (protegido por lock; el servidor es multihilo)
# --------------------------------------------------------------------------- #
class SaviaState:
    """Guarda la ultima lectura recibida y los umbrales configurables."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.last_payload: dict | None = None
        self.last_update_ts: float | None = None
        self.last_irrigation_ts: float = time.time()

        # Umbrales ajustables desde la UI ("Ajustar umbrales").
        self.humedad_min = 40.0
        self.humedad_max = 70.0
        self.luz_min = 200.0
        self.luz_max = 10000.0

    def update_telemetry(self, payload: dict) -> None:
        with self._lock:
            self.last_payload = payload
            self.last_update_ts = time.time()

    def set_thresholds(self, data: dict) -> None:
        with self._lock:
            for key in ("humedad_min", "humedad_max", "luz_min", "luz_max"):
                if data.get(key) is not None:
                    setattr(self, key, float(data[key]))

    def mark_irrigated(self) -> None:
        with self._lock:
            self.last_irrigation_ts = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            return self._build_state()

    # -- calculo del estado que consume la interfaz -------------------------- #
    def _build_state(self) -> dict:
        payload = self.last_payload or {}
        now = time.time()
        connected = (
            self.last_update_ts is not None
            and (now - self.last_update_ts) <= STALE_AFTER_S
        )

        soil = _as_float(payload.get("soil_moisture_pct"))
        lux = _as_float(payload.get("lux"))
        distance = _as_float(payload.get("distance_cm"))

        # --- Humedad ---
        hum_pct = soil
        hum_bar = _clamp(hum_pct if hum_pct is not None else 0, 0, 100)
        hum_color = "green" if (hum_pct is not None and hum_pct >= self.humedad_min) else "red"

        # --- Luz ---
        lux_bar = _clamp((lux / LUX_FULL_REF) * 100 if lux is not None else 0, 0, 100)
        if lux is None:
            lux_color = "red"
        elif lux < self.luz_min or lux > self.luz_max:
            lux_color = "orange"
        else:
            lux_color = "green"

        # --- Tanque (a partir de la distancia) ---
        if distance is None or distance < 0:
            tank_pct = None
            tank_level = "UNKNOWN"
        else:
            tank_pct = _clamp(
                (TANK_PCT_EMPTY_CM - distance)
                / (TANK_PCT_EMPTY_CM - TANK_PCT_FULL_CM) * 100,
                0, 100,
            )
            if distance <= WATER_FULL_MAX_CM:
                tank_level = "FULL"
            elif distance >= WATER_EMPTY_MIN_CM:
                tank_level = "EMPTY"
            else:
                tank_level = "MID"
        tank_color = {"FULL": "green", "MID": "orange", "EMPTY": "red"}.get(tank_level, "red")

        # --- Estado actual (refleja Controller.evaluate_*) ---
        alert, message, severity = self._evaluate(hum_pct, lux, tank_level)

        # --- Contador de riego automatico ---
        remaining = AUTO_IRRIGATION_INTERVAL_S - (
            (now - self.last_irrigation_ts) % AUTO_IRRIGATION_INTERVAL_S
        )

        return {
            "connected": connected,
            "device": payload.get("device", "—"),
            "humedad": {
                "value": _round(hum_pct), "bar": round(hum_bar), "color": hum_color,
            },
            "luz": {
                "value": _round(lux), "bar": round(lux_bar), "color": lux_color,
            },
            "tanque": {
                "value": _round(tank_pct), "bar": round(tank_pct or 0),
                "color": tank_color, "level": tank_level,
            },
            "estado": {"alert": alert, "message": message, "severity": severity},
            "thresholds": {
                "humedad_min": self.humedad_min, "humedad_max": self.humedad_max,
                "luz_min": self.luz_min, "luz_max": self.luz_max,
            },
            "auto_irrigation_remaining_s": round(remaining),
            "updated_at": (
                datetime.fromtimestamp(self.last_update_ts).strftime("%H:%M:%S")
                if self.last_update_ts else None
            ),
        }

    def _evaluate(self, hum, lux, tank_level) -> tuple[str, str, str]:
        """Devuelve (titulo_alerta, mensaje, severidad)."""
        if hum is None and lux is None:
            return ("Esperando datos del Arduino…",
                    "Aun no se ha recibido telemetria del dispositivo. "
                    "Verifica que el Arduino este enviando a /telemetry.",
                    "info")

        if hum is not None and hum < self.humedad_min:
            return ("Tu planta necesita agua.",
                    f"La humedad del suelo ({hum:.0f}%) esta por debajo del umbral "
                    f"configurado ({self.humedad_min:.0f}%). "
                    + ("El tanque tiene agua suficiente para un riego completo. "
                       "Podes regar manualmente o esperar al riego automatico."
                       if tank_level in ("FULL", "MID")
                       else "Atencion: el tanque esta bajo, rellenalo pronto."),
                    "warning")

        if tank_level == "EMPTY":
            return ("Tanque de agua vacio.",
                    "El nivel del tanque es bajo. Rellenalo para asegurar el "
                    "riego automatico.", "warning")

        if lux is not None and lux < self.luz_min:
            return ("Poca luz para tu planta.",
                    f"La iluminacion ({lux:.0f} lux) esta por debajo del minimo "
                    f"recomendado ({self.luz_min:.0f} lux).", "warning")

        if lux is not None and lux > self.luz_max:
            return ("Exceso de luz.",
                    f"La iluminacion ({lux:.0f} lux) supera el maximo "
                    f"recomendado ({self.luz_max:.0f} lux).", "warning")

        return ("Tu planta esta sana.",
                "Humedad, luz y nivel de agua dentro de los rangos configurados. "
                "No se requiere ninguna accion.", "ok")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _as_float(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _round(v):
    return round(v) if v is not None else None


STATE = SaviaState()


# --------------------------------------------------------------------------- #
# Handler HTTP
# --------------------------------------------------------------------------- #
class SaviaHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silencia el log por defecto
        return

    # -- GET ---------------------------------------------------------------- #
    def do_GET(self):
        if self.path in ("/", "/index.html", "/mimaceta.html"):
            self._send_file(HTML_FILE, "text/html; charset=utf-8")
        elif self.path == "/imagen_cactus_bonito.jpeg":
            self._send_file(IMAGE_FILE, "image/jpeg")
        elif self.path == "/api/state":
            self._send_json(STATE.snapshot())
        else:
            self._send(404, b"Not Found", "text/plain")

    # -- POST --------------------------------------------------------------- #
    def do_POST(self):
        if self.path == "/telemetry":
            payload = self._read_json()
            if payload is None:
                return
            STATE.update_telemetry(payload)
            self._log_telemetry(payload)
            self._send_json({"status": "ok"})
        elif self.path == "/api/irrigate":
            STATE.mark_irrigated()
            print(f"[{_now()}] Riego manual solicitado desde la interfaz")
            self._send_json({"status": "ok"})
        elif self.path == "/api/thresholds":
            payload = self._read_json()
            if payload is None:
                return
            STATE.set_thresholds(payload)
            print(f"[{_now()}] Umbrales actualizados: {payload}")
            self._send_json({"status": "ok", "thresholds": STATE.snapshot()["thresholds"]})
        else:
            self._send(404, b"Not Found", "text/plain")

    # -- utilidades --------------------------------------------------------- #
    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._send(400, b"Invalid JSON", "text/plain")
            return None

    def _log_telemetry(self, p: dict):
        print(
            f"[{_now()}] device={p.get('device', 'unknown')} "
            f"lux={p.get('lux')} distance_cm={p.get('distance_cm')} "
            f"soil_moisture_pct={p.get('soil_moisture_pct')} "
            f"soil_raw_adc={p.get('soil_raw_adc')} uptime_ms={p.get('uptime_ms', 'n/a')}"
        )

    def _send_file(self, path: Path, content_type: str):
        try:
            data = path.read_bytes()
        except OSError:
            self._send(404, b"File not found", "text/plain")
            return
        self._send(200, data, content_type)

    def _send_json(self, obj):
        self._send(200, json.dumps(obj).encode("utf-8"), "application/json")

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _local_ip() -> str:
    """IP local de la PC en la red (la que debe ir en SERVER_HOST del Arduino).

    Abre un socket UDP "hacia afuera" (sin enviar nada) solo para que el SO
    revele que interfaz/IP usaria para salir; es el metodo mas fiable cuando
    hay varias interfaces. Cae a 127.0.0.1 si no hay red.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Servidor web SAVIA · mi maceta")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"Puerto (por defecto {DEFAULT_PORT})")
    args = parser.parse_args()

    server = ThreadingHTTPServer((HOST, args.port), SaviaHandler)
    ip = _local_ip()
    print("=" * 56)
    print("  SAVIA · mi maceta")
    print(f"  Interfaz   ->  http://localhost:{args.port}/")
    print(f"  Telemetria ->  POST http://{ip}:{args.port}/telemetry")
    print()
    print("  >> IP para el Arduino (SERVER_HOST en el sketch):")
    print(f"        {ip}")
    print("  Ctrl+C para salir")
    print("=" * 56)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor…")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
