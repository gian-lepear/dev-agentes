import json

import mede_agente
import pytest


def _uso(entrada=10, lido=1000, criado=0, saida=50):
    return {
        "input_tokens": entrada,
        "cache_read_input_tokens": lido,
        "cache_creation_input_tokens": criado,
        "output_tokens": saida,
    }


def _assistente(ts, requisicao, blocos, uso=None):
    return {
        "type": "assistant",
        "timestamp": ts,
        "requestId": requisicao,
        "message": {"model": "claude-opus-5", "content": blocos, "usage": uso or _uso()},
    }


def _bash(id_, comando, timeout=None):
    entrada = {"command": comando}
    if timeout:
        entrada["timeout"] = timeout
    return {"type": "tool_use", "id": id_, "name": "Bash", "input": entrada}


def _resultado(ts, id_, texto="ok"):
    return {
        "type": "user",
        "timestamp": ts,
        "message": {"content": [{"type": "tool_result", "tool_use_id": id_, "content": texto}]},
    }


@pytest.fixture
def transcript(tmp_path):
    eventos = [
        {"type": "user", "timestamp": "2026-01-01T10:00:00Z", "message": {"content": "tarefa"}},
        _assistente("2026-01-01T10:00:20Z", "r1", [{"type": "thinking", "thinking": ""}]),
        _assistente(
            "2026-01-01T10:00:30Z",
            "r1",
            [_bash("t1", "cd x && uv run pytest tests -q", timeout=600000)],
            _uso(saida=80),
        ),
        _resultado("2026-01-01T10:05:30Z", "t1"),
        _assistente(
            "2026-01-01T10:05:40Z",
            "r2",
            [
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "Read",
                    "input": {"file_path": "/x/tela.png"},
                },
                _bash("t3", "git status", timeout=60000),
            ],
        ),
        _resultado("2026-01-01T10:05:41Z", "t2", "img"),
        _resultado("2026-01-01T10:06:40Z", "t3"),
        _assistente("2026-01-01T10:07:00Z", "r3", [_bash("t4", "just pronto")]),
    ]
    arquivo = tmp_path / "agent-abc.jsonl"
    arquivo.write_text("\n".join(json.dumps(e) for e in eventos) + "\nlixo\n", encoding="utf-8")
    return arquivo


def test_tokens_usam_o_ultimo_uso_de_cada_requisicao(transcript):
    medida = mede_agente.mede(transcript)

    assert medida["requisicoes"] == 3
    assert medida["saida"] == 80 + 50 + 50
    assert medida["imagens_lidas"] == 1
    assert medida["ferramentas"] == {"Bash": 3, "Read": 1}
    assert medida["custo_usd"] is not None


def test_tempo_por_ferramenta_modelo_e_parede(transcript):
    tempo = mede_agente.mede(transcript)["tempo"]
    por_id = {c["resumo"]: c for c in tempo["chamadas"]}

    assert tempo["parede_s"] == 420
    assert por_id["cd x && uv run pytest tests -q"]["segundos"] == 300
    assert por_id["cd x && uv run pytest tests -q"]["categoria"] == "testes"
    assert por_id["git status"]["categoria"] == "git"
    assert por_id["/x/tela.png"]["categoria"] == "leitura"
    assert tempo["modelo_s"] == 30 + 10 + 20


def test_chamada_sem_resultado_e_perto_do_prazo_sao_penduradas(transcript):
    achadas = mede_agente.penduradas([mede_agente.mede(transcript)], 0.9)

    resumos = {c["resumo"]: c["segundos"] for _, c in achadas}
    assert resumos == {"just pronto": None, "git status": 60.0}


def test_categoria_do_cli_vem_antes_das_padrao(transcript, capsys):
    assert mede_agente.main([str(transcript), "--categoria", "suite=pytest"]) == 0

    saida = capsys.readouterr().out
    assert "suite" in saida
    assert "PENDURADAS" in saida
    assert "CHAMADAS MAIS LENTAS" in saida


def test_so_categorias_descarta_as_padrao(transcript):
    regras = mede_agente.compila((("x", "nunca-casa"),))
    categorias = {c["categoria"] for c in mede_agente.mede(transcript, regras)["tempo"]["chamadas"]}

    assert categorias == {"bash (outro)", "leitura"}


def test_pasta_le_todos_os_transcripts_e_json(transcript, capsys):
    (transcript.parent / "sub").mkdir()
    (transcript.parent / "sub" / "agent-def.jsonl").write_text(transcript.read_text())

    assert mede_agente.main([str(transcript.parent), "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 2


def test_categoria_mal_escrita_e_recusada():
    with pytest.raises(SystemExit):
        mede_agente.main(["x.jsonl", "--categoria", "sem-igual"])


def test_modelo_sem_preco_nao_inventa_custo():
    assert mede_agente.custo_usd("outro-modelo", _uso()) is None
