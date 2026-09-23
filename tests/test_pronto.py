import sys

import pronto
import pytest
from conftest import commita

PY = sys.executable


def test_passos_que_passam_gravam_o_selo(repo, capsys):
    assert pronto.main([f"{PY} -c 'print(1)'", "true"]) == 0

    saida = capsys.readouterr().out
    assert saida.count("ok ") == 2
    assert "selo gravado" in saida
    selo = (repo / pronto.SELO).read_text().strip()
    assert selo == pronto.arvore_do_disco(repo)


def test_falha_mostra_so_a_cauda_do_passo_que_falhou(repo, capsys):
    ruidoso = f"{PY} -c \"print('\\n'.join(map(str, range(100)))); raise SystemExit(3)\""

    assert pronto.main(["true", ruidoso, "--linhas", "3"]) == 1

    saida = capsys.readouterr().out
    assert "FALHOU" in saida
    assert "97\n98\n99\n" in saida
    assert "\n96\n" not in saida
    assert not (repo / pronto.SELO).exists()


def test_roda_todos_os_passos_ou_para_no_primeiro(repo, capsys):
    assert pronto.main(["false", "echo segundo"]) == 1
    assert "ok " in capsys.readouterr().out

    assert pronto.main(["false", "echo segundo", "--para"]) == 1
    assert "ok " not in capsys.readouterr().out


def test_prazo_mata_o_passo_e_os_filhos(repo, capsys):
    assert pronto.main([f"{PY} -c 'import time; time.sleep(30)' & wait", "--prazo", "0.5"]) == 1
    assert "PRAZO" in capsys.readouterr().out


def test_disco_que_muda_durante_o_portao_nao_grava_selo(repo, capsys):
    assert pronto.main(["echo x >> a.py"]) == 0

    assert "selo não gravado" in capsys.readouterr().out
    assert not (repo / pronto.SELO).exists()


def test_passos_do_pronto_toml(repo, capsys):
    (repo / ".pronto.toml").write_text('passos = ["echo do-toml"]\nlinhas = 5\n')

    assert pronto.main([]) == 0
    assert "echo do-toml" in capsys.readouterr().out


def test_passos_do_pyproject(repo, capsys):
    commita(repo, "pyproject.toml", '[tool.pronto]\npassos = ["echo do-pyproject"]\n')

    assert pronto.main([]) == 0
    assert "echo do-pyproject" in capsys.readouterr().out


@pytest.mark.parametrize(
    "texto", ['passos = "um só"', "passos = []", "linhas = 3"], ids=["texto", "vazia", "ausente"]
)
def test_config_sem_lista_de_passos_e_recusada(texto):
    with pytest.raises(pronto.ConfigInvalida):
        pronto.le_config(texto, ".pronto.toml")


def test_sem_passos_e_erro(repo, capsys):
    assert pronto.main([]) == 2
    assert "nenhum passo" in capsys.readouterr().err


def test_fora_do_git_roda_sem_selo(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert pronto.main(["true"]) == 0
    assert "selo" not in capsys.readouterr().out
