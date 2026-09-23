import sys

import mutacao_ast
import pytest

REGRA = "def pode(idade, socio):\n    return idade >= 18 and not socio\n"


@pytest.fixture
def projeto(tmp_path):
    (tmp_path / "regra.py").write_text(REGRA, encoding="utf-8")
    (tmp_path / "test_regra.py").write_text(
        "from regra import pode\n\n\ndef test_adulto():\n    assert pode(30, False)\n\n\n"
        "def test_menor():\n    assert not pode(10, False)\n",
        encoding="utf-8",
    )
    return tmp_path


def test_pontos_seguem_a_ordem_da_arvore():
    marcas = [p.marca for p in mutacao_ast.pontos(REGRA)]

    assert marcas == ["L2: And -> Or", "L2: comparador GtE -> Gt", "L2: remove `not`"]


def test_cada_mutante_troca_so_um_ponto():
    assert "idade > 18 and (not socio)" in mutacao_ast.mutante(REGRA, 1)
    assert "idade >= 18 and socio" in mutacao_ast.mutante(REGRA, 2)


def test_lista_o_sobrevivente_e_restaura_o_arquivo(projeto, capsys):
    original = (projeto / "regra.py").read_bytes()
    argv = [
        "--raiz",
        str(projeto),
        "--alvo",
        "regra.py=test_regra.py",
        "--pytest",
        f"{sys.executable} -m pytest",
    ]

    assert mutacao_ast.main(argv) == 1

    saida = capsys.readouterr().out
    assert "LACUNA  L2: comparador GtE -> Gt" in saida
    assert "1 lacuna(s), 0 equivalente(s) de 3" in saida
    assert (projeto / "regra.py").read_bytes() == original


def test_equivalente_registrado_nao_conta_como_lacuna(projeto, capsys):
    (projeto / ".mutacao.toml").write_text(
        '[alvos]\n"regra.py" = ["test_regra.py"]\n\n'
        '[equivalentes."regra.py"]\n"L2: comparador GtE -> Gt" = "fronteira fora do domínio"\n',
        encoding="utf-8",
    )

    assert (
        mutacao_ast.main(["--raiz", str(projeto), "--pytest", f"{sys.executable} -m pytest"]) == 0
    )
    assert "equiv.  L2: comparador GtE -> Gt: fronteira fora do domínio" in capsys.readouterr().out


def test_arquivo_volta_mesmo_com_interrupcao(tmp_path):
    alvo = tmp_path / "m.py"
    alvo.write_bytes(b"x = a and b  # comentario  some no unparse\n")

    def interrompe(_testes):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        mutacao_ast.muta(tmp_path, "m.py", ["t"], interrompe)

    assert alvo.read_bytes() == b"x = a and b  # comentario  some no unparse\n"


def test_pyproject_sem_secao_nao_e_config():
    assert mutacao_ast.le_config("[project]\nname = 'x'\n", "pyproject.toml") is None


@pytest.mark.parametrize(
    "texto", ["x = 1", '[alvos]\n"a.py" = "t.py"'], ids=["sem-alvos", "testes-nao-lista"]
)
def test_config_fora_do_formato_e_recusada(texto):
    with pytest.raises(mutacao_ast.ConfigInvalida):
        mutacao_ast.le_config(texto, ".mutacao.toml")


def test_arquivo_fora_da_config_e_recusado(projeto, capsys):
    assert mutacao_ast.main(["--raiz", str(projeto), "--alvo", "regra.py=t.py", "outro.py"]) == 2
    assert "fora da config" in capsys.readouterr().err
