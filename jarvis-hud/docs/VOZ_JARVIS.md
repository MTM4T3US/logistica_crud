# Voz do JARVIS

## Identidade vocal pretendida

Masculina, adulta, registro médio-grave, timbre encorpado e elegante. Dicção brasileira clara,
ritmo moderado com pausas naturais, calma e confiante. Um leve acabamento "tecnológico" que
não atrapalhe a compreensão. É uma identidade **original**: nada aqui clona ou imita a voz de
um ator ou dublador.

## Estado real desta entrega

| Item | Situação |
|---|---|
| Caminho completo texto → voz → núcleo reagindo | Funciona e foi medido (ver `evidence/0.2`). |
| Voz local em Linux (espeak-ng) | Testada. É robótica — serve como reserva sem nuvem. |
| Voz local no Windows (SAPI5 via pyttsx3) | Implementada, **não testada** (não tive acesso a Windows). |
| Gemini TTS (Charon, Orus e outras) | Implementado, **não testado com a API real** (sem chave). |
| Comparação das vozes em português | **Não feita.** O script abaixo gera as amostras para você comparar. |
| Gemini Live API | Investigada, **não integrada** (ver abaixo). |

Ou seja: a "voz cinematográfica" ainda depende de você rodar a comparação com a sua chave e
escolher. Não afirmo que Charon ou Orus entregam o resultado desejado.

## Como comparar as vozes

```powershell
cd jarvis-hud\backend
.venv\Scripts\python scripts\check_gemini.py Charon Orus Algieba Algenib Iapetus Schedar
```

Para cada voz o script grava `backend/samples/gemini-<voz>.wav` com a mesma frase e imprime a
duração e o **tom mediano em Hz** (quanto menor, mais grave). O número ajuda a ordenar o
registro, mas timbre, naturalidade e sotaque só se julgam ouvindo. Depois escolha em
Configurações → Áudio → Voz (o botão "Ouvir amostra" repete a frase) ou em `JARVIS_TTS_VOICE`.

A lista do painel (Charon, Orus, Algieba, Algenib, Iapetus, Rasalgethi, Schedar, Sadaltager,
Alnilam, Enceladus, Gacrux, Fenrir, Puck) e os adjetivos ao lado vêm da descrição pública das
vozes que eu conhecia; a lista oficial pode ter mudado.

## Direção de estilo (Gemini TTS)

O Gemini TTS aceita instruções em linguagem natural junto com o texto. A direção usada está em
`backend/app/voice/tts.py` (`STYLE_PROMPT`):

> Leia o texto a seguir em português do Brasil, com dicção brasileira natural e perfeitamente
> compreensível. Voz masculina adulta, registro médio-grave, timbre encorpado e elegante. Tom
> calmo, confiante e cortês, como um assistente sofisticado: pronúncia clara e precisa, ritmo
> moderado com pausas naturais, sem soar robótico nem teatral.

Ajuste esse texto para refinar a interpretação (por exemplo, mais sobriedade ou mais calor).
A gravidade vem da escolha da voz e da direção, não de baixar o tom artificialmente.

## Mecanismos de síntese

| Mecanismo | Onde roda | Observações |
|---|---|---|
| `gemini` | Nuvem | Envia o texto de cada frase ao Google. Qualidade neural. |
| `local` | Computador | Windows: vozes SAPI5 instaladas (as pt-BR aparecem primeiro). Linux/macOS: espeak-ng. Gratuito e offline. |
| `auto` | — | Gemini se houver chave; se a nuvem falhar, continua pela voz local e avisa. |
| `off` | — | Só legenda. O núcleo não simula fala. |

Para uma voz local melhor no Windows, instale vozes adicionais em *Configurações → Hora e
idioma → Fala*. Um motor neural offline (como o Piper, que tem voz pt-BR) caberia na mesma
interface `TTSEngine`; não foi incluído porque exigiria baixar modelos.

## Cadeia de áudio no HUD

`src/core/audio.ts`, tudo ajustável em Configurações → Áudio:

1. Filtro passa-altas em 65 Hz.
2. **Processamento "tecnológico"** (0–100 %): dobra de 13 ms filtrada em 2,4 kHz, realce de
   presença em 2,9 kHz e de corpo em 170 Hz. Em 0 % a voz sai praticamente original.
3. Compressor leve.
4. **Volume** e **velocidade** (0,8× a 1,3×, preservando o tom).
5. Analisador → saída escolhida.

O analisador mede a amplitude do que está tocando; esse valor é `rig.level`, que move o glifo,
os anéis, o feixe e a base. Não há envelope simulado fora do modo demonstração.

## Fala incremental e legendas

A resposta da IA chega em pedaços. O backend corta em frases completas e sintetiza cada uma
assim que termina, para a fala começar antes do fim da resposta. Cada trecho de áudio traz o
texto da frase; a legenda revela as palavras conforme `currentTime / duration` do áudio.

## Reconhecimento de fala

- **Botão de falar** (ou tecla `M`): pede o microfone, grava e encerra sozinho após cerca de
  1 s de silêncio. Um novo clique encerra antes. O microfone é liberado ao final.
- **Escuta contínua** (opcional, desligada por padrão): o microfone fica aberto, um detector
  de voz por energia recorta cada fala, ela é transcrita e só vira comando se contiver a
  palavra de ativação ("Jarvis" e grafias próximas). Falas sem a palavra são descartadas.
- **Motores:** Gemini (nuvem — exige consentimento e mostra o selo NUVEM) ou Whisper local
  (`pip install -r backend/requirements-whisper.txt`; não testado nesta entrega).
- **Eco:** a captura usa cancelamento de eco, supressão de ruído e ganho automático do
  navegador, e a escuta contínua fica bloqueada enquanto o assistente fala e por 450 ms depois.
- **Interrupção:** botão "Parar", `Esc`, um novo comando ou o botão de falar cortam a fala e a
  geração. Interromper apenas falando por cima só funciona pelo botão: com a escuta bloqueada
  durante a fala, a voz do usuário não é ouvida nesse intervalo.
- **Sem microfone:** tudo funciona por texto.

Na escuta contínua com transcrição em nuvem, **toda fala detectada é enviada ao Google** para
descobrir se contém a palavra de ativação. Para manter o áudio no computador, use o Whisper.

## Gemini Live API

A Live API oferece conversa por áudio em tempo real, com detecção de turno e interrupção
nativas. Não foi integrada porque não pude testá-la nem consultar a documentação atual, e
porque ela muda o desenho: o áudio vai direto ao modelo, e o registro de ferramentas, as
legendas e a medição de amplitude precisam ser religados a esse fluxo. O caminho previsto é um
novo `AIProvider` de sessão contínua que reutilize `ToolRegistry` e o protocolo de eventos
atual. Enquanto isso, a latência depende de três chamadas em sequência (transcrever, responder,
sintetizar por frase).
