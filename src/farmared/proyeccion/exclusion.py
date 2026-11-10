"""Exclusión local entre procesos con bloqueo del sistema operativo."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path

from farmared.errores import CodigoError, ErrorDominio


@contextmanager
def exclusion(lock_path):
    """Bloquea sin esperar; no borrar/reemplazar el archivo durante su uso.

    Protege procesos que abren el mismo archivo, no hosts con archivos distintos.
    El SO libera el bloqueo al cerrar o terminar el proceso, incluso tras caída.
    """
    try:
        nombre = os.fspath(lock_path)
        if not isinstance(nombre, str) or not nombre.strip():
            raise ValueError('ruta vacía')
        ruta = Path(nombre).resolve()
        if ruta.is_dir():
            raise ValueError('se requiere un archivo')
    except (TypeError, ValueError):
        raise ErrorDominio(CodigoError.VALIDACION, 'lock_path debe ser una ruta de archivo.') from None
    with ruta.open('a+b') as archivo:
        if os.fstat(archivo.fileno()).st_size == 0:
            archivo.write(b'\0')
            archivo.flush()
        archivo.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(archivo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise ErrorDominio(CodigoError.SYNC_EN_CURSO,
                                   'Ya hay una sincronización usando este lock compartido.') from None
            raise
        try:
            yield
        finally:
            archivo.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(archivo.fileno(), fcntl.LOCK_UN)
