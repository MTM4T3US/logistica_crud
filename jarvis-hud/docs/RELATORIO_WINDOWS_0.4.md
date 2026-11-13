# Relatório — JARVIS OS 0.4 no Windows

Data: 12/11/2026, 23:28–00:00 (continuação do teste da 0.3, ver [`RELATORIO_WINDOWS_0.3.md`](RELATORIO_WINDOWS_0.3.md)).

**PC real (não é o esperado Windows 10/i7):** Windows 11 Pro 10.0.22621 · AMD Ryzen 7 7435HS (8 núcleos/16 threads) ·
15,8 GB RAM · NVIDIA RTX 2050 4 GB · ASUS TUF A15 · Bluetooth Realtek (LE ok) · Python 3.12.3 (venv) · Node 24.14.1.

Instalação: pasta nova `Downloads\jarvis-os-0.4` (do .zip, **não é repositório git**). Copiados da 0.3, como o roteiro manda manter:
`backend\.env` (cópia de arquivo, sem exibir), `backend\config\permissions.json` (caminho do projeto jarvis → pasta da 0.4),
`backend\data\` e `backend\models\` (524 MB, evita baixar de novo).

## 1. Tabela de testes

| Fase | Teste | Status | Evidência |
|---|---|---|---|
| 1 | `INICIAR.bat` (venv novo, npm, build, núcleo) | REAL-FALHOU → corrigido → REAL-OK | 1ª vez: núcleo caiu com `JSONDecodeError: Unexpected UTF-8 BOM` no `permissions.json` (o BOM veio do meu ajuste via PowerShell 5.1; o mesmo acontece com quem salva no Bloco de Notas antigo). Leitor agora aceita BOM. Depois: "JARVIS OS 0.4 · NÚCLEO ONLINE · IA GEMINI" |
| 1 | `INSTALAR_RECURSOS_LOCAIS.bat` | REAL-OK | "Tudo pronto." já na 1ª execução (correção do openWakeWord trazida da 0.3) |
| 1 | `VALIDAR_GEMINI.bat --rapido` (uma vez) | SÓ-API | 17 passaram · 0 falharam. 1ª resposta em **37,8 s** (o automático escolheu `gemini-3.8-flash`, indisponível; trocou de modelo). Ferramentas reais, histórico, fechadura recusada, erros traduzidos (`backend\samples\validacao.md`) |
| — | `pytest -q` | REAL-OK | 194 passed, 2 skipped (178 da 0.4 + 16 trazidos/criados nesta sessão) |
| — | `npm run build` | REAL-OK | "✓ built" |
| 4 | Comandos locais sem Gemini (volume, LEDs, hora, clima, VS Code, mapa, novidades) | REAL-OK | `turn_end.mode = "router"` em todos |
| 4 | **Sem internet** (simulado só no núcleo: proxy inválido, escolha do usuário) | SIMULADO | volume 30 ✓ (real 30 %), LEDs azul ✓, hora ✓, VS Code ✓ (janela apareceu); clima: "Clima indisponível: sem conexão com o provedor"; pergunta aberta: erro `offline` → "Continuando em modo local, sem IA" + "Continuando com a voz local" |
| 4 | Entrada por rosto sem internet | REAL-OK | usuário entrou com o rosto com o núcleo sem internet |
| 4 | Contagem de pedidos por modelo | REAL-OK | painel lista cada modelo de voz com "cota esgotada"; após a validação só `gemini-2.5-flash-preview-tts` tinha cota |
| 6 | Fita na 0.4 (driver com as correções da 0.3) | REAL-OK | conectou sozinha ao iniciar; "coloque os leds em azul" executado |
| 6 | **Efeito de abertura** na 0.4 | REAL-OK | usuário: "Sim, vi o efeito" (núcleo iniciado 23:35, sem rosto cadastrado) |
| 6 | **Apresentação de entrada** (novo: rosto/PIN aceito → acende, pulsa, "respira" com a música; voz assume nas boas-vindas) | REAL-OK (visão geral) | usuário, após a 1ª entrada completa: "deu tudo certo". Detalhes por etapa não foram anotados |
| 6 | Luz acompanha a voz (boas-vindas e resumo) | REAL-OK (com ressalva da 0.3) | idem; ainda um pouco atrasada segundo o usuário (ajuste pendente) |
| 7 | Desempenho | NÃO-TESTADO (FPS) | medido no painel de navegador do app, mas o painel estava **oculto**: 3,7 FPS com GPU a 1 % = navegador em segundo plano, não vale. Leituras reais do PC na hora: CPU 11 %, **RAM 80 % (12,7/15,8 GB)**, GPU 1 %, VRAM 1157/4096 MB, núcleo 739 MB (`backend\data\desempenho-20261112-235136.md`). Medir no Brave em tela cheia |
| 8 | Núcleo só em 127.0.0.1 | REAL-OK | `netstat`: `127.0.0.1:8765 LISTENING` |
| 8 | Bloqueado: o que responde | REAL-OK | `/api/state` 200 (tela de bloqueio); history, actions, memory, system, briefing, música, settings → **423** |
| 9 | Cadastro do rosto (PIN + 6 capturas) | REAL-OK | núcleo: `enrolled: true, samples: 6, pin_set: true`; usuário: "deu tudo certo". **Tempo e leituras/s não anotados** |
| 9 | Entrada pelo rosto (dono) | REAL-OK | entrou 2 vezes (com e sem internet). **Correspondência % não anotada** |
| 9 | Recusas (foto, outra pessoa, vídeo), luz fraca, óculos | NÃO-TESTADO | usuário sem os números agora |
| 9 | Luz da webcam apaga depois de entrar | REAL-OK (visão geral) | incluído no "deu tudo certo"; não perguntado separadamente |
| 9 | PIN errado 5× → pausa | REAL-OK | PINs com letras (nunca coincidem com o do usuário): 1–4 "PIN incorreto."; 5ª "Muitas tentativas: aguarde 30 s."; 6ª `cooldown`, retry 30 s |
| 9 | Fechar navegador > 2 min / F5 | NÃO-TESTADO | |
| 10 | Música de entrada escolhida | REAL-OK | `intro.music_name = Highway_to_hell.mp3`, guardada só em `backend\data\entrada\musica.mp3` (4,5 MB) |
| 10 | Música + boas-vindas + voo para a cidade | REAL-OK (visão geral) | "deu tudo certo"; volume, momento da fala e corte final não avaliados em detalhe |
| 11 | `baixar_mapa.py` | REAL-OK | 37,7 s: **935 ruas, 191 prédios** (13 com altura), 73 trechos de água, 54 parques, 11 pontos de referência; aviso de poucos prédios no OSM |
| 11 | "mostra o mapa" | REAL-OK | roteador; `ui.show_map`; "Mapa real de Itumbiara aberto no HUD (© colaboradores do OpenStreetMap (ODbL))". Reconhecimento das ruas pelo usuário: não perguntado |
| 11 | "quais as novidades" | REAL-FALHOU → corrigido | clima real (Open-Meteo 22,7 °C) e manchetes reais (Agência Brasil, Rota Jurídica), mas um post do **Instagram** veio com a legenda cortada ("…a expectativa d") e era o **mesmo fato** da manchete seguinte. Corrigido (ver abaixo). Links: 2 conferidos, HTTP 200 (páginas do Google Notícias) |
| 11 | "bloqueia o Jarvis" | REAL-OK | "Bloqueado, senhor. Até logo."; depois "desbloqueia o Jarvis" e "volume 20" → `locked` |
| 2 | Voz (amostras, escolha, tempos) | NÃO-TESTADO | |
| 3 | Microfone físico, escuta contínua, "Jarvis" sem "Hey", eco, ruído | NÃO-TESTADO | |

## 2. Problemas e correções

**Trazidos da 0.3** (mesmo código na 0.4; ver relatório da 0.3 para o motivo de cada um): modelo do openWakeWord; `.env` com
valores vazios; Whisper com PyAV 19; Whisper travando na GPU sem CUDA; scan BLE do diagnóstico; respostas do roteador com voz
local; rotina parcial dita como "executada"; "brilho em 30%" indo à IA; aviso quando a IA afirma ação sem ferramenta; fita fora
da tomada (82 s → 25 s); loop Bluetooth tardio; efeitos de luz (abertura e voz). Aplicados com `patch` (só `config.py` precisou
de ajuste à mão, pois a 0.4 mudou o mesmo trecho).

**Novos na 0.4:**
1. `app/security/permissions.py` — `permissions.json` com BOM derrubava o núcleo; lê com `utf-8-sig`. Teste novo.
2. `app/devices/led_effects.py` + `assistant.py` (`on_entry`) + `main.py` — **apresentação de entrada** pedida pelo usuário: ao
   aceitar rosto/PIN, a fita acende, pulsa e "respira" (2,4 s por ciclo) enquanto a música toca, por até 25 s; quando as
   boas-vindas começam, o efeito de voz assume; no fim fica no estado escolhido (ou Azul JARVIS). Com a entrada por rosto ativa,
   o efeito ao iniciar o núcleo não roda (ele começa bloqueado). Com as luzes desligadas pelo usuário, voltam a apagar. 2 testes.
3. `app/services/briefing.py` — manchetes: corta legendas longas na última frase/palavra inteira e não repete o mesmo fato
   vindo de duas fontes (fica a manchete mais curta). Teste com o caso real.

**Observado, não corrigido:**
- O Windows estava no **mudo** no fim do teste (não fui eu); "volume 30" respondeu "Volume em 30% (mudo)" e não tira do mudo.
  Sugestão: definir volume tira do mudo.
- A entrada usa a voz Gemini nas boas-vindas e no resumo (2 pedidos de voz por entrada); com a cota de voz esgotada, cai para Piper.
- RAM do PC em 80 % e disco 93 % cheio (31 GB livres) durante os testes.
- O 1º pedido do dia ao Gemini pode demorar ~38 s quando o modelo automático está indisponível.
- Título da aba do navegador ainda "JARVIS OS 0.2.1".

## 3. Desempenho

FPS não medido de forma válida (ver Fase 7). `backend\data\desempenho-20261112-235136.md` contém as leituras reais do PC.

### Entrada por rosto

| Tentativa | Pessoa/objeto | Correspondência % | Anti-foto % | Entrou? |
|---|---|---|---|---|
| 1 | dono (1ª entrada, com internet) | não anotado | não anotado | sim |
| 2 | dono (sem internet) | não anotado | não anotado | sim |

Sem os números não é possível sugerir `JARVIS_FACE_THRESHOLD` (continua 0,62) nem `JARVIS_FACE_ANTISPOOF_MIN` (continua 0).

## 4. Pendente

1. Fase 9 completa com números: 3× luz normal, luz fraca, óculos/boné, foto no celular, outra pessoa (com consentimento),
   vídeo; tempo do cadastro e leituras/s; F5 e navegador fechado > 2 min. Depois calibrar o limiar.
2. Fase 10 em detalhe: volume da música, momento da fala, corte final.
3. Fase 11: o usuário reconhece as ruas de Itumbiara?
4. Fases 2 e 3 (voz e microfone reais, incluindo se "Jarvis" sem "Hey" dispara — na simulação com voz sintética só "Hey Jarvis" disparou).
5. Fase 7 no Brave em tela cheia (média e alta).
6. Atraso da luz em relação à voz (o usuário pediu para deixar para depois).
7. Mídia (Spotify/YouTube) e acesso de outro aparelho.
8. Commit: as pastas vieram de .zip, **não são repositório git**; nada foi commitado.
