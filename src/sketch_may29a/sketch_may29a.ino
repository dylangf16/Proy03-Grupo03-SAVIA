#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <Adafruit_VEML7700.h>

// WiFi
const char* WIFI_SSID = "WiFi_DGF";
const char* WIFI_PASSWORD = "D16G01F03!";

// Receptor Python
const char* SERVER_URL = "http://192.168.5.52:5000/telemetry";

// VEML7700 por I2C (ESP32 por defecto: SDA=21, SCL=22)
const int I2C_SDA_PIN = 21;
const int I2C_SCL_PIN = 22;
Adafruit_VEML7700 veml;

// Ultrasónico (HC-SR04)
const int US_TRIG_PIN = 18;
const int US_ECHO_PIN = 19;
const float MIN_VALID_CM = 5.0f;
const float MAX_VALID_CM = 80.0f;

// Humedad suelo (HW-080 + HW-103)
// AO -> GPIO34 (solo entrada ADC), DO -> GPIO4
const int SOIL_ANALOG_PIN = 34;
const int SOIL_DIGITAL_PIN = 4;

// Calibracion inicial para ESP32 ADC (0-4095)
const int AIR_VALUE = 3200;
const int WATER_VALUE = 1500;

const unsigned long SEND_INTERVAL_MS = 1000;
unsigned long lastSendMs = 0;

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  Serial.print("Conectando WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi conectada. IP ESP32: ");
  Serial.println(WiFi.localIP());
}

void setupSensors() {
  Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN);
  if (!veml.begin()) {
    Serial.println("No se detecto VEML7700. Revisa cableado I2C.");
  } else {
    veml.setGain(VEML7700_GAIN_1);
    veml.setIntegrationTime(VEML7700_IT_100MS);
    Serial.println("VEML7700 inicializado.");
  }

  pinMode(US_TRIG_PIN, OUTPUT);
  pinMode(US_ECHO_PIN, INPUT);
  digitalWrite(US_TRIG_PIN, LOW);

  pinMode(SOIL_DIGITAL_PIN, INPUT);
  Serial.println("Ultrasonico y humedad inicializados.");
}

float readDistanceCm() {
  digitalWrite(US_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(US_TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(US_TRIG_PIN, LOW);

  unsigned long duration = pulseIn(US_ECHO_PIN, HIGH, 30000);
  if (duration == 0) {
    return -1.0f;
  }

  float distanceCm = (duration * 0.0343f) / 2.0f;
  if (distanceCm < MIN_VALID_CM || distanceCm > MAX_VALID_CM) {
    return -1.0f;
  }
  return distanceCm;
}

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

void sendTelemetry(float lux, float white, float distanceCm, int soilRaw, float moisturePct, int soilDo) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi caida, reconectando...");
    connectWiFi();
    return;
  }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");

  String payload = "{";
  payload += "\"device\":\"esp32-multi-sensor\",";
  payload += "\"lux\":" + String(lux, 2) + ",";
  payload += "\"white\":" + String(white, 2) + ",";
  payload += "\"distance_cm\":" + String(distanceCm, 2) + ",";
  payload += "\"soil_raw_adc\":" + String(soilRaw) + ",";
  payload += "\"soil_moisture_pct\":" + String(moisturePct, 2) + ",";
  payload += "\"soil_do\":" + String(soilDo) + ",";
  payload += "\"uptime_ms\":" + String(millis());
  payload += "}";

  int httpCode = http.POST(payload);
  Serial.print("POST codigo: ");
  Serial.println(httpCode);
  if (httpCode > 0) {
    Serial.println(http.getString());
  } else {
    Serial.print("Error HTTP: ");
    Serial.println(http.errorToString(httpCode));
  }

  http.end();
}

void setup() {
  Serial.begin(115200);
  delay(1200);

  setupSensors();
  connectWiFi();
  Serial.println("Sistema listo: 3 sensores + WiFi");
}

void loop() {
  unsigned long now = millis();
  if (now - lastSendMs >= SEND_INTERVAL_MS) {
    lastSendMs = now;

    float lux = veml.readLux();
    float white = veml.readWhite();
    float distanceCm = readDistanceCm();
    int soilRaw = readSoilRaw();
    float moisturePct = rawToMoisturePct(soilRaw);
    int soilDo = digitalRead(SOIL_DIGITAL_PIN);

    Serial.print("Lux=");
    Serial.print(lux, 1);
    Serial.print(" | Dist=");
    Serial.print(distanceCm, 1);
    Serial.print(" cm | Soil=");
    Serial.print(moisturePct, 1);
    Serial.println("%");

    sendTelemetry(lux, white, distanceCm, soilRaw, moisturePct, soilDo);
  }
}
