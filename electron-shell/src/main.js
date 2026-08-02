/**
 * Processo principal do Electron. Fino de propósito: TODA a lógica de
 * segurança/pareamento/execução já existe e está testada em ../agente-local —
 * este arquivo só cria janelas e importa aqueles módulos, sem reimplementar
 * nada. Ver ../agente-local/README.md pra saber o que cada peça faz.
 */
import { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, dialog, Notification, shell } from "electron";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import {
  MODELOS_WHISPER,
  caminhoDoInstalador,
  ligaMotores,
  motoresEmDisco,
  paraMotores,
  raizDasVozes,
  rodaInstalador,
} from "./instalador-vozes.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SHELL_ROOT = path.resolve(__dirname, "..");
const ICON_PNG = path.join(SHELL_ROOT, "build", "icon.png");
const TRAY_PNG = path.join(SHELL_ROOT, "build", "tray.png");

/** Raiz do agente-local — resolvida diferente em dev (repo irmão) vs empacotado
 * (extraResources, ver electron-builder.config.js). */
function agenteLocalRoot() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "agente-local")
    : path.resolve(SHELL_ROOT, "..", "agente-local");
}

/** file:// URL de um módulo do agente-local, pronta pra `import()` dinâmico —
 * pathToFileURL evita quebrar no Windows (backslash, letra de unidade). */
function agenteLocalModule(...segments) {
  return pathToFileURL(path.join(agenteLocalRoot(), "src", ...segments)).href;
}

function webappPath(...segments) {
  const base = app.isPackaged ? path.join(process.resourcesPath, "webapp") : path.join(SHELL_ROOT, "webapp");
  return path.join(base, ...segments);
}

let tray = null;
let mainWindow = null;
let pairingWindow = null;
let splash = null;
let wsConnection = null;
let quitting = false;
/** Instalação de vozes em andamento (só uma por vez) e servidores que subiram. */
let instalacaoVozes = null;
let motoresVivos = [];

/** Traz de volta QUALQUER janela ativa no momento (principal ou de pareamento).
 * Sem isto, clicar na bandeja durante o pareamento não fazia nada — se essa
 * janela ficasse atrás de outra coisa (outro monitor, minimizada), o usuário
 * via só o ícone na bandeja e achava que o app tinha travado (bug real, achado
 * em teste no Windows: "fica só na bandeja, clico e não abre nada"). */
function focusAnyWindow() {
  const win = mainWindow && !mainWindow.isDestroyed() ? mainWindow
    : pairingWindow && !pairingWindow.isDestroyed() ? pairingWindow
    : null;
  if (!win) return false;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
  return true;
}

function createSplash() {
  splash = new BrowserWindow({
    width: 380,
    height: 240,
    frame: false,
    resizable: false,
    movable: false,
    alwaysOnTop: true,
    backgroundColor: "#111114",
    icon: ICON_PNG,
    webPreferences: { contextIsolation: true },
  });
  splash.loadFile(path.join(__dirname, "splash.html"));
}

function closeSplash() {
  if (splash && !splash.isDestroyed()) splash.close();
  splash = null;
}

/**
 * Tela preta e silenciosa é o pior resultado possível: usuário sem pista
 * nenhuma do que aconteceu. index.html carrega bibliotecas de CDN externas
 * (marked, DOMPurify, Firebase etc.) antes do app.js — se a rede do Windows
 * bloquear/travar alguma delas (firewall, antivírus, proxy corporativo), a
 * página pode nunca terminar de carregar. `loadFile` sozinho não avisa disso.
 * Por isso: (1) trata falha de load de verdade, (2) força a janela aparecer
 * mesmo se o carregamento nunca terminar, com uma mensagem clara em vez de
 * ficar preso atrás do splash pra sempre, (3) log de console do renderer vai
 * pro terminal (útil rodando via `npm start`; no .msi some, mas não piora nada).
 */
function createMainWindow(pairedBackendUrl) {
  // Passa a URL do backend pareado pro painel web via argumento do preload —
  // é o que faz a aba "Agente Local" enxergar o agente que acabou de parear.
  const extraArgs = pairedBackendUrl ? [`--jarvis-backend-url=${pairedBackendUrl}`] : [];
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 860,
    minHeight: 560,
    icon: ICON_PNG,
    backgroundColor: "#111114",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: extraArgs,
    },
  });

  /* Permissões do renderer: liberar SÓ o microfone, que é o que a cena JARVIS
   * e o ditado precisam (Seção 14). Sem handler explícito o padrão do Electron
   * é aprovar tudo — inclusive geolocalização, notificação e captura de tela,
   * que este app não usa. Lista fechada: o que não está aqui é negado. */
  const PERMITIDAS = new Set(["media", "audioCapture", "clipboard-sanitized-write"]);
  mainWindow.webContents.session.setPermissionRequestHandler((_wc, permissao, aceitar, detalhes) => {
    // "media" cobre mic e câmera — só passa quando o pedido é de áudio.
    if (permissao === "media" && detalhes?.mediaTypes?.includes("video")) return aceitar(false);
    aceitar(PERMITIDAS.has(permissao));
  });

  trancaNavegacao(mainWindow);

  let shown = false;
  const showOnce = () => {
    if (shown) return;
    shown = true;
    closeSplash();
    if (!mainWindow.isDestroyed()) mainWindow.show();
  };

  mainWindow.loadFile(webappPath("index.html")).catch((err) => {
    dialog.showErrorBox(
      "Falha ao abrir o painel",
      `Não consegui carregar a interface do JARVIS.\n\n${err.message}\n\n` +
        "Verifique sua conexão com a internet (o painel carrega bibliotecas externas) e tente reabrir o app."
    );
    showOnce(); // mostra mesmo assim — melhor uma janela com erro visível que nada
  });

  mainWindow.webContents.on("did-fail-load", (_evt, errorCode, errorDescription, validatedUrl) => {
    if (errorCode === -3) return; // ERR_ABORTED: navegação cancelada por redirecionamento normal, não é falha real
    dialog.showErrorBox(
      "Falha ao carregar o painel",
      `${errorDescription} (código ${errorCode})\nURL: ${validatedUrl}\n\n` +
        "Verifique sua conexão com a internet e tente reabrir o app."
    );
    showOnce();
  });

  // Rede de segurança: se a página não terminar de carregar em 15s (CDN travada,
  // sem internet), mostra a janela mesmo assim em vez de ficar preso atrás do
  // splash pra sempre — o usuário pelo menos VÊ que algo está errado.
  const stuckTimer = setTimeout(() => {
    if (!shown) {
      dialog.showErrorBox(
        "O painel está demorando demais pra carregar",
        "Isso costuma ser falta de internet ou alguma biblioteca externa bloqueada " +
          "(firewall/antivírus). O app vai abrir mesmo assim, mas pode aparecer incompleto."
      );
      showOnce();
    }
  }, 15_000);

  mainWindow.webContents.once("did-finish-load", () => clearTimeout(stuckTimer));
  mainWindow.once("ready-to-show", () => {
    clearTimeout(stuckTimer);
    showOnce();
  });

  mainWindow.webContents.on("render-process-gone", (_evt, details) => {
    dialog.showErrorBox("O painel travou", `Motivo: ${details.reason}. Tente reabrir o app.`);
  });

  // Fechar a janela minimiza pra bandeja — não derruba o agente. Só "Sair" no
  // menu da bandeja (ou Cmd+Q) encerra de verdade.
  mainWindow.on("close", (e) => {
    if (!quitting) {
      e.preventDefault();
      mainWindow.hide();
    }
  });
}

/* Notificação nativa pedida pelo painel (preload → jarvisDesktop.notify).
 * Só notifica quando a janela NÃO está em foco: avisar de algo que a pessoa
 * está olhando é ruído. Clicar traz o JARVIS pra frente. */
function setupNotificacoes() {
  ipcMain.on("jarvis:notify", (_evt, { titulo, corpo } = {}) => {
    if (!Notification.isSupported()) return;
    const focada = mainWindow && !mainWindow.isDestroyed() && mainWindow.isFocused();
    if (focada) return;
    const n = new Notification({
      title: String(titulo || "JARVIS").slice(0, 120),
      body: String(corpo || "").slice(0, 400),
      icon: ICON_PNG,
      silent: false,
    });
    n.on("click", () => focusAnyWindow());
    n.show();
  });
}

/* ==========================================================================
 * INSTALAR AS VOZES SEM SAIR DO APP
 *
 * Antes: o botão "Instalar tudo" baixava um .bat, e a pessoa tinha que achar o
 * arquivo, abrir, ler, rodar, e acompanhar numa janela preta que fechava
 * sozinha quando dava errado. Cada um desses passos era um lugar pra desistir,
 * e o resultado prático é que a voz local nunca saía do papel.
 *
 * Agora o app roda o mesmo .bat e mostra a saída aqui dentro. O que NÃO muda: a
 * pessoa confirma antes, num diálogo nativo que diz o que vai acontecer e onde.
 * Instalar programa continua sendo a coisa mais invasiva que este app faz, e a
 * decisão continua sendo tomada NO PC — só deixou de exigir terminal. É a
 * mesma forma dos Tier 2 do gate (docs/SEGURANCA-AGENTE-LOCAL.md): a ação é
 * possível, mas nunca acontece sem um humano dizer sim na própria máquina.
 * ========================================================================== */

/** Manda uma linha de progresso pro painel que pediu a instalação. */
function avisaVozes(wc, evento) {
  if (wc && !wc.isDestroyed()) wc.send("jarvis:vozes-progresso", evento);
}

function estadoDasVozes() {
  return {
    // O instalador é um .bat: só existe caminho pra Windows. Em macOS/Linux o
    // painel volta sozinho pro download, em vez de oferecer um botão morto.
    suportado: process.platform === "win32",
    rodando: !!instalacaoVozes,
    raiz: raizDasVozes(app.getPath("documents")),
    motores: motoresEmDisco(app.getPath("documents")).map(({ id, nome, porta, instalado, motivo, via }) => ({
      id,
      nome,
      porta,
      instalado,
      motivo,
      via,
      ligado: motoresVivos.some((v) => v.id === id && v.filho.exitCode === null),
    })),
  };
}

function setupInstaladorVozes() {
  ipcMain.handle("jarvis:vozes-estado", () => estadoDasVozes());

  ipcMain.handle("jarvis:vozes-instalar", async (evt, modelo) => {
    if (process.platform !== "win32") {
      return { ok: false, erro: "O instalador embutido só existe no Windows." };
    }
    // Conferido aqui e não só no painel: o renderer é a parte não confiável.
    if (!MODELOS_WHISPER.includes(modelo)) {
      return { ok: false, erro: "Modelo de whisper desconhecido." };
    }
    if (instalacaoVozes) return { ok: false, erro: "Já existe uma instalação em andamento." };

    let bat;
    try {
      bat = caminhoDoInstalador(webappPath(), modelo);
    } catch (err) {
      return { ok: false, erro: err.message };
    }

    const raiz = raizDasVozes(app.getPath("documents"));
    const janela = BrowserWindow.fromWebContents(evt.sender) || mainWindow;
    /* Com janela pai o diálogo é modal e não some atrás do app; sem ela,
       `showMessageBox(null, ...)` não é a mesma chamada — a sobrecarga sem
       janela existe justamente pra isso. Passar null onde se espera uma
       BrowserWindow é o tipo de coisa que só falha na máquina do usuário. */
    const opcoes = {
      type: "warning",
      buttons: ["Instalar agora", "Cancelar"],
      defaultId: 1,
      cancelId: 1,
      title: "Instalar as vozes neste PC",
      message: "Instalar Chatterbox, Kokoro e o whisper neste computador?",
      detail:
        `Vai baixar vários GB e instalar em:\n${raiz}\n\n` +
        "Também instala Git, Python 3.12 e ffmpeg pelo winget, se faltarem.\n" +
        "Desinstalar depois é apagar essa pasta.\n\n" +
        "Você acompanha cada passo dentro do JARVIS e pode cancelar no meio.",
    };
    const { response } = janela
      ? await dialog.showMessageBox(janela, opcoes)
      : await dialog.showMessageBox(opcoes);
    if (response !== 0) return { ok: false, cancelado: true, erro: "Instalação cancelada." };

    const wc = evt.sender;
    const aoLinha = (linha) => avisaVozes(wc, { tipo: "linha", texto: linha });

    avisaVozes(wc, { tipo: "fase", fase: "instalando", texto: `Rodando o instalador (modelo ${modelo})…` });
    instalacaoVozes = rodaInstalador({ bat, pastaTemp: app.getPath("temp"), aoLinha });

    const r = await instalacaoVozes.terminou;
    instalacaoVozes = null;

    if (!r.ok) {
      avisaVozes(wc, { tipo: "fim", ok: false, texto: r.erro || `O instalador terminou com código ${r.codigo}.` });
      return { ok: false, erro: r.erro || `O instalador terminou com código ${r.codigo}.` };
    }

    /* "No fim os motores sobem sozinhos" — a parte do pedido que faltava. Sem
       isto a instalação terminava e a aba Voz continuava dizendo "não está
       rodando", que é indistinguível de ter falhado. */
    avisaVozes(wc, { tipo: "fase", fase: "ligando", texto: "Instalado. Subindo os motores…" });
    paraMotores(motoresVivos);
    motoresVivos = await ligaMotores({ documentos: app.getPath("documents"), aoLinha });

    const estado = estadoDasVozes();
    avisaVozes(wc, {
      tipo: "fim",
      ok: true,
      texto: motoresVivos.length
        ? "Pronto. Na primeira vez o Chatterbox ainda baixa ~2 GB de modelo antes de responder."
        : "Instalado, mas nenhum motor subiu — veja o log acima.",
      estado,
    });
    return { ok: true, estado };
  });

  /* Ligar sem reinstalar: quem já instalou e só reabriu o app. */
  ipcMain.handle("jarvis:vozes-ligar", async (evt) => {
    if (process.platform !== "win32") return { ok: false, erro: "Só no Windows." };
    const aoLinha = (linha) => avisaVozes(evt.sender, { tipo: "linha", texto: linha });
    paraMotores(motoresVivos);
    motoresVivos = await ligaMotores({ documentos: app.getPath("documents"), aoLinha });
    return { ok: motoresVivos.length > 0, estado: estadoDasVozes() };
  });

  ipcMain.handle("jarvis:vozes-cancelar", () => {
    if (!instalacaoVozes) return { ok: false, erro: "Nada rodando." };
    instalacaoVozes.cancela();
    return { ok: true };
  });

  registraModeloLocal();
}

/* ===========================================================================
 * MODELO LOCAL — por que a chamada passa por aqui, e não pelo painel
 *
 * O painel fala com o OpenRouter direto do navegador, então o caminho óbvio pro
 * Ollama seria o mesmo: `fetch` pra 127.0.0.1:11434. Não funciona. O Ollama tem
 * lista de origens própria e recusa com 403 quem não está nela — medido nesta
 * máquina: `https://…pages.dev` e `Origin: null` levam 403.
 *
 * Daria pra pedir ao Victor que abrisse o `OLLAMA_ORIGINS`, mas isso é afrouxar
 * a trava de um serviço local pra resolver problema nosso, e deixaria qualquer
 * site aberto no navegador usando a GPU dele. O processo principal do Electron é
 * Node: não tem origem, não tem CORS, e já é por onde passam as vozes.
 *
 * O QUE ESTA PONTE NÃO FAZ
 *
 * Ela devolve TEXTO. Não executa nada, não toca em arquivo, não chama
 * ferramenta. Se um dia a resposta do modelo local virar ação, essa ação passa
 * pelo gate de 4 camadas como qualquer outra (docs/SEGURANCA-AGENTE-LOCAL.md) —
 * a ponte não é atalho pra isso.
 *
 * O renderer NUNCA escolhe pra onde a chamada vai: a base vem do módulo, e o
 * nome do modelo é conferido contra o que está instalado. Mesma regra do
 * instalador de vozes, pelo mesmo motivo — o renderer é a janela que transforma
 * resposta de modelo em HTML.
 * =========================================================================== */
function registraModeloLocal() {
  const carrega = () => import(agenteLocalModule("ollama.js"));

  ipcMain.handle("jarvis:local-estado", async () => {
    try {
      const mod = await carrega();
      const est = await mod.disponivel();
      if (!est.ok) return { ok: false, motivo: est.motivo };
      const escolhido = await mod.escolhe({ precisaFerramentas: true });
      return {
        ok: !!escolhido,
        modelo: escolhido?.nome || null,
        cabeNaGpu: escolhido?.cabeNaGpu ?? null,
        motivo: escolhido?.motivo || "nenhum modelo local aceita ferramentas",
      };
    } catch (e) {
      return { ok: false, motivo: String(e.message).slice(0, 120) };
    }
  });

  ipcMain.handle("jarvis:local-chat", async (_evt, pedido) => {
    try {
      const mod = await carrega();
      const est = await mod.disponivel();
      if (!est.ok) return { ok: false, erro: est.motivo };

      /* Lista fechada montada na hora: o renderer só consegue nomear um modelo
         que JÁ está no disco desta máquina. Nome desconhecido não vira erro —
         cai no que o gerente de residência escolheria, que é o comportamento
         útil. */
      const instalados = new Set((await mod.modelos()).map((m) => m.nome));
      const pedido_ = String(pedido?.model || "");
      const modelo = instalados.has(pedido_)
        ? pedido_
        : (await mod.escolhe({ precisaFerramentas: true }))?.nome;
      if (!modelo) return { ok: false, erro: "nenhum modelo local disponível" };

      const mensagens = Array.isArray(pedido?.messages) ? pedido.messages : [];
      if (!mensagens.length) return { ok: false, erro: "sem mensagens" };

      const teto = Number(pedido?.max_tokens);
      const r = await fetch(`${mod.base()}/v1/chat/completions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: modelo,
          messages: mensagens,
          max_tokens: Number.isFinite(teto) && teto > 0 ? Math.min(teto, 8192) : 2048,
        }),
        /* Teto generoso: modelo grande nesta GPU escorre pra RAM e fica lento,
           mas responder devagar ainda é melhor que falhar. */
        signal: AbortSignal.timeout(180000),
      });
      if (!r.ok) return { ok: false, erro: `o modelo local respondeu ${r.status}` };
      const dados = await r.json();
      return { ok: true, modelo, dados };
    } catch (e) {
      return { ok: false, erro: String(e.message).slice(0, 160) };
    }
  });
}

/**
 * Refaz o pareamento do zero. Existe porque a config salva é definitiva demais:
 * runPairingFlow() devolve a config existente sem perguntar nada, então um
 * pareamento feito contra um backend que depois mudou de URL (ou nunca subiu)
 * deixa o app tentando conectar num endereço morto pra sempre — falhando calado,
 * com o único sinal sendo o texto da bandeja. Sem isto, a saída era achar e
 * apagar o arquivo de config na mão.
 */
async function reparear() {
  const escolha = dialog.showMessageBoxSync({
    type: "question",
    buttons: ["Parear de novo", "Cancelar"],
    defaultId: 1,
    cancelId: 1,
    title: "Parear de novo",
    message: "Refazer o pareamento deste PC?",
    detail: "Apaga a ligação atual com o backend e pede a URL de novo. As suas conversas não são tocadas.",
  });
  if (escolha !== 0) return;

  const { clearConfig } = await import(agenteLocalModule("config.js"));
  const { deleteToken } = await import(agenteLocalModule("token-vault.js"));
  wsConnection?.close();
  wsConnection = null;
  clearConfig();
  await deleteToken().catch(() => {});   // sem token salvo já é o estado desejado

  try {
    const cfg = await runPairingFlow();
    if (cfg) {
      await connectAgent(cfg);
      dialog.showMessageBoxSync({ type: "info", title: "Pareado",
        message: "PC pareado de novo.",
        detail: `Backend: ${cfg.backendUrl}\n\nRecarregue o painel se a aba Agente Local ainda mostrar o estado antigo.` });
    }
  } catch (err) {
    dialog.showErrorBox("Pareamento não concluído", err.message);
  }
}

function createTray() {
  const tray_ = new Tray(nativeImage.createFromPath(TRAY_PNG));
  tray_.setToolTip("JARVIS — iniciando…");
  const menu = Menu.buildFromTemplate([
    { label: "Mostrar JARVIS", click: () => focusAnyWindow() },
    { type: "separator" },
    { label: "Parear de novo…", click: () => { reparear(); } },
    { type: "separator" },
    { label: "Sair", click: () => { quitting = true; app.quit(); } },
  ]);
  tray_.setContextMenu(menu);
  tray_.on("click", () => {
    // Durante o pareamento (mainWindow ainda não existe), sempre traz a janela
    // de pareamento pra frente — nunca esconde nada nessa fase. Só alterna
    // mostrar/esconder quando a janela principal já existe.
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.isVisible() && !mainWindow.isMinimized() ? mainWindow.hide() : focusAnyWindow();
    } else {
      focusAnyWindow();
    }
  });
  tray = tray_;
}

/**
 * A casca do app não é um navegador. Uma janela daqui carrega o preload, que
 * expõe `window.jarvisDesktop` — a ponte pro processo principal. Se um clique
 * levar essa janela pra um site qualquer, o site herda a ponte.
 *
 * E o clique não precisa ser distraído: a resposta de um modelo é texto que
 * vira HTML, com links dentro. Basta o modelo escrever um link (ou repetir um
 * que leu numa página) pra existir um caminho de saída.
 *
 * Então: navegação só dentro do próprio app (file://). Qualquer outro destino
 * — clique normal, target="_blank", window.open — vai pro navegador do sistema,
 * que é onde site de fora deve abrir de qualquer forma.
 */
function trancaNavegacao(win) {
  const daCasa = (url) => {
    try {
      const u = new URL(url);
      if (u.protocol !== "file:") return false;
      // file:// de fora da pasta do app também é "rua" (ex.: um .html baixado).
      return path.resolve(fileURLToPath(u)).startsWith(path.resolve(SHELL_ROOT, ".."));
    } catch {
      return false;
    }
  };
  const abreFora = (url) => {
    // Só esquemas de navegação. mailto:/tel: passam; file:// e outros, não —
    // shell.openExternal com file:// abriria arquivo local do PC sem confirmação.
    if (/^(https?|mailto|tel):/i.test(url)) shell.openExternal(url);
  };

  win.webContents.on("will-navigate", (evento, url) => {
    if (daCasa(url)) return;
    evento.preventDefault();
    abreFora(url);
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    abreFora(url);
    return { action: "deny" };   // nunca abre uma segunda janela com o preload
  });
  // Um <webview> aqui seria outro renderer com outras regras; o app não usa.
  win.webContents.on("will-attach-webview", (evento) => evento.preventDefault());
}

/**
 * Se já pareado, devolve a config direto. Senão, abre uma janela pedindo a
 * URL do backend, mostra o código de pareamento (Seção 3) e espera aprovação
 * — reaproveitando pairWithBackend() já testado em pairing.js. A UI aqui é só
 * uma casca HTML fina; a lógica de rede/estado é toda emprestada.
 */
async function runPairingFlow() {
  const { loadConfig, saveConfig } = await import(agenteLocalModule("config.js"));
  const existing = loadConfig();
  if (existing) return existing;

  return new Promise((resolve, reject) => {
    const win = new BrowserWindow({
      width: 480,
      height: 440,
      resizable: false,
      icon: ICON_PNG,
      backgroundColor: "#111114",
      webPreferences: {
        preload: path.join(__dirname, "pairing-preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
      },
    });
    pairingWindow = win;
    trancaNavegacao(win);   // também tem preload: mesma regra da janela principal
    win.setMenuBarVisibility(false);
    win.loadFile(path.join(__dirname, "pairing.html")).catch((err) => {
      dialog.showErrorBox("Falha ao abrir o pareamento", err.message);
    });
    win.webContents.on("did-fail-load", (_evt, errorCode, errorDescription) => {
      if (errorCode === -3) return; // ERR_ABORTED
      dialog.showErrorBox("Falha ao abrir o pareamento", `${errorDescription} (código ${errorCode})`);
    });
    // Assim que a janela pinta o primeiro frame, garante que ela fica na frente
    // — pareamento é sempre a primeira coisa que o usuário precisa ver/fazer.
    win.once("ready-to-show", () => { win.show(); win.focus(); });

    ipcMain.handle("pairing:start", async (_evt, { backendUrl, name, platform }) => {
      try {
        const { pairWithBackend } = await import(agenteLocalModule("pairing.js"));
        const { saveToken } = await import(agenteLocalModule("token-vault.js"));
        const result = await pairWithBackend({
          backendUrl,
          name,
          platform,
          onEvent: (evt) => { if (!win.isDestroyed()) win.webContents.send("pairing:event", evt); },
        });
        await saveToken(result.agentToken);
        const cfg = { agentId: result.agentId, backendUrl, name, platform, allowedRoots: result.allowedRoots || [] };
        saveConfig(cfg);
        resolve(cfg);
        win.close();
        return { ok: true };
      } catch (err) {
        return { ok: false, error: err.message };
      }
    });

    win.on("closed", () => {
      ipcMain.removeHandler("pairing:start");
      if (pairingWindow === win) pairingWindow = null;
      reject(new Error("Pareamento cancelado."));
    });
  });
}

async function connectAgent(cfg) {
  const { getToken } = await import(agenteLocalModule("token-vault.js"));
  const { createAgentConnection } = await import(agenteLocalModule("ws-client.js"));
  const { createNativeConfirm } = await import(agenteLocalModule("confirm.js"));
  const { createCommandHandler } = await import(agenteLocalModule("command-dispatcher.js"));

  const token = await getToken();
  let allowedRoots = cfg.allowedRoots || [];
  const confirmFn = createNativeConfirm(); // usa os.platform() real — osascript/PowerShell/zenity

  wsConnection = createAgentConnection({
    backendUrl: cfg.backendUrl,
    token,
    onEvent: (evt) => {
      if (evt.type === "policy_update") allowedRoots = evt.allowed_roots || [];
      if (!tray) return;
      const label = { open: "conectado", close: "desconectado", connecting: "conectando…", unauthorized: "token inválido" }[evt.type];
      tray.setToolTip(`JARVIS${label ? " — " + label : ""}`);
    },
    onCommand: createCommandHandler({
      getAllowedRoots: () => allowedRoots,
      confirmFn,
      sendAudit: (entry) => wsConnection.sendAudit(entry),
      // Tier 3 sem UI de configuração ainda — nenhum item liberado por padrão.
      isUnlocked: () => false,
    }),
  });
}

// Trava de instância única: abrir o app de novo (ex.: clique duplo acidental no
// atalho) só foca a janela existente em vez de subir um segundo processo com
// seu próprio ícone de bandeja — dois processos concorrendo pela mesma conexão
// WS/config é uma fonte clássica de "sumiu tudo, só ficou um ícone confuso".
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => { focusAnyWindow(); });

  app.whenReady().then(async () => {
    createSplash();
    createTray();
    setupNotificacoes();
    setupInstaladorVozes();

    // Failsafe absoluto: não importa o que trave no fluxo (pareamento, keytar,
    // conexão), a splash NUNCA fica pra sempre. Se em 12s nada abriu o painel e
    // não há janela de pareamento aberta esperando o usuário, abre assim mesmo.
    const splashFailsafe = setTimeout(() => {
      if (!mainWindow && !(pairingWindow && !pairingWindow.isDestroyed())) createMainWindow(null);
    }, 12_000);

    // cfg fica no escopo da função (NÃO dentro do try) — declarar com let dentro
    // do try e usar depois dava ReferenceError e travava a abertura do painel
    // (bug real da splash infinita, achado testando o .msi no Windows).
    let cfg = null;
    try {
      cfg = await runPairingFlow();
    } catch (err) {
      dialog.showErrorBox("Pareamento não concluído", `${err.message}\n\nO painel abre mesmo assim, mas ações no PC ficam indisponíveis até parear.`);
    }

    // Abre o painel JÁ — sem esperar a conexão do agente. Se o backend estiver
    // lento/fora do ar, connectAgent pode demorar, e isso não pode segurar a
    // janela. A conexão roda em segundo plano.
    clearTimeout(splashFailsafe);
    if (!mainWindow) createMainWindow(cfg?.backendUrl || null);
    if (cfg) {
      connectAgent(cfg).catch((err) => dialog.showErrorBox("Falha ao conectar o Agente Local", err.message));
    }
  });

  app.on("before-quit", () => {
    quitting = true;
    wsConnection?.close();
    /* Os servidores de voz são filhos deste processo. Sem derrubar aqui eles
       ficariam ocupando 8004/8880 sem nada que os desligue a não ser o Gerenciador
       de Tarefas — e o JARVIS seguinte não conseguiria subir os seus. Quem quer
       voz sem o app aberto tem o atalho na Inicialização, que é outro caminho. */
    instalacaoVozes?.cancela();
    paraMotores(motoresVivos);
    motoresVivos = [];
  });

  // Sem "quit ao fechar a última janela" — o app fica vivo na bandeja
  // (é o ponto de ter Agente Local rodando mesmo com a janela fechada).
  app.on("window-all-closed", () => {});
}
