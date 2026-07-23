/**
 * Processo principal do Electron. Fino de propósito: TODA a lógica de
 * segurança/pareamento/execução já existe e está testada em ../agente-local —
 * este arquivo só cria janelas e importa aqueles módulos, sem reimplementar
 * nada. Ver ../agente-local/README.md pra saber o que cada peça faz.
 */
import { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, dialog } from "electron";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

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
function createMainWindow() {
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
    },
  });

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

function createTray() {
  const tray_ = new Tray(nativeImage.createFromPath(TRAY_PNG));
  tray_.setToolTip("JARVIS — iniciando…");
  const menu = Menu.buildFromTemplate([
    { label: "Mostrar JARVIS", click: () => focusAnyWindow() },
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
    try {
      let cfg = null;
      try {
        cfg = await runPairingFlow();
      } catch (err) {
        dialog.showErrorBox("Pareamento não concluído", `${err.message}\n\nO painel abre mesmo assim, mas ações no PC ficam indisponíveis até parear.`);
      }
      if (cfg) {
        await connectAgent(cfg).catch((err) => dialog.showErrorBox("Falha ao conectar o Agente Local", err.message));
      }
    } finally {
      createMainWindow();
    }
  });

  app.on("before-quit", () => {
    quitting = true;
    wsConnection?.close();
  });

  // Sem "quit ao fechar a última janela" — o app fica vivo na bandeja
  // (é o ponto de ter Agente Local rodando mesmo com a janela fechada).
  app.on("window-all-closed", () => {});
}
