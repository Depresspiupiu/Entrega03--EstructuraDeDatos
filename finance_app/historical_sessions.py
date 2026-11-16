import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Mapping


class HistoricalSessionError(RuntimeError):
    """Raised when a saved historical simulation cannot be used."""


class HistoricalSessionStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS historical_sessions (
                        name TEXT PRIMARY KEY,
                        updated_at TEXT NOT NULL DEFAULT (
                            strftime('%Y-%m-%d %H:%M:%S', 'now')
                        ),
                        state TEXT NOT NULL
                    )
                    """
                )

    @staticmethod
    def _name(value: str) -> str:
        name = value.strip()
        if not name or len(name) > 80:
            raise HistoricalSessionError(
                "El nombre de sesión debe tener entre 1 y 80 caracteres."
            )
        return name

    def save(self, name: str, state: Mapping[str, object]) -> None:
        session_name = self._name(name)
        try:
            payload = json.dumps(state, allow_nan=False, separators=(",", ":"))
        except (TypeError, ValueError) as exc:
            raise HistoricalSessionError(
                "No se pudo serializar el estado de la sesión."
            ) from exc
        with closing(sqlite3.connect(self.database_path, timeout=10)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO historical_sessions (name, state)
                    VALUES (?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        updated_at = strftime('%Y-%m-%d %H:%M:%S', 'now'),
                        state = excluded.state
                    """,
                    (session_name, payload),
                )

    def list_sessions(self) -> list[tuple[str, str]]:
        with closing(sqlite3.connect(self.database_path, timeout=10)) as connection:
            rows = connection.execute(
                """
                SELECT name, updated_at
                FROM historical_sessions
                ORDER BY updated_at DESC, name COLLATE NOCASE
                """
            ).fetchall()
        return [(str(name), str(updated_at)) for name, updated_at in rows]

    def load(self, name: str) -> dict[str, object]:
        session_name = self._name(name)
        with closing(sqlite3.connect(self.database_path, timeout=10)) as connection:
            row = connection.execute(
                "SELECT state FROM historical_sessions WHERE name = ?",
                (session_name,),
            ).fetchone()
        if row is None:
            raise HistoricalSessionError(
                f"No existe una sesión guardada llamada «{session_name}»."
            )
        try:
            state = json.loads(row[0])
        except json.JSONDecodeError as exc:
            raise HistoricalSessionError(
                f"El estado guardado de «{session_name}» no es válido."
            ) from exc
        if not isinstance(state, dict):
            raise HistoricalSessionError(
                f"El estado guardado de «{session_name}» no es válido."
            )
        return state
