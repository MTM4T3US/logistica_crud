# Relatório — JARVIS OS 0.4 (entrada por rosto, música, resumo e mapa reais)

Feito entre 12 e 13/11/2026, num contêiner Linux na nuvem, **sem acesso ao seu Windows, à sua webcam
nem à internet aberta**. Os testes de navegador usaram uma câmera falsa (um quadro com fotos públicas de
rostos) e um processador gráfico em software. O que falta testar no seu PC está em
[`PROMPT_TESTE_WINDOWS.md`](PROMPT_TESTE_WINDOWS.md), fases 9 a 11.

## O que mudou

| Pedido | O que foi feito |
|---|---|
| Rosto parecendo um "ovo" | A cabeça holográfica agora usa a malha canônica do MediaPipe Face Mesh (468 pontos, 898 triângulos). Com a câmera ligada, **os mesmos 468 pontos seguem o seu rosto real** (sorriso, cabeça virada). |
| Entrar só se o rosto coincidir | Tela de bloqueio "IDENTIFICAÇÃO NECESSÁRIA". A câmera liga, o navegador mede o rosto **no próprio PC** (biblioteca Human, MIT) e manda ao núcleo só um vetor de números; o núcleo compara com o cadastro e libera. Pede uma piscada (prova de vida). PIN reserva. 5 erros → pausa de 30 s, depois 2 e 10 min. |
| Música ao entrar | Configurações → MÚSICA DE ENTRADA: você escolhe um arquivo **seu**; ele fica só em `backend/data/entrada/`. Toca ao confirmar o rosto, abaixa quando o JARVIS fala e some no fim. |
| Boas-vindas e cidade | Depois do rosto: "Boa noite, senhor. Bem-vindo de volta. São 22 horas e 55, quinta-feira, 12 de novembro." → a câmera voa para a cidade **no momento em que essa parte da fala começa** → clima e notícias. Montado no próprio núcleo: **não gasta o Gemini**. |
| Novidades e clima reais | Clima: Open-Meteo. Notícias: Google Notícias de Itumbiara (7 dias) e do Brasil (1 dia), os mesmos feeds do seu `noticias_jarvis.py`. Fonte falhou → ele diz que falhou. |
| Cidade 3D | Itumbiara real do OpenStreetMap: ruas brilhantes, prédios nas pegadas reais, rio, parques e pontos de referência. Baixada uma vez e guardada no PC. Sem o mapa, a cidade fictícia continua, com o aviso na tela. |
| Comandos locais | "mostra o mapa", "quais as novidades", "bloqueia o Jarvis" — sem Gemini. Nenhum comando de voz ou da IA desbloqueia. |

## Testes executados aqui

**Núcleo:** 178 testes automáticos passando (eram 157 na 0.3). Os 21 novos cobrem:
- comparação de rostos, cadastro, prova de vida, pausas, PIN e rebloqueio;
- bloqueio do servidor (HTTP 423 e WebSocket);
- ordem da entrada (boas-vindas → mapa → resumo);
- música (formato, tamanho, conteúdo);
- notícias com dois feeds, resumo honesto quando falta fonte, conversão do mapa OSM, comandos locais.

**Navegador com câmera falsa** (Chromium sem GPU; cada leitura do rosto levou ~21 s aqui):

| # | Situação | Resultado |
|---|---|---|
| 1 | Cadastro com piscada (6 capturas) | **OK** — o holograma copiou o rosto da foto |
| 2 | Bloquear agora | **OK** — tela de bloqueio, barra de comandos escondida |
| 3 | Núcleo reiniciado | **OK** — volta bloqueado |
| 4 | Foto parada da pessoa certa, sem piscar, 3 leituras | **Recusada** (fica em "Pisque uma vez") |
| 5 | Outra pessoa, piscando | **Recusada** — correspondência 44% (mínimo 62%) |
| 6 | Pessoa cadastrada, **outra foto dela**, piscando | **Entrou** — correspondência 69% |
| 7 | Depois de entrar | Câmera desligada; música buscada (200); boas-vindas com a hora certa de Itumbiara; foi para a cidade |
| 8 | Entrada com clima ligado | Clima **real** de Itumbiara falado: "23 graus, céu limpo… máxima de 30 e mínima de 21… 98 por cento de chance de chuva" |
| 9 | Notícias | Bloqueadas pela rede daqui → ele disse "Não consegui ler as notícias de Itumbiara agora" (não inventou) |
| 10 | Mapa real | OpenStreetMap bloqueado daqui → cidade fictícia com o aviso "NÃO REPRESENTA ITUMBIARA". O desenho da cidade real foi conferido com um **mapa sintético** (só para teste, não incluído) |
| 11 | "quais as novidades" | Respondido pelo roteador local, sem IA |

**Regressão da 0.3:** o teste de navegador antigo passou de novo, 14 de 14: conexão, relógio, clima real,
sistema, ferramentas, voz, microfone, configurações e nenhum erro de JavaScript.

As capturas destes testes não foram para o repositório: mostram fotos de terceiros e um mapa sintético.

## Status por item

| Item | Status |
|---|---|
| Malha do rosto realista + rosto ao vivo | **Real aqui** (câmera falsa) · **pendente** com a sua webcam |
| Reconhecimento: dono entra, outra pessoa não | **Real aqui** com fotos públicas · **pendente** com você e alguém da casa |
| Prova de vida (piscar) | **Real aqui** (pálpebras pintadas na câmera falsa) · **pendente** no PC |
| Nota anti-foto | **Não confiável ainda**: deu 72–83% para fotos digitais. Fica só como informação (`JARVIS_FACE_ANTISPOOF_MIN=0`); calibrar no PC |
| PIN reserva, pausas, rebloqueio | **Testes automáticos** |
| Música de entrada | Busca e ordem **testadas**; o som, a "abaixada" e o corte final **pendentes** (navegador daqui não tem saída de som) |
| Boas-vindas + voo para a cidade | **Real aqui** (voz local; com Gemini a voz será a escolhida no painel) |
| Clima no resumo | **Real aqui** (Open-Meteo respondeu) |
| Notícias no resumo | **Pendente** no PC (rede daqui bloqueia o Google Notícias) |
| Mapa real de Itumbiara | Download e conversão **testados com dados de exemplo**; desenho conferido com mapa sintético; **download real pendente** no PC |

## Segurança e privacidade

- **Nenhuma imagem é gravada ou enviada.** O cadastro guarda só números em `backend/data/rosto.json`
  (fora do Git), e o PIN guarda apenas o hash (PBKDF2, 200 mil iterações).
- **A câmera** liga só na verificação ou no cadastro e desliga logo depois de entrar.
- **Enquanto bloqueado,** o núcleo recusa tudo, exceto o rosto e o PIN: comandos, ajustes, música e mapa.
- **Limite honesto:** isto protege o JARVIS de quem senta no seu computador. Não substitui a senha do Windows.
  Quem tem acesso à sua conta do Windows ou usa ferramentas de desenvolvedor pode contornar. Um vídeo seu
  piscando pode enganar a prova de vida. Por isso a entrada por rosto **nunca** abre a fechadura.
- **Música:** o JARVIS não baixa nem distribui músicas. "Highway to Hell" tem direitos autorais: use um
  arquivo que você já tem.

## Pendências

1. Rodar as fases 9 a 11 do roteiro no seu PC e calibrar `JARVIS_FACE_THRESHOLD` com os seus números.
2. Ver se o mapa do OpenStreetMap de Itumbiara tem prédios suficientes. Se tiver poucos, o HUD mostra só
   as ruas e o que existe; não inventa prédios.
3. Prova de vida mais forte (ex.: pedir para virar o rosto para um lado sorteado).
4. Herdados da 0.3: IA local para assuntos sensíveis, efeitos de LED durante a fala, Gemini Live.
