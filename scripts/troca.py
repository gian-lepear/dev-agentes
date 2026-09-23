import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Troca:
    arquivo: Path
    velho: str
    novo: str
    todas: bool = False


class TrocaRecusada(Exception):
    pass


def le_trocas(texto: str, base: Path) -> list[Troca]:
    """Lê a lista de trocas do JSON.

    Args:
        texto: Lista de objetos com `arquivo`, `velho`, `novo` e, opcional, `todas`.
        base: Diretório contra o qual `arquivo` relativo é resolvido.

    Raises:
        TrocaRecusada: JSON que não é lista de trocas.
    """
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError as erro:
        raise TrocaRecusada(f"JSON inválido: {erro}") from erro
    if not isinstance(dados, list) or not dados:
        raise TrocaRecusada("esperava uma lista não vazia de trocas")
    trocas = []
    for i, item in enumerate(dados):
        if not isinstance(item, dict) or not {"arquivo", "velho", "novo"} <= item.keys():
            raise TrocaRecusada(f"troca {i}: precisa de arquivo, velho e novo")
        if not item["velho"]:
            raise TrocaRecusada(f"troca {i}: velho vazio")
        trocas.append(
            Troca(
                arquivo=base / item["arquivo"],
                velho=item["velho"],
                novo=item["novo"],
                todas=bool(item.get("todas", False)),
            )
        )
    return trocas


def aplica(trocas: list[Troca]) -> dict[Path, int]:
    """Aplica todas as trocas ou nenhuma.

    As trocas de um mesmo arquivo rodam em ordem, cada uma sobre o resultado da anterior.
    Nada é gravado se alguma falhar.

    Returns:
        Quantas substituições cada arquivo recebeu.

    Raises:
        TrocaRecusada: Arquivo ausente, ou `velho` que não aparece exatamente uma vez
            (ou nenhuma, com `todas`).
    """
    conteudos: dict[Path, str] = {}
    contagem: dict[Path, int] = {}
    erros = []
    for i, troca in enumerate(trocas):
        if troca.arquivo not in conteudos:
            if not troca.arquivo.is_file():
                erros.append(f"troca {i}: {troca.arquivo} não existe")
                continue
            conteudos[troca.arquivo] = troca.arquivo.read_text(encoding="utf-8")
            contagem[troca.arquivo] = 0
        texto = conteudos[troca.arquivo]
        vezes = texto.count(troca.velho)
        if vezes == 0 or (vezes > 1 and not troca.todas):
            erros.append(
                f"troca {i}: {troca.arquivo} tem {vezes} ocorrências de {troca.velho[:60]!r}"
            )
            continue
        conteudos[troca.arquivo] = texto.replace(troca.velho, troca.novo)
        contagem[troca.arquivo] += vezes
    if erros:
        raise TrocaRecusada("\n".join(erros))
    for arquivo, texto in conteudos.items():
        arquivo.write_text(texto, encoding="utf-8")
    return contagem


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Aplica trocas de texto em lote: todas ou nenhuma.",
    )
    parser.add_argument("json", help="arquivo com a lista de trocas, ou - para stdin")
    parser.add_argument(
        "--base",
        type=Path,
        default=Path.cwd(),
        help="diretório contra o qual `arquivo` relativo é resolvido (padrão: o atual)",
    )
    args = parser.parse_args(argv)
    texto = sys.stdin.read() if args.json == "-" else Path(args.json).read_text(encoding="utf-8")
    try:
        contagem = aplica(le_trocas(texto, args.base))
    except TrocaRecusada as erro:
        print(f"nada gravado.\n{erro}", file=sys.stderr)
        return 1
    for arquivo, vezes in contagem.items():
        print(f"{vezes:3d}  {arquivo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
