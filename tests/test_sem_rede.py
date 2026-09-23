pytest_plugins = ["pytester"]

PLUGIN = "sem_rede"


def _roda(pytester, codigo):
    pytester.makepyfile(test_x=codigo)
    return pytester.runpytest_subprocess("-p", PLUGIN, "-q")


def test_conexao_externa_falha_mesmo_engolida(pytester, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(__import__("conftest").SCRIPTS))
    resultado = _roda(
        pytester,
        """
import socket

def test_engole():
    try:
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    except OSError:
        pass
""",
    )
    resultado.assert_outcomes(passed=1, errors=1)
    resultado.stdout.fnmatch_lines(["*tentou sair da máquina*192.0.2.1*"])


def test_resolver_nome_externo_falha(pytester, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(__import__("conftest").SCRIPTS))
    resultado = _roda(
        pytester,
        """
import socket
import pytest

def test_resolve():
    with pytest.raises(socket.gaierror):
        socket.getaddrinfo("exemplo.invalid", 443)
""",
    )
    resultado.assert_outcomes(passed=1, errors=1)


def test_loopback_e_local_extra_passam(pytester, monkeypatch):
    monkeypatch.setenv("PYTHONPATH", str(__import__("conftest").SCRIPTS))
    monkeypatch.setenv("SEM_REDE_LOCAIS", "banco-local,10.99.0.0/16")
    resultado = _roda(
        pytester,
        """
import socket
import sem_rede

def test_locais():
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen()
    cliente = socket.create_connection(servidor.getsockname(), timeout=1)
    cliente.close()
    servidor.close()
    assert sem_rede._local("banco-local")
    assert sem_rede._local("10.99.3.4")
    assert not sem_rede._local("10.98.0.1")
""",
    )
    resultado.assert_outcomes(passed=1)
