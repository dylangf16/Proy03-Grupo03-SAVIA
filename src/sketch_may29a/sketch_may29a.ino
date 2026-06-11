#include <Arduino.h>
#include <Wire.h>
#include "Adafruit_VEML7700.h"

// Implementacion base para Arduino UNO R4:
// Lee humedad en A0 y activa bomba/relay en D2 mientras la humedad este baja.

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
const int AIR_VALUE = 760;
const int WATER_VALUE = 390;

// Histeresis para evitar encendido/apagado rapido.
const float MOISTURE_LOW_THRESHOLD = 35.0f;
const float MOISTURE_HIGH_THRESHOLD = 45.0f;

// Rangos solicitados para nivel de agua medido por distancia.
const float WATER_FULL_MAX_CM = 7.0f;
const float WATER_MID_MAX_CM = 11.0f;

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
}
