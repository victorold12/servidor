/**
 * Guarda o token do agente no cofre de credenciais do SO (Windows Credential
 * Manager / macOS Keychain / libsecret no Linux), via `keytar` — Seção 4 do
 * esquema de segurança. NUNCA em arquivo `.env`/`.json` em texto puro.
 *
 * Decisão deliberada: se o keytar não estiver disponível (não instalado, ou a
 * plataforma não tem um backend de cofre), as funções abaixo REJEITAM a
 * promise com um erro claro. Não existe fallback pra arquivo texto — isso
 * seria uma downgrade silenciosa de segurança, exatamente o tipo de atalho que
 * o esquema de pareamento existe pra evitar.
 */
const SERVICE = "jarvis-agente-local";
const ACCOUNT = "agent-token";

let _keytarPromise = null;
// Injetável só pra teste — a propriedade "sem cofre disponível, falha alto"
// precisa ser verificável em QUALQUER plataforma, não só nesta que por acaso
// não tem libsecret. Em produção é sempre `() => import("keytar")` de verdade.
let _importKeytar = () => import("keytar");

function loadKeytar() {
  if (!_keytarPromise) {
    _keytarPromise = _importKeytar().catch((err) => {
      _keytarPromise = null; // permite tentar de novo numa próxima chamada
      throw new Error(
        "Cofre de credenciais do SO indisponível (keytar não carregou). O token " +
          "do agente NUNCA é gravado em texto puro como alternativa — isto é uma " +
          "falha bloqueante, não um aviso. Rode `npm install` nesta pasta na " +
          "máquina de destino (Windows/macOS funcionam sem passo extra; Linux " +
          "precisa do pacote de sistema `libsecret-1-dev` antes do install). " +
          `Causa original: ${err.message}`
      );
    });
  }
  return _keytarPromise;
}

/** Só pra teste: força a próxima chamada a recarregar o módulo `keytar`. */
export function _resetForTest() {
  _keytarPromise = null;
}

/** Só pra teste: troca o loader do keytar (ex.: forçar falha determinística
 * mesmo numa máquina onde o keytar de verdade funcionaria). `null` restaura o
 * import real. */
export function _setImportForTest(fn) {
  _importKeytar = fn || (() => import("keytar"));
  _keytarPromise = null;
}

export async function saveToken(token) {
  if (!token) throw new Error("saveToken: token vazio.");
  const keytar = (await loadKeytar()).default;
  await keytar.setPassword(SERVICE, ACCOUNT, token);
}

export async function getToken() {
  const keytar = (await loadKeytar()).default;
  return keytar.getPassword(SERVICE, ACCOUNT);
}

export async function deleteToken() {
  const keytar = (await loadKeytar()).default;
  await keytar.deletePassword(SERVICE, ACCOUNT);
}
