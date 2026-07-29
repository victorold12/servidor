"""Backend publicado não pode subir aberto.

Sem pytest (`python3 tests/test_producao_fechada.py`), igual aos outros.

Por que este teste existe: antes, BACKEND_TOKEN vazio em produção gerava um
warning no log e o serviço subia mesmo assim. Quem não configurou o token também
não estava lendo o log — e um backend aberto COM a chave do OpenRouter dentro é
a internet inteira gastando o crédito do dono.

O que fica travado aqui:
  - RENDER=true e sem token: o boot ABORTA (não é warning)
  - a mensagem diz o que fazer, não só o que está errado
  - ALLOW_OPEN_BACKEND=1 continua sendo uma saída — mas exige ato deliberado
  - máquina local (sem RENDER) segue subindo sem token, que é o modo de uso
"""
import importlib
import os
import sys
import tempfile

_TMP = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

falhas = []


def checa(nome, cond, extra=""):
    if cond:
        print(f"  ok  {nome}")
    else:
        print(f"FALHA {nome} {extra}")
        falhas.append(nome)


def sobe(env, nome_db):
    """Sobe o app num ambiente limpo e devolve (subiu?, erro).

    Reimporta config e main porque `settings` é lido uma vez na importação:
    sem o reload, o segundo cenário herdaria as env vars do primeiro e o teste
    diria "passou" testando o ambiente errado.
    """
    antigo = dict(os.environ)
    for k in ("RENDER", "BACKEND_TOKEN", "ALLOW_OPEN_BACKEND", "ALLOWED_ORIGINS"):
        os.environ.pop(k, None)
    os.environ["JARVIS_DB_PATH"] = os.path.join(_TMP, nome_db)
    os.environ.update(env)
    try:
        import app.config
        import app.main
        importlib.reload(app.config)
        importlib.reload(app.main)
        from fastapi.testclient import TestClient
        with TestClient(app.main.app) as c:
            c.get("/api/health")
        return True, None
    except Exception as e:
        return False, e
    finally:
        os.environ.clear()
        os.environ.update(antigo)


print("— máquina local segue livre")

ok, err = sobe({}, "local.db")
checa("sem RENDER e sem token: sobe", ok, err)


print("— produção sem token: não sobe")

ok, err = sobe({"RENDER": "true"}, "prod.db")
checa("aborta o boot", not ok, "subiu aberto!")
msg = str(err or "")
checa("o erro nomeia a variável que falta", "BACKEND_TOKEN" in msg, msg[:120])
checa("e diz onde configurar", "Render" in msg and "Environment" in msg, msg[:200])
checa("e avisa do risco concreto", "OpenRouter" in msg, msg[:200])
checa("e mostra a saída consciente", "ALLOW_OPEN_BACKEND" in msg, msg[:200])


print("— produção com token: sobe")

ok, err = sobe({"RENDER": "true", "BACKEND_TOKEN": "um-token-longo-e-aleatorio"}, "prodok.db")
checa("sobe normalmente", ok, err)


print("— backend aberto de propósito continua possível")

ok, err = sobe({"RENDER": "true", "ALLOW_OPEN_BACKEND": "1"}, "aberto.db")
checa("ALLOW_OPEN_BACKEND=1 deixa subir sem token", ok, err)


print("— CORS")

ok, err = sobe({"RENDER": "true", "BACKEND_TOKEN": "t",
                "ALLOWED_ORIGINS": "https://meu-painel.onrender.com"}, "cors.db")
checa("origem específica é aceita na configuração", ok, err)
import app.config  # noqa: E402  — já recarregado por sobe()
checa("e vira lista, não string solta",
      isinstance(app.config.settings.origins, list), app.config.settings.origins)

print()
if falhas:
    print(f"{len(falhas)} falha(s): {', '.join(falhas)}")
    sys.exit(1)
print("produção fechada: todos os testes passaram")
