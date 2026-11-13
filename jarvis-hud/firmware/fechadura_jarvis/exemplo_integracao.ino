// exemplo_integracao.ino — COMO ENCAIXAR o módulo JARVIS no firmware que você já tem.
// Não substitui o seu firmware: copie só as linhas marcadas com  // JARVIS
// (o teclado, o app e o reconhecimento facial continuam funcionando como hoje).
//
// Ligações recomendadas (ESP32 DevKit + solenoide 12 V):
//   GPIO26 → módulo relé ou MOSFET logic-level (ex.: IRLZ44N) que liga o solenoide;
//   diodo 1N4007 em paralelo com o solenoide (catodo no +12 V) — protege o ESP32 do pico ao desligar;
//   fonte 12 V separada, GND comum com o ESP32;
//   (opcional, recomendado) sensor de porta reed: um fio no GPIO27, o outro no GND.

#include <WiFi.h>
#include <WebServer.h>
#include "JarvisLock.h"     // JARVIS
#include "secrets.h"        // JARVIS — WIFI_SSID, WIFI_PASS, JARVIS_SECRET_HEX (não versionar!)

const int PINO_SOLENOIDE = 26;
const int PINO_PORTA = -1;          // 27 se instalar o sensor reed; -1 = sem sensor
const bool SOLENOIDE_ATIVO_ALTO = true;

WebServer jarvisServer(8080);       // JARVIS — porta 8080 (o seu servidor atual pode continuar na 80)
jarvis::Lock jarvisLock;            // JARVIS
unsigned long fecharEm = 0;         // sem delay(): o ESP32 continua atendendo o teclado e o JARVIS durante a abertura

void abrirPorta(const char* origem) {
  // origem: "teclado", "app", "rosto", "painel"
  if (strcmp(origem, "teclado") != 0 && jarvisLock.lockdown()) {   // JARVIS — modo trancado: só o teclado abre
    jarvisLock.logEvent(origem, false);
    return;
  }
  digitalWrite(PINO_SOLENOIDE, SOLENOIDE_ATIVO_ALTO ? HIGH : LOW);
  jarvisLock.logEvent(origem, true);                              // JARVIS — o JARVIS avisa quem abriu
  fecharEm = millis() + 3000;                                     // o seu tempo de abertura atual
}

void codigoErradoNoTeclado() {
  jarvisLock.logEvent("teclado", false);                          // JARVIS — 3 erros seguidos → alerta no JARVIS
}

void codigoMestreDesligaModoTrancado() {
  jarvisLock.setLockdown(false);                                  // JARVIS — só pelo teclado, nunca pela rede
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_SOLENOIDE, OUTPUT);
  digitalWrite(PINO_SOLENOIDE, SOLENOIDE_ATIVO_ALTO ? LOW : HIGH);   // começa travada
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(250);
  Serial.printf("Wi-Fi: %s  IP: %s\n", WiFi.status() == WL_CONNECTED ? "ok" : "falhou", WiFi.localIP().toString().c_str());
  if (!jarvisLock.begin(jarvisServer, JARVIS_SECRET_HEX, PINO_SOLENOIDE, SOLENOIDE_ATIVO_ALTO, PINO_PORTA))   // JARVIS
    Serial.println("JARVIS: segredo invalido em secrets.h");
  // ... o resto do seu setup (teclado, conexão com o backend do app etc.)
}

void loop() {
  jarvisLock.loop();                                              // JARVIS
  if (fecharEm && (long)(millis() - fecharEm) >= 0) {             // fim da abertura: solenoide desligado = travada
    digitalWrite(PINO_SOLENOIDE, SOLENOIDE_ATIVO_ALTO ? LOW : HIGH);
    fecharEm = 0;
  }
  // ... o resto do seu loop (ler o teclado, comandos do app etc.)
}
