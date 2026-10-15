"""In-memory record store persisted to CSV files (one ``<table>.csv`` per model).

The CSV files in the data folder are the only storage. On start they are loaded into memory;
after every unit of work the tables it changed are written back (atomic file replace).

Concurrency: the app runs on one asyncio event loop, so code between two ``await``s never
interleaves with other code. Every store operation is synchronous, so a check-then-write such
as "claim the oldest queued run" or "decide only if still pending at version N" is atomic as
long as there is no ``await`` between the check and the write. Repositories and services keep
it that way. Unique rules (one active run per policy, one open recommendation per lifecycle
event, one approval per recommendation, ...) are enforced by ``add``.

One process owns a data folder: stop the API before editing CSVs or running the seed / reset
scripts.
"""

from __future__ import annotations

import asyncio
import csv
import dataclasses
import json
import os
import types
import typing
from collections.abc import AsyncIterator, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, ClassVar, TypeVar

from backend.utils.clock import utcnow
from backend.utils.logging import get_logger

log = get_logger(__name__)

R = TypeVar("R", bound="Record")


class IntegrityError(Exception):
    """A unique rule would be broken (the write did not happen)."""


class Record:
    """Base for every stored model (models are ``@dataclass(kw_only=True)`` subclasses).

    ``__table__`` names the CSV file, ``__pk__`` the primary-key field, ``__unique__`` lists
    unique field groups and ``unique_scope`` narrows a rule to some rows (a partial index).
    Attribute writes on a stored record mark its table for saving.
    """

    __table__: ClassVar[str]
    __pk__: ClassVar[str] = "id"
    __unique__: ClassVar[tuple[tuple[str, ...], ...]] = ()
    # False = kept in memory while the app runs, never written to a CSV file.
    __persist__: ClassVar[bool] = True

    def unique_scope(self, fields: tuple[str, ...]) -> bool:
        """Whether this row takes part in the unique rule on ``fields`` (default: always)."""
        return True

    def __setattr__(self, key: str, value: Any) -> None:
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError(f"{key}: naive datetime not allowed; use utils.clock.utcnow()")
        object.__setattr__(self, key, value)
        store: Store | None = self.__dict__.get("_store")
        if store is not None and not key.startswith("_"):
            if key != "updated_at" and "updated_at" in self.__dict__:
                object.__setattr__(self, "updated_at", utcnow())
            store.mark(self.__table__)

    @property
    def pk(self) -> Any:
        return getattr(self, self.__pk__)


# ------------------------------------------------------------------- CSV cells ---


def _field_types(model: type[Record]) -> dict[str, Any]:
    hints = typing.get_type_hints(model)
    return {f.name: hints[f.name] for f in dataclasses.fields(model)}  # type: ignore[arg-type]


def _base(tp: Any) -> tuple[Any, bool]:
    """(underlying type, nullable) for ``X | None`` style hints."""
    if isinstance(tp, types.UnionType) or typing.get_origin(tp) is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        return args[0], True
    return tp, False


def to_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, dict | list):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def from_cell(tp: Any, cell: str) -> Any:
    base, nullable = _base(tp)
    origin = typing.get_origin(base) or base
    if cell == "":
        if nullable:
            return None
        if origin in (dict, list):
            return origin()
        if base is str:
            return ""
        raise ValueError("empty value for a required field")
    if origin in (dict, list):
        return json.loads(cell)
    if base is bool:
        return cell.strip().lower() in ("true", "1", "yes")
    if base is int:
        return int(cell)
    if base is float:
        return float(cell)
    if base is datetime:
        dt = datetime.fromisoformat(cell)
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    if base is date:
        return date.fromisoformat(cell)
    return cell


# ----------------------------------------------------------------------- store ---


class Store:
    def __init__(self, data_dir: Path | str | None, models: Iterable[type[Record]]) -> None:
        """``data_dir`` holds the CSV files; ``None`` = memory only (tests)."""
        self.data_dir = Path(data_dir).resolve() if data_dir is not None else None
        self.models = list(models)
        self.tables: dict[type[Record], dict[Any, Record]] = {m: {} for m in self.models}
        self._by_name = {m.__table__: m for m in self.models}
        self._dirty: set[str] = set()
        self._save_lock = asyncio.Lock()
        self._loaded = False

    @property
    def location(self) -> str:
        return str(self.data_dir) if self.data_dir else "(in memory, not persisted)"

    # ------------------------------------------------------------- lifecycle ---

    async def create_all(self) -> None:
        """Load the CSV files (once per process)."""
        if self._loaded:
            return
        self._loaded = True
        if self.data_dir is None or not self.data_dir.exists():
            return
        counts = {}
        for model in self.models:
            path = self.data_dir / f"{model.__table__}.csv"
            if model.__persist__ and path.exists():
                counts[model.__table__] = self._load(model, path)
        self._dirty.clear()
        log.info("store.loaded", data_dir=str(self.data_dir), rows=counts)

    def _load(self, model: type[Record], path: Path) -> int:
        ftypes = _field_types(model)
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            unknown = set(reader.fieldnames or []) - set(ftypes)
            if unknown:
                raise ValueError(f"{path.name}: unknown columns {sorted(unknown)}")
            n = 0
            for line, raw in enumerate(reader, start=2):
                try:
                    values = {k: from_cell(ftypes[k], v or "") for k, v in raw.items()}
                except ValueError as e:
                    raise ValueError(f"{path.name} line {line}: {e}") from e
                self.insert(model(**values))
                n += 1
        return n

    @asynccontextmanager
    async def session(self) -> AsyncIterator[DbSession]:
        """One unit of work. On error, rows added in it are removed again (field changes
        already made to existing rows stay). On success, changed tables are saved."""
        s = DbSession(self)
        try:
            yield s
        except BaseException:
            s.rollback()
            raise
        await self.save()

    def mark(self, table: str) -> None:
        if self._by_name[table].__persist__:
            self._dirty.add(table)

    async def save(self, tables: Iterable[str] | None = None) -> None:
        """Write changed tables (or ``tables``) to CSV. A failed write (e.g. the file is open
        in Excel on Windows) is retried on the next save; the caller never fails over it."""
        if self.data_dir is None:
            self._dirty.clear()
            return
        async with self._save_lock:
            todo = set(tables) if tables is not None else set(self._dirty)
            todo = {t for t in todo if self._by_name[t].__persist__}
            self._dirty -= todo
            failed = set()
            for name in sorted(todo):
                try:
                    self._dump(self._by_name[name])
                except OSError:
                    failed.add(name)
                    log.exception("store.csv_write_failed", table=name)
            self._dirty |= failed

    def _dump(self, model: type[Record]) -> None:
        assert self.data_dir is not None
        self.data_dir.mkdir(parents=True, exist_ok=True)
        names = [f.name for f in dataclasses.fields(model)]  # type: ignore[arg-type]
        path = self.data_dir / f"{model.__table__}.csv"
        tmp = path.with_suffix(".csv.tmp")
        with tmp.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(names)
            for row in sorted(self.tables[model].values(), key=_sort_key):
                w.writerow([to_cell(getattr(row, n)) for n in names])
        os.replace(tmp, path)

    async def dispose(self) -> None:
        await self.save()

    # ----------------------------------------------------------------- access ---

    def insert(self, obj: Record) -> None:
        model = type(obj)
        table = self.tables[model]
        if obj.__pk__ == "id" and getattr(obj, "id", 0) is None:  # autoincrement
            object.__setattr__(obj, "id", max(table, default=0) + 1)
        if obj.pk in table:
            raise IntegrityError(f"{model.__table__}: duplicate key {obj.pk!r}")
        for fields in model.__unique__:
            if not obj.unique_scope(fields):
                continue
            key = tuple(getattr(obj, f) for f in fields)
            if None in key:
                continue
            for other in table.values():
                if other.unique_scope(fields) and tuple(getattr(other, f) for f in fields) == key:
                    dup = dict(zip(fields, key, strict=True))
                    raise IntegrityError(f"{model.__table__}: duplicate {dup}")
        table[obj.pk] = obj
        object.__setattr__(obj, "_store", self)
        self.mark(model.__table__)

    def remove(self, obj: Record) -> None:
        if self.tables[type(obj)].pop(obj.pk, None) is not None:
            object.__setattr__(obj, "_store", None)
            self.mark(obj.__table__)


def _sort_key(row: Record) -> Any:
    pk = row.pk
    return (0, pk, "") if isinstance(pk, int) else (1, 0, str(pk))


class DbSession:
    """Handle for one unit of work. All methods are synchronous apart from ``get`` and
    ``flush`` (kept async for call-site symmetry; they never suspend)."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._added: list[Record] = []

    async def get(self, model: type[R], pk: Any) -> R | None:
        return self.store.tables[model].get(pk)  # type: ignore[return-value]

    def all(self, model: type[R]) -> list[R]:
        return list(self.store.tables[model].values())  # type: ignore[arg-type]

    def where(self, model: type[R], pred: Callable[[R], bool]) -> list[R]:
        return [r for r in self.store.tables[model].values() if pred(r)]  # type: ignore[arg-type]

    def add(self, obj: Record) -> None:
        self.store.insert(obj)
        self._added.append(obj)

    def add_all(self, objs: Iterable[Record]) -> None:
        for o in objs:
            self.add(o)

    def delete(self, obj: Record) -> None:
        self.store.remove(obj)

    async def flush(self) -> None:
        return None

    def rollback(self) -> None:
        for obj in reversed(self._added):
            self.store.remove(obj)
        self._added.clear()
