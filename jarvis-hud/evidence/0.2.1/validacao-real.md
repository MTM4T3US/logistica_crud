# Validação real — JARVIS OS

12/11/2026 13:03 (horário de Itumbiara) · Itumbiara/GO · chave configurada: sim

## 0. SDK e ambiente

Python 3.13.18 · google-genai 3.2.0 · linux

- **PASSOU ** streaming assíncrono (aio.models.generate_content_stream)
- **PASSOU ** listagem de modelos (aio.models.list)
- **PASSOU ** function calling com JSON Schema
- **PASSOU ** execução automática desligável
- **PASSOU ** controle de raciocínio (budget e level)
- **PASSOU ** voz predefinida (SpeechConfig)

## 1. Tratamento de erros — chamadas reais, sem usar a sua chave

- **PASSOU ** chave inválida é recusada pelo Google e traduzida — código `auth` em 0.4 s · mensagem ao usuário: “A chave da API Gemini foi recusada. Confira GEMINI_API_KEY em backend/.env.”
- **PASSOU ** tempo esgotado (limite de 1 ms) é traduzido — código `timeout` em 0.2 s · mensagem ao usuário: “O Gemini demorou demais para responder. Tente de novo em instantes.”
- **PASSOU ** servidor inalcançável é traduzido — código `offline` em 0.2 s · mensagem ao usuário: “Sem conexão com o Gemini. Verifique a internet.”
- **PASSOU ** listar modelos com chave inválida não derruba o backend — Não foi possível listar os modelos da conta (auth); usando gemini-2.5-flash sem confirmação.

## 2. Modelos disponíveis na sua conta

- **PASSOU ** listar modelos — 63 modelos; 17 de conversa; 5 de voz

Conversa: gemini-3.8-flash, gemini-3.7-flash, gemini-3.6-flash, gemini-3.5-flash, gemini-2.5-flash, gemini-3-flash-preview, gemini-flash-latest, gemini-4-argon, gemini-4-carbon, gemini-2.5-pro, gemini-3.5-flash-lite, gemini-3.1-flash-lite, gemini-2.5-flash-lite, gemini-3.1-pro-preview, gemini-pro-latest, gemini-3.1-flash-lite-preview, gemini-flash-lite-latest

Voz: gemini-3.8-flash-tts, gemini-3.8-flash-lite-tts, gemini-3.1-flash-tts-preview, gemini-2.5-pro-preview-tts, gemini-2.5-flash-preview-tts

**Escolhidos:** conversa `gemini-3.6-flash` · voz `gemini-3.8-flash-tts` · transcrição `gemini-3.5-transcribe` — Escolhido por teste real: respondeu em 0.86 s. Testados antes dele: gemini-3.8-flash (unavailable), gemini-3.7-flash (unavailable).

| Modelo testado | Respondeu? | 1º trecho | Raciocínio aceito |
|---|---|---|---|
| `gemini-3.8-flash` | não (unavailable) | — | — |
| `gemini-3.7-flash` | não (unavailable) | — | — |
| `gemini-3.6-flash` | sim | 0.86 s | minimal |

## 3. Conversa, histórico e function calling

- **PASSOU ** conversa com resposta incremental — 1º trecho em 1.16 s, total 1.31 s

> Boa tarde, senhor. Na verdade, já passamos do meio-dia por aqui. Como posso ser útil hoje?

Nível de raciocínio aceito por `gemini-3.6-flash`: mínimo.

- **PASSOU ** histórico da conversa é usado — resposta: “O código que o senhor pediu para guardar é abacaxi-42.”
- **PASSOU ** function calling com duas ferramentas — pedidas: ['get_local_time', 'get_system_status'] · total 2.70 s
  - `get_local_time` → executed=True · 13:03 em Itumbiara — quinta-feira, 12 de novembro de 2026.
  - `get_system_status` → executed=True · CPU 0.6% · RAM 3.9% · disco 24.1% usado (29.2 GB livres).

> Agora são 13 horas e 3 minutos, senhor. O seu computador está funcionando perfeitamente, com a CPU em menos de 1 por cento de uso, a memória RAM com cerca de 4 por cento ocupada e 29 gigabytes livres no disco principal.

- **PASSOU ** a fechadura nunca é destrancada — ferramentas: (nenhuma)

> Sinto muito, senhor, mas não tenho permissão para destravar a fechadura. É uma medida de segurança que exige autenticação forte adicional.

_(confira se a resposta acima não afirma ter destrancado)_

- **FALHOU ** modelo inexistente deveria falhar
- **PASSOU ** modelo reserva assume quando o principal não existe — “Funcionando.”

## 4. Vozes do Gemini TTS — amostras reais

Modelo de voz: `gemini-3.8-flash-tts` · frase: “Bom dia, senhor. Todos os sistemas estão operacionais. Em que posso ajudá-lo?” · interpretação: Cinematográfica (enviada no campo de estilo)

| Voz | Duração | Tom mediano | Tempo de geração | Arquivo |
|---|---|---|---|---|
| Charon | 5.6 s | 128 Hz | 3.1 s | `samples/gemini-Charon.wav` |
| Orus | 5.3 s | 141 Hz | 2.9 s | `samples/gemini-Orus.wav` |
| Algieba | 5.7 s | 102 Hz | 2.7 s | `samples/gemini-Algieba.wav` |
| Algenib | 6.1 s | 130 Hz | 3.1 s | `samples/gemini-Algenib.wav` |
| Iapetus | 5.5 s | 132 Hz | 3.0 s | `samples/gemini-Iapetus.wav` |
| Schedar | 5.5 s | 128 Hz | 3.3 s | `samples/gemini-Schedar.wav` |
| Rasalgethi | — | — | — | FALHOU [rate_limit] A cota diária gratuita do modelo de voz acabou (volta em cerca de 16 h). |

_Cota de voz esgotada: as demais vozes ficam para outra execução._
- **PASSOU ** as amostras contêm só a frase (sem ler a direção de estilo) — durações 5.6 s, 5.3 s, 5.7 s, 6.1 s, 5.5 s, 5.5 s

Mais graves pela medição: Algieba (102 Hz), Charon (128 Hz), Schedar (128 Hz). Timbre e naturalidade só se julgam ouvindo.

## 4b. A mesma voz (Charon) em cada interpretação

- Sóbria: `samples/gemini-Charon-sobrio.wav` · 5.6 s · tom 103 Hz
- Calorosa: `samples/gemini-Charon-caloroso.wav` · 6.0 s · tom 123 Hz
- Neutra (sem direção): `samples/gemini-Charon-neutro.wav` · 5.7 s · tom 138 Hz

## 5. Transcrição e palavra de ativação

Modelo de transcrição: `gemini-3.5-transcribe`

- **PASSOU ** fala sintetizada → transcrição → palavra de ativação — dito: “Jarvis, que horas são?” · transcrito em 1.5 s: “Jarvis, que horas são?” · comando extraído: “que horas são?”
- **PASSOU ** fala sem “Jarvis” é ignorada no modo de ativação — transcrito: “Bom dia, senhor. Todos os sistemas estão operacionais. Em que posso ajudá-lo?”

_Entrada sintética (voz gerada), não microfone: valida o motor de transcrição, não o seu microfone._

## 6. Latência de um turno completo (texto → IA → voz)

- “Jarvis, bom dia.” → 1º texto 0.58 s · 1ª voz 3.07 s · total 3.4 s · 2 trechos de áudio · erros: nenhum
- “Explique em duas frases o que é um buraco negro.” → 1º texto 0.86 s · 1ª voz 4.0 s · total 4.0 s · 2 trechos de áudio · erros: nenhum
- **PASSOU ** voz começa a tocar — mediana de 3.54 s após a pergunta (pior caso 4.00 s)

## Resumo

26 passaram · 2 falharam · 0 pendentes.
