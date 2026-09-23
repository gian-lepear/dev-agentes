import ipaddress
import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest

VARIAVEL_LOCAIS = "SEM_REDE_LOCAIS"
NOMES_LOCAIS = frozenset({"localhost"})
TENTATIVAS: list[str] = []


class RedeExternaError(ConnectionRefusedError):
    pass


def _extras() -> tuple[frozenset[str], tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]]:
    nomes, redes = set(), []
    for item in os.environ.get(VARIAVEL_LOCAIS, "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            redes.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            nomes.add(item)
    return frozenset(nomes), tuple(redes)


def _local(host: object) -> bool:
    if isinstance(host, bytes):
        host = host.decode()
    nomes, redes = _extras()
    if not isinstance(host, str) or host in NOMES_LOCAIS or host in nomes:
        return True
    try:
        endereco = ipaddress.ip_address(host.split("%")[0])
    except ValueError:
        return False
    return endereco.is_loopback or any(endereco in rede for rede in redes)


def _recusa(destino: object) -> RedeExternaError:
    TENTATIVAS.append(str(destino))
    return RedeExternaError(f"teste tentou falar com {destino}, fora da máquina")


@pytest.fixture(autouse=True, scope="session")
def _sem_rede_externa() -> Iterator[None]:
    conecta = socket.socket.connect
    conecta_ex = socket.socket.connect_ex
    resolve = socket.getaddrinfo

    def _confere(sock: socket.socket, endereco: Any) -> None:
        rede = sock.family in (socket.AF_INET, socket.AF_INET6)
        if rede and isinstance(endereco, tuple) and not _local(endereco[0]):
            raise _recusa(endereco[0])

    def _conecta(sock: socket.socket, endereco: Any) -> None:
        _confere(sock, endereco)
        return conecta(sock, endereco)

    def _conecta_ex(sock: socket.socket, endereco: Any) -> int:
        _confere(sock, endereco)
        return conecta_ex(sock, endereco)

    def _resolve(host: Any, *args: Any, **kwargs: Any) -> list:
        if host is not None and not _local(host):
            TENTATIVAS.append(str(host))
            raise socket.gaierror(socket.EAI_NONAME, f"teste tentou resolver {host}")
        return resolve(host, *args, **kwargs)

    with pytest.MonkeyPatch.context() as troca:
        troca.setattr(socket.socket, "connect", _conecta)
        troca.setattr(socket.socket, "connect_ex", _conecta_ex)
        troca.setattr(socket, "getaddrinfo", _resolve)
        yield


@pytest.fixture(autouse=True)
def _nenhuma_tentativa_de_rede() -> Iterator[None]:
    TENTATIVAS.clear()
    yield
    assert TENTATIVAS == [], f"o teste tentou sair da máquina: {sorted(set(TENTATIVAS))}"
