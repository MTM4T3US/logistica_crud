#pragma once
#include "Arduino.h"
#define WIFI_STA 1
#define WL_CONNECTED 3
struct IPStub { String toString() const { return String("192.168.0.50"); } };
struct WiFiStub { int RSSI() { return -55; } void mode(int) {} void begin(const char*, const char*) {} int status() { return WL_CONNECTED; } IPStub localIP() { return {}; } };
inline WiFiStub WiFi;
