// JarvisLock.h — módulo JARVIS para o firmware da fechadura (ESP32 DevKit + solenoide 12 V).
//
// ACRESCENTA ao seu firmware atual (teclado, app, reconhecimento facial continuam como estão):
//   GET  /status   → estado: travada?, solenoide energizado?, modo trancado?, últimos eventos
//   POST /lock     → corta o solenoide na hora (se estiver abrindo) — "garante travada"
//   POST /lockdown → liga o MODO TRANCADO: app/rosto/painel deixam de abrir; o teclado continua abrindo.
//                    Desligar o modo trancado só no próprio teclado (código mestre) — nunca pela rede.
// Não existe rota de destrancar. Pedidos e respostas são assinados (HMAC-SHA256, segredo do pareamento).
//
// Uso (veja exemplo_integracao.ino):
//   #include "JarvisLock.h"
//   WebServer jarvisServer(8080);
//   jarvis::Lock jarvisLock;
//   setup(): conectar o Wi-Fi; jarvisLock.begin(jarvisServer, JARVIS_SECRET_HEX, PINO_SOLENOIDE, true);
//   loop():  jarvisLock.loop();
//   onde o seu código ABRE a porta:  if (origem != teclado && jarvisLock.lockdown()) { recusar }
//                                    jarvisLock.logEvent("teclado", true);   // ou "app", "rosto", "painel"
//   código errado no teclado:        jarvisLock.logEvent("teclado", false);
#pragma once
#include <Arduino.h>
#include <Preferences.h>
#include <WebServer.h>
#include <WiFi.h>
#include <time.h>

#include "jarvis_proto.h"
#include "mbedtls/md.h"

namespace jarvis {

inline void hmac_mbedtls(const uint8_t* key, size_t key_len, const uint8_t* msg, size_t msg_len, uint8_t out[32]) {
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, key, key_len);
  mbedtls_md_hmac_update(&ctx, msg, msg_len);
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);
}

struct Event {
  uint32_t t;
  char src[10];
  bool ok;
};

class Lock {
 public:
  // pinoSolenoide: o pino que liga o relé/MOSFET do solenoide; ativoAlto: true se HIGH energiza.
  // pinoPorta: sensor de porta (reed) opcional, com INPUT_PULLUP (aberta = HIGH). -1 = sem sensor.
  bool begin(WebServer& server, const char* secretHex, int pinoSolenoide, bool ativoAlto, int pinoPorta = -1) {
    server_ = &server;
    pin_ = pinoSolenoide;
    activeHigh_ = ativoAlto;
    doorPin_ = pinoPorta;
    if (doorPin_ >= 0) pinMode(doorPin_, INPUT_PULLUP);
    prefs_.begin("jarvis", false);
    lockdown_ = prefs_.getBool("lockdown", false);
    configTime(0, 0, "pool.ntp.org", "time.google.com");   // a assinatura usa a hora (UTC)
    static const char* keys[] = {"X-Jarvis-Time", "X-Jarvis-Nonce", "X-Jarvis-Sig"};
    server.collectHeaders(keys, 3);
    server.on("/status", HTTP_GET, [this]() { handle(false); });
    server.on("/lock", HTTP_POST, [this]() { handle(true, "lock"); });
    server.on("/lockdown", HTTP_POST, [this]() { handle(true, "lockdown"); });
    server.begin();
    return guard_.begin(secretHex, hmac_mbedtls);
  }

  void loop() {
    if (server_) server_->handleClient();
  }

  bool lockdown() const { return lockdown_; }

  // chame do SEU código do teclado, depois de conferir o código mestre
  void setLockdown(bool on) {
    lockdown_ = on;
    prefs_.putBool("lockdown", on);
    logEvent(on ? "trancado" : "liberado", true);
  }

  // registre cada abertura (ok=true) e cada código errado (ok=false). src: "teclado", "app", "rosto", "painel"…
  void logEvent(const char* src, bool ok) {
    Event& e = events_[next_];
    e.t = (uint32_t)time(nullptr);
    strncpy(e.src, src, sizeof(e.src) - 1);
    e.src[sizeof(e.src) - 1] = 0;
    e.ok = ok;
    next_ = (next_ + 1) % N;
    if (count_ < N) count_++;
    if (!ok) wrong_++;
    else if (strcmp(src, "teclado") == 0) wrong_ = 0;
  }

  bool energized() const { return pin_ >= 0 && digitalRead(pin_) == (activeHigh_ ? HIGH : LOW); }

 private:
  static const int N = 10;
  WebServer* server_ = nullptr;
  Guard guard_;
  Preferences prefs_;
  int pin_ = -1, doorPin_ = -1;
  bool activeHigh_ = true, lockdown_ = false;
  Event events_[N];
  int next_ = 0, count_ = 0, wrong_ = 0;

  std::string statusJson() const {
    std::string s = "{\"locked\":";
    s += energized() ? "false" : "true";
    s += ",\"energized\":";
    s += energized() ? "true" : "false";
    s += ",\"door_open\":";
    s += doorPin_ < 0 ? "null" : (digitalRead(doorPin_) == HIGH ? "true" : "false");
    s += ",\"lockdown\":";
    s += lockdown_ ? "true" : "false";
    s += ",\"wrong_codes\":" + std::to_string(wrong_);
    s += ",\"battery\":null,\"rssi\":" + std::to_string(WiFi.RSSI());
    s += ",\"uptime\":" + std::to_string(millis() / 1000);
    s += ",\"events\":[";
    for (int i = 0; i < count_; i++) {
      const Event& e = events_[(next_ - 1 - i + N) % N];   // mais recente primeiro
      if (i) s += ",";
      s += "{\"t\":" + std::to_string(e.t) + ",\"src\":\"" + e.src + "\",\"ok\":" + (e.ok ? "true" : "false") + "}";
    }
    s += "]}";
    return s;
  }

  void reply(int code, const std::string& nonce, const std::string& body) {
    server_->sendHeader("X-Lock-Sig", guard_.sign_response(nonce, body).c_str());
    server_->send(code, "application/json", body.c_str());
  }

  void handle(bool post, const char* action = "") {
    std::string method = post ? "POST" : "GET";
    std::string path = std::string(server_->uri().c_str());
    std::string ts = server_->header("X-Jarvis-Time").c_str();
    std::string nonce = server_->header("X-Jarvis-Nonce").c_str();
    std::string sig = server_->header("X-Jarvis-Sig").c_str();
    std::string body = post ? std::string(server_->arg("plain").c_str()) : "";
    Verdict v = guard_.check(method, path, ts, nonce, body, sig, (uint32_t)time(nullptr));
    if (v != OK) {
      // sem assinatura válida não há resposta assinada: o JARVIS descarta, e quem forjou não aprende nada
      server_->send(v == NO_CLOCK ? 503 : 401, "application/json", (std::string("{\"error\":\"") + verdict_text(v) + "\"}").c_str());
      return;
    }
    if (strcmp(action, "lock") == 0) {
      if (energized()) digitalWrite(pin_, activeHigh_ ? LOW : HIGH);   // corta a abertura em andamento
      logEvent("jarvis", true);
    } else if (strcmp(action, "lockdown") == 0) {
      setLockdown(true);
    }
    reply(200, nonce, statusJson());
  }
};

}  // namespace jarvis
