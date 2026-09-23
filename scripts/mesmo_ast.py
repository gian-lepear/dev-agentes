import argparse
import ast
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

CORPOS = ("body", "orelse", "finalbody")
DEFINICOES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
REGISTRO_PADRAO = r"-\d{4}-\d{2}-\d{2}\.md$"


@dataclass
class Resultado:
    arquivo: str
    igual: bool
    renomeados: list[tuple[str, str]] = field(default_factory=list)
    duplicados: list[str] = field(default_factory=list)
    diferenca: str = ""


def _descartavel(no: ast.stmt) -> bool:
    if isinstance(no, ast.Pass):
        return True
    return (
        isinstance(no, ast.Expr)
        and isinstance(no.value, ast.Constant)
        and (isinstance(no.value.value, str) or no.value.value is ...)
    )


def normaliza(fonte: str, teste: bool) -> tuple[ast.Module, list[str], list[str]]:
    """Tira texto solto e corpo vazio da árvore e troca os nomes de teste pela posição.

    Returns:
        A árvore normalizada, os nomes de teste na ordem em que aparecem e os nomes
        definidos mais de uma vez no mesmo corpo.
    """
    arvore = ast.parse(fonte)
    nomes: list[str] = []
    duplicados: list[str] = []
    pilha: list[ast.AST] = [arvore]
    while pilha:
        no = pilha.pop()
        for campo in CORPOS:
            corpo = getattr(no, campo, None)
            if not (isinstance(corpo, list) and (not corpo or isinstance(corpo[0], ast.stmt))):
                continue
            restante = [s for s in corpo if not _descartavel(s)] or [ast.Pass()]
            setattr(no, campo, restante)
            contagem = Counter(s.name for s in restante if isinstance(s, DEFINICOES))
            duplicados += [nome for nome, n in contagem.items() if n > 1]
        if teste and isinstance(no, DEFINICOES) and no.name.startswith(("test", "Test")):
            nomes.append(no.name)
            no.name = "__teste__"
        for campo in (*CORPOS, "handlers", "cases"):
            pilha.extend(
                reversed([f for f in getattr(no, campo, None) or () if isinstance(f, ast.AST)])
            )
    return arvore, nomes, duplicados


def _primeira_diferenca(antes: ast.AST, depois: ast.AST) -> str:
    fila: list[tuple[object, object, ast.AST, ast.AST]] = [(antes, depois, antes, depois)]
    while fila:
        a, b, dono_a, dono_b = fila.pop()
        if type(a) is not type(b):
            break
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                break
            fila.extend(
                (x, y, dono_a, dono_b) for x, y in zip(reversed(a), reversed(b), strict=True)
            )
            continue
        if not (isinstance(a, ast.AST) and isinstance(b, ast.AST)):
            if a != b:
                break
            continue
        if hasattr(a, "lineno"):
            dono_a, dono_b = a, b
        fila.extend(
            (getattr(a, f, None), getattr(b, f, None), dono_a, dono_b) for f in reversed(a._fields)
        )
    else:
        return ""
    return "\n".join(
        f"  {rotulo} (linha {getattr(dono, 'lineno', '?')}): {ast.unparse(dono)[:160]}"
        for rotulo, dono in (("antes ", dono_a), ("depois", dono_b))
    )


def compara(arquivo: str, antes: str, depois: str) -> Resultado:
    """Compara duas versões de um arquivo ignorando comentário, docstring e nome de teste."""
    caminho = Path(arquivo)
    teste = "tests" in caminho.parts or caminho.name.startswith("test_")
    arvore_antes, nomes_antes, dup_antes = normaliza(antes, teste)
    arvore_depois, nomes_depois, dup_depois = normaliza(depois, teste)
    diferenca = _primeira_diferenca(arvore_antes, arvore_depois)
    return Resultado(
        arquivo=arquivo,
        igual=not diferenca,
        renomeados=[(a, b) for a, b in zip(nomes_antes, nomes_depois, strict=False) if a != b],
        duplicados=sorted(set(dup_depois) - set(dup_antes)),
        diferenca=diferenca,
    )


def _versoes(ref: str, arquivos: list[str]) -> dict[str, str]:
    entrada = "".join(f"{ref}:{a}\n" for a in arquivos).encode()
    saida = subprocess.run(
        ["git", "cat-file", "--batch"], input=entrada, capture_output=True, check=True
    ).stdout
    versoes: dict[str, str] = {}
    pos = 0
    for arquivo in arquivos:
        fim_cabecalho = saida.index(b"\n", pos)
        cabecalho = saida[pos:fim_cabecalho].split()
        pos = fim_cabecalho + 1
        if cabecalho[-1] == b"missing":
            continue
        tamanho = int(cabecalho[2])
        versoes[arquivo] = saida[pos : pos + tamanho].decode("utf-8")
        pos += tamanho + 1
    return versoes


def referencias_orfas(
    nomes: set[str],
    ocorrencias: list[str],
    fonte_de: Callable[[str], str],
    registro: str = REGISTRO_PADRAO,
) -> list[str]:
    """Aponta onde um nome de teste antigo ainda é citado depois de renomeado.

    Args:
        nomes: Os nomes antigos.
        ocorrencias: Linhas `caminho:linha:conteúdo`, como o `git grep -n` devolve.
        fonte_de: Lê o conteúdo atual de um caminho.
        registro: Regex dos caminhos de registro datado, que ficam como foram escritos.

    Returns:
        As ocorrências que sobram depois de descartar os `.py` que ainda definem o nome,
        porque outro teste com o mesmo nome não é referência ao renomeado, e os registros
        datados, que ficam como foram escritos.
    """
    eh_registro = re.compile(registro) if registro else None
    padroes = {nome: re.compile(rf"\b{re.escape(nome)}\b") for nome in nomes}
    orfas = []
    for ocorrencia in ocorrencias:
        caminho, _, conteudo = ocorrencia.split(":", 2)
        if eh_registro and eh_registro.search(caminho):
            continue
        for nome, padrao in padroes.items():
            if not padrao.search(conteudo):
                continue
            definicao = re.compile(rf"^\s*(?:async\s+)?(?:def|class)\s+{re.escape(nome)}\b", re.M)
            if caminho.endswith(".py") and definicao.search(fonte_de(caminho)):
                continue
            orfas.append(f"{ocorrencia.strip()}  ({nome})")
    return orfas


def _git_grep(nomes: set[str]) -> list[str]:
    if not nomes:
        return []
    padroes = [arg for nome in sorted(nomes) for arg in ("-e", nome)]
    saida = subprocess.run(
        ["git", "grep", "-n", "-w", "-I", *padroes], capture_output=True, text=True, check=False
    )
    return saida.stdout.splitlines()


@cache
def _fonte(caminho: str) -> str:
    return Path(caminho).read_text(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prova que só comentário, docstring e nome de teste mudaram desde REF."
    )
    parser.add_argument("--ref", default="main", help="ref do git a comparar (padrão: main)")
    parser.add_argument(
        "--registro",
        default=REGISTRO_PADRAO,
        help=(
            "regex dos caminhos de registro datado, onde nome antigo citado não conta "
            "como referência órfã; vazio desliga (padrão: arquivo .md terminado em data)"
        ),
    )
    parser.add_argument("caminhos", nargs="*", default=["."], help="restringe a estes caminhos")
    args = parser.parse_args(argv)

    arquivos = subprocess.run(
        ["git", "diff", "--name-only", args.ref, "--", *args.caminhos],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    arquivos = [a for a in arquivos if a.endswith(".py")]
    versoes = _versoes(args.ref, arquivos)
    faltando = [a for a in arquivos if a not in versoes or not Path(a).exists()]
    for arquivo in faltando:
        print(f"NOVO OU APAGADO  {arquivo}")
    falhou = bool(faltando)
    pares = [a for a in arquivos if a not in faltando]
    with ProcessPoolExecutor() as pool:
        resultados = list(
            pool.map(
                compara,
                pares,
                [versoes[a] for a in pares],
                [Path(a).read_text(encoding="utf-8") for a in pares],
                chunksize=8,
            )
        )
    for resultado in resultados:
        arquivo = resultado.arquivo
        if not resultado.igual:
            print(f"CÓDIGO   {arquivo}\n{resultado.diferenca}")
            falhou = True
        if resultado.duplicados:
            print(f"DUPLICA  {arquivo}: {', '.join(resultado.duplicados)}")
            falhou = True
        for velho, novo in resultado.renomeados:
            print(f"RENOMEIA {arquivo}: {velho} -> {novo}")
    antigos = {velho for r in resultados for velho, novo in r.renomeados if velho != novo}
    for orfa in referencias_orfas(antigos, _git_grep(antigos), _fonte, args.registro):
        print(f"REFERÊNCIA {orfa}")
        falhou = True
    print(f"{len(arquivos)} arquivos conferidos")
    return 1 if falhou else 0


if __name__ == "__main__":
    sys.exit(main())
