#include <Arduino.h>

// Calibracion del sensor de humedad de suelo (Arduino UNO R4).
//
// Como usar:
//   1. Sube este sketch y abre el Monitor Serie a 115200 baudios.
//   2. Deja el sensor en AIRE (seco) y anota el valor estable -> AIR_VALUE.
//   3. Sumerge la punta en AGUA (humedo) y anota el valor estable -> WATER_VALUE.
//   4. Copia esos dos numeros a AIR_VALUE / WATER_VALUE en el sketch principal.
//
// El sketch promedia varias lecturas para reducir ruido y muestra el ADC crudo,
// el minimo y maximo vistos, y el % de humedad estimado con la calibracion actual.

const int SOIL_ANALOG_PIN = A0;

// Calibracion actual (ajusta tras tomar tus lecturas).
const int AIR_VALUE = 760;    // lectura tipica en aire (seco)
const int WATER_VALUE = 390;  // lectura tipica en agua (humedo)

const int SAMPLES = 16;             // lecturas promediadas por muestra
const unsigned long INTERVAL_MS = 500;

unsigned long lastSampleMs = 0;
int minRaw = 1023;
int maxRaw = 0;

int readSoilRaw() {
  long sum = 0;
  for (int i = 0; i < SAMPLES; i++) {
    sum += analogRead(SOIL_ANALOG_PIN);
    delay(3);
  }
  return (int)(sum / SAMPLES);
}

float rawToMoisturePct(int raw) {
  if (AIR_VALUE == WATER_VALUE) {
    return -1.0f;
  }
  float pct = (float)(AIR_VALUE - raw) * 100.0f / (float)(AIR_VALUE - WATER_VALUE);
  if (pct < 0.0f) pct = 0.0f;
  if (pct > 100.0f) pct = 100.0f;
  return pct;
}

void setup() {
  Serial.begin(115200);
  delay(1200);
  Serial.println("=== Calibracion sensor de humedad ===");
  Serial.println("AIRE = sensor seco | AGUA = punta sumergida");
  Serial.println("Anota el ADC estable en cada caso.");
  Serial.println();
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleMs < INTERVAL_MS) {
    return;
  }
  lastSampleMs = now;

  int raw = readSoilRaw();
  if (raw < minRaw) minRaw = raw;
  if (raw > maxRaw) maxRaw = raw;

  float pct = rawToMoisturePct(raw);

  Serial.print("ADC=");
  Serial.print(raw);
  Serial.print(" | min=");
  Serial.print(minRaw);
  Serial.print(" max=");
  Serial.print(maxRaw);
  Serial.print(" | Humedad estimada=");
  Serial.print(pct, 1);
  Serial.println("%");
}
