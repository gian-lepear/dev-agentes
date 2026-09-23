import json

import pytest
import troca


def _json(tmp_path, trocas):
    arquivo = tmp_path / "trocas.json"
    arquivo.write_text(json.dumps(trocas), encoding="utf-8")
    return str(arquivo)


def test_aplica_todas_as_trocas_em_varios_arquivos(tmp_path, capsys):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 2\ny = 2\n", encoding="utf-8")
    trocas = [
        {"arquivo": "a.py", "velho": "x = 1", "novo": "x = 10"},
        {"arquivo": "b.py", "velho": "y = 2", "novo": "y = 3", "todas": True},
    ]

    assert troca.main([_json(tmp_path, trocas), "--base", str(tmp_path)]) == 0
    assert (tmp_path / "a.py").read_text() == "x = 10\n"
    assert (tmp_path / "b.py").read_text() == "y = 3\ny = 3\n"
    assert "  2  " in capsys.readouterr().out


def test_trocas_do_mesmo_arquivo_rodam_em_ordem(tmp_path):
    (tmp_path / "a.py").write_text("um\n", encoding="utf-8")
    trocas = [
        troca.Troca(tmp_path / "a.py", "um", "dois"),
        troca.Troca(tmp_path / "a.py", "dois", "tres"),
    ]

    assert troca.aplica(trocas) == {tmp_path / "a.py": 2}
    assert (tmp_path / "a.py").read_text() == "tres\n"


@pytest.mark.parametrize(
    ("conteudo", "velho"),
    [("nada aqui\n", "ausente"), ("dup dup\n", "dup")],
    ids=["ausente", "ambiguo"],
)
def test_uma_troca_recusada_nao_grava_nenhuma(tmp_path, capsys, conteudo, velho):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(conteudo, encoding="utf-8")
    trocas = [
        {"arquivo": "a.py", "velho": "x = 1", "novo": "x = 2"},
        {"arquivo": "b.py", "velho": velho, "novo": "z"},
    ]

    assert troca.main([_json(tmp_path, trocas), "--base", str(tmp_path)]) == 1
    assert (tmp_path / "a.py").read_text() == "x = 1\n"
    assert "nada gravado" in capsys.readouterr().err


def test_arquivo_ausente_e_recusado(tmp_path):
    with pytest.raises(troca.TrocaRecusada, match="não existe"):
        troca.aplica([troca.Troca(tmp_path / "x.py", "a", "b")])


@pytest.mark.parametrize(
    "texto",
    [
        "{",
        "[]",
        '{"arquivo": "a"}',
        '[{"arquivo": "a", "velho": "", "novo": "b"}]',
        '[{"arquivo": "a"}]',
    ],
)
def test_json_fora_do_formato_e_recusado(tmp_path, texto):
    with pytest.raises(troca.TrocaRecusada):
        troca.le_trocas(texto, tmp_path)
