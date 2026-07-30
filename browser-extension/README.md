# JARVIS Assistant — extensão de navegador

Extensão Manifest V3 (Seção 6 do esquema de arquitetura). Fala **direto com o
backend** do JARVIS — não com o Electron/app, não com o site — usando a mesma
URL + token de acesso configurados em Config > Backend VTz OS no site.

## Instalar (modo desenvolvedor)

1. Abra `chrome://extensions` (ou `edge://extensions`)
2. Ative "Modo do desenvolvedor"
3. "Carregar sem compactação" → aponte pra esta pasta (`browser-extension/`)
4. Clique no ícone da extensão, cole a mesma URL/token do backend que você usa
   no site, e clique "Salvar backend"

Atalho: `Ctrl+Shift+J` abre o popup (configurável em `chrome://extensions/shortcuts`).

## O que funciona hoje

- **Extrair página**: título, URL e texto legível da aba ativa
- **Pegar seleção**: texto selecionado na página
- **Pesquisar**: chama `/api/search` do backend (mesma busca que o site usa) e
  lista resultados com link
- **Preencher formulário**: heurística por nome/id/autocomplete de campo
  (nome, email, telefone) — perfil salvo localmente na extensão

## O que NÃO está feito ainda (escopo honesto)

O plano original (Seção 6) descreve a extensão sendo **acionada pelo chat** —
"pesquisa X e resume os 3 primeiros resultados" digitado na conversa, que o
backend repassa pra extensão executar e devolve o resultado pro chat. Isso
exige um hub bidirecional backend↔extensão (pareamento + WebSocket +
correlação de comando/resultado) equivalente ao que existe para o Agente
Local (`app/routers/agents_hub.py`) — só que pra abas de navegador em vez de
PC. Essa peça ainda não existe; é trabalho separado, maior, e mais sensível
(decidir automaticamente qual aba usar, quando permitir preenchimento
automático de formulário sem o usuário estar olhando, etc.).

Por ora a extensão é uma ferramenta manual: você clica, ela age na aba atual.
Não há execução remota disparada pelo chat ainda.
