import json
import sys

import muta
import pytest

PYTEST = f"{sys.executable} -m pytest"


@pytest.fixture
def projeto(tmp_path):
    (tmp_path / "regra.py").write_text("def maior(x):\n    return x >= 10\n", encoding="utf-8")
    (tmp_path / "test_regra.py").write_text(
        "from regra import maior\n\n\ndef test_limite():\n    assert maior(10)\n\n\n"
        "def test_longe():\n    assert maior(50)\n",
        encoding="utf-8",
    )
    return tmp_path


def _roda(projeto, mutacoes):
    arquivo = projeto / "mutacoes.json"
    arquivo.write_text(json.dumps(mutacoes), encoding="utf-8")
    return muta.main([str(arquivo), "--base", str(projeto), "--pytest", PYTEST])


def test_teste_que_pega_a_mutacao(projeto, capsys):
    original = (projeto / "regra.py").read_bytes()
    mutacao = {
        "teste": "test_regra.py::test_limite",
        "arquivo": "regra.py",
        "velho": ">=",
        "novo": ">",
    }

    assert _roda(projeto, [mutacao]) == 0
    assert "PEGA     test_regra.py::test_limite" in capsys.readouterr().out
    assert (projeto / "regra.py").read_bytes() == original


def test_teste_que_nao_pega_a_mutacao(projeto, capsys):
    mutacao = {
        "teste": "test_regra.py::test_longe",
        "arquivo": "regra.py",
        "velho": ">=",
        "novo": ">",
    }

    assert _roda(projeto, [mutacao]) == 1
    assert "passa mesmo com a mutação" in capsys.readouterr().out


def test_mutacao_ambigua_e_recusada(projeto, capsys):
    mutacao = {
        "teste": "test_regra.py::test_limite",
        "arquivo": "regra.py",
        "velho": "x",
        "novo": "y",
    }

    assert _roda(projeto, [mutacao]) == 1
    assert "RECUSADA" in capsys.readouterr().out


def test_arquivo_volta_mesmo_se_o_pytest_levanta(tmp_path):
    alvo = tmp_path / "m.py"
    alvo.write_bytes(b"x = 1\r\n")
    chamadas = []

    def roda(teste, base):
        chamadas.append(alvo.read_bytes())
        if len(chamadas) == 2:
            raise KeyboardInterrupt
        return True, ""

    with pytest.raises(KeyboardInterrupt):
        muta.confere(muta.Mutacao("t", alvo, "x = 1", "x = 2"), tmp_path, roda)

    assert chamadas[1] != b"x = 1\r\n"
    assert alvo.read_bytes() == b"x = 1\r\n"
