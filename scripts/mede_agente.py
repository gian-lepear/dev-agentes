import argparse
import collections
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

IMAGEM = (".png", ".jpg", ".jpeg", ".webp")
CHAVES_DE_USO = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
# US$ por MTok: (entrada, saída, fator da leitura de cache sobre a entrada). Vale o prefixo mais
# longo que casa com o id do modelo. `--preco` e o arquivo de MEDE_AGENTE_PRECOS passam por cima.
type Preco = tuple[float, float, float]
LEITURA_DE_CACHE = 0.1
PRECO_POR_MTOK: dict[str, Preco] = {
    "claude-fable-5-2": (10.0, 50.0, 0.025),
    "claude-fable-5-1": (10.0, 50.0, 0.025),
    "claude-fable-5": (10.0, 50.0, LEITURA_DE_CACHE),
    "claude-opus-5-5": (4.0, 20.0, 0.05),
    "claude-opus-5": (5.0, 25.0, LEITURA_DE_CACHE),
    "claude-sonnet-5": (2.0, 10.0, LEITURA_DE_CACHE),
    "claude-haiku-5-5": (0.1, 0.5, LEITURA_DE_CACHE),
    "claude-haiku-4-5": (1.0, 5.0, LEITURA_DE_CACHE),
}
# Preço que não veio de tabela publicada: o custo sai, com aviso de onde o número veio.
PRECO_ASSUMIDO = {"claude-fable-5-2": "o do Fable 5.1"}
VARIAVEL_PRECOS = "MEDE_AGENTE_PRECOS"
ESCRITA_DE_CACHE = 1.25  # TTL de 5 minutos
ESCRITA_DE_CACHE_1H = 2.0
PRAZO_PADRAO_BASH_S = 120.0
EM_SEGUNDO_PLANO = re.compile(r"Command running in background with ID: (\w+)")
FIM_DE_TAREFA = re.compile(r"<task-id>([^<]+)</task-id>")

CATEGORIAS_DE_COMANDO: tuple[tuple[str, str], ...] = (
    (
        "portão",
        r"\bjust (pronto|check|ci)\b|pronto\.py|pre-commit run|\bmake (check|ci)\b|\btox\b|\bnox\b",
    ),
    (
        "testes",
        r"\bpytest\b|\b(npm|pnpm|yarn) (run )?test\b|\bvitest\b|\bjest\b|\bgo test\b|\bcargo test\b",
    ),
    ("lint/tipos", r"\bruff\b|\bmypy\b|\bpyright\b|\bpyrefly\b|\beslint\b|\btsc\b"),
    ("git", r"^\s*(cd [^;&]*(&&|;)\s*)?(git|gh)\b"),
    ("leitura", r"^\s*(cd [^;&]*(&&|;)\s*)?(grep|rg|sed -n|cat|head|tail|ls|find|wc|tree)\b"),
)
CATEGORIAS_DE_FERRAMENTA = {
    "Read": "leitura",
    "Grep": "leitura",
    "Glob": "leitura",
    "Edit": "edição",
    "MultiEdit": "edição",
    "Write": "edição",
    "NotebookEdit": "edição",
    "Agent": "subagente",
    "Task": "subagente",
}


@dataclass(frozen=True)
class Chamada:
    ferramenta: str
    categoria: str
    resumo: str
    segundos: float | None
    prazo_s: float | None
    segundo_plano: bool = False


def preco_de(modelo: str, precos: dict[str, Preco] | None = None) -> Preco | None:
    """O preço do prefixo mais longo que casa com o id do modelo, ou None."""
    tabela = PRECO_POR_MTOK if precos is None else precos
    casam = [prefixo for prefixo in tabela if modelo.startswith(prefixo)]
    return tabela[max(casam, key=len)] if casam else None


def custo_usd(modelo: str, uso: dict, precos: dict[str, Preco] | None = None) -> float | None:
    """Estima o custo de uma requisição pela tabela de preços, ou None sem preço para o modelo.

    A escrita de cache de 1 hora (`cache_creation.ephemeral_1h_input_tokens`) conta 2x a entrada;
    o resto da escrita, 1,25x. Requisição sem token nenhum custa zero em qualquer modelo.
    """
    criado = uso.get("cache_creation_input_tokens") or 0
    lido = uso.get("cache_read_input_tokens") or 0
    entrada_tokens = uso.get("input_tokens") or 0
    saida_tokens = uso.get("output_tokens") or 0
    if not (criado or lido or entrada_tokens or saida_tokens):
        return 0.0
    preco = preco_de(modelo, precos)
    if preco is None:
        return None
    entrada, saida, leitura = preco
    detalhe = uso.get("cache_creation")
    de_1h = (detalhe.get("ephemeral_1h_input_tokens") or 0) if isinstance(detalhe, dict) else 0
    de_1h = min(de_1h, criado)
    return (
        entrada_tokens * entrada
        + lido * entrada * leitura
        + (criado - de_1h) * entrada * ESCRITA_DE_CACHE
        + de_1h * entrada * ESCRITA_DE_CACHE_1H
        + saida_tokens * saida
    ) / 1_000_000


def categoriza(
    ferramenta: str, entrada: dict, regras: tuple[tuple[str, re.Pattern[str]], ...]
) -> str:
    """Dá a categoria de uma chamada: pelo comando, no Bash, e pelo nome, no resto."""
    if ferramenta == "Bash":
        comando = str(entrada.get("command", ""))
        return next((nome for nome, padrao in regras if padrao.search(comando)), "bash (outro)")
    return CATEGORIAS_DE_FERRAMENTA.get(ferramenta, ferramenta)


def _instante(texto: str) -> datetime | None:
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError:
        return None


def _prazo(ferramenta: str, entrada: dict) -> float | None:
    if ferramenta != "Bash" or entrada.get("run_in_background"):
        return None
    prazo_ms = entrada.get("timeout")
    return float(prazo_ms) / 1000 if isinstance(prazo_ms, int | float) else PRAZO_PADRAO_BASH_S


def _tarefa_de_fundo(evento: dict, bloco: dict) -> str | None:
    """O id da tarefa quando o resultado só avisa que o comando foi para o segundo plano."""
    resultado = evento.get("toolUseResult")
    if isinstance(resultado, dict) and resultado.get("backgroundTaskId"):
        return str(resultado["backgroundTaskId"])
    achado = EM_SEGUNDO_PLANO.search(json.dumps(bloco.get("content"), ensure_ascii=False))
    return achado.group(1) if achado else None


def mede(
    caminho: Path,
    regras: tuple[tuple[str, re.Pattern[str]], ...] | None = None,
    precos: dict[str, Preco] | None = None,
) -> dict:
    """Resume o transcript JSONL de um agente do Claude Code: tokens, ferramentas, imagens e tempo.

    O tempo de ferramenta vai do `tool_use` ao `tool_result`; o do modelo, de cada resultado
    (ou pedido) à última mensagem do assistente antes do próximo. Chamadas em paralelo se
    sobrepõem, então a soma das ferramentas pode passar do tempo de parede.

    Comando em segundo plano: o `tool_result` chega na hora, só com o id da tarefa. O tempo dele
    vai do `tool_use` até o primeiro evento com a notificação de fim (`<task-id>` da tarefa); sem
    notificação, fica sem resultado, como chamada pendurada.
    """
    regras = compila(CATEGORIAS_DE_COMANDO) if regras is None else regras
    em_fundo: dict[str, tuple[datetime | None, str, str, str]] = {}
    ultimo_por_requisicao: dict[str, tuple[str, dict]] = {}
    ferramentas: collections.Counter[str] = collections.Counter()
    bytes_por_ferramenta: collections.Counter[str] = collections.Counter()
    nome_por_id: dict[str, str] = {}
    abertas: dict[str, tuple[datetime | None, str, str, str, float | None]] = {}
    chamadas: list[Chamada] = []
    imagens = 0
    inicio = fim = ""
    modelo_s = 0.0
    espera_desde: datetime | None = None
    ultima_resposta: datetime | None = None
    for linha in caminho.open(encoding="utf-8"):
        try:
            evento = json.loads(linha)
        except ValueError:
            continue
        if not isinstance(evento, dict):
            continue
        instante = evento.get("timestamp", "")
        inicio = inicio or instante
        fim = instante or fim
        quando = _instante(instante) if instante else None
        if em_fundo and quando and "<task-id>" in linha:
            for tarefa in FIM_DE_TAREFA.findall(linha):
                if tarefa in em_fundo:
                    t0, nome, categoria, resumo = em_fundo.pop(tarefa)
                    segundos = (quando - t0).total_seconds() if t0 else None
                    chamadas.append(Chamada(nome, categoria, resumo, segundos, None, True))
        mensagem = evento.get("message") or {}
        conteudo = mensagem.get("content")
        if evento.get("type") == "assistant":
            ultima_resposta = quando or ultima_resposta
            if mensagem.get("usage"):
                ultimo_por_requisicao[evento.get("requestId", instante)] = (
                    str(mensagem.get("model", "")),
                    mensagem["usage"],
                )
            for bloco in conteudo if isinstance(conteudo, list) else []:
                if not isinstance(bloco, dict) or bloco.get("type") != "tool_use":
                    continue
                nome = bloco["name"]
                entrada = bloco.get("input") or {}
                ferramentas[nome] += 1
                nome_por_id[bloco["id"]] = nome
                alvo = str(entrada.get("file_path", ""))
                if nome == "Read" and alvo.lower().endswith(IMAGEM):
                    imagens += 1
                resumo = str(entrada.get("command") or entrada.get("file_path") or nome)
                abertas[bloco["id"]] = (
                    quando,
                    nome,
                    categoriza(nome, entrada, regras),
                    " ".join(resumo.split())[:110],
                    _prazo(nome, entrada),
                )
        elif evento.get("type") == "user":
            if espera_desde and ultima_resposta and ultima_resposta > espera_desde:
                modelo_s += (ultima_resposta - espera_desde).total_seconds()
            espera_desde = quando or espera_desde
            ultima_resposta = None
            for bloco in conteudo if isinstance(conteudo, list) else []:
                if not isinstance(bloco, dict) or bloco.get("type") != "tool_result":
                    continue
                id_ = bloco.get("tool_use_id", "")
                nome = nome_por_id.get(id_, "?")
                bytes_por_ferramenta[nome] += len(
                    json.dumps(bloco.get("content"), ensure_ascii=False)
                )
                if id_ in abertas:
                    t0, nome, categoria, resumo, prazo = abertas.pop(id_)
                    tarefa = _tarefa_de_fundo(evento, bloco) if nome == "Bash" else None
                    if tarefa:
                        em_fundo[tarefa] = (t0, nome, categoria, resumo)
                        continue
                    segundos = (quando - t0).total_seconds() if quando and t0 else None
                    chamadas.append(Chamada(nome, categoria, resumo, segundos, prazo))
    if espera_desde and ultima_resposta and ultima_resposta > espera_desde:
        modelo_s += (ultima_resposta - espera_desde).total_seconds()
    for _, nome, categoria, resumo, prazo in abertas.values():
        chamadas.append(Chamada(nome, categoria, resumo, None, prazo))
    for _, nome, categoria, resumo in em_fundo.values():
        chamadas.append(Chamada(nome, categoria, resumo, None, None, True))

    total: collections.Counter[str] = collections.Counter()
    contextos = []
    custos = []
    modelos: collections.Counter[str] = collections.Counter()
    sem_preco: collections.Counter[str] = collections.Counter()
    for modelo, uso in ultimo_por_requisicao.values():
        modelos[modelo] += 1
        custos.append(custo_usd(modelo, uso, precos))
        if custos[-1] is None:
            sem_preco[modelo] += 1
        for chave in CHAVES_DE_USO:
            total[chave] += uso.get(chave) or 0
        contextos.append(
            (uso.get("input_tokens") or 0)
            + (uso.get("cache_read_input_tokens") or 0)
            + (uso.get("cache_creation_input_tokens") or 0)
        )
    t_inicio, t_fim = _instante(inicio), _instante(fim)
    return {
        "transcript": str(caminho),
        "requisicoes": len(ultimo_por_requisicao),
        "entrada_total": sum(contextos),
        "contexto_max": max(contextos, default=0),
        "saida": total["output_tokens"],
        "cache_lido": total["cache_read_input_tokens"],
        "cache_criado": total["cache_creation_input_tokens"],
        "imagens_lidas": imagens,
        "custo_usd": None if None in custos else round(sum(c or 0 for c in custos), 4),
        # Só das requisições com preço: igual ao `custo_usd` quando nenhum modelo ficou de fora.
        "custo_parcial_usd": round(sum(c or 0 for c in custos), 4),
        "sem_preco": dict(sem_preco),
        "modelos": dict(modelos),
        "ferramentas": dict(ferramentas.most_common()),
        "bytes_de_resultado": dict(bytes_por_ferramenta.most_common()),
        "inicio": inicio,
        "fim": fim,
        "tempo": {
            "parede_s": round((t_fim - t_inicio).total_seconds(), 1) if t_inicio and t_fim else 0.0,
            "modelo_s": round(modelo_s, 1),
            "ferramentas_s": round(sum(c.segundos or 0 for c in chamadas), 1),
            "segundo_plano_s": round(sum(c.segundos or 0 for c in chamadas if c.segundo_plano), 1),
            "chamadas": [c.__dict__ for c in chamadas],
        },
    }


def compila(pares: tuple[tuple[str, str], ...]) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((nome, re.compile(padrao)) for nome, padrao in pares)


def por_categoria(medidas: list[dict]) -> list[tuple[str, float, int]]:
    """Soma o tempo de ferramenta por categoria em todos os transcripts, do maior ao menor."""
    segundos: collections.Counter[str] = collections.Counter()
    vezes: collections.Counter[str] = collections.Counter()
    for medida in medidas:
        for chamada in medida["tempo"]["chamadas"]:
            segundos[chamada["categoria"]] += chamada["segundos"] or 0
            vezes[chamada["categoria"]] += 1
    return [(nome, s, vezes[nome]) for nome, s in segundos.most_common()]


def penduradas(medidas: list[dict], limiar: float) -> list[tuple[str, dict]]:
    """Chamadas sem resultado, ou que chegaram a `limiar` do prazo do Bash."""
    achadas = []
    for medida in medidas:
        for chamada in medida["tempo"]["chamadas"]:
            segundos, prazo = chamada["segundos"], chamada["prazo_s"]
            if segundos is None or (prazo and segundos >= limiar * prazo):
                achadas.append((medida["transcript"], chamada))
    return achadas


def _nome(transcript: str, largura: int) -> str:
    return Path(transcript).stem.removeprefix("agent-")[-largura:]


def _min(segundos: float) -> str:
    return f"{segundos / 60:6.1f}"


def _imprime_tempo(medidas: list[dict], lentas: int, limiar: float) -> None:
    print("\nTEMPO POR AGENTE (min): parede, modelo, ferramentas e as 3 categorias maiores")
    for medida in medidas:
        tempo = medida["tempo"]
        top = por_categoria([medida])[:3]
        print(
            _nome(medida["transcript"], 28).ljust(28),
            _min(tempo["parede_s"]),
            _min(tempo["modelo_s"]),
            _min(tempo["ferramentas_s"]),
            "  " + ", ".join(f"{nome} {s / 60:.1f}" for nome, s, _ in top),
        )
    categorias = por_categoria(medidas)
    soma = sum(s for _, s, _ in categorias) or 1
    print("\nFERRAMENTAS POR CATEGORIA (soma de todos)")
    for nome, segundos, vezes in categorias:
        print(
            f"  {nome:14} {_min(segundos)} min  {100 * segundos / soma:5.1f}%"
            f"  {vezes:4d} chamadas  média {segundos / max(vezes, 1):5.0f}s"
        )
    todas = [
        (
            c["segundos"],
            _nome(m["transcript"], 20),
            ("[2º plano] " if c["segundo_plano"] else "") + c["resumo"],
        )
        for m in medidas
        for c in m["tempo"]["chamadas"]
        if c["segundos"] is not None
    ]
    if lentas:
        print("\nCHAMADAS MAIS LENTAS")
        for segundos, agente, resumo in sorted(todas, reverse=True)[:lentas]:
            print(f"  {_min(segundos)} min  {agente:20} {resumo}")
    achadas = penduradas(medidas, limiar)
    if achadas:
        print(f"\nPENDURADAS (sem resultado, ou a {limiar:.0%} do prazo)")
        for transcript, c in achadas:
            quanto = (
                ("2º plano sem fim" if c["segundo_plano"] else "sem resultado")
                if c["segundos"] is None
                else f"{c['segundos']:.0f}s de {c['prazo_s']:.0f}s"
            )
            print(f"  {quanto:18} {_nome(transcript, 20):20} {c['resumo']}")


def _transcripts(caminhos: list[Path]) -> list[Path]:
    saida = []
    for caminho in caminhos:
        if caminho.is_dir():
            saida += sorted(caminho.rglob("*.jsonl"))
        else:
            saida.append(caminho)
    return saida


def _categoria(texto: str) -> tuple[str, str]:
    nome, sep, padrao = texto.partition("=")
    if not sep or not nome or not padrao:
        raise argparse.ArgumentTypeError("use NOME=REGEX")
    try:
        re.compile(padrao)
    except re.error as erro:
        raise argparse.ArgumentTypeError(f"regex inválida: {erro}") from erro
    return nome, padrao


def _preco(texto: str) -> tuple[str, Preco]:
    modelo, sep, valores = texto.partition("=")
    try:
        numeros = [float(v) for v in valores.split(",")]
    except ValueError:
        numeros = []
    if not sep or not modelo or len(numeros) not in (2, 3) or min(numeros, default=-1) < 0:
        raise argparse.ArgumentTypeError(
            "use MODELO=ENTRADA,SAIDA[,FATOR_DA_LEITURA_DE_CACHE] em US$ por MTok"
        )
    leitura = numeros[2] if len(numeros) == 3 else LEITURA_DE_CACHE
    return modelo, (numeros[0], numeros[1], leitura)


def precos_do_arquivo(caminho: Path) -> dict[str, Preco]:
    """Lê `{"<prefixo do modelo>": [entrada, saída, fator da leitura de cache?]}` de um JSON."""
    lido = json.loads(caminho.read_text(encoding="utf-8"))
    if not isinstance(lido, dict):
        raise ValueError(f"{caminho}: esperava um objeto JSON de modelo para preço")
    return dict(
        _preco(f"{modelo}={','.join(str(v) for v in valores)}") for modelo, valores in lido.items()
    )


def _avisa_precos(medidas: list[dict], precos: dict[str, Preco]) -> None:
    sem: collections.Counter[str] = collections.Counter()
    assumidos = set()
    for medida in medidas:
        sem.update(medida["sem_preco"])
        for modelo in medida["modelos"]:
            casam = [p for p in precos if modelo.startswith(p)]
            prefixo = max(casam, key=len) if casam else ""
            if precos.get(prefixo) == PRECO_POR_MTOK.get(prefixo) and prefixo in PRECO_ASSUMIDO:
                assumidos.add((prefixo, PRECO_ASSUMIDO[prefixo]))
    for modelo, vezes in sem.most_common():
        print(
            f"aviso: sem preço para `{modelo}` ({vezes} requisições): o custo desses agentes fica "
            f"vazio e a soma, parcial. Passe --preco '{modelo}=ENTRADA,SAIDA' ou {VARIAVEL_PRECOS}.",
            file=sys.stderr,
        )
    for prefixo, origem in sorted(assumidos):
        print(
            f"aviso: preço de `{prefixo}` assumido igual a {origem}; confira e passe --preco "
            "se for outro.",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mede custo e tempo de agentes do Claude Code a partir dos transcripts JSONL "
            "(~/.claude/projects/<projeto>/<sessao>/subagents/agent-<id>.jsonl). "
            "Aceita pasta: lê todos os .jsonl dentro dela."
        )
    )
    parser.add_argument("transcripts", nargs="+", type=Path, help="arquivos .jsonl ou pastas")
    parser.add_argument("--json", action="store_true", help="saída em JSON em vez de tabela")
    parser.add_argument(
        "--categoria",
        action="append",
        type=_categoria,
        default=[],
        metavar="NOME=REGEX",
        help=(
            "categoria de comando Bash, testada antes das padrão (repita para várias). "
            "Ex.: --categoria 'navegador=-m navegador|playwright'"
        ),
    )
    parser.add_argument(
        "--so-categorias",
        action="store_true",
        help="usa só as categorias de --categoria, sem as padrão",
    )
    parser.add_argument(
        "--lentas", type=int, default=10, help="quantas chamadas mais lentas listar (padrão 10)"
    )
    parser.add_argument(
        "--limiar",
        type=float,
        default=0.9,
        help="fração do prazo do Bash a partir da qual a chamada conta como pendurada (0.9)",
    )
    parser.add_argument("--sem-tempo", action="store_true", help="só a tabela de custo")
    parser.add_argument(
        "--preco",
        action="append",
        type=_preco,
        default=[],
        metavar="MODELO=ENTRADA,SAIDA[,LEITURA]",
        help=(
            "preço em US$ por MTok para os modelos cujo id começa com MODELO (repita para "
            "vários); LEITURA é o fator da leitura de cache sobre a entrada (padrão 0.1). Passa "
            f"por cima da tabela do script e do arquivo JSON de {VARIAVEL_PRECOS}. "
            "Ex.: --preco claude-fable-5-2=10,50,0.025"
        ),
    )
    args = parser.parse_args(argv)
    pares = tuple(args.categoria) + (() if args.so_categorias else CATEGORIAS_DE_COMANDO)
    regras = compila(pares)
    precos = dict(PRECO_POR_MTOK)
    if arquivo := os.environ.get(VARIAVEL_PRECOS):
        try:
            precos.update(precos_do_arquivo(Path(arquivo)))
        except (OSError, ValueError, argparse.ArgumentTypeError) as erro:
            parser.error(f"{VARIAVEL_PRECOS}={arquivo}: {erro}")
    precos.update(args.preco)
    medidas = [mede(caminho, regras, precos) for caminho in _transcripts(args.transcripts)]
    _avisa_precos(medidas, precos)
    if args.json:
        print(json.dumps(medidas, ensure_ascii=False, indent=1))
        return 0
    colunas = (
        "requisicoes",
        "entrada_total",
        "contexto_max",
        "saida",
        "imagens_lidas",
        "custo_usd",
    )
    print("transcript".ljust(28), *(c.rjust(14) for c in colunas))
    for medida in medidas:
        nome = _nome(medida["transcript"], 28)
        print(nome.ljust(28), *(str(medida[c]).rjust(14) for c in colunas))
    if not args.sem_tempo:
        _imprime_tempo(medidas, args.lentas, args.limiar)
    return 0


if __name__ == "__main__":
    sys.exit(main())
