"""Hlídání přechodných HTTP 401. Bez importu homeassistant.*.

Golemio může na platný klíč přechodně odpovědět 401 (pozorováno při souběžně běžící mapě a dalších dotazech
se stejným klíčem). Okamžitý reauth by pak zbytečně vyzval uživatele k novému zadání klíče. Reauth se proto
spustí až tehdy, když 401 trvá nepřetržitě déle než `grace` — jakýkoli úspěšný dotaz počítadlo vynuluje.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuthFailureTracker:
    """Od kdy (pro daný záznam) trvá nepřetržitá série 401."""

    def __init__(
        self,
        grace: timedelta,
        now: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._grace = grace
        self._now = now
        self._since: dict[str, datetime] = {}

    def failed(self, key: str) -> bool:
        """Zaznamená 401. Vrátí `True`, pokud série trvá déle než `grace` (tj. klíč je nejspíš neplatný)."""
        now = self._now()
        since = self._since.setdefault(key, now)
        return now - since >= self._grace

    def ok(self, key: str) -> None:
        """Úspěšný dotaz — série 401 skončila."""
        self._since.pop(key, None)

    def since(self, key: str) -> datetime | None:
        return self._since.get(key)
