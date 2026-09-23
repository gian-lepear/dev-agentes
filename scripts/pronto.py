import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

SELO = Path(".local/pronto.stamp")
CONFIGS = (".pronto.toml", "pyproject.toml")
LINHAS_PADRAO = 40


@dataclass(frozen=True)
class Config:
    passos: list[str]
    prazo_s: float | None = None
    linhas: int = LINHAS_PADRAO


@dataclass(frozen=True)
class Passo:
    comando: str
    ok: bool
    segundos: float
    estourou: bool
    cauda: str


class ConfigInvalida(Exception):
    pass


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    resultado = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    )
    return resultado.stdout.strip()


def raiz(onde: Path | None = None) -> Path | None:
    """Devolve a raiz do repositório git que contém `onde`, ou None fora de um."""
    try:
        return Path(_git(onde or Path.cwd(), "rev-parse", "--show-toplevel"))
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def arvore_do_disco(repo: Path, selo: Path = SELO) -> str:
    """Devolve o hash da árvore que o disco teria se tudo fosse commitado.

    Usa uma cópia temporária do índice: o índice de verdade não muda. Respeita o
    `.gitignore` e deixa o próprio selo de fora.
    """
    indice = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index"))
    with tempfile.TemporaryDirectory() as pasta:
        temporario = Path(pasta) / "index"
        if indice.is_file():
            shutil.copyfile(indice, temporario)
        env = {**os.environ, "GIT_INDEX_FILE": str(temporario)}
        ignorado = subprocess.run(
            ["git", "-C", str(repo), "check-ignore", "-q", "--no-index", selo.as_posix()],
            capture_output=True,
            check=False,
        )
        fora = [] if ignorado.returncode == 0 else ["--", ".", f":(exclude){selo.as_posix()}"]
        _git(repo, "add", "-A", *fora, env=env)
        return _git(repo, "write-tree", env=env)


def grava_selo(repo: Path, testada: str, selo: Path = SELO) -> bool:
    """Grava o selo com a árvore testada, se o disco ainda for essa árvore."""
    if arvore_do_disco(repo, selo) != testada:
        return False
    arquivo = repo / selo
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(testada + "\n", encoding="utf-8")
    return True


def le_config(texto: str, nome: str) -> Config | None:
    """Lê `passos`, `prazo` e `linhas` do TOML: no topo, ou em `[tool.pronto]` no pyproject.

    Raises:
        ConfigInvalida: `passos` ausente ou que não é lista de texto.
    """
    dados = tomllib.loads(texto)
    if nome == "pyproject.toml":
        dados = dados.get("tool", {}).get("pronto")
        if dados is None:
            return None
    passos = dados.get("passos")
    if not isinstance(passos, list) or not passos or not all(isinstance(p, str) for p in passos):
        raise ConfigInvalida(f"{nome}: `passos` precisa ser uma lista de comandos")
    prazo = dados.get("prazo")
    return Config(
        passos=passos,
        prazo_s=float(prazo) if prazo else None,
        linhas=int(dados.get("linhas", LINHAS_PADRAO)),
    )


def acha_config(onde: Path) -> Config | None:
    for nome in CONFIGS:
        arquivo = onde / nome
        if arquivo.is_file():
            config = le_config(arquivo.read_text(encoding="utf-8"), nome)
            if config:
                return config
    return None


def roda_passo(comando: str, prazo_s: float | None, linhas: int, cwd: Path) -> Passo:
    """Roda um comando no shell com a saída num arquivo e devolve só a cauda dela.

    Estourado o prazo, o grupo de processos inteiro é morto, com os filhos do shell.
    """
    inicio = time.monotonic()
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as saida:
        processo = subprocess.Popen(
            comando,
            shell=True,
            cwd=cwd,
            stdout=saida,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        estourou = False
        try:
            codigo = processo.wait(timeout=prazo_s)
        except subprocess.TimeoutExpired:
            estourou = True
            os.killpg(processo.pid, signal.SIGKILL)
            codigo = processo.wait()
        saida.seek(0)
        cauda = "".join(saida.readlines()[-linhas:]) if linhas else ""
    return Passo(comando, codigo == 0 and not estourou, time.monotonic() - inicio, estourou, cauda)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Portão antes de commit ou PR: roda os passos que o CI roda, sem consertar nada, "
            "e mostra só a saída do que falhou. Se tudo passa e o disco não mudou no meio, "
            "grava o selo com a árvore testada, que o push_pronto.py lê no pre-push."
        ),
        epilog=(
            "Passos: da linha de comando, ou de --config, ou de .pronto.toml "
            "(passos = [...], prazo = 600, linhas = 40), ou de [tool.pronto] no pyproject.toml."
        ),
    )
    parser.add_argument("passos", nargs="*", help="comandos de shell, na ordem")
    parser.add_argument("--config", type=Path, help="arquivo TOML com `passos`")
    parser.add_argument("--prazo", type=float, help="segundos por passo antes de matar")
    parser.add_argument(
        "--linhas", type=int, help=f"linhas finais da falha (padrão {LINHAS_PADRAO})"
    )
    parser.add_argument("--para", action="store_true", help="para no primeiro passo que falha")
    parser.add_argument("--selo", type=Path, default=SELO, help=f"onde gravar o selo ({SELO})")
    parser.add_argument("--sem-selo", action="store_true", help="não grava o selo")
    args = parser.parse_args(argv)

    repo = raiz()
    base = repo or Path.cwd()
    try:
        if args.passos:
            config = Config(passos=list(args.passos))
        elif args.config:
            config = le_config(args.config.read_text(encoding="utf-8"), args.config.name)
        else:
            config = acha_config(base)
    except (ConfigInvalida, tomllib.TOMLDecodeError, OSError) as erro:
        print(f"config inválida: {erro}", file=sys.stderr)
        return 2
    if not config:
        print("nenhum passo: passe comandos ou crie .pronto.toml", file=sys.stderr)
        return 2
    prazo = args.prazo if args.prazo is not None else config.prazo_s
    linhas = args.linhas if args.linhas is not None else config.linhas

    testada = arvore_do_disco(repo, args.selo) if repo and not args.sem_selo else None
    falhou = False
    for comando in config.passos:
        passo = roda_passo(comando, prazo, linhas, Path.cwd())
        if passo.ok:
            print(f"ok     {passo.segundos:6.1f}s  {comando}")
            continue
        falhou = True
        rotulo = "PRAZO " if passo.estourou else "FALHOU"
        print(f"{rotulo} {passo.segundos:6.1f}s  {comando}")
        print(passo.cauda, end="" if passo.cauda.endswith("\n") or not passo.cauda else "\n")
        if args.para:
            break
    if falhou:
        return 1
    if repo and testada:
        if grava_selo(repo, testada, args.selo):
            print(f"selo gravado: {args.selo}")
        else:
            print("selo não gravado: o disco mudou durante o portão")
    return 0


if __name__ == "__main__":
    sys.exit(main())
