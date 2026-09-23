import mesmo_ast
from conftest import commita, git


def test_so_docstring_comentario_e_nome_de_teste_e_igual():
    antes = 'def f(x):\n    """doc."""\n    return x + 1\n\n\ndef test_a():\n    assert f(1) == 2\n'
    depois = "def f(x):\n    # comentário\n    return x + 1\n\n\ndef test_soma():\n    assert f(1) == 2\n"

    resultado = mesmo_ast.compara("tests/test_f.py", antes, depois)

    assert resultado.igual
    assert resultado.renomeados == [("test_a", "test_soma")]


def test_mudanca_de_codigo_aponta_a_linha():
    resultado = mesmo_ast.compara(
        "m.py", "def f(x):\n    return x + 1\n", "def f(x):\n    return x + 2\n"
    )

    assert not resultado.igual
    assert "linha 2" in resultado.diferenca


def test_nome_de_teste_fora_de_arquivo_de_teste_conta_como_codigo():
    resultado = mesmo_ast.compara("m.py", "def test_a():\n    pass\n", "def test_b():\n    pass\n")

    assert not resultado.igual


def test_renomear_para_nome_que_ja_existe_acusa_duplicado():
    antes = "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"
    depois = "def test_b():\n    pass\n\n\ndef test_b():\n    pass\n"

    assert mesmo_ast.compara("test_x.py", antes, depois).duplicados == ["test_b"]


def test_referencia_orfa_ignora_registro_datado_e_quem_ainda_define():
    ocorrencias = [
        "docs/guia.md:3:rode test_velho",
        "docs/notas-2026-01-02.md:1:test_velho",
        "tests/test_y.py:4:def test_velho():",
    ]
    fontes = {"tests/test_y.py": "def test_velho():\n    pass\n"}

    orfas = mesmo_ast.referencias_orfas({"test_velho"}, ocorrencias, fontes.__getitem__)

    assert orfas == ["docs/guia.md:3:rode test_velho  (test_velho)"]


def test_registro_configuravel():
    orfas = mesmo_ast.referencias_orfas(
        {"test_velho"}, ["pesquisa/x.md:1:test_velho"], lambda _: "", registro=r"^pesquisa/"
    )

    assert orfas == []


def test_main_contra_ref_do_git(repo, capsys):
    commita(repo, "tests/test_m.py", "def test_a():\n    assert 1\n")
    (repo / "tests/test_m.py").write_text('def test_b():\n    """x."""\n    assert 1\n')
    (repo / "guia.md").write_text("rode test_a\n")
    git(repo, "add", "guia.md")

    assert mesmo_ast.main(["--ref", "main"]) == 1
    saida = capsys.readouterr().out
    assert "RENOMEIA tests/test_m.py: test_a -> test_b" in saida
    assert "REFERÊNCIA guia.md:1:rode test_a" in saida


def test_main_passa_quando_so_texto_mudou(repo, capsys):
    commita(repo, "m.py", "def f():\n    return 1\n")
    (repo / "m.py").write_text('def f():\n    """Um."""\n    return 1\n')

    assert mesmo_ast.main(["--ref", "main"]) == 0
    assert "1 arquivos conferidos" in capsys.readouterr().out
