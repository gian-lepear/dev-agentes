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


def test_requisicao_sem_token_custa_zero_em_qualquer_modelo():
    assert mede_agente.custo_usd("<synthetic>", _uso(entrada=0, lido=0, saida=0)) == 0.0


def test_preco_vale_o_prefixo_mais_longo():
    um_milhao = _uso(entrada=1_000_000, lido=1_000_000, saida=0)

    # Opus 5: 5 de entrada e leitura a 0,1x. Opus 5.5: 4 de entrada e leitura a 0,05x.
    assert mede_agente.custo_usd("claude-opus-5", um_milhao) == pytest.approx(5 + 0.5)
    assert mede_agente.custo_usd("claude-opus-5-5", um_milhao) == pytest.approx(4 + 0.2)
    assert mede_agente.custo_usd("claude-fable-5-2", um_milhao) == pytest.approx(10 + 0.25)


def test_escrita_de_cache_de_uma_hora_conta_o_dobro():
    uso = _uso(entrada=0, lido=0, criado=1_000_000, saida=0)

    assert mede_agente.custo_usd("claude-sonnet-5-5", uso) == pytest.approx(2 * 1.25)
    uso["cache_creation"] = {
        "ephemeral_1h_input_tokens": 600_000,
        "ephemeral_5m_input_tokens": 400_000,
    }
    assert mede_agente.custo_usd("claude-sonnet-5-5", uso) == pytest.approx(
        0.6 * 2 * 2 + 0.4 * 2 * 1.25
    )


def _em_fundo(ts, id_, tarefa):
    evento = _resultado(ts, id_, f"Command running in background with ID: {tarefa}. Output in x")
    evento["toolUseResult"] = {"stdout": "", "backgroundTaskId": tarefa}
    return evento


def _notificacao(ts, tarefa):
    return {
        "type": "queue-operation",
        "operation": "enqueue",
        "timestamp": ts,
        "content": f"<task-notification>\n<task-id>{tarefa}</task-id>\n<status>completed</status>",
    }


@pytest.fixture
def com_segundo_plano(tmp_path):
    fundo = {"command": "just test", "run_in_background": True}
    eventos = [
        {"type": "user", "timestamp": "2026-01-01T10:00:00Z", "message": {"content": "tarefa"}},
        _assistente(
            "2026-01-01T10:00:10Z",
            "r1",
            [
                {"type": "tool_use", "id": "t1", "name": "Bash", "input": fundo},
                {
                    "type": "tool_use",
                    "id": "t2",
                    "name": "Bash",
                    "input": fundo | {"command": "just carregar"},
                },
            ],
        ),
        _em_fundo("2026-01-01T10:00:11Z", "t1", "b1"),
        _em_fundo("2026-01-01T10:00:11Z", "t2", "b2"),
        _assistente("2026-01-01T10:00:20Z", "r2", [_bash("t3", "git status")]),
        _resultado("2026-01-01T10:00:21Z", "t3"),
        _notificacao("2026-01-01T10:06:10Z", "b1"),
        # A mesma notificação volta em eventos seguintes (anexo, cópia do pedido): só a primeira conta.
        _notificacao("2026-01-01T10:09:00Z", "b1"),
        _assistente("2026-01-01T10:09:10Z", "r3", [{"type": "text", "text": "fim"}]),
    ]
    arquivo = tmp_path / "agent-fundo.jsonl"
    arquivo.write_text("\n".join(json.dumps(e) for e in eventos) + "\n", encoding="utf-8")
    return arquivo


def test_segundo_plano_conta_ate_a_notificacao_de_fim(com_segundo_plano):
    tempo = mede_agente.mede(com_segundo_plano)["tempo"]
    por_resumo = {c["resumo"]: c for c in tempo["chamadas"]}

    assert por_resumo["just test"]["segundos"] == 360
    assert por_resumo["just test"]["segundo_plano"] is True
    assert por_resumo["just test"]["categoria"] == "bash (outro)"
    assert por_resumo["git status"]["segundo_plano"] is False
    assert tempo["segundo_plano_s"] == 360
    assert tempo["ferramentas_s"] == 360 + 1


def test_segundo_plano_sem_notificacao_fica_pendurado(com_segundo_plano, capsys):
    achadas = mede_agente.penduradas([mede_agente.mede(com_segundo_plano)], 0.9)

    assert [(c["resumo"], c["segundos"], c["segundo_plano"]) for _, c in achadas] == [
        ("just carregar", None, True)
    ]
    assert mede_agente.main([str(com_segundo_plano)]) == 0
    saida = capsys.readouterr().out
    assert "2º plano sem fim" in saida
    assert "[2º plano] just test" in saida


@pytest.fixture
def de_outro_modelo(transcript):
    arquivo = transcript.with_name("agent-outro.jsonl")
    arquivo.write_text(transcript.read_text().replace("claude-opus-5", "modelo-novo-9"))
    return arquivo


def test_modelo_sem_preco_avisa_e_nao_soma_zero(de_outro_modelo, capsys):
    assert mede_agente.main([str(de_outro_modelo), "--json"]) == 0

    capturado = capsys.readouterr()
    (medida,) = json.loads(capturado.out)
    assert medida["custo_usd"] is None
    assert medida["sem_preco"] == {"modelo-novo-9": 3}
    assert "sem preço para `modelo-novo-9` (3 requisições)" in capturado.err
    assert "--preco 'modelo-novo-9=ENTRADA,SAIDA'" in capturado.err


def test_preco_pela_linha_de_comando_e_pelo_arquivo(de_outro_modelo, tmp_path, monkeypatch, capsys):
    assert mede_agente.main([str(de_outro_modelo), "--json", "--preco", "modelo-novo=5,25"]) == 0
    capturado = capsys.readouterr()
    pela_linha = json.loads(capturado.out)[0]["custo_usd"]
    assert pela_linha == mede_agente.mede(de_outro_modelo.with_name("agent-abc.jsonl"))["custo_usd"]
    assert capturado.err == ""

    precos = tmp_path / "precos.json"
    precos.write_text(json.dumps({"modelo-novo": [10, 50, 0.1]}))
    monkeypatch.setenv("MEDE_AGENTE_PRECOS", str(precos))
    assert mede_agente.main([str(de_outro_modelo), "--json"]) == 0
    # O dobro do preço dá o dobro do custo, a menos do arredondamento de 4 casas da saída.
    do_arquivo = json.loads(capsys.readouterr().out)[0]["custo_usd"]
    assert do_arquivo == pytest.approx(2 * pela_linha, abs=2e-4)
    # A linha de comando passa por cima do arquivo.
    assert mede_agente.main([str(de_outro_modelo), "--json", "--preco", "modelo-novo=5,25"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["custo_usd"] == pela_linha


def test_preco_assumido_avisa_de_onde_veio(transcript, capsys):
    do_fable = transcript.with_name("agent-fable.jsonl")
    do_fable.write_text(transcript.read_text().replace("claude-opus-5", "claude-fable-5-2"))

    assert mede_agente.main([str(do_fable), "--json"]) == 0
    capturado = capsys.readouterr()
    assert json.loads(capturado.out)[0]["custo_usd"] > 0
    assert "preço de `claude-fable-5-2` assumido igual a o do Fable 5.1" in capturado.err
    assert (
        mede_agente.main([str(do_fable), "--json", "--preco", "claude-fable-5-2=10,50,0.025"]) == 0
    )
    assert "assumido" in capsys.readouterr().err  # mesmo número da tabela: ainda é o assumido


def test_preco_mal_escrito_e_recusado():
    for ruim in ("sem-igual", "m=1", "m=a,b", "m=1,2,3,4", "m=-1,2"):
        with pytest.raises(SystemExit):
            mede_agente.main(["x.jsonl", "--preco", ruim])
