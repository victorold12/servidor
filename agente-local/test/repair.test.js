/**
 * "Parear de novo" (bandeja do app) precisa deixar o PC no MESMO estado de quem
 * nunca pareou — senão o botão engana: o usuário clica, acha que refez, e o app
 * segue apontando pro backend velho.
 *
 * O que garante isso é o par clearConfig() + deleteToken(), que é exatamente o
 * que reparear() chama em electron-shell/src/main.js. Este teste trava esse
 * contrato: se alguém trocar clearConfig por um "marcar como inativo", o teste
 * cai antes de virar um botão que não repara nada.
 *
 * HOME é redirecionado pra uma pasta temporária: config.js escreve em
 * ~/.jarvis-agente, e um teste que apagasse a config real do desenvolvedor
 * seria um teste que estraga a máquina de quem roda.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";

const LAR = fs.mkdtempSync(path.join(os.tmpdir(), "jarvis-repair-"));
process.env.HOME = LAR;
process.env.USERPROFILE = LAR;          // o Windows lê daqui

const { loadConfig, saveConfig, clearConfig } = await import("../src/config.js");
const vault = await import("../src/token-vault.js");

const CFG = {
  agentId: "ag-teste",
  backendUrl: "https://backend-velho.onrender.com",
  name: "PC do Victor",
  platform: "win32",
  allowedRoots: ["C:/Users/victor/Documents"],
};

test("config volta igual antes de reparear", () => {
  saveConfig(CFG);
  assert.deepEqual(loadConfig(), CFG);
});

test("clearConfig apaga a ligação com o backend velho", () => {
  saveConfig(CFG);
  clearConfig();
  assert.equal(loadConfig(), null,
    "loadConfig ainda devolve algo — runPairingFlow devolveria a config velha sem perguntar nada");
});

test("clearConfig numa máquina nunca pareada não estoura", () => {
  clearConfig();
  assert.doesNotThrow(() => clearConfig());
  assert.equal(loadConfig(), null);
});

test("o token sai do cofre junto", async () => {
  vault._resetForTest();
  let guardado = null;
  /* Cofre falso: keytar depende do chaveiro do SO, que não existe no CI. O que
     importa aqui é a sequência de chamadas, não a implementação do keytar. */
  vault._setImportForTest(async () => ({
    default: {                       // token-vault lê `.default` do módulo
      setPassword: async (_s, _c, senha) => { guardado = senha; },
      getPassword: async () => guardado,
      deletePassword: async () => { const tinha = guardado !== null; guardado = null; return tinha; },
    },
  }));

  await vault.saveToken("token-do-pareamento-velho");
  assert.equal(await vault.getToken(), "token-do-pareamento-velho");

  await vault.deleteToken();
  assert.equal(await vault.getToken(), null,
    "token velho sobreviveu ao repareamento — o agente reconectaria com a credencial antiga");
});

test("depois de reparear, config e token estão os dois limpos", async () => {
  assert.equal(loadConfig(), null);
  assert.equal(await vault.getToken(), null);
});

process.on("exit", () => fs.rmSync(LAR, { recursive: true, force: true }));
