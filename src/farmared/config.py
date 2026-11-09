
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from farmared.errores import CodigoError, ErrorDominio


@dataclass(frozen=True)
class Config:
    mongo_uri: str = field(default="mongodb://localhost:27017/?replicaSet=rs0", repr=False)
    mongo_db: str = "farmared"
    neo4j_uri: str = field(default="bolt://localhost:7687", repr=False)
    neo4j_user: str = "neo4j"
    neo4j_password: str | None = field(default=None, repr=False)
    db_timeout_ms: int = 10000

    def __post_init__(self) -> None:
        for nombre in ("mongo_uri", "mongo_db", "neo4j_uri", "neo4j_user"):
            valor = getattr(self, nombre)
            if not isinstance(valor, str) or not valor.strip():
                raise ErrorDominio(CodigoError.VALIDACION, f"{nombre} no puede estar vacío.")
        if any(c in self.mongo_db for c in '/\\. "$*<>:|?\x00'):
            raise ErrorDominio(CodigoError.VALIDACION, "MONGO_DB contiene caracteres inválidos.")
        if type(self.db_timeout_ms) is not int or not 1 <= self.db_timeout_ms <= 300000:
            raise ErrorDominio(CodigoError.VALIDACION, "DB_TIMEOUT_MS debe estar entre 1 y 300000.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        """Lee solo las claves documentadas. No modifica os.environ ni lee .env."""
        env = os.environ if environ is None else environ
        valores = {
            campo: env[clave]
            for campo, clave in {
                "mongo_uri": "MONGO_URI", "mongo_db": "MONGO_DB",
                "neo4j_uri": "NEO4J_URI", "neo4j_user": "NEO4J_USER",
                "neo4j_password": "NEO4J_PASSWORD",
            }.items()
            if clave in env
        }
        try:
            timeout = int(env.get("DB_TIMEOUT_MS", "10000"))
        except ValueError:
            raise ErrorDominio(CodigoError.VALIDACION, "DB_TIMEOUT_MS debe ser un entero.") from None
        return cls(**valores, db_timeout_ms=timeout)
