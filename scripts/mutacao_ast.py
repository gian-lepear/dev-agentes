import argparse
import ast
import json
import os
import shlex
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

CONFIGS = (".mutacao.toml", "pyproject.toml")
PYTEST_PADRAO = f"{shlex.quote(sys.executable)} -m pytest"
OPCOES = [
    "-x",
    "-q",
    "--no-header",
    "-p",
    "no:cacheprovider",
    "-p",
    "no:randomly",
    "-o",
    "addopts=",
]

_COMPARADORES: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.GtE: ast.Gt,
    ast.Gt: ast.GtE,
    ast.LtE: ast.Lt,
    ast.Lt: ast.LtE,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
}


@dataclass
class Mutante:
    linha: int
    descricao: str

    @property
    def marca(self) -> str:
        return f"L{self.linha}: {self.descricao}"


@dataclass
class Config:
    alvos: dict[str, list[str]]
    equivalentes: dict[str, dict[str, str]] = field(default_factory=dict)


class ConfigInvalida(Exception):
    pass


class _Contador(ast.NodeVisitor):
    def __init__(self) -> None:
        self.pontos: list[Mutante] = []

    def visit_Compare(self, node: ast.Compare) -> None:
        for op in node.ops:
            if type(op) in _COMPARADORES:
                alvo = _COMPARADORES[type(op)].__name__
                self.pontos.append(
                    Mutante(node.lineno, f"comparador {type(op).__name__} -> {alvo}")
                )
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        novo = "Or" if isinstance(node.op, ast.And) else "And"
        self.pontos.append(Mutante(node.lineno, f"{type(node.op).__name__} -> {novo}"))
        self.generic_visit(node)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:
        if isinstance(node.op, ast.Not):
            self.pontos.append(Mutante(node.lineno, "remove `not`"))
        self.generic_visit(node)


class _Aplicador(ast.NodeTransformer):
    def __init__(self, alvo: int) -> None:
        self.alvo = alvo
        self.i = 0

    def _proximo(self) -> bool:
        acertou = self.i == self.alvo
        self.i += 1
        return acertou

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        node.ops = [
            _COMPARADORES[type(op)]() if type(op) in _COMPARADORES and self._proximo() else op
            for op in node.ops
        ]
        self.generic_visit(node)
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        if self._proximo():
            node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
        self.generic_visit(node)
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        remover = isinstance(node.op, ast.Not) and self._proximo()
        self.generic_visit(node)
        return node.operand if remover else node


def pontos(fonte: str) -> list[Mutante]:
    """Enumera os pontos mutáveis do módulo, na ordem em que a árvore é percorrida."""
    contador = _Contador()
    contador.visit(ast.parse(fonte))
    return contador.pontos


def mutante(fonte: str, indice: int) -> str:
    """Devolve o código com só a mutação de número `indice` aplicada."""
    arvore = _Aplicador(indice).visit(ast.parse(fonte))
    ast.fix_missing_locations(arvore)
    return ast.unparse(arvore)


def roda_pytest(pytest: list[str], testes: list[str], raiz: Path) -> bool:
    """Roda os testes e diz se passaram, sem reaproveitar bytecode velho do módulo mutado."""
    with tempfile.TemporaryDirectory() as cache:
        env = {**os.environ, "PYTHONPYCACHEPREFIX": cache, "PYTHONDONTWRITEBYTECODE": "1"}
        feito = subprocess.run(
            [*pytest, *OPCOES, *testes], cwd=raiz, capture_output=True, env=env, check=False
        )
    return feito.returncode == 0


def muta(
    raiz: Path,
    caminho: str,
    testes: list[str],
    passa: Callable[[list[str]], bool],
) -> tuple[int, list[str]]:
    """Roda os testes contra cada mutante do arquivo e devolve o total e os sobreviventes.

    O arquivo volta byte a byte ao original em qualquer caso, inclusive com Ctrl-C.
    """
    arquivo = raiz / caminho
    original = arquivo.read_bytes()
    fonte = original.decode("utf-8")
    lista = pontos(fonte)
    sobreviventes: list[str] = []
    print(f"\n{caminho}: {len(lista)} mutantes")
    try:
        for i, ponto in enumerate(lista):
            try:
                codigo = mutante(fonte, i)
            except (ValueError, RecursionError) as erro:
                print(f"  [{i + 1}/{len(lista)}] pulado (unparse falhou: {erro})")
                continue
            arquivo.write_text(codigo, encoding="utf-8")
            if passa(testes):
                sobreviventes.append(ponto.marca)
                print(f"  [{i + 1}/{len(lista)}] SOBREVIVEU  {ponto.marca}")
            else:
                print(f"  [{i + 1}/{len(lista)}] morto")
    finally:
        arquivo.write_bytes(original)
    return len(lista), sobreviventes


def le_config(texto: str, nome: str) -> Config | None:
    """Lê `[alvos]` e `[equivalentes]` do TOML (ou `[tool.mutacao]` no pyproject, ou JSON).

    Raises:
        ConfigInvalida: `alvos` ausente ou fora do formato `arquivo = [testes]`.
    """
    dados = json.loads(texto) if nome.endswith(".json") else tomllib.loads(texto)
    if nome == "pyproject.toml":
        dados = dados.get("tool", {}).get("mutacao")
        if dados is None:
            return None
    alvos = dados.get("alvos")
    if not isinstance(alvos, dict) or not alvos:
        raise ConfigInvalida(f"{nome}: `alvos` precisa mapear arquivo para lista de testes")
    for alvo, testes in alvos.items():
        if not isinstance(testes, list) or not all(isinstance(t, str) for t in testes):
            raise ConfigInvalida(f"{nome}: os testes de {alvo} precisam ser uma lista")
    return Config(alvos=alvos, equivalentes=dados.get("equivalentes") or {})


def _alvo(texto: str) -> tuple[str, list[str]]:
    arquivo, sep, testes = texto.partition("=")
    if not sep or not arquivo or not testes:
        raise argparse.ArgumentTypeError("use ARQUIVO=teste1,teste2")
    return arquivo, [t for t in testes.split(",") if t]


def relatorio(
    resumo: list[tuple[str, int, list[str]]], equivalentes: dict[str, dict[str, str]]
) -> int:
    """Imprime o placar por arquivo e devolve quantas lacunas reais sobraram."""
    print("\n" + "=" * 72)
    lacunas_geral = 0
    for caminho, total, sobreviventes in resumo:
        conhecidos = equivalentes.get(caminho, {})
        lacunas = [s for s in sobreviventes if s not in conhecidos]
        lacunas_geral += len(lacunas)
        placar = (total - len(sobreviventes)) / total * 100 if total else 100.0
        equiv = len(sobreviventes) - len(lacunas)
        print(
            f"{placar:5.1f}%  {caminho}  ({len(lacunas)} lacuna(s), {equiv} equivalente(s) de {total})"
        )
        for s in lacunas:
            print(f"     LACUNA  {s}")
        for s in sobreviventes:
            if s in conhecidos:
                print(f"     equiv.  {s}: {conhecidos[s]}")
    total_geral = sum(t for _, t, _ in resumo)
    print(f"\nlacunas reais: {lacunas_geral} de {total_geral} mutantes")
    print("Lacuna: linha que dá para quebrar sem a suíte reclamar. Equivalente: troca que")
    print("não muda comportamento observável, então nenhum teste pode matá-la.")
    return lacunas_geral


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mutação automática por AST em módulos de regra pura: troca >= por >, and por or, "
            "tira `not`, roda os testes mapeados e lista o mutante que sobrevive (linha que "
            "nenhuma asserção protege). Diagnóstico sob demanda, não para o CI. "
            "Sai com 1 se sobrar lacuna real."
        ),
        epilog=(
            "Alvos: --alvo, ou --config, ou .mutacao.toml, ou [tool.mutacao] no pyproject.toml, "
            'no formato [alvos] "src/regra.py" = ["tests/test_regra.py"] e, opcional, '
            '[equivalentes."src/regra.py"] "L12: And -> Or" = "por que não muda nada".'
        ),
    )
    parser.add_argument("arquivos", nargs="*", help="só estes alvos da config")
    parser.add_argument(
        "--alvo",
        action="append",
        type=_alvo,
        default=[],
        metavar="ARQUIVO=TESTES",
        help="alvo e testes separados por vírgula (repita para vários)",
    )
    parser.add_argument("--config", type=Path, help="TOML ou JSON com [alvos]")
    parser.add_argument("--raiz", type=Path, default=Path.cwd(), help="raiz do projeto")
    parser.add_argument(
        "--pytest",
        default=PYTEST_PADRAO,
        help="como chamar o pytest (padrão: este Python -m pytest)",
    )
    args = parser.parse_args(argv)
    try:
        if args.alvo:
            config = Config(alvos=dict(args.alvo))
        elif args.config:
            config = le_config(args.config.read_text(encoding="utf-8"), args.config.name)
        else:
            config = next(
                (
                    c
                    for nome in CONFIGS
                    if (args.raiz / nome).is_file()
                    and (c := le_config((args.raiz / nome).read_text(encoding="utf-8"), nome))
                ),
                None,
            )
    except (ConfigInvalida, tomllib.TOMLDecodeError, json.JSONDecodeError, OSError) as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2
    if not config:
        print("nenhum alvo: use --alvo ou crie .mutacao.toml", file=sys.stderr)
        return 2
    faltando = [a for a in args.arquivos if a not in config.alvos]
    if faltando:
        print(f"fora da config: {', '.join(faltando)}", file=sys.stderr)
        return 2
    alvos = {a: config.alvos[a] for a in args.arquivos} if args.arquivos else config.alvos
    pytest = shlex.split(args.pytest)
    resumo = []
    for caminho, testes in alvos.items():
        total, sobreviventes = muta(
            args.raiz, caminho, testes, lambda t: roda_pytest(pytest, t, args.raiz)
        )
        resumo.append((caminho, total, sobreviventes))
    return 1 if relatorio(resumo, config.equivalentes) else 0


if __name__ == "__main__":
    sys.exit(main())
