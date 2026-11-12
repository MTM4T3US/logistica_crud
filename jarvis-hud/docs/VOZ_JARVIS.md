# Voz do JARVIS

## Identidade vocal pretendida

Masculina, adulta, registro médio-grave, timbre encorpado e elegante. Dicção brasileira clara,
ritmo moderado com pausas naturais, calma e confiante, com um leve acabamento "tecnológico" que
não atrapalhe a compreensão. É uma identidade **original**: nada aqui clona ou imita a voz de um
ator ou dublador. O SDK do Gemini tem um recurso de voz replicada (`ReplicatedVoiceConfig`); ele
não é usado e não deve ser usado para copiar a voz de outra pessoa.

## Estado (0.2.1)

| Item | Situação |
|---|---|
| Amostras reais com vozes Gemini | ✅ Charon, Orus, Algieba, Algenib, Iapetus e Schedar, mais 3 interpretações da Charon. |
| Ouvir e escolher cada voz pelo painel | ✅ Configurações → Voz: ▶ para ouvir, "Usar" para escolher. |
| Interpretação, ritmo e pausas | ✅ 4 interpretações; ritmo de 0,8× a 1,3×; normalização de horas e unidades. |
| Latência | ✅ Streaming: primeiro áudio ~0,7 s após a frase ficar pronta. |
| Núcleo sincronizado com o áudio verdadeiro | ✅ Amplitude medida do áudio que está tocando. |
| Escolha final da voz | ⚠️ Depende de você ouvir. Eu meço o tom, mas não avalio timbre nem naturalidade. |
| Voz local no Windows (SAPI5) | ⚠️ Implementada, não testada. |
| Gemini Live API | ❌ Não integrada (pendência da 0.3). |

## Amostras para comparar

Em [`evidence/0.2.1/vozes/`](../evidence/0.2.1/vozes/) (MP3). Frase: "Bom dia, senhor. Todos os
sistemas estão operacionais. Em que posso ajudá-lo?" — modelo `gemini-3.8-flash-tts`,
interpretação cinematográfica, salvo indicação.

| Voz | Tom mediano | Observação |
|---|---|---|
| Algieba | 102 Hz | a mais grave medida |
| Charon | 128 Hz | |
| Schedar | 128 Hz | |
| Algenib | 130 Hz | |
| Iapetus | 132 Hz | |
| Orus | 141 Hz | a mais aguda das seis |
| Charon · sóbria | 103 Hz | a interpretação sóbria deixou a voz mais grave |
| Charon · calorosa | 123 Hz | |
| Charon · neutra | 138 Hz | sem direção |
| Charon · streaming (3.1-flash-tts-preview) | 183 Hz | mesmo nome, outro modelo: bem mais aguda |

O tom mediano é medido por autocorrelação; quanto menor, mais grave. É um critério objetivo para
o "médio-grave", não para timbre. Sugestão de ordem para ouvir: **Algieba, Charon (sóbria),
Charon, Schedar**.

Para gerar mais vozes com a sua cota: `VALIDAR_GEMINI.bat --vozes Rasalgethi Sadaltager Kore`
(cada voz gasta 1 pedido de voz).

## Como a interpretação é enviada

O Gemini TTS recebe a direção de interpretação no **campo de estilo** de cada trecho
(`speech_metadata.style`), separado do texto a ser falado. Na 0.2 a direção ia junto do texto e
o modelo a **lia em voz alta** (amostra de 38 s); isso foi corrigido. Se um modelo recusar o campo
de estilo, só o texto é enviado — a direção nunca vira fala.

Interpretações (`backend/app/voice/tts.py`, `STYLES`):

| Interpretação | Direção (resumo) |
|---|---|
| Cinematográfica (padrão) | assistente de IA sofisticado: calmo, confiante, cortês, elegância contida, leve ironia fina; pausas curtas nas vírgulas e mais longas entre frases |
| Sóbria | sereno, profissional, discreto, quase sem ênfases |
| Calorosa | acolhedor, leve sorriso na voz, sem perder a elegância |
| Neutra | sem direção |

Todas começam por "voz masculina adulta, registro médio-grave, timbre encorpado, português do
Brasil com dicção natural e clara". Edite os textos para refinar.

## Ritmo, pausas e pronúncia

- **Ritmo:** no Gemini, o controle de velocidade vira uma instrução na direção ("ritmo um pouco
  mais lento…"); acelerar a reprodução mudaria o tom da voz. Na voz local, ajusta a taxa do motor.
- **Pausas:** travessões e parênteses viram vírgulas; a direção pede pausas maiores entre frases.
- **Pronúncia:** antes da síntese, "07:18" vira "7 e 18", "22.5°C" vira "22,5 graus", "87%" vira
  "87 por cento", "km/h" vira "quilômetros por hora", "GB" vira "gigabytes". A legenda mostra o
  texto original.

## Latência

| Etapa | Medido |
|---|---|
| Arquivo de voz inteiro (sem streaming) | 2,7–4,0 s por pedido |
| Primeiro pedaço em streaming | 0,70–0,74 s |

Como a fala começa cedo:

1. A primeira frase é enviada à síntese assim que termina (mesmo curta, como "Bom dia, senhor.").
2. O áudio vem em streaming e o HUD toca cada pedaço assim que chega.
3. As frases seguintes são sintetizadas em paralelo e tocadas em ordem, sem buracos.

**Modo econômico** (padrão, `JARVIS_TTS_CHUNKING=economico`): a primeira frase sai sozinha e todo o
resto vai em um único pedido — no máximo 2 pedidos de voz por resposta, por causa da cota. Com
`frase`, cada frase é um pedido (fala mais fluida em respostas longas, gasta mais cota).

## Mecanismos de síntese

| Mecanismo | Onde roda | Observações |
|---|---|---|
| `gemini` | Nuvem | Streaming; troca de modelo de voz quando um esgota a cota. |
| `local` | Computador | Windows: vozes SAPI5 (pt-BR primeiro). Linux: espeak-ng (robótica). Gratuito e offline. |
| `auto` | — | Gemini com chave; se a nuvem falhar antes do primeiro áudio, a frase sai pela voz local, com aviso. |
| `off` | — | Só legenda; o núcleo não simula fala. |

## Cadeia de áudio no HUD

`src/core/audio.ts`: os pedaços (PCM 16 bits, 24 kHz) e os WAVs entram em uma linha do tempo do
Web Audio → passa-altas → processamento "tecnológico" (0–100 %) → compressor leve → volume →
analisador → saída escolhida. O analisador mede a amplitude do que está tocando: é esse valor que
move o glifo, os anéis, o feixe e a base. A legenda revela o texto de cada trecho conforme o
tempo de reprodução.

## Reconhecimento de fala

- **Botão de falar** (ou `M`): pede o microfone, grava e encerra após ~1 s de silêncio.
- **Escuta contínua:** **desligada por padrão**. Ligada, só vira comando a frase que contém
  "Jarvis" (e grafias próximas); o "Jarvis" é removido do comando.
- **Transcrição:** `gemini-3.5-transcribe` (modelo dedicado da sua conta) ou, se indisponível, o
  modelo de conversa. O HUD pede autorização antes do primeiro envio e mostra
  **NUVEM · ÁUDIO ENVIADO AO GEMINI** enquanto grava.
- **Atenção:** na escuta contínua com transcrição na nuvem, **toda fala detectada é enviada** para
  checar se contém "Jarvis", e cada envio gasta cota. Para manter o áudio no computador, use o
  Whisper local (`pip install -r backend\requirements-whisper.txt`, não testado nesta versão).
- **Eco:** cancelamento de eco do navegador; a escuta fica bloqueada enquanto o assistente fala.
- **Interromper:** botão "Parar", `Esc`, novo comando ou o botão de falar.

## Gemini Live API

A conta oferece `gemini-3.8-live` e `gemini-3.1-flash-live-preview`. A Live API faria conversa por
voz contínua, com interrupção falando por cima e sem as três etapas atuais (transcrever, responder,
sintetizar). Fica para a 0.3: exige um provedor de sessão contínua que reaproveite as ferramentas
e o protocolo atuais.
