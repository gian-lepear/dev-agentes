import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

VARIAVEL_DSN = "PG_TOP_DSN"
PRAZO_PADRAO = "5s"
SO_LEITURA = re.compile(r"^\s*(SELECT|SHOW|WITH)\b", re.IGNORECASE)
PROIBIDO = re.compile(
    r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|GRANT|REVOKE|COPY|VACUUM|"
    r"pg_stat_statements_reset|pg_stat_reset)\b",
    re.IGNORECASE,
)

ORDENS = {
    "total": ("total_exec_time DESC", "tempo total (onde o banco passa o dia)"),
    "media": ("mean_exec_time DESC", "tempo médio por chamada (a consulta lenta em si)"),
    "chamadas": ("calls DESC", "chamadas (N+1, laço que consulta)"),
    "linhas": ("rows DESC", "linhas devolvidas (consulta que traz demais)"),
    "cache": ("hit_pct ASC NULLS LAST, shared_blks_read DESC", "menor acerto de cache (lê disco)"),
}

CONSULTA_TOPO = """
SELECT calls,
       round(total_exec_time::numeric, 1) AS total_ms,
       round(mean_exec_time::numeric, 2) AS media_ms,
       rows,
       round(rows::numeric / nullif(calls, 0), 1) AS linhas_por_chamada,
       round(100.0 * shared_blks_hit / nullif(shared_blks_hit + shared_blks_read, 0), 1) AS hit_pct,
       left(regexp_replace(query, '\\s+', ' ', 'g'), {largura}) AS consulta
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
ORDER BY {ordem}
LIMIT {limite}
"""
CONSULTA_EXTENSAO = "SELECT extversion FROM pg_extension WHERE extname = 'pg_stat_statements'"
CONSULTA_PRELOAD = "SHOW shared_preload_libraries"
CONSULTA_JANELA = "SELECT stats_reset FROM pg_stat_statements_info"
CONSULTA_BANCO = """
SELECT datname, numbackends, xact_commit, xact_rollback,
       round(100.0 * blks_hit / nullif(blks_hit + blks_read, 0), 2) AS hit_pct,
       stats_reset
FROM pg_stat_database
WHERE datname = current_database()
"""

ACOES_HUMANAS = {
    "preload": (
        "ESCRITA + REINÍCIO: em postgresql.conf, shared_preload_libraries = 'pg_stat_statements' "
        "(somar às que já existem) e reiniciar o Postgres"
    ),
    "extensao": "ESCRITA: CREATE EXTENSION IF NOT EXISTS pg_stat_statements;",
    "zerar": "ESCRITA: SELECT pg_stat_statements_reset();  -- zera a janela antes de medir",
}


class ConsultaRecusada(Exception):
    pass


@dataclass(frozen=True)
class Resultado:
    colunas: list[str]
    linhas: list[list[str]]


Executor = Callable[[str], Resultado]


def confere_leitura(sql: str) -> str:
    """Devolve o SQL se ele só lê; senão recusa.

    Raises:
        ConsultaRecusada: SQL que não começa por SELECT, SHOW ou WITH, ou que cita escrita.
    """
    if not SO_LEITURA.match(sql) or PROIBIDO.search(sql):
        raise ConsultaRecusada(f"pg_top só lê estatística; recusado: {sql.strip()[:80]!r}")
    return sql


def ambiente_psql(base: dict[str, str], prazo: str, alvo: str) -> dict[str, str]:
    """Ambiente do psql: sessão só de leitura, prazo por comando e nome de aplicação."""
    opcoes = f"-c default_transaction_read_only=on -c statement_timeout={prazo}"
    anteriores = base.get("PGOPTIONS", "")
    return {
        **base,
        "PGOPTIONS": f"{anteriores} {opcoes}".strip(),
        "PGAPPNAME": f"pg_top-{alvo}",
    }


def executor_psql(dsn: str, prazo: str, alvo: str, psql: str = "psql") -> Executor:
    env = ambiente_psql(dict(os.environ), prazo, alvo)

    def executa(sql: str) -> Resultado:
        feito = subprocess.run(
            [
                psql,
                "-X",
                "-q",
                "-A",
                "-F",
                "\t",
                "-P",
                "footer=off",
                "-v",
                "ON_ERROR_STOP=1",
                "-d",
                dsn,
                "-c",
                confere_leitura(sql),
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if feito.returncode != 0:
            raise RuntimeError(feito.stderr.strip() or f"psql saiu com {feito.returncode}")
        linhas = [linha.split("\t") for linha in feito.stdout.splitlines() if linha]
        return Resultado(linhas[0] if linhas else [], linhas[1:])

    return executa


def _tabela(resultado: Resultado) -> str:
    if not resultado.linhas:
        return "  (nada)"
    larguras = [
        max(len(c), *(len(linha[i]) for linha in resultado.linhas if i < len(linha)))
        for i, c in enumerate(resultado.colunas)
    ]
    ultima = len(resultado.colunas) - 1

    def formata(linha: list[str]) -> str:
        return "  " + "  ".join(
            v if i == ultima else v.rjust(larguras[i]) for i, v in enumerate(linha)
        )

    return "\n".join([formata(resultado.colunas), *(formata(linha) for linha in resultado.linhas)])


def diagnostica(executa: Executor) -> list[str]:
    """Diz o que falta para medir: extensão criada e biblioteca pré-carregada."""
    faltas = []
    if not executa(CONSULTA_EXTENSAO).linhas:
        faltas.append("extensao")
    preload = executa(CONSULTA_PRELOAD).linhas
    if not preload or "pg_stat_statements" not in preload[0][0]:
        faltas.insert(0, "preload")
    return faltas


def relata(executa: Executor, ordens: list[str], limite: int, largura: int) -> int:
    faltas = diagnostica(executa)
    if faltas:
        print("pg_stat_statements não está pronto neste banco. Falta, para um humano fazer:")
        for falta in faltas:
            print(f"  - {ACOES_HUMANAS[falta]}")
        return 3
    print("BANCO (contexto)")
    print(_tabela(executa(CONSULTA_BANCO)))
    try:
        janela = executa(CONSULTA_JANELA).linhas
        print(f"\njanela das estatísticas desde: {janela[0][0] if janela else '?'}")
    except RuntimeError:
        print("\njanela das estatísticas: indisponível nesta versão")
    for nome in ordens:
        ordem, rotulo = ORDENS[nome]
        print(f"\nTOPO {limite} POR {rotulo}")
        sql = CONSULTA_TOPO.format(ordem=ordem, limite=int(limite), largura=int(largura))
        print(_tabela(executa(sql)))
    print(
        "\nO texto das consultas pode revelar o esquema e, raramente, valores literais: "
        "não cole esta saída em lugar público."
    )
    print(f"Para zerar a janela antes da próxima medida, um humano roda: {ACOES_HUMANAS['zerar']}")
    return 0


def main(argv: Sequence[str] | None = None, executor: Executor | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Lê o pg_stat_statements e mostra as consultas mais caras. Só lê: a sessão abre com "
            "default_transaction_read_only=on e statement_timeout, e todo SQL enviado é SELECT ou "
            "SHOW. Nunca cria extensão, muda configuração ou zera estatística: imprime esses "
            "comandos para um humano. Usa o psql do PATH."
        ),
        epilog=(
            f"DSN por --dsn ou pela variável {VARIAVEL_DSN}. Senha fica no ~/.pgpass ou em "
            "PGPASSWORD, não no DSN, que aparece na lista de processos."
        ),
    )
    parser.add_argument("--alvo", choices=("dev", "prod"), help="qual banco é (obrigatório)")
    parser.add_argument("--dsn", help=f"conexão (ou {VARIAVEL_DSN})")
    parser.add_argument(
        "--confirmo",
        action="store_true",
        help="a pessoa disse sim a esta leitura, neste banco (obrigatório)",
    )
    parser.add_argument(
        "--ordem",
        action="append",
        choices=tuple(ORDENS),
        help="quais rankings mostrar (repita; padrão: todos)",
    )
    parser.add_argument("--limite", type=int, default=10, help="linhas por ranking (10)")
    parser.add_argument("--largura", type=int, default=120, help="caracteres da consulta (120)")
    parser.add_argument("--prazo", default=PRAZO_PADRAO, help=f"statement_timeout ({PRAZO_PADRAO})")
    parser.add_argument("--psql", default="psql", help="caminho do psql")
    args = parser.parse_args(argv)
    if not args.alvo:
        parser.error("diga --alvo dev ou --alvo prod")
    dsn = args.dsn or os.environ.get(VARIAVEL_DSN)
    if not dsn:
        parser.error(f"diga --dsn ou defina {VARIAVEL_DSN}")
    if not args.confirmo:
        parser.error(
            f"recusado sem --confirmo: diga à pessoa que vai ler estatísticas do banco "
            f"{args.alvo}, por qual conexão, e espere o sim"
        )
    if not re.fullmatch(r"\d+\s*(ms|s|min)?", args.prazo):
        parser.error("--prazo precisa ser duração do Postgres, como 5s ou 500ms")
    if args.alvo == "prod":
        print("alvo: PRODUÇÃO, só leitura de estatística agregada")
    executa = executor or executor_psql(dsn, args.prazo, args.alvo, args.psql)
    try:
        return relata(executa, args.ordem or list(ORDENS), args.limite, args.largura)
    except (RuntimeError, ConsultaRecusada) as erro:
        print(f"falhou: {erro}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
