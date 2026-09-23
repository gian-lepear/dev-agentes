import pronto
import push_pronto
import pytest
from conftest import commita, git


@pytest.fixture
def confere(tmp_path):
    marca = tmp_path / "rodou"

    def _confere(entrada: str = "") -> bool:
        marca.unlink(missing_ok=True)
        assert push_pronto.main(["--", "touch", str(marca)], entrada=entrada) == 0
        return marca.exists()

    return _confere


def _pronto(repo) -> None:
    assert pronto.grava_selo(repo, pronto.arvore_do_disco(repo))


def test_arvore_que_passou_no_portao_pula_os_testes(repo, confere, capsys):
    _pronto(repo)

    assert not confere()
    assert "já passou" in capsys.readouterr().out


def test_sem_selo_roda_os_testes(repo, confere):
    assert confere()


def test_commit_depois_do_portao_roda_os_testes(repo, confere):
    _pronto(repo)
    commita(repo, "b.py", "b = 2\n")

    assert confere()


def test_mudanca_fora_do_commit_roda_os_testes(repo, confere):
    _pronto(repo)
    (repo / "a.py").write_text("a = 3\n", encoding="utf-8")

    assert confere()


def test_arquivo_novo_fora_do_commit_roda_os_testes(repo, confere):
    _pronto(repo)
    (repo / "novo.py").write_text("n = 1\n", encoding="utf-8")

    assert confere()


def test_portao_com_mudanca_pendente_vale_depois_do_commit_dela(repo, confere):
    (repo / "a.py").write_text("a = 4\n", encoding="utf-8")
    _pronto(repo)
    git(repo, "commit", "-qam", "a")

    assert not confere()


def test_ref_empurrada_diferente_do_disco_roda_os_testes(repo, confere, monkeypatch):
    anterior = git(repo, "rev-parse", "HEAD")
    commita(repo, "b.py", "b = 2\n")
    _pronto(repo)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", anterior)

    assert confere()


def test_linhas_do_hook_pre_push_sao_conferidas(repo, confere):
    anterior = git(repo, "rev-parse", "HEAD")
    commita(repo, "b.py", "b = 2\n")
    _pronto(repo)
    atual = git(repo, "rev-parse", "HEAD")
    zero = "0" * 40

    assert not confere(f"refs/heads/main {atual} refs/heads/main {anterior}\n")
    assert confere(f"refs/heads/velho {anterior} refs/heads/velho {zero}\n")


def test_push_que_so_apaga_ref_nao_roda_nada(repo, confere):
    zero = "0" * 40

    assert not confere(f"(delete) {zero} refs/heads/x {'1' * 40}\n")


def test_disco_que_mudou_durante_o_portao_nao_grava_selo(repo):
    testada = pronto.arvore_do_disco(repo)
    (repo / "a.py").write_text("a = 5\n", encoding="utf-8")

    assert not pronto.grava_selo(repo, testada)
    assert not (repo / pronto.SELO).exists()


def test_arvore_do_disco_nao_mexe_no_indice(repo):
    (repo / "novo.py").write_text("n = 1\n", encoding="utf-8")
    pronto.arvore_do_disco(repo)

    assert git(repo, "status", "--porcelain") == "?? novo.py"


def test_selo_fora_do_gitignore_nao_muda_a_arvore(repo, confere):
    (repo / ".gitignore").write_text("", encoding="utf-8")
    git(repo, "commit", "-qam", "sem ignore")
    _pronto(repo)

    assert not confere()


def test_codigo_de_saida_do_comando_e_o_do_hook(repo):
    assert push_pronto.main(["--", "false"], entrada="") == 1


def test_sem_comando_e_erro(repo):
    with pytest.raises(SystemExit):
        push_pronto.main([], entrada="")
