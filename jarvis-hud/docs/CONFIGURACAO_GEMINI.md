# Configuração do Gemini

> **Estado:** validado com a API real em 12/11/2026, com uma chave no nível gratuito — conversa,
> histórico, function calling, erros, voz em streaming e transcrição. Resultados em
> [`RELATORIO_0.2.1.md`](RELATORIO_0.2.1.md).

## 1. Criar a chave

1. Acesse <https://aistudio.google.com/apikey> com a sua conta Google e clique em **Create API key**.
2. Não é preciso habilitar faturamento. O nível gratuito tem limites (abaixo). Este projeto
   nunca habilita cobrança.

## 2. Guardar a chave com segurança (Windows)

1. Rode o `INICIAR.bat` uma vez: ele cria `backend\.env` a partir do exemplo.
2. Abra `backend\.env` no Bloco de Notas.
3. Na linha `GEMINI_API_KEY=`, cole a chave logo depois do sinal de igual, sem espaços nem aspas:
   ```
   GEMINI_API_KEY=cole-a-chave-aqui
   ```
4. Salve e reinicie o `INICIAR.bat`. No HUD, o selo do topo deve mostrar **IA GEMINI**.

Regras para a chave:

- Ela fica **só** em `backend\.env`. Esse arquivo está no `.gitignore` e não vai para o Git nem
  para os pacotes `.zip`. O HUD nunca recebe a chave (um teste automatizado falha se ela aparecer
  no código do navegador).
- **Não cole a chave em conversas, e-mails ou capturas de tela.** Se isso acontecer, apague a chave
  em <https://aistudio.google.com/apikey> e crie outra.
- Em outra máquina, crie um `backend\.env` novo; não copie a chave por canais públicos.

## 3. Validar

Dois cliques em **`VALIDAR_GEMINI.bat`** (ou
`backend\.venv\Scripts\python backend\scripts\validar_gemini.py`). Ele verifica o SDK, os erros,
lista os modelos da sua conta, testa conversa, histórico, ferramentas, gera amostras de voz,
testa a transcrição e mede a latência. O relatório fica em `backend\samples\validacao.md` e as
amostras em `backend\samples\*.wav`.

Opções: `--rapido` (sem vozes), `--vozes Charon Orus Kore` (só gerar essas vozes),
`--erros` (só o tratamento de erros, não usa a chave). A execução completa gasta cerca de
15 pedidos de conversa e 14 de voz — veja as cotas abaixo.

## 4. Modelos — escolhidos a partir da sua conta

Com `GEMINI_MODEL=auto` (padrão) nenhum nome é presumido:

1. Na inicialização o núcleo lista os modelos da conta (API `v1beta`) e separa os de conversa,
   de voz (`…-tts`) e de transcrição (`…-transcribe`).
2. Testa os candidatos de conversa **um por vez**, do mais novo ao mais antigo, e para no
   primeiro que responde em até `GEMINI_MAX_FIRST_TOKEN_S` (1,5 s). Se nenhum couber nesse
   tempo, fica com o mais rápido que respondeu.
3. Guarda a escolha por 12 h, além das cotas esgotadas e do nível de raciocínio aceito por cada
   modelo, em `backend\data\gemini_state.json`. Assim não gasta cota testando de novo a cada
   inicialização.
4. Durante o uso, se o modelo falhar (sobrecarga, cota, tempo esgotado), o pedido segue no
   próximo modelo da lista, que passa a ser o principal.

Em Configurações → IA dá para fixar um modelo entre os que a conta lista; o mesmo vale para o
modelo de voz.

## 5. Variáveis (`backend\.env`)

| Variável | Padrão | Efeito |
|---|---|---|
| `GEMINI_API_KEY` | vazio | Sem chave, o sistema roda em modo local (sem IA). |
| `GEMINI_MODEL` | `auto` | Ou o nome exato de um modelo da conta. |
| `GEMINI_TTS_MODEL` / `GEMINI_STT_MODEL` | `auto` / vazio | Modelos de voz e de transcrição. |
| `GEMINI_FALLBACK_MODEL` | vazio | Reserva fixo, além dos reservas automáticos. |
| `GEMINI_AUTO_MODEL` | `true` | `false` usa os nomes exatamente como escritos. |
| `GEMINI_API_VERSION` | `v1beta` | A `v1` recusa instrução de sistema e não lista modelos de voz. |
| `GEMINI_PROBE_MODELS` | `true` | Teste de resposta na inicialização. |
| `GEMINI_MAX_FIRST_TOKEN_S` | `1.5` | Tempo-alvo do teste. |
| `GEMINI_LOW_LATENCY` | `true` | Pede o menor nível de raciocínio que cada modelo aceitar. |
| `GEMINI_TIMEOUT_S` | `30` | Limite por chamada. Até o 1º trecho o limite é 12 s. |
| `GEMINI_THINKING_BUDGET` | vazio | Orçamento fixo de raciocínio (desliga o ajuste automático). |

## 6. Cotas do nível gratuito (medidas na sua conta)

| Limite | Valor |
|---|---|
| Pedidos por minuto, por modelo | 5 |
| Pedidos por dia, por modelo | 20 |

Uma resposta falada usa de 1 a 3 pedidos de conversa e até 2 de voz (modo econômico). O núcleo
troca de modelo quando um se esgota, então o total diário rende algumas dezenas de respostas
faladas. As cotas esgotadas aparecem em Configurações → IA e renovam no dia seguinte.

Para uso contínuo é preciso habilitar faturamento na conta Google. É uma decisão sua; o projeto
não faz isso.

## 7. O que é enviado ao Google

| Quando | O que sai do computador |
|---|---|
| Conversa | Sua fala em texto, o histórico recente, a instrução de sistema (cidade, data, hora) e os resultados das ferramentas. |
| Voz Gemini | O texto de cada resposta e a direção de interpretação. |
| Transcrição Gemini | O áudio gravado — só depois de você autorizar. Na escuta contínua, toda fala detectada. |
| Lembranças | Se a memória estiver ligada, os fatos guardados entram na instrução de sistema. |

## 8. Falhas e o que o usuário vê

| Código | Causa | Comportamento |
|---|---|---|
| `offline` | Sem internet. | Tenta outro modelo; depois modo local. |
| `timeout` | Sem resposta a tempo. | Tenta outro modelo; depois modo local. |
| `unavailable` | Sobrecarga (503/504). | Tenta outro modelo. |
| `rate_limit` | Cota (429). | Diz se é por minuto ("aguarde N s") ou diária ("volta em ~N h"); não repete no mesmo modelo; tenta outro. |
| `auth` | Chave inválida. | Aviso apontando para `backend\.env`. |
| `model_not_found` | Modelo inexistente. | Tenta outro modelo da conta. |
| `bad_request` | Parâmetro recusado. | Se for o nível de raciocínio, repete sem ele. |
| `blocked`, `empty` | Filtro de segurança ou resposta vazia. | Aviso; não cai para o modo local. |

Depois que a resposta começou a ser dita, não há nova tentativa: o que saiu fica registrado e o
erro aparece no HUD.
