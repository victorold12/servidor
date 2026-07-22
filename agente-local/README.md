# JARVIS — Agente Local

Cliente que roda no PC e executa ações (arquivo, comando) pedidas pelo JARVIS,
sob as 4 camadas de risco. Ele **nunca abre porta** — conecta de saída no hub
WebSocket do backend e mantém a conexão. A fonte da verdade das regras é
[`../docs/SEGURANCA-AGENTE-LOCAL.md`](../docs/SEGURANCA-AGENTE-LOCAL.md).

## Uso

```bash
npm install      # keytar é optionalDependency — se o build nativo falhar
                  # (falta libsecret no Linux, por ex.), o resto instala normal
npm run pair      # fluxo de pareamento no terminal (mostra o user_code)
npm start         # conecta no hub e fica rodando
npm test          # 71 testes (node --test, sem framework externo)
```

## Estado atual — tudo implementado e testado

| Arquivo | Papel | Como é testado |
|---|---|---|
| `src/tier-validator.js` | **Núcleo de segurança.** Classifica caminho (sandbox + canonicaliza `..`/symlink + denylist de segredo) e comando (allowlist Tier 1 / blocklist Tier 3 / shell → Tier 2). Parse sem shell. | Puro — traversal, symlink escape, injeção `&&`/pipe/backtick/`$()`, `curl\|bash`, fork bomb. |
| `src/safe-exec.js` | Gate das 4 camadas + execução real com `execFile` (shell:false). | Puro — Tier 3 nunca executa nem pergunta; Tier 2 sem `confirmFn` nega (fail-safe). |
| `src/token-vault.js` | Token do agente no cofre do SO (`keytar`) — Windows Credential Manager / macOS Keychain / libsecret. **Nunca** cai pra arquivo texto se o cofre faltar: rejeita alto e claro. | A propriedade "nunca grava plaintext" é testável até aqui, sem keytar de verdade. |
| `src/pairing.js` | Cliente RFC 8628: `start` → poll → trata `pending`/`approved`/`denied`/`expired`/HTTP 429. | **Integração real** — sobe o backend Python de verdade num banco temporário. |
| `src/ws-client.js` | Conecta `/ws/agent` (token por query, não header — limitação do WebSocket padrão), reconecta com backoff+jitter, para em `code=4401` (não autorizado), heartbeat, despacha `command`→`result`. | Unit puro (WebSocket falso + timers mockados) **e** integração real (comando ida-e-volta pelo hub de verdade). |
| `src/confirm.js` | Janela nativa de confirmação (Seção 7) — macOS via `osascript`, Windows via PowerShell/WinForms, Linux via `zenity`. Fail-safe: qualquer erro/cancelamento/ferramenta ausente = `"deny"`. | Mensagem e parsing são puros e testados. **A chamada real ao SO não roda neste ambiente** (sem display, sem os três binários) — precisa de smoke test manual em cada plataforma alvo antes de produção. |
| `src/audit.js` | Escrita dupla (Seção 10): local (JSONL) sempre, hub quando dá. | Puro — inclusive o caso "hub fora do ar não perde o registro local". |
| `src/command-dispatcher.js` | Traduz `{type:"command"}` do hub numa chamada ao `safe-exec` + audita. Só a ação `"run"` está ligada por ora (cobre leitura/escrita/organização via allowlist de comando). | Puro, com fakes de `confirmFn`/`sendAudit`. |
| `src/pair-cli.js` / `src/index.js` | Fiação final: `npm run pair` e `npm start`. | **Integração real** — roda o CLI como processo filho contra o backend real; confirma que o fluxo chega até `saveToken()` e falha exatamente ali (não antes, não com crash) neste ambiente sem cofre de SO. |

## O que falta (fora do escopo aqui)

- **Ações de arquivo estruturadas** (`fs_read`/`fs_write`/`fs_list` via `classifyPath`
  direto, sem passar por shell) — hoje cobertas indiretamente pela ação `"run"`
  com comandos da allowlist (`ls`/`cat`/`mkdir`/`copy`/`move`). `classifyPath` já
  existe e é testado; falta só o segundo verbo de ação no dispatcher.
- **UI de configuração** pra liberar itens de Tier 3 (`isUnlocked`) e editar
  `allowed_roots` fora do que o `policy_update` do hub manda.
- **Frontend** (`VTz-painel`): tela "Parear dispositivo", painel de agentes,
  detecção de capacidade — consome os endpoints já prontos no backend.

## Por que alguns testes sobem um servidor Python de verdade

`pairing.js` e `ws-client.js` falam com o backend `servidor` (FastAPI) pela
rede — é a fronteira Node↔Python mais arriscada do projeto, porque é onde os
dois lados podem "achar" contratos diferentes sem que nenhum teste unitário
isolado perceba (foi assim que apareceu o bug do `close(code=4401)` antes do
`accept()`: fechava a conexão, mas nenhum cliente WS real via o código — só
apareceu testando o cliente Node de verdade contra o servidor de verdade).
Por isso `test/*.integration.test.js` sobem `uvicorn` num banco SQLite
temporário (nunca o `jarvis.db` real, via `JARVIS_DB_PATH`) e falam HTTP/WS de
verdade. São mais lentos (~4-7s cada) que os testes puros, mas cobrem o que
importa mais.
