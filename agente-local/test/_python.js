/**
 * Nome do executável Python pra spawnar o backend nos testes de integração.
 * No Windows o instalador oficial geralmente só registra `python`, não
 * `python3` (diferente de Linux/macOS) — sem isso, os testes de integração
 * quebram no CI do Windows por um motivo bobo, não por bug de verdade.
 * `PYTHON_BIN` permite forçar (útil se o CI tiver os dois e quiser um específico).
 */
export const PYTHON_BIN = process.env.PYTHON_BIN || (process.platform === "win32" ? "python" : "python3");
