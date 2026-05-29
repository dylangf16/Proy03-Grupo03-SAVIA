import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "0.0.0.0"
PORT = 5000


class TelemetryHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silencia logs HTTP por defecto para mantener limpia la consola.
        return

    def do_POST(self):
        if self.path != "/telemetry":
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

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        device = payload.get("device", "unknown")
        distance_cm = payload.get("distance_cm")
        lux = payload.get("lux")
        white = payload.get("white")
        soil_raw_adc = payload.get("soil_raw_adc")
        soil_moisture_pct = payload.get("soil_moisture_pct")
        soil_do = payload.get("soil_do")
        uptime_ms = payload.get("uptime_ms", "n/a")

        if (
            lux is not None
            or distance_cm is not None
            or soil_moisture_pct is not None
        ):
            print(
                f"[{timestamp}] device={device} "
                f"lux={lux} white={white} "
                f"distance_cm={distance_cm} "
                f"soil_moisture_pct={soil_moisture_pct} soil_raw_adc={soil_raw_adc} soil_do={soil_do} "
                f"uptime_ms={uptime_ms}"
            )
        else:
            print(f"[{timestamp}] device={device} payload={payload}")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')


def main():
    server = HTTPServer((HOST, PORT), TelemetryHandler)
    print(f"Servidor escuchando en http://{HOST}:{PORT}/telemetry")
    print("Presiona Ctrl+C para salir")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDeteniendo servidor...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
