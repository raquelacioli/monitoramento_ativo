"""Bounded, account-bound import previews for a single server process."""
import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

from monitoramento.bulletin_import import ExtractedBulletin

T = TypeVar("T")


@dataclass(frozen=True)
class PendingImport:
    owner_id: int
    competence: str
    unit: str
    content: bytes
    bulletin: ExtractedBulletin
    expires_at: float
    size: int


class PreviewStore:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic,
                 max_bytes: int = 40 * 1024 * 1024):
        self._clock = clock
        self._max_bytes = max_bytes
        self._items: dict[str, PendingImport] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = self._clock()
        self._items = {token: item for token, item in self._items.items()
                       if item.expires_at > now}

    def create(self, *, owner_id: int, competence: str, unit: str,
               content: bytes, bulletin: ExtractedBulletin) -> str:
        size = len(content) + len(json.dumps(bulletin.records, ensure_ascii=False).encode("utf-8"))
        with self._lock:
            self._purge()
            owned = [token for token, item in self._items.items() if item.owner_id == owner_id]
            if len(owned) >= 2:
                raise ValueError("Conclua uma das duas prévias pendentes ou aguarde sua expiração.")
            if len(self._items) >= 50 or sum(item.size for item in self._items.values()) + size > self._max_bytes:
                raise ValueError("Limite de prévias em memória atingido. Conclua uma importação ou tente mais tarde.")
            token = secrets.token_urlsafe(32)
            self._items[token] = PendingImport(owner_id, competence, unit, content, bulletin,
                                               self._clock() + 600, size)
            return token

    def _get(self, token: str, owner_id: int) -> PendingImport:
        self._purge()
        item = self._items.get(token)
        if item is None or item.owner_id != owner_id:
            raise ValueError("Prévia inválida ou expirada. Envie o boletim novamente.")
        return item

    def get(self, token: str, *, owner_id: int) -> PendingImport:
        with self._lock:
            return self._get(token, owner_id)

    def consume(self, token: str, *, owner_id: int, importer: Callable[[PendingImport], T]) -> T:
        with self._lock:
            item = self._get(token, owner_id)
            result = importer(item)
            del self._items[token]
            return result


preview_store = PreviewStore()
