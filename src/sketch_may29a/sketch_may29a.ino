#include <Arduino.h>
#include <Wire.h>
#include <WiFiS3.h>
#include "Adafruit_VEML7700.h"

// Implementacion base para Arduino UNO R4 WiFi:
// Lee humedad en A0 y activa bomba/relay en D2 mientras la humedad este baja.
// Ademas se conecta por WiFi y envia la telemetria de los sensores y el estado
// del motor por HTTP POST al servidor (telemetry_receiver.py).

// ---- Configuracion WiFi y servidor de telemetria ----
const char* WIFI_SSID = "DGF";
const char* WIFI_PASSWORD = "123456789";

// IP/host y puerto donde corre telemetry_receiver.py (HOST=0.0.0.0 PORT=5000).
// Usa la IP local de la PC que ejecuta el servidor, por ejemplo "192.168.1.50".
const char* SERVER_HOST = "10.177.158.85";
const uint16_t SERVER_PORT = 5000;
const char* SERVER_PATH = "/telemetry";
const char* DEVICE_NAME = "savia-uno-r4";

// Cada cuantos ms se reintenta conectar si se cae el WiFi.
const unsigned long WIFI_RETRY_INTERVAL_MS = 10000;
unsigned long lastWifiRetryMs = 0;

const int SOIL_ANALOG_PIN = A0;
const int MOTOR_PIN = 2;

// Sensor ultrasonico del tanque (HC-SR04)
const int US_TRIG_PIN = 5;
const int US_ECHO_PIN = 6;

// Sensor de luz ambiental Adafruit VEML7700 (I2C: SDA/SCL).
Adafruit_VEML7700 veml = Adafruit_VEML7700();
bool vemlReady = false;

// LEDs de estado de nivel de agua
const int LED_GREEN_PIN = 9;
const int LED_YELLOW_PIN = 10;
const int LED_RED_PIN = 11;

// Ajusta estos niveles segun tu modulo relay/transistor.
const int MOTOR_ACTIVE_LEVEL = HIGH;
const int MOTOR_INACTIVE_LEVEL = LOW;

// Diagnostico rapido: si esta en true, ignora el sensor y alterna el pin del motor.
const bool MOTOR_PIN_TEST_MODE = false;
const unsigned long MOTOR_PIN_TEST_INTERVAL_MS = 1000;

// Calibracion inicial para ADC de 10 bits (0-1023) en UNO R4.
// AIR_VALUE: lectura con sensor en aire (seco)
// WATER_VALUE: lectura con sensor en agua (humedo)
const int AIR_VALUE = 1000;
const int WATER_VALUE = 900;

// Histeresis para evitar encendido/apagado rapido.
const float MOISTURE_LOW_THRESHOLD = 35.0f;
const float MOISTURE_HIGH_THRESHOLD = 45.0f;

// Rangos solicitados para nivel de agua medido por distancia.
// FULL  : distancia <= 5 cm  (agua cerca del sensor, tanque lleno)
// EMPTY : distancia >= 13 cm (agua lejos, tanque vacio)
// MID   : entre 5 y 13 cm
const float WATER_FULL_MAX_CM = 5.0f;
const float WATER_MID_MAX_CM = 13.0f;

// Filtro ultrasónico: buffer + descarte de outliers.
const int US_BUFFER_SAMPLES = 7;
const float US_MAX_VALID_CM = 400.0f;

const unsigned long SAMPLE_INTERVAL_MS = 1000;
unsigned long lastSampleMs = 0;
bool motorOn = false;
unsigned long lastPinTestMs = 0;

enum WaterLevel {
  WATER_LEVEL_FULL,
  WATER_LEVEL_MID,
  WATER_LEVEL_LOW,
  WATER_LEVEL_UNKNOWN
};

int readSoilRaw() {
  long sum = 0;
  const int samples = 8;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(SOIL_ANALOG_PIN);
    delay(3);
  }
  return (int)(sum / samples);
}

float rawToMoisturePct(int raw) {
  if (AIR_VALUE == WATER_VALUE) {
    return -1.0f;
  }

  float pct = (float)(AIR_VALUE - raw) * 100.0f / (float)(AIR_VALUE - WATER_VALUE);
  if (pct < 0.0f) {
    pct = 0.0f;
  }
  if (pct > 100.0f) {
    pct = 100.0f;
  }
  return pct;
}

void setMotor(bool on) {
  motorOn = on;
  digitalWrite(MOTOR_PIN, on ? MOTOR_ACTIVE_LEVEL : MOTOR_INACTIVE_LEVEL);
}

void evaluateIrrigation(float moisturePct) {
  if (moisturePct < 0.0f) {
    setMotor(false);
    return;
  }

  if (!motorOn && moisturePct <= MOISTURE_LOW_THRESHOLD) {
    setMotor(true);
  } else if (motorOn && moisturePct >= MOISTURE_HIGH_THRESHOLD) {
    setMotor(false);
  }
}

float readDistanceCm() {
  digitalWrite(US_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(US_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(US_TRIG_PIN, LOW);

  unsigned long durationUs = pulseIn(US_ECHO_PIN, HIGH, 30000);
  if (durationUs == 0) {
    return -1.0f;
  }

  return (durationUs * 0.0343f) / 2.0f;
}

void sortFloatArray(float* values, int count) {
  for (int i = 0; i < count - 1; i++) {
    for (int j = 0; j < count - i - 1; j++) {
      if (values[j] > values[j + 1]) {
        float temp = values[j];
        values[j] = values[j + 1];
        values[j + 1] = temp;
      }
    }
  }
}

float readDistanceFilteredCm() {
  float samples[US_BUFFER_SAMPLES];
  int validCount = 0;

  for (int i = 0; i < US_BUFFER_SAMPLES; i++) {
    float d = readDistanceCm();
    if (d > 0.0f && d <= US_MAX_VALID_CM) {
      samples[validCount++] = d;
    }
    delay(8);
  }

  if (validCount == 0) {
    return -1.0f;
  }

  sortFloatArray(samples, validCount);

  // Si hay suficientes muestras, descarta el menor y el mayor (outliers extremos).
  int start = 0;
  int end = validCount;
  if (validCount >= 5) {
    start = 1;
    end = validCount - 1;
  }

  float sum = 0.0f;
  int count = 0;
  for (int i = start; i < end; i++) {
    sum += samples[i];
    count++;
  }

  if (count == 0) {
    return -1.0f;
  }
  return sum / (float)count;
}

WaterLevel classifyWaterLevel(float distanceCm) {
  if (distanceCm < 0.0f) {
    return WATER_LEVEL_UNKNOWN;
  }

  if (distanceCm <= WATER_FULL_MAX_CM) {
    return WATER_LEVEL_FULL;
  }
  if (distanceCm >= WATER_MID_MAX_CM) {
    return WATER_LEVEL_LOW;
  }
  return WATER_LEVEL_MID;
}

void updateLevelLeds(WaterLevel level) {
  digitalWrite(LED_GREEN_PIN, level == WATER_LEVEL_FULL ? HIGH : LOW);
  digitalWrite(LED_YELLOW_PIN, level == WATER_LEVEL_MID ? HIGH : LOW);
  digitalWrite(LED_RED_PIN, level == WATER_LEVEL_LOW ? HIGH : LOW);
}

const char* levelToText(WaterLevel level) {
  switch (level) {
    case WATER_LEVEL_FULL:
      return "FULL";
    case WATER_LEVEL_MID:
      return "MID";
    case WATER_LEVEL_LOW:
      return "EMPTY";
    default:
      return "UNKNOWN";
  }
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  if (WiFi.status() == WL_NO_MODULE) {
    Serial.println("Modulo WiFi no detectado");
    return;
  }

  Serial.print("Conectando a WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  // Espera hasta ~12s a que conecte Y que DHCP asigne una IP valida.
  // En el UNO R4 (WiFiS3) el estado pasa a WL_CONNECTED antes de tener IP,
  // por eso tambien esperamos a que localIP() deje de ser 0.0.0.0.
  unsigned long start = millis();
  while (millis() - start < 12000) {
    if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0)) {
      break;
    }
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  IPAddress ip = WiFi.localIP();
  if (WiFi.status() == WL_CONNECTED && ip != IPAddress(0, 0, 0, 0)) {
    Serial.print("WiFi conectado. IP: ");
    Serial.println(ip);
  } else {
    Serial.println("No se pudo conectar / sin IP (se reintentara)");
    // Fuerza un nuevo intento limpio en la proxima llamada.
    WiFi.disconnect();
  }
}

void sendTelemetry(int soilRaw, float moisturePct, bool dry, bool motor,
                   float distanceCm, WaterLevel level, float lux) {
  if (WiFi.status() != WL_CONNECTED) {
    return;
  }

  // Construye el cuerpo JSON con los campos que espera telemetry_receiver.py.
  String body = "{";
  body += "\"device\":\"";
  body += DEVICE_NAME;
  body += "\",";
  body += "\"soil_raw_adc\":";
  body += String(soilRaw);
  body += ",";
  body += "\"soil_moisture_pct\":";
  body += (moisturePct >= 0.0f) ? String(moisturePct, 1) : String("null");
  body += ",";
  body += "\"soil_dry\":";
  body += dry ? "true" : "false";
  body += ",";
  body += "\"motor_on\":";
  body += motor ? "true" : "false";
  body += ",";
  body += "\"distance_cm\":";
  body += (distanceCm >= 0.0f) ? String(distanceCm, 1) : String("null");
  body += ",";
  body += "\"water_level\":\"";
  body += levelToText(level);
  body += "\",";
  body += "\"lux\":";
  body += (lux >= 0.0f) ? String(lux, 1) : String("null");
  body += ",";
  body += "\"uptime_ms\":";
  body += String(millis());
  body += "}";

  WiFiClient client;
  if (!client.connect(SERVER_HOST, SERVER_PORT)) {
    Serial.println("No se pudo conectar al servidor de telemetria");
    return;
  }

  client.print("POST ");
  client.print(SERVER_PATH);
  client.println(" HTTP/1.1");
  client.print("Host: ");
  client.print(SERVER_HOST);
  client.print(":");
  client.println(SERVER_PORT);
  client.println("Content-Type: application/json");
  client.print("Content-Length: ");
  client.println(body.length());
  client.println("Connection: close");
  client.println();
  client.print(body);

  // Espera breve la respuesta y cierra para liberar el socket.
  unsigned long start = millis();
  while (client.connected() && millis() - start < 2000) {
    while (client.available()) {
      client.read();
    }
  }
  client.stop();
}

void runPinTest(unsigned long now) {
  if (now - lastPinTestMs < MOTOR_PIN_TEST_INTERVAL_MS) {
    return;
  }
  lastPinTestMs = now;
  setMotor(!motorOn);
  Serial.print("TEST D8 -> ");
  Serial.println(motorOn ? "ON" : "OFF");
}

void setup() {
  Serial.begin(115200);
  delay(1200);

  pinMode(MOTOR_PIN, OUTPUT);
  setMotor(false);

  pinMode(US_TRIG_PIN, OUTPUT);
  pinMode(US_ECHO_PIN, INPUT);
  digitalWrite(US_TRIG_PIN, LOW);

  pinMode(LED_GREEN_PIN, OUTPUT);
  pinMode(LED_YELLOW_PIN, OUTPUT);
  pinMode(LED_RED_PIN, OUTPUT);
  updateLevelLeds(WATER_LEVEL_UNKNOWN);

  // Inicializa el sensor de luz VEML7700 por I2C (SDA/SCL).
  if (veml.begin()) {
    vemlReady = true;
    veml.setGain(VEML7700_GAIN_1);
    veml.setIntegrationTime(VEML7700_IT_100MS);
    Serial.println("VEML7700 detectado en I2C");
  } else {
    Serial.println("VEML7700 NO detectado (revisa cableado SDA/SCL)");
  }

  connectWiFi();

  Serial.println("Sistema listo: humedad A0 + control motor D8");
  if (MOTOR_PIN_TEST_MODE) {
    Serial.println("MODO TEST PIN ACTIVO: D8 alterna ON/OFF cada 1s");
  }
}

void loop() {
  unsigned long now = millis();
  if (MOTOR_PIN_TEST_MODE) {
    runPinTest(now);
    return;
  }

  // Reintenta WiFi periodicamente sin bloquear el muestreo.
  if (WiFi.status() != WL_CONNECTED && now - lastWifiRetryMs >= WIFI_RETRY_INTERVAL_MS) {
    lastWifiRetryMs = now;
    connectWiFi();
  }

  if (now - lastSampleMs < SAMPLE_INTERVAL_MS) {
    return;
  }
  lastSampleMs = now;

  int soilRaw = readSoilRaw();
  float moisturePct = rawToMoisturePct(soilRaw);
  evaluateIrrigation(moisturePct);

  float distanceCm = readDistanceFilteredCm();
  WaterLevel level = classifyWaterLevel(distanceCm);
  updateLevelLeds(level);

  float lux = vemlReady ? veml.readLux() : -1.0f;

  bool isDry = moisturePct >= 0.0f && moisturePct <= MOISTURE_LOW_THRESHOLD;
  Serial.print("ADC=");
  Serial.print(soilRaw);
  Serial.print(" | Humedad=");
  Serial.print(moisturePct, 1);
  Serial.print("% | Estado=");
  Serial.print(isDry ? "SECO" : "HUMEDO");
  Serial.print(" | Motor=");
  Serial.print(motorOn ? "ON" : "OFF");
  Serial.print(" | Distancia=");
  Serial.print(distanceCm, 1);
  Serial.print(" cm | NivelAgua=");
  Serial.print(levelToText(level));
  Serial.print(" | Luz=");
  if (lux >= 0.0f) {
    Serial.print(lux, 1);
    Serial.println(" lux");
  } else {
    Serial.println("N/D");
  }

  // Envia la telemetria de sensores + estado del motor al servidor por WiFi.
  sendTelemetry(soilRaw, moisturePct, isDry, motorOn, distanceCm, level, lux);
}
