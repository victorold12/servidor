# JARVIS — Agente Local

Cliente que roda no PC e executa ações (arquivo, comando) pedidas pelo JARVIS,
sob as 4 camadas de risco. Ele **nunca abre porta** — conecta de saída no hub
WebSocket do backend e mantém a conexão. A fonte da verdade das regras é
[`../docs/SEGURANCA-AGENTE-LOCAL.md`](../docs/SEGURANCA-AGENTE-LOCAL.md).

## Estado atual

### ✅ Núcleo de segurança (pronto e testado — 27 testes)

Este é o coração: decide o que roda sozinho, o que pergunta e o que bloqueia.
É puro (sem rede, sem estado), então é testável isolado e não muda quando o
resto for plugado.

| Arquivo | O que faz |
|---|---|
| `src/tier-validator.js` | Classifica caminho (sandbox + `..`/symlink + denylist de segredo) e comando (allowlist Tier 1 / blocklist Tier 3 / shell → Tier 2). Parse sem shell. |
| `src/safe-exec.js` | Gate das 4 camadas + execução com `execFile` (shell:false). Tier 3 bloqueia; Tier 2 chama a confirmação local injetada; Tier 0/1 roda. |

```bash
npm test        # roda os 27 testes (node --test, sem dependências)
```

Os testes cobrem os vetores de ataque reais: path traversal, escape por
symlink, injeção via `&&`/pipe/backtick/`$()`, `curl | bash`, fork bomb,
leitura de `.ssh`/`.env`.

### ⏳ Plumbing (próximo passo — não é segurança-crítico)

O núcleo acima é agnóstico de como as coisas chegam e saem. Falta ligar:

- **Pareamento**: mostrar o `user_code`, fazer poll em `/api/pair/*`, guardar o
  token no cofre do SO (`keytar`). Backend já pronto.
- **Cliente WSS**: conectar em `/ws/agent` com o token, reconectar, heartbeat,
  receber `command` e responder `result`/`audit`. Backend já pronto.
- **Confirmação nativa** (`confirmFn`): a janela/notificação do SO que o
  `safe-exec` chama no Tier 2. A REGRA de quando aparece já está no núcleo; falta
  só o diálogo nativo.
- **Auditoria dupla**: espelhar cada linha localmente além de mandar pro backend.

> A fronteira é de propósito: o que decide segurança está testado e fechado; o
> que falta é encanamento de I/O, que não muda nenhuma regra de risco.
