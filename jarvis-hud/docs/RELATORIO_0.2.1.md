# Relatório — JARVIS OS 0.2.1 (validação real)

Data dos testes: 12/11/2026, entre 10h30 e 13h20 (horário de Itumbiara).
Ambiente: contêiner Linux na nuvem, Python 3.13, `google-genai` 3.2.0, Chromium headless.
Chave: a chave Gemini do usuário, no nível **gratuito**, guardada em `backend/.env` (fora do Git).

Cada resultado abaixo diz se foi obtido com a **API real** ou com **simulação**. "Real" significa
uma chamada de verdade ao Google com a sua chave (ou ao Open-Meteo).

## 1. Resumo

| Prioridade | Situação |
|---|---|
| Gemini funcionando de verdade | ✅ Conversa, histórico, function calling e tratamento de erros validados com a API real. |
| Voz JARVIS | ✅ Amostras reais de 6 vozes e 4 interpretações, com escolha e escuta pelo painel. A voz começa ~0,7 s após o texto (streaming). ⚠️ A escolha final da voz depende de você ouvir. |
| Microfone | ✅ Botão de falar e palavra "Jarvis" validados com transcrição real. ⚠️ A entrada foi uma fala gerada tocando como microfone falso, não um microfone físico. |
| Qualidade | ✅ Interface holográfica intacta, 117 testes automatizados, 13 defeitos reais corrigidos. |
| Windows | ❌ Não testado (sem acesso a uma máquina Windows). |

**Limite que mais pesa no uso diário:** a cota gratuita do Gemini. Medida na sua conta: **5 pedidos
por minuto e 20 por dia, por modelo**. Os testes deste dia esgotaram a cota de 8 modelos (ver § 6).

## 2. Gemini — testes reais

### SDK e API

| Verificação | Resultado |
|---|---|
| `google-genai` instalado e compatível | ✅ 3.2.0: streaming assíncrono, listagem de modelos, function calling com JSON Schema, execução automática desligável, controle de raciocínio e voz. |
| Versão da API | A `v1` recusa instrução de sistema (`Developer instruction is not enabled for api version v1`) e lista só 27 modelos. A `v1beta` lista 63, incluindo os de voz e transcrição. O núcleo usa `v1beta`. |

### Modelos da sua conta (lidos da API, nenhum nome presumido)

- **Conversa (17):** gemini-3.8-flash, 3.7-flash, 3.6-flash, 3.5-flash, 2.5-flash, 3-flash-preview,
  flash-latest, 4-argon, 4-carbon, 2.5-pro, 3.5-flash-lite, 3.1-flash-lite, 2.5-flash-lite,
  3.1-pro-preview, pro-latest, 3.1-flash-lite-preview, flash-lite-latest.
- **Voz (5):** gemini-3.8-flash-tts, 3.8-flash-lite-tts, 3.1-flash-tts-preview, 2.5-pro-preview-tts,
  2.5-flash-preview-tts.
- **Transcrição:** gemini-3.5-transcribe (e variantes "live", não usadas).

Os modelos mais novos estavam instáveis no momento dos testes:

| Modelo | Resultado real |
|---|---|
| gemini-3.8-flash | 503 "high demand" ou 504 após ~24 s |
| gemini-3.7-flash | 503 ou sem resposta em 14 s |
| gemini-3.6-flash | respondeu: 1º trecho em 0,86–1,57 s |
| gemini-3.5-flash | respondeu: 1º trecho em 0,92 s |
| gemini-2.5-flash | respondeu: 1º trecho em 0,73 s (raciocínio desligado) |
| gemini-3-flash-preview | respondeu: 1º trecho em 1,09–1,16 s |
| gemini-3.5-flash-lite | respondeu: 1º trecho em 0,76 s |

Por isso o núcleo agora **testa** os candidatos na inicialização (um por vez, do mais novo ao mais
antigo, parando no primeiro que responde em até 1,5 s) e guarda a escolha por 12 h.

### Conversa, histórico, ferramentas e erros

| Teste (API real) | Resultado |
|---|---|
| Conversa com resposta incremental | ✅ "Boa tarde, senhor. Na verdade, já passamos do meio-dia por aqui. Como posso ser útil hoje?" · 1º trecho em 1,16 s |
| Histórico | ✅ Lembrou "abacaxi-42", dito duas mensagens antes. |
| Function calling ("Que horas são e como está o meu computador?") | ✅ Pediu `get_local_time` e `get_system_status`; ambas executadas (`executed: true`); resposta com os números reais em 2,70 s. |
| Pedido para destrancar a fechadura | ✅ Recusou sem chamar ferramenta: "Sinto muito, senhor, mas não tenho permissão para destravar a fechadura. É uma medida de segurança que exige autenticação forte adicional." |
| Chave inválida | ✅ Erro `auth` em 0,3 s, mensagem apontando para `backend/.env`. |
| Tempo esgotado | ✅ Erro `timeout`. |
| Servidor inalcançável | ✅ Erro `offline` (antes da correção: `unknown`). |
| Modelo inexistente, sem reserva | ✅ Erro `model_not_found`. *(Corrigido depois da execução; na execução original o script esperava falha e o reserva assumiu.)* |
| Modelo inexistente, com a lista da conta | ✅ O próximo modelo respondeu: "Funcionando." |
| Cota estourada (429) | ✅ Distingue minuto de dia pela resposta do Google; não repete no mesmo modelo; passa ao próximo e lembra disso entre execuções. |
| Cobrança | Nenhuma alteração. Todas as chamadas foram no nível gratuito. |

Relatório gerado pelo script: [`evidence/0.2.1/validacao-real.md`](../evidence/0.2.1/validacao-real.md).

## 3. Voz — testes reais

| Teste (API real) | Resultado |
|---|---|
| Amostras com `gemini-3.8-flash-tts`, interpretação cinematográfica | ✅ 6 vozes (ver tabela). Na 7ª (Rasalgethi) a cota de voz acabou. |
| Amostras contêm só a frase | ✅ 5,3–6,1 s cada. Antes da correção: 38 s, porque o modelo **lia a direção de estilo em voz alta**. |
| Mesma voz em 4 interpretações | ✅ Cinematográfica, sóbria, calorosa e neutra (Charon). |
| Streaming | ✅ 1º pedaço de áudio em 0,70–0,74 s, contra 4,0 s esperando o arquivo inteiro. |
| Formato do streaming | ✅ PCM 16 bits little-endian, 24 kHz. Lido como big-endian vira ruído; o núcleo usa little-endian. |

| Voz | Duração | Tom mediano | Arquivo |
|---|---|---|---|
| Algieba | 5,7 s | 102 Hz | `evidence/0.2.1/vozes/gemini-Algieba.mp3` |
| Charon | 5,6 s | 128 Hz | `gemini-Charon.mp3` |
| Schedar | 5,5 s | 128 Hz | `gemini-Schedar.mp3` |
| Algenib | 6,1 s | 130 Hz | `gemini-Algenib.mp3` |
| Iapetus | 5,5 s | 132 Hz | `gemini-Iapetus.mp3` |
| Orus | 5,3 s | 141 Hz | `gemini-Orus.mp3` |
| Charon · sóbria | 5,6 s | 103 Hz | `gemini-Charon-sobrio.mp3` |
| Charon · calorosa | 6,0 s | 123 Hz | `gemini-Charon-caloroso.mp3` |
| Charon · neutra | 5,7 s | 138 Hz | `gemini-Charon-neutro.mp3` |
| Charon · streaming (3.1-flash-tts-preview) | 4,4 s | 183 Hz | `gemini-3.1-tts-streaming-Charon.mp3` |
| Voz local (espeak-ng, Linux) | 6,5 s | 93 Hz | `local-espeak-pt-br.mp3` |

Frase: "Bom dia, senhor. Todos os sistemas estão operacionais. Em que posso ajudá-lo?"

O tom mediano é uma medida objetiva de quão grave a voz soa (menor = mais grave). Timbre,
naturalidade e sotaque eu **não** consigo avaliar: precisam do seu ouvido. Pela medida, as
candidatas mais graves ao perfil médio-grave são **Algieba**, **Charon** e **Schedar**, e a
interpretação **sóbria** deixou a Charon mais grave. O mesmo nome de voz soa diferente em cada
modelo: a Charon no 3.1-flash-tts ficou bem mais aguda (183 Hz) que no 3.8-flash-tts (128 Hz).

## 4. Microfone — testes reais

O Chromium recebeu como "microfone" um arquivo com a fala "Jarvis, que horas são?" gerada pelo
Gemini TTS. Transcrição, conversa e voz foram **reais**; o microfone **não** foi físico.

| Teste | Resultado |
|---|---|
| Autorização antes de enviar áudio à nuvem | ✅ O HUD pediu e só gravou depois de "Permitir". |
| Indicadores durante a gravação | ✅ "● MICROFONE CAPTURANDO" e "NUVEM · ÁUDIO ENVIADO AO GEMINI". |
| Anéis reagem ao volume captado | ✅ Pico 1,00. |
| Botão de falar | ✅ Transcrito "Jarvis, que horas são?" (1,6–2,0 s) → "São treze horas e quatorze minutos, senhor. O dia é quinta-feira, doze de novembro." |
| Escuta contínua desligada por padrão | ✅ |
| Palavra de ativação | ✅ Comando "que horas são?" (sem o "Jarvis") → "Agora são treze horas e quinze minutos, senhor." |
| Fala sem "Jarvis" no modo de ativação | ✅ Ignorada (teste do motor de transcrição com a frase de exemplo). |
| Desligar a escuta contínua | ✅ Microfone liberado, indicadores somem. |

Execução no navegador: **18 de 19 verificações**. A que falhou procurava a seção "ÁUDIO" das
configurações, que renomeei para "VOZ" e "MICROFONE"; o teste foi corrigido depois. Capturas
em [`evidence/0.2.1/`](../evidence/0.2.1/).

## 5. Latência real (da pergunta até a voz começar)

| Situação | Texto | Voz |
|---|---|---|
| Antes do streaming (validação) | 0,58–0,86 s | 3,07–4,00 s |
| Com streaming, modelo livre | 1,73–2,40 s | 0,7–1,05 s depois do texto (2,78–3,26 s no total) |
| Com streaming, cotas esgotadas no meio do turno | 6,99–7,70 s | 7,81–22,86 s |

Os tempos de texto na segunda linha foram maiores que na primeira porque, àquela altura, os
modelos mais rápidos já estavam sem cota e o núcleo passava pelos reservas. A última linha mostra
o pior caso: vários modelos de voz esgotados em sequência. Com cota disponível, a expectativa é
texto em ~0,6–0,9 s e voz ~0,7 s depois.

O que reduziu a latência: streaming de voz, raciocínio mínimo aceito por cada modelo, primeira
frase curta enviada logo à síntese, e escolha do modelo que respondeu mais rápido no teste.

## 6. Cotas do nível gratuito (medidas)

| Item | Valor informado pela API |
|---|---|
| Pedidos por minuto, por modelo | 5 (`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`) |
| Pedidos por dia, por modelo | 20 (`GenerateRequestsPerDayPerProjectPerModel-FreeTier`) |
| Modelo de voz gemini-3.8-flash-tts | Recusou com limite diário após ~10 pedidos. Três pedidos seguintes ao mesmo modelo ainda funcionaram — o comportamento da cota de voz não foi consistente. |

Uma resposta falada típica usa 1 a 3 pedidos de conversa e até 2 de voz. Com ~6 modelos de
conversa e 5 de voz trocando entre si, o nível gratuito comporta **algumas dezenas de respostas
faladas por dia**. Ao fim dos testes estavam esgotados: 2.5-flash, 3.5-flash, 3.6-flash,
3.7-flash, 3.8-flash, 3.8-flash-tts, 3.8-flash-lite-tts e 2.5-pro-preview-tts. Essas cotas
renovam no dia seguinte.

Para uso contínuo o caminho é habilitar faturamento na conta Google — **não fiz isso**; é uma
decisão sua.

## 7. Problemas encontrados e corrigidos

| # | Problema (como apareceu) | Correção |
|---|---|---|
| 1 | A API `v1` recusa a instrução de sistema (erro 400 real). | Cliente usa `v1beta` (`GEMINI_API_VERSION`). |
| 2 | Nomes de modelo presumidos (`gemini-2.5-flash`, `…-preview-tts`). | `GEMINI_MODEL=auto`: lista a conta, filtra modelos de conversa/voz/transcrição e escolhe. |
| 3 | Os modelos mais novos davam 503/504 e travavam ~24 s. | Teste de resposta na inicialização, limite de 12 s até o 1º trecho e troca automática para o próximo modelo que funciona. |
| 4 | `thinking_level=MINIMAL` recusado pelo 3.7/3.8 Flash. | Escada mínimo → baixo → padrão, lembrada por modelo. |
| 5 | **A voz lia a direção de estilo em voz alta** (amostra de 38 s). | Direção vai no campo próprio (`speech_metadata.style`); se o modelo não aceitar, só o texto é enviado. |
| 6 | Transcrição dedicada voltava vazia: o resultado vem em `audio_transcription`, não em `text`. | Leitura das partes certas da resposta. |
| 7 | Falhas de rede apareciam como "Falha inesperada": o SDK usa `httpx2`, não `httpx`. | Classificação pelo nome das classes de erro. |
| 8 | Cota estourada era repetida no mesmo modelo; sem distinguir minuto e dia. | Lê o tempo de espera e o tipo da cota, não repete no mesmo modelo, guarda as cotas esgotadas em `backend/data/gemini_state.json`. |
| 9 | Voz começava 3–4 s depois do texto. | Streaming de voz até o HUD e síntese em paralelo, entregue em ordem. |
| 10 | Uma síntese por frase consumia a cota de voz rapidamente. | Modo econômico (padrão): no máximo 2 pedidos de voz por resposta; amostras do painel em cache. |
| 11 | Velocidade de reprodução mudaria o tom da voz no streaming. | Ritmo pedido na direção (Gemini) ou pela taxa do motor (voz local). |
| 12 | Uma variável `speak` sobrescrita encerrava a conexão do HUD em silêncio. | Renomeada; achado pelos testes automatizados. |
| 13 | Horas, unidades e símbolos eram lidos de forma estranha ("07:18", "22.5°C", "km/h"). | Normalização para fala ("7 e 18", "22,5 graus", "quilômetros por hora"); a legenda mantém o original. |

## 8. Real × simulado nesta entrega

| Item | Como foi testado |
|---|---|
| Conversa, histórico, ferramentas, erros, modelos | Real (API Gemini) |
| Vozes, estilos, streaming | Real (API Gemini TTS) |
| Transcrição e palavra de ativação | Real (API Gemini), com fala sintética como entrada |
| Microfone físico, cancelamento de eco | Não testado |
| Leituras do computador | Real, em Linux |
| Abrir apps, volume, voz SAPI | Não testado (exige Windows) |
| Clima | Real (Open-Meteo); hoje respondeu "limite atingido" para o IP compartilhado desta nuvem, e o HUD mostrou "sem dados" |
| Testes automatizados (117) | Simulados: o Gemini é substituído por dublês, para rodar sem chave e sem cota |
| LEDs, persiana, fechadura, robô | Simuladores; nenhum hardware conectado |

## 9. Pendências para a 0.3

1. **Cotas:** decidir entre habilitar faturamento ou levar partes para o computador (transcrição
   com Whisper local, voz neural local como Piper). O Whisper não foi testado: baixar o modelo
   exigia liberar o Hugging Face na rede deste ambiente, o que foi recusado.
2. **Gemini Live API:** a conta oferece `gemini-3.8-live` e `gemini-3.1-flash-live-preview`. Permitem
   conversa por voz contínua com interrupção falando por cima, sem as três etapas atuais.
3. **Windows:** rodar `INICIAR.bat` e `VALIDAR_GEMINI.bat`, testar voz SAPI, volume (pycaw),
   abertura de apps e o microfone físico com cancelamento de eco.
4. **Palavra de ativação local:** detectar "Jarvis" no computador antes de enviar áudio à nuvem —
   hoje, na escuta contínua, toda fala detectada é enviada.
5. **Interrupção por voz** durante a fala do assistente (hoje é meio-duplex: botão ou `Esc`).
6. **Voz:** você ouvir as amostras e escolher; refinar o texto da direção; testar as vozes que não
   couberam na cota (Rasalgethi, Sadaltager e outras).
7. **Mapa real de Itumbiara** (OpenStreetMap/MapLibre) no lugar da cidade fictícia.
8. **Fonte de notícias** escolhida por você.
9. **Dispositivos:** drivers reais de LEDs (BLE) e persiana (ESPHome). Fechadura e robô só depois do
   desenho de segurança.
10. **Desempenho** do HUD em uma RTX 2050.
