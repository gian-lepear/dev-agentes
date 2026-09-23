import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from pronto import SELO, _git, arvore_do_disco, raiz


def refs_empurradas(texto: str) -> list[str]:
    """Lê as linhas que o git passa ao pre-push e devolve os commits locais empurrados.

    Linha: `<ref local> <sha local> <ref remota> <sha remoto>`. Apagar uma ref remota
    manda o sha local zerado, e essa linha não tem árvore para conferir.
    """
    shas = []
    for linha in texto.splitlines():
        partes = linha.split()
        if len(partes) == 4 and set(partes[1]) != {"0"}:
            shas.append(partes[1])
    return shas


def ja_passou(repo: Path, empurrados: Sequence[str], selo: Path = SELO) -> bool:
    """Diz se o selo, o disco e cada commit empurrado são a mesma árvore."""
    arquivo = repo / selo
    if not arquivo.is_file() or not empurrados:
        return False
    carimbada = arquivo.read_text(encoding="utf-8").strip()
    if carimbada != arvore_do_disco(repo, selo):
        return False
    return all(_git(repo, "rev-parse", f"{sha}^{{tree}}") == carimbada for sha in empurrados)


def _le_stdin() -> str:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def main(argv: Sequence[str] | None = None, entrada: str | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ajudante de pre-push: sai com 0 sem rodar nada quando a árvore empurrada já passou "
            "no pronto.py (o selo, o disco e o commit empurrado são a mesma árvore). Senão roda "
            "o comando e devolve o código de saída dele."
        ),
        epilog=(
            "O que é empurrado vem, nesta ordem: de PRE_COMMIT_TO_REF (framework pre-commit), "
            "das linhas que o git passa no stdin do hook pre-push, ou do HEAD. "
            "Ex.: push_pronto.py -- pytest -q"
        ),
    )
    parser.add_argument("--selo", type=Path, default=SELO, help=f"onde está o selo ({SELO})")
    parser.add_argument("comando", nargs=argparse.REMAINDER, help="o que rodar se o selo não vale")
    args = parser.parse_args(argv)
    comando = args.comando[1:] if args.comando[:1] == ["--"] else args.comando
    if not comando:
        parser.error("diga o comando a rodar quando o selo não vale")
    repo = raiz()
    if repo is None:
        return subprocess.run(comando, check=False).returncode
    alvo = os.environ.get("PRE_COMMIT_TO_REF")
    if alvo:
        empurrados = [alvo]
    else:
        linhas = _le_stdin() if entrada is None else entrada
        empurrados = refs_empurradas(linhas)
        if linhas.strip() and not empurrados:
            print("nada a testar: o push só apaga refs")
            return 0
        empurrados = empurrados or ["HEAD"]
    if ja_passou(repo, empurrados, args.selo):
        print("testes pulados: esta árvore já passou no portão")
        return 0
    return subprocess.run(comando, cwd=repo, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
