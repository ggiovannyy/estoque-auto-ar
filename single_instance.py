"""Um sistema aberto por pasta de dados.

No Windows, dois processos conseguem escutar na mesma porta: com o início automático e dois cliques no
iniciar.bat, os pedidos se dividiam entre os dois. Pior, numa atualização a versão nova migraria o banco com a
antiga ainda rodando. A trava é do sistema operacional e se solta sozinha quando o processo termina.
"""
import os

LOCK_FILE = "sistema.lock"


def lock_data_dir(data_dir):
    """Trava a pasta de dados para este processo. Devolve o arquivo da trava (mantenha-o aberto enquanto o sistema
    roda) ou None se outro processo já a travou."""
    os.makedirs(data_dir, exist_ok=True)
    lock = open(os.path.join(data_dir, LOCK_FILE), "a+")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return None
    return lock
