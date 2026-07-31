# Passagem de sessão — JARVIS / VTz OS

## 1. O que já vai sozinho (não precisa carregar nada)

Está **commitado nos repositórios** e volta pro contexto do Claude automaticamente:

| onde | o quê |
|---|---|
| `servidor/CLAUDE.md` | memória principal: grafo, orçamento, 4 camadas de segurança, armadilhas já pagas |
| `VTz-painel/CLAUDE.md` | específico do painel: build IIFE, `app.js` gerado, CSP |
| `servidor/.grafo/` | grafo de conhecimento: relatório, `graph.json`, cache semântico |

Só é preciso que os **dois repositórios** estejam anexados na sessão. Se faltar um:

```
add_repo(owner="victorold12", repo="servidor")
add_repo(owner="victorold12", repo="VTz-painel")
```

---

## 2. Cole isto na sessão nova

> Leia primeiro o `CLAUDE.md` do repositório `servidor` e o `.grafo/GRAPH_REPORT.md`.
>
> **Tarefa:** construir o instalador de vozes **dentro do app** (Electron), substituindo
> o download do `.bat`. Ao clicar em "Instalar tudo" na aba Voz, abre um painel no
> próprio JARVIS mostrando cada etapa em tempo real, e no fim os motores sobem
> sozinhos. Sem arquivo em Documentos, sem terminal, sem copiar comando.
>
> O `.bat` continua existindo por baixo — é gerado por
> `VTz-painel/scripts/gera-instalador.mjs` e testado pelo workflow
> `servidor/.github/workflows/testa-instalador.yml` num Windows real. **Teste no CI
> antes de me entregar**; é o único mecanismo que funcionou.
>
> Peças: IPC no `electron-shell/src/main.js`, exposição no `preload.cjs`, e a tela em
> `VTz-painel/src/js/30-voice-config.js`. No navegador (fora do Electron), manter o
> download do `.bat` como está.

---

## 3. Estado em 31/07/2026, ~05h

**No ar (`main` dos dois repositórios):**
- Fórmulas matemáticas renderizadas (KaTeX)
- 402 do OpenRouter corrigido — o app não mandava `max_tokens`, e o OpenRouter
  reservava o máximo do modelo (65536) cobrando adiantado
- Aba Voz procura os motores sozinha a cada 12s + botão "Procurar as vozes agora"
- Instalador em `Documentos\VTz LLM`, com `ligar-vozes.bat` e atalho na Inicialização
- `.msi` **1.0.0** publicado (tag `msi-v1.0.0`)

**AVISO IMPORTANTE — nada abaixo foi verificado ponta a ponta.**

As correções de dependência que estão no gerador foram **deduzidas dos erros**, não
confirmadas com o servidor no ar. O Victor mudou de máquina antes de testar. Em
particular: o nome da chave do watermark no `config.yaml` foi **chutado**
(`enable_watermarking`) — ninguém viu o arquivo.

Isso importa porque a lição desta sessão foi exatamente essa: o CI passou 7/7
testando a *instalação* e nunca ligou os servidores. Validar a etapa errada custou
uma madrugada. **O critério de pronto é o servidor respondendo na porta**, não o
comando terminando com código 0.

Quando o Victor voltar ao PC dele, confirmar antes de confiar:
```
cd /d "%USERPROFILE%\Documents\VTz LLM\vozes\Chatterbox-TTS-Server"
findstr /n "watermark" config.yaml
```

**Chatterbox — onde parou, na máquina do Victor:**

Servidor sobe na 8004, modelo de 3,82 GB baixado. Falta **uma linha**: desligar a
marca-d'água no `config.yaml`. O `resemble-perth` está instalado mas o `__init__`
engole `ImportError` e deixa a classe como `None` → `TypeError: 'NoneType' object is
not callable` na hora de carregar o modelo.

Comando pendente:
```
findstr /n "watermark" config.yaml
```

**Kokoro — não testado ainda.** Ponto de entrada provável:
```
python -m uvicorn api.src.main:app --host 0.0.0.0 --port 8880
```

**Correções de dependência descobertas por execução real** (já embutidas no gerador):
- `requirements.txt` do Chatterbox instala tudo **menos** o motor → `pip install chatterbox-tts`
- `chatterbox-tts` exige `torch==2.6.0`; o `requirements.txt` fixa `2.5.1`. O pip sobe
  o torch e deixa o `torchvision` velho → "ponto de entrada não encontrado".
  Alinhar: `torch==2.6.0 torchvision==0.21.0 torchaudio==2.6.0`
- **O limite de Python 3.12 estava errado.** Vinha do `torch==2.5.1` do
  `requirements.txt`, não do motor. O `chatterbox-tts` quer 2.6.0, que suporta 3.13.

---

## 4. Pendências do Victor (não são código)

- **Trocar o `BACKEND_TOKEN`** no Render — foi enviado em texto puro no chat há semanas
- Comprar ~R$ 28 de crédito de embeddings (`EMBEDDINGS_BASE/MODEL/KEY`) — sem isso a
  busca nos documentos cai pra palavra-chave em vez de significado
- Disco pago no Render (US$ 1–7/mês) — sem ele o banco é apagado a cada deploy **e a
  cada hibernação**

---

## 5. Duas coisas que valem mais que o resto

**O ambiente sofreu 4 rollbacks nesta sessão** — o diretório local voltou sozinho a
commits antigos, nos dois repositórios, levando arquivos junto. O GitHub nunca foi
afetado. **Confira `git log --oneline -1` contra o `origin/main` antes de trabalhar**,
e commite cedo.

**Sucesso do `pip` não é prova de que dá pra usar.** O CI passou 7/7 testando a
instalação e nunca chegou a ligar os servidores — validou a etapa errada. Foi o que
custou a noite. Ao construir o instalador embutido, o critério de pronto é o servidor
**respondendo na porta**, não o comando terminando com código 0.
