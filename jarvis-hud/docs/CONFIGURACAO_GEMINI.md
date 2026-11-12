# Configuração do Gemini

> **Estado da validação:** esta integração foi escrita contra o SDK oficial `google-genai`
> 3.2.0 e testada com um cliente falso que usa os tipos do próprio SDK. **Ela não foi
> executada contra a API real**, porque não havia uma chave disponível durante o
> desenvolvimento. Rode o passo 3 abaixo antes de confiar nela.

## 1. Criar a chave

1. Acesse <https://aistudio.google.com/apikey> com a sua conta Google e crie uma chave.
2. Não é preciso habilitar faturamento para começar. Os limites gratuitos e os preços mudam;
   confira em <https://ai.google.dev/gemini-api/docs/rate-limits> e
   <https://ai.google.dev/gemini-api/docs/pricing>. Este projeto nunca habilita cobrança.

## 2. Guardar a chave no backend

Copie `backend/.env.example` para `backend/.env` (o `INICIAR.bat` faz isso) e preencha:

```
GEMINI_API_KEY=sua-chave-aqui
```

`backend/.env` está no `.gitignore`. A chave é lida só pelo processo Python; o código React
nunca a recebe (há um teste que falha se `GEMINI_API_KEY` aparecer em `src/`). Reinicie o
backend depois de editar.

## 3. Verificar

```powershell
cd jarvis-hud\backend
.venv\Scripts\python scripts\check_gemini.py
```

O script lista os modelos da conta, faz uma conversa com resposta incremental, um pedido com
ferramentas (hora e estado do computador), gera amostras de voz e transcreve uma delas.
Cada etapa imprime o resultado ou o erro traduzido.

## Variáveis

| Variável | Padrão | Efeito |
|---|---|---|
| `GEMINI_MODEL` | `gemini-2.5-flash` | Modelo de conversa. |
| `GEMINI_FALLBACK_MODEL` | vazio | Segundo modelo, usado se o principal falhar ou não existir. |
| `GEMINI_TTS_MODEL` | `gemini-2.5-flash-preview-tts` | Modelo de voz. |
| `GEMINI_STT_MODEL` | igual ao de conversa | Modelo usado para transcrever áudio. |
| `GEMINI_AUTO_MODEL` | `true` | Ajusta os nomes ao que a conta oferece. |
| `GEMINI_TIMEOUT_S` | `30` | Limite por chamada e entre pedaços da resposta. |
| `GEMINI_THINKING_BUDGET` | vazio | Orçamento de raciocínio; `0` reduz a latência em modelos 2.5. |
| `JARVIS_HISTORY_TURNS` | `16` | Quantas trocas recentes vão como contexto. |

**Sobre os nomes de modelo:** os padrões acima vêm do que eu conhecia ao escrever; não pude
consultar a documentação atual. Por isso, ao iniciar, o backend lista os modelos da sua conta:
se o configurado não existir, ele escolhe o Flash estável mais recente (ignorando variantes
`lite`, `image`, `tts`, `live`) e avisa em Configurações → IA. Com `GEMINI_AUTO_MODEL=false`
os nomes são usados exatamente como escritos.

## O que é enviado ao Google

| Quando | O que sai do computador |
|---|---|
| Conversa | Sua fala em texto, o histórico recente, a instrução de sistema (com cidade, data e hora) e os resultados das ferramentas. |
| Voz Gemini TTS | O texto de cada frase da resposta. |
| Transcrição Gemini | O áudio gravado — só depois de você autorizar em Configurações → Privacidade. |
| Lembranças | Se a memória estiver ligada, os fatos guardados entram na instrução de sistema. |

Sem chave, nada disso acontece: o sistema opera em modo local.

## Function calling

A IA recebe a descrição das ferramentas autorizadas e pode pedi-las; a execução automática do
SDK está **desligada**. O backend valida e executa, devolve `executed`/`simulated`, e a IA
escreve a resposta. A instrução de sistema proíbe afirmar sucesso sem `executed: true`. Há um
limite de 6 rodadas de ferramentas por pedido.

## Falhas e o que o usuário vê

| Código | Causa | Comportamento |
|---|---|---|
| `offline` | Sem internet. | 1 nova tentativa; depois modo local. |
| `timeout` | Resposta lenta ou travada. | 1 nova tentativa; depois modo local. |
| `unavailable` | Erro 5xx / sobrecarga. | 1 nova tentativa, modelo reserva; depois modo local. |
| `rate_limit` | Cota (HTTP 429). | Aviso; modo local neste pedido. |
| `auth` | Chave inválida ou sem permissão. | Aviso apontando para `backend/.env`. |
| `model_not_found` | Modelo inexistente na conta. | Modelo reserva, se houver. |
| `blocked`, `empty` | Filtro de segurança ou resposta vazia. | Aviso; não cai para o modo local. |
| `tool_loop` | Mais de 6 rodadas de ferramentas. | Interrompe por segurança. |

Depois que a resposta começou a ser dita, não há nova tentativa: o que saiu fica registrado e
o erro aparece no HUD.
