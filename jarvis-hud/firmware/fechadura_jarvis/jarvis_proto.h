// jarvis_proto.h — protocolo JARVIS ⇄ fechadura (parte portátil, sem Arduino).
//
// Verifica pedidos assinados do JARVIS e assina as respostas, exatamente como
// backend/app/devices/own_lock.py:
//   pedido   : HMAC-SHA256(segredo, "MÉTODO\ncaminho\ntimestamp\nnonce\ncorpo")  em hex minúsculo
//   resposta : HMAC-SHA256(segredo, "RESP\nnonce\ncorpo")
// Recusa assinatura errada, relógio fora de ±30 s e nonce repetido (últimos 32).
// A função HMAC é injetada: mbedtls no ESP32, OpenSSL no teste nativo.
#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <string>

namespace jarvis {

typedef void (*HmacFn)(const uint8_t* key, size_t key_len, const uint8_t* msg, size_t msg_len, uint8_t out[32]);

inline int hexval(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// "a1b2…" (64 hex) → 32 bytes. Devolve o número de bytes, ou -1 se inválido.
inline int parse_hex(const char* hex, uint8_t* out, size_t max) {
  size_t n = strlen(hex);
  if (n % 2 || n / 2 > max) return -1;
  for (size_t i = 0; i < n; i += 2) {
    int a = hexval(hex[i]), b = hexval(hex[i + 1]);
    if (a < 0 || b < 0) return -1;
    out[i / 2] = (uint8_t)(a * 16 + b);
  }
  return (int)(n / 2);
}

inline std::string to_hex(const uint8_t* b, size_t n) {
  static const char* d = "0123456789abcdef";
  std::string s;
  s.reserve(n * 2);
  for (size_t i = 0; i < n; i++) { s += d[b[i] >> 4]; s += d[b[i] & 15]; }
  return s;
}

// comparação em tempo constante (não vaza quantos caracteres batem)
inline bool same(const std::string& a, const std::string& b) {
  if (a.size() != b.size()) return false;
  unsigned char diff = 0;
  for (size_t i = 0; i < a.size(); i++) diff |= (unsigned char)(a[i] ^ b[i]);
  return diff == 0;
}

enum Verdict { OK = 0, BAD_SIGNATURE, BAD_TIME, REPLAY, NO_CLOCK, BAD_REQUEST };

inline const char* verdict_text(Verdict v) {
  switch (v) {
    case OK: return "ok";
    case BAD_SIGNATURE: return "assinatura invalida";
    case BAD_TIME: return "horario fora da janela";
    case REPLAY: return "pedido repetido";
    case NO_CLOCK: return "fechadura sem hora (NTP)";
    default: return "pedido invalido";
  }
}

class Guard {
 public:
  Guard() : key_len_(0), hmac_(nullptr), next_(0) { memset(seen_, 0, sizeof(seen_)); }

  bool begin(const char* secret_hex, HmacFn fn) {
    hmac_ = fn;
    int n = parse_hex(secret_hex, key_, sizeof(key_));
    key_len_ = n >= 16 ? (size_t)n : 0;   // pelo menos 128 bits
    return key_len_ > 0 && hmac_ != nullptr;
  }

  std::string sign(const std::string& text) const {
    uint8_t mac[32];
    hmac_(key_, key_len_, (const uint8_t*)text.data(), text.size(), mac);
    return to_hex(mac, 32);
  }

  // now: hora atual em segundos Unix (0 se o relógio ainda não sincronizou)
  Verdict check(const std::string& method, const std::string& path, const std::string& ts, const std::string& nonce,
                const std::string& body, const std::string& sig, uint32_t now) {
    if (!key_len_ || ts.empty() || nonce.size() < 16 || nonce.size() > 64 || sig.size() != 64) return BAD_REQUEST;
    if (!same(sign(method + "\n" + path + "\n" + ts + "\n" + nonce + "\n" + body), sig)) return BAD_SIGNATURE;
    if (now < 1700000000UL) return NO_CLOCK;
    long long t = atoll(ts.c_str());
    long long delta = (long long)now - t;
    if (delta > 30 || delta < -30) return BAD_TIME;
    for (int i = 0; i < SEEN; i++)
      if (seen_[i][0] && nonce == seen_[i]) return REPLAY;
    strncpy(seen_[next_], nonce.c_str(), 64);
    seen_[next_][64] = 0;
    next_ = (next_ + 1) % SEEN;
    return OK;
  }

  std::string sign_response(const std::string& nonce, const std::string& body) const { return sign("RESP\n" + nonce + "\n" + body); }

 private:
  static const int SEEN = 32;
  uint8_t key_[64];
  size_t key_len_;
  HmacFn hmac_;
  char seen_[SEEN][65];
  int next_;
};

}  // namespace jarvis
