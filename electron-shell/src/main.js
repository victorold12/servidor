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
let splash = null;
let wsConnection = null;
let quitting = false;

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
  mainWindow.loadFile(webappPath("index.html"));
  mainWindow.once("ready-to-show", () => {
    closeSplash();
    mainWindow.show();
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
    { label: "Mostrar JARVIS", click: () => mainWindow?.show() },
    { type: "separator" },
    { label: "Sair", click: () => { quitting = true; app.quit(); } },
  ]);
  tray_.setContextMenu(menu);
  tray_.on("click", () => {
    if (!mainWindow) return;
    mainWindow.isVisible() ? mainWindow.hide() : mainWindow.show();
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
    win.setMenuBarVisibility(false);
    win.loadFile(path.join(__dirname, "pairing.html"));

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
