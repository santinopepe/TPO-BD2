
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Protocol
from zoneinfo import ZoneInfo

ZONA_COMERCIAL = ZoneInfo("America/Argentina/Buenos_Aires")


class Clock(Protocol):
    def today(self) -> date:
        """Día comercial actual en Buenos Aires."""
        ...

    def now_utc(self) -> datetime:
        """Instante técnico actual, consciente de zona y expresado en UTC."""
        ...


class SystemClock:
    def today(self) -> date:
        return self.now_utc().astimezone(ZONA_COMERCIAL).date()

    def now_utc(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True)
class FixedClock:
    """Instante explícito de prueba; el día local se deriva del mismo instante."""

    instante: datetime

    def __post_init__(self) -> None:
        if self.instante.tzinfo is None or self.instante.utcoffset() is None:
            raise ValueError("FixedClock requiere un instante con zona horaria.")

    def today(self) -> date:
        return self.now_utc().astimezone(ZONA_COMERCIAL).date()

    def now_utc(self) -> datetime:
        return self.instante.astimezone(UTC)


def inicio_dia_utc(dia: date) -> datetime:
    """Día comercial → medianoche Buenos Aires → UTC, apto para BSON Date."""
    if not isinstance(dia, date) or isinstance(dia, datetime):
        raise TypeError("Se requiere date, sin hora.")
    return datetime.combine(dia, time.min, tzinfo=ZONA_COMERCIAL).astimezone(UTC)
