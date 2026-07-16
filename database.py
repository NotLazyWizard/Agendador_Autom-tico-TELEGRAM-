"""Módulo de persistencia SQLite del proyecto.

Este módulo implementa:
- modelos de datos del dominio de notas
- Repository Pattern
- creación automática de la base de datos SQLite
- creación automática de tablas
- CRUD completo
- búsqueda por fecha
- búsqueda por texto
- últimas notas
- estadísticas

No contiene lógica de Telegram ni reglas de interacción con el usuario.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol


def _utc_now() -> datetime:
    """Devuelve la fecha y hora actual en UTC con zona horaria explícita."""

    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    """Convierte un datetime a formato ISO 8601 normalizado a UTC."""

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _from_iso(value: str) -> datetime:
    """Convierte un valor ISO 8601 en datetime con información de zona horaria."""

    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Note:
    """Representa una nota persistida en SQLite."""

    id: int
    title: str
    content: str
    created_at: datetime
    updated_at: datetime
    source: str = "telegram"
    source_message_id: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class NoteCreate:
    """Datos necesarios para crear una nota nueva."""

    title: str
    content: str
    source: str = "telegram"
    source_message_id: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class NoteUpdate:
    """Datos opcionales para actualizar una nota existente."""

    title: str | None = None
    content: str | None = None
    source: str | None = None
    source_message_id: str | None = None
    tags: tuple[str, ...] | None = None


@dataclass(frozen=True)
class NoteFilter:
    """Filtros reutilizables para búsquedas y listados."""

    start_date: date | None = None
    end_date: date | None = None
    text: str | None = None
    limit: int | None = None


@dataclass(frozen=True)
class NoteStatistics:
    """Consolida estadísticas de notas almacenadas."""

    total_notes: int
    notes_today: int
    notes_last_7_days: int
    notes_last_30_days: int
    average_content_length: float
    first_note_at: datetime | None
    last_note_at: datetime | None


class NoteRepository(Protocol):
    """Contrato del repositorio de notas."""

    def create(self, note: NoteCreate) -> Note:
        """Persiste una nota nueva y devuelve la entidad creada."""

    def get_by_id(self, note_id: int) -> Note | None:
        """Busca una nota por su identificador."""

    def update(self, note_id: int, changes: NoteUpdate) -> Note | None:
        """Actualiza una nota existente y devuelve la entidad final o None."""

    def delete(self, note_id: int) -> bool:
        """Elimina una nota por identificador y devuelve si fue encontrada."""

    def list_all(self, limit: int | None = None) -> list[Note]:
        """Lista todas las notas ordenadas por fecha descendente."""

    def search_by_text(self, text: str, limit: int | None = None) -> list[Note]:
        """Busca notas por coincidencia textual en título, contenido o etiquetas."""

    def search_by_date(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> list[Note]:
        """Busca notas dentro de un rango de fechas inclusivo."""

    def latest_notes(self, limit: int = 10) -> list[Note]:
        """Obtiene las notas más recientes."""

    def statistics(self) -> NoteStatistics:
        """Calcula estadísticas agregadas de la base de datos."""


class SQLiteDatabase:
    """Gestiona la creación automática y las conexiones SQLite del proyecto."""

    def __init__(self, database_path: str | Path | None = None) -> None:
        """Inicializa la base de datos y asegura el esquema mínimo."""

        self._database_path = Path(database_path or Path("database") / "app.db").expanduser().resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_schema()

    @property
    def path(self) -> Path:
        """Devuelve la ruta física del archivo SQLite."""

        return self._database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Abre una conexión SQLite configurada para el proyecto."""

        connection = sqlite3.connect(self._database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        """Crea automáticamente la base de datos y las tablas requeridas."""

        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'telegram',
                    source_message_id TEXT,
                    tags TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notes_created_at
                ON notes(created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notes_title
                ON notes(title)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notes_content
                ON notes(content)
                """
            )


def _serialize_tags(tags: Iterable[str]) -> str:
    """Serializa etiquetas a un formato JSON simple almacenado como texto."""

    import json

    return json.dumps([tag.strip() for tag in tags if tag and tag.strip()], ensure_ascii=False)


def _deserialize_tags(value: str | None) -> tuple[str, ...]:
    """Deserializa las etiquetas almacenadas en la base de datos."""

    if not value:
        return ()

    import json

    raw = json.loads(value)
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if str(item).strip())


def _row_to_note(row: sqlite3.Row) -> Note:
    """Convierte una fila SQLite en una entidad Note."""

    return Note(
        id=int(row["id"]),
        title=str(row["title"]),
        content=str(row["content"]),
        source=str(row["source"]),
        source_message_id=row["source_message_id"],
        tags=_deserialize_tags(row["tags"]),
        created_at=_from_iso(str(row["created_at"])),
        updated_at=_from_iso(str(row["updated_at"])),
    )


class SQLiteNoteRepository(NoteRepository):
    """Implementación SQLite del repositorio de notas."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Recibe una base SQLite ya preparada para operar."""

        self._database = database

    def create(self, note: NoteCreate) -> Note:
        """Inserta una nueva nota y devuelve la entidad persistida."""

        now = _utc_now()
        with self._database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO notes (title, content, source, source_message_id, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    note.title.strip(),
                    note.content.strip(),
                    note.source.strip() or "telegram",
                    note.source_message_id,
                    _serialize_tags(note.tags),
                    _to_iso(now),
                    _to_iso(now),
                ),
            )
            created_id = int(cursor.lastrowid)
        return self.get_by_id(created_id) or self._raise_missing(created_id)

    def get_by_id(self, note_id: int) -> Note | None:
        """Busca una nota por su identificador."""

        with self._database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()
        return _row_to_note(row) if row is not None else None

    def update(self, note_id: int, changes: NoteUpdate) -> Note | None:
        """Actualiza una nota existente conservando los campos no informados."""

        current = self.get_by_id(note_id)
        if current is None:
            return None

        merged = replace(
            current,
            title=changes.title.strip() if changes.title is not None else current.title,
            content=changes.content.strip() if changes.content is not None else current.content,
            source=changes.source.strip() if changes.source is not None else current.source,
            source_message_id=changes.source_message_id if changes.source_message_id is not None else current.source_message_id,
            tags=changes.tags if changes.tags is not None else current.tags,
            updated_at=_utc_now(),
        )

        with self._database.connect() as connection:
            connection.execute(
                """
                UPDATE notes
                SET title = ?, content = ?, source = ?, source_message_id = ?, tags = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    merged.title,
                    merged.content,
                    merged.source,
                    merged.source_message_id,
                    _serialize_tags(merged.tags),
                    _to_iso(merged.updated_at),
                    note_id,
                ),
            )
        return self.get_by_id(note_id)

    def delete(self, note_id: int) -> bool:
        """Elimina físicamente una nota de la base de datos."""

        with self._database.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM notes WHERE id = ?",
                (note_id,),
            )
        return cursor.rowcount > 0

    def list_all(self, limit: int | None = None) -> list[Note]:
        """Lista todas las notas ordenadas por fecha descendente."""

        query = "SELECT * FROM notes ORDER BY created_at DESC, id DESC"
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,) 

        with self._database.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [_row_to_note(row) for row in rows]

    def search_by_text(self, text: str, limit: int | None = None) -> list[Note]:
        """Busca notas por coincidencia textual en título, contenido o etiquetas."""

        pattern = f"%{text.strip()}%"
        query = (
            "SELECT * FROM notes "
            "WHERE title LIKE ? COLLATE NOCASE OR content LIKE ? COLLATE NOCASE OR tags LIKE ? "
            "ORDER BY created_at DESC, id DESC"
        )
        params: list[Any] = [pattern, pattern, pattern]
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_row_to_note(row) for row in rows]

    def search_by_date(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int | None = None,
    ) -> list[Note]:
        """Busca notas dentro de un rango de fechas inclusivo."""

        conditions: list[str] = []
        params: list[Any] = []

        if start_date is not None:
            conditions.append("date(created_at) >= date(?)")
            params.append(start_date.isoformat())

        if end_date is not None:
            conditions.append("date(created_at) <= date(?)")
            params.append(end_date.isoformat())

        query = "SELECT * FROM notes"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC, id DESC"

        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
        return [_row_to_note(row) for row in rows]

    def latest_notes(self, limit: int = 10) -> list[Note]:
        """Obtiene las notas más recientes."""

        return self.list_all(limit=limit)

    def statistics(self) -> NoteStatistics:
        """Calcula estadísticas agregadas de las notas almacenadas."""

        now = _utc_now()
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        seven_days_start = today_start - timedelta(days=7)
        thirty_days_start = today_start - timedelta(days=30)
        now_iso = _to_iso(now)

        with self._database.connect() as connection:
            total_notes = int(connection.execute("SELECT COUNT(*) FROM notes").fetchone()[0])
            notes_today = int(
                connection.execute(
                    "SELECT COUNT(*) FROM notes WHERE created_at >= ? AND created_at <= ?",
                    (_to_iso(today_start), now_iso),
                ).fetchone()[0]
            )
            notes_last_7_days = int(
                connection.execute(
                    "SELECT COUNT(*) FROM notes WHERE created_at >= ? AND created_at <= ?",
                    (_to_iso(seven_days_start), now_iso),
                ).fetchone()[0]
            )
            notes_last_30_days = int(
                connection.execute(
                    "SELECT COUNT(*) FROM notes WHERE created_at >= ? AND created_at <= ?",
                    (_to_iso(thirty_days_start), now_iso),
                ).fetchone()[0]
            )
            average_content_length = float(
                connection.execute(
                    "SELECT COALESCE(AVG(LENGTH(content)), 0) FROM notes",
                ).fetchone()[0]
            )
            first_row = connection.execute(
                "SELECT MIN(created_at) AS created_at FROM notes",
            ).fetchone()
            last_row = connection.execute(
                "SELECT MAX(created_at) AS created_at FROM notes",
            ).fetchone()

        first_note_at = _from_iso(first_row[0]) if first_row and first_row[0] else None
        last_note_at = _from_iso(last_row[0]) if last_row and last_row[0] else None

        return NoteStatistics(
            total_notes=total_notes,
            notes_today=notes_today,
            notes_last_7_days=notes_last_7_days,
            notes_last_30_days=notes_last_30_days,
            average_content_length=average_content_length,
            first_note_at=first_note_at,
            last_note_at=last_note_at,
        )

    @staticmethod
    def _raise_missing(note_id: int) -> Note:
        """Helper defensivo para mantener tipos estrictos tras un insert exitoso."""

        raise RuntimeError(f"No fue posible recuperar la nota creada con id={note_id}")


def create_database(database_path: str | Path | None = None) -> SQLiteDatabase:
    """Crea y prepara automáticamente la base SQLite del proyecto."""

    return SQLiteDatabase(database_path=database_path)


def create_note_repository(database_path: str | Path | None = None) -> SQLiteNoteRepository:
    """Factory de conveniencia para obtener el repositorio SQLite listo para usar."""

    database = create_database(database_path)
    return SQLiteNoteRepository(database)


__all__ = [
    "Note",
    "NoteCreate",
    "NoteFilter",
    "NoteRepository",
    "NoteStatistics",
    "NoteUpdate",
    "SQLiteDatabase",
    "SQLiteNoteRepository",
    "create_database",
    "create_note_repository",
]
