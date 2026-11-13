// mbedtls simulado com OpenSSL (mesma API que o JarvisLock.h usa).
#pragma once
#include <openssl/hmac.h>
#include <vector>
enum mbedtls_md_type_t { MBEDTLS_MD_SHA256 };
struct mbedtls_md_context_t { std::vector<unsigned char> key, msg; };
struct mbedtls_md_info_t {};
inline const mbedtls_md_info_t* mbedtls_md_info_from_type(mbedtls_md_type_t) { static mbedtls_md_info_t i; return &i; }
inline void mbedtls_md_init(mbedtls_md_context_t* c) { c->key.clear(); c->msg.clear(); }
inline int mbedtls_md_setup(mbedtls_md_context_t*, const mbedtls_md_info_t*, int) { return 0; }
inline int mbedtls_md_hmac_starts(mbedtls_md_context_t* c, const unsigned char* k, size_t n) { c->key.assign(k, k + n); return 0; }
inline int mbedtls_md_hmac_update(mbedtls_md_context_t* c, const unsigned char* m, size_t n) { c->msg.insert(c->msg.end(), m, m + n); return 0; }
inline int mbedtls_md_hmac_finish(mbedtls_md_context_t* c, unsigned char* out) { unsigned int n = 32; HMAC(EVP_sha256(), c->key.data(), (int)c->key.size(), c->msg.data(), c->msg.size(), out, &n); return 0; }
inline void mbedtls_md_free(mbedtls_md_context_t*) {}
