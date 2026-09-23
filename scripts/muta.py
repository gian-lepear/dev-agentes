import argparse
import json
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from troca import Troca, TrocaRecusada, aplica

PYTEST_PADRAO = "uv run pytest"
OPCOES = ["-o", "addopts=", "-p", "no:randomly", "-p", "no:warnings", "-q"]
PYTEST = [*shlex.split(PYTEST_PADRAO), *OPCOES]


@dataclass(frozen=True)
class Mutacao:
    teste: str
    arquivo: Path
    velho: str
    novo: str


@dataclass(frozen=True)
class Veredito:
    teste: str
    arquivo: str
    passa_sem: bool
    falha_com: bool
    restaurado: bool
    saida: str

    @property
    def pega(self) -> bool:
        return self.passa_sem and self.falha_com and self.restaurado


def le_mutacoes(texto: str, base: Path) -> list[Mutacao]:
    """Lê a lista de mutações do JSON: `{teste, arquivo, velho, novo}` por item."""
    return [
        Mutacao(item["teste"], base / item["arquivo"], item["velho"], item["novo"])
        for item in json.loads(texto)
    ]


def roda_pytest(teste: str, base: Path, pytest: list[str] = PYTEST) -> tuple[bool, str]:
    feito = subprocess.run([*pytest, teste], cwd=base, capture_output=True, text=True, check=False)
    linhas = feito.stdout.splitlines()
    decisiva = next((linha for linha in linhas if linha.startswith("E ")), None)
    return feito.returncode == 0, decisiva or (linhas[-1] if linhas else "")


def confere(
    mutacao: Mutacao, base: Path, roda: Callable[[str, Path], tuple[bool, str]] = roda_pytest
) -> Veredito:
    """Prova que o teste passa no código atual, falha com a mutação e passa de novo depois.

    O arquivo mutado volta byte a byte ao original em qualquer caso, inclusive se o pytest
    levantar.
    """
    original = mutacao.arquivo.read_bytes()
    passa_sem, _ = roda(mutacao.teste, base)
    try:
        aplica([Troca(mutacao.arquivo, mutacao.velho, mutacao.novo)])
        passou_com, saida = roda(mutacao.teste, base)
    finally:
        mutacao.arquivo.write_bytes(original)
    return Veredito(
        teste=mutacao.teste,
        arquivo=str(mutacao.arquivo.relative_to(base)),
        passa_sem=passa_sem,
        falha_com=not passou_com,
        restaurado=mutacao.arquivo.read_bytes() == original,
        saida=saida,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prova, por mutação, que cada teste pega a armadilha que diz pegar."
    )
    parser.add_argument("json", help="lista de {teste, arquivo, velho, novo}, ou - para stdin")
    parser.add_argument(
        "--base", type=Path, default=Path.cwd(), help="raiz do projeto (padrão: o atual)"
    )
    parser.add_argument(
        "--pytest",
        default=PYTEST_PADRAO,
        help=f"como chamar o pytest neste projeto (padrão: {PYTEST_PADRAO!r})",
    )
    args = parser.parse_args(argv)
    roda = partial(roda_pytest, pytest=[*shlex.split(args.pytest), *OPCOES])
    texto = sys.stdin.read() if args.json == "-" else Path(args.json).read_text(encoding="utf-8")

    falhou = False
    for mutacao in le_mutacoes(texto, args.base):
        try:
            veredito = confere(mutacao, args.base, roda)
        except TrocaRecusada as erro:
            print(f"RECUSADA {mutacao.teste}\n  {erro}")
            falhou = True
            continue
        if veredito.pega:
            print(f"PEGA     {veredito.teste}\n  {veredito.saida}")
            continue
        falhou = True
        motivo = (
            "não passa no código atual"
            if not veredito.passa_sem
            else "passa mesmo com a mutação"
            if not veredito.falha_com
            else "o arquivo não voltou ao original"
        )
        print(f"NÃO PEGA {veredito.teste}: {motivo}")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
