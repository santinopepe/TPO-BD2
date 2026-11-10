
import os
import secrets
from pathlib import Path


def preparar_env(raiz: Path) -> bool:
    contenido = (raiz / ".env.example").read_text(encoding="utf-8")
    contenido = contenido.replace("NEO4J_PASSWORD=\n", f"NEO4J_PASSWORD={secrets.token_urlsafe(24)}\n")
    try:
        fd = os.open(raiz / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as archivo:
        archivo.write(contenido)
    return True


def enlazar_env_compose(raiz: Path) -> None:
    """Dev Containers ejecuta Compose desde infra; mantener una única fuente."""
    enlace = raiz / "infra" / ".env"
    try:
        enlace.symlink_to("../.env")
    except FileExistsError:
        if not enlace.is_symlink() or enlace.resolve() != (raiz / ".env").resolve():
            raise RuntimeError("infra/.env existente no apunta al .env raíz; se conserva. Revisar configuración.")


if __name__ == "__main__":
    raiz = Path(__file__).resolve().parents[1]
    creado = preparar_env(raiz)
    enlazar_env_compose(raiz)
    print(".env creado con secreto local aleatorio." if creado else ".env existente conservado.")
