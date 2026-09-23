import subprocess

import pg_top
import pytest

BASE = ["--alvo", "dev", "--dsn", "postgresql://localhost/app", "--confirmo"]


class BancoFalso:
    def __init__(self, extensao=True, preload="pg_stat_statements"):
        self.enviados: list[str] = []
        self.extensao = extensao
        self.preload = preload

    def __call__(self, sql):
        pg_top.confere_leitura(sql)
        self.enviados.append(sql)
        if "pg_extension" in sql:
            return pg_top.Resultado(["extversion"], [["1.10"]] if self.extensao else [])
        if sql.startswith("SHOW"):
            return pg_top.Resultado(["shared_preload_libraries"], [[self.preload]])
        if "pg_stat_statements_info" in sql:
            return pg_top.Resultado(["stats_reset"], [["2026-01-01"]])
        if "pg_stat_database" in sql:
            return pg_top.Resultado(["datname", "hit_pct"], [["app", "99.1"]])
        return pg_top.Resultado(["calls", "consulta"], [["42", "SELECT * FROM t WHERE id = $1"]])


@pytest.mark.parametrize(
    "argv",
    [
        ["--dsn", "x", "--confirmo"],
        ["--alvo", "dev", "--dsn", "x"],
        ["--alvo", "dev", "--confirmo"],
        ["--alvo", "teste", "--dsn", "x", "--confirmo"],
        [*BASE, "--prazo", "5s; DROP TABLE t"],
    ],
    ids=["sem-alvo", "sem-confirmo", "sem-dsn", "alvo-invalido", "prazo-injetado"],
)
def test_guardas_recusam_antes_de_conectar(argv, monkeypatch):
    monkeypatch.delenv(pg_top.VARIAVEL_DSN, raising=False)
    banco = BancoFalso()

    with pytest.raises(SystemExit):
        pg_top.main(argv, executor=banco)
    assert banco.enviados == []


def test_dsn_pela_variavel(monkeypatch):
    monkeypatch.setenv(pg_top.VARIAVEL_DSN, "postgresql://localhost/app")

    assert pg_top.main(["--alvo", "dev", "--confirmo"], executor=BancoFalso()) == 0


def test_so_envia_select_e_show(capsys):
    banco = BancoFalso()

    assert pg_top.main(BASE, executor=banco) == 0

    assert banco.enviados
    assert all(sql.lstrip().split()[0] in {"SELECT", "SHOW"} for sql in banco.enviados)
    saida = capsys.readouterr().out
    assert "SELECT * FROM t WHERE id = $1" in saida
    assert "não cole esta saída" in saida
    assert saida.count("TOPO 10") == len(pg_top.ORDENS)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE EXTENSION pg_stat_statements",
        "ALTER SYSTEM SET shared_preload_libraries = 'x'",
        "SELECT pg_stat_statements_reset()",
        "select 1; delete from t",
        "  update t set a = 1",
    ],
)
def test_escrita_e_recusada(sql):
    with pytest.raises(pg_top.ConsultaRecusada):
        pg_top.confere_leitura(sql)


@pytest.mark.parametrize(
    ("extensao", "preload", "esperado"),
    [
        (False, "", ["REINÍCIO", "CREATE EXTENSION"]),
        (False, "pg_stat_statements", ["CREATE EXTENSION"]),
    ],
)
def test_sem_extensao_diz_o_que_falta_e_nao_cria(extensao, preload, esperado, capsys):
    banco = BancoFalso(extensao=extensao, preload=preload)

    assert pg_top.main(BASE, executor=banco) == 3

    saida = capsys.readouterr().out
    assert all(trecho in saida for trecho in esperado)
    assert not any("CREATE" in sql for sql in banco.enviados)
    assert not any("pg_stat_statements\n" in sql for sql in banco.enviados)


def test_sessao_psql_so_leitura_com_prazo(monkeypatch):
    chamadas = []

    def run(args, **kwargs):
        chamadas.append((args, kwargs["env"]))
        return subprocess.CompletedProcess(args, 0, "extversion\n1.10\n", "")

    monkeypatch.setattr(pg_top.subprocess, "run", run)
    monkeypatch.setenv("PGOPTIONS", "-c search_path=app")
    executa = pg_top.executor_psql("postgresql://localhost/app", "3s", "prod")

    resultado = executa(pg_top.CONSULTA_EXTENSAO)

    args, env = chamadas[0]
    assert resultado == pg_top.Resultado(["extversion"], [["1.10"]])
    assert "-X" in args and "ON_ERROR_STOP=1" in args
    assert env["PGOPTIONS"] == (
        "-c search_path=app -c default_transaction_read_only=on -c statement_timeout=3s"
    )
    assert env["PGAPPNAME"] == "pg_top-prod"


def test_executor_psql_recusa_escrita_sem_chamar_o_psql(monkeypatch):
    monkeypatch.setattr(pg_top.subprocess, "run", lambda *a, **k: pytest.fail("chamou o psql"))
    executa = pg_top.executor_psql("x", "5s", "dev")

    with pytest.raises(pg_top.ConsultaRecusada):
        executa("SELECT pg_stat_statements_reset()")
