"""Cola local de ventas y mesas pausadas. SQLite almacena temporalmente los datos."""

from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from src.gsheets import append_rows

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pos_queue.db"
SALES_SHEET = "Ventas"
_SYNC_LOCK = threading.Lock()

def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection

def init_queue() -> None:
    with _get_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_venta TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                synced_at TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS local_open_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mesa TEXT NOT NULL,
                empleado TEXT NOT NULL,
                carrito_json TEXT NOT NULL
            )
            """
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_pending_sales_synced ON pending_sales(synced_at)")
        connection.commit()

# --- FUNCIONES DE VENTAS ---
def enqueue_sale(filas: list[list[Any]], id_venta: str, created_at: str) -> bool:
    if not id_venta: raise ValueError("id_venta es obligatorio.")
    if not filas: raise ValueError("La venta debe contener al menos una fila.")
    init_queue()
    payload = json.dumps(filas, ensure_ascii=False, separators=(",", ":"))
    try:
        with _get_connection() as connection:
            connection.execute(
                "INSERT INTO pending_sales (id_venta, payload_json, created_at) VALUES (?, ?, ?)",
                (id_venta, payload, created_at),
            )
            connection.commit()
        return True
    except sqlite3.IntegrityError:
        return False

def pending_sales_count() -> int:
    init_queue()
    with _get_connection() as connection:
        result = connection.execute("SELECT COUNT(*) FROM pending_sales WHERE synced_at IS NULL").fetchone()
    return int(result[0])

def sync_pending_sales(batch_size: int = 25) -> int:
    if batch_size <= 0: raise ValueError("batch_size debe ser mayor que cero.")
    if not _SYNC_LOCK.acquire(blocking=False): return 0
    try:
        init_queue()
        with _get_connection() as connection:
            rows = connection.execute(
                "SELECT id, id_venta, payload_json FROM pending_sales WHERE synced_at IS NULL ORDER BY id ASC LIMIT ?",
                (batch_size,),
            ).fetchall()
        if not rows: return 0
        synced = 0
        for row in rows:
            queue_id = row["id"]
            try:
                filas = json.loads(row["payload_json"])
                if not isinstance(filas, list): raise ValueError("payload_json inválido.")
                append_rows(SALES_SHEET, filas)
                with _get_connection() as connection:
                    connection.execute("UPDATE pending_sales SET synced_at = CURRENT_TIMESTAMP, last_error = NULL WHERE id = ?", (queue_id,))
                    connection.commit()
                synced += 1
            except Exception as exc:
                with _get_connection() as connection:
                    connection.execute("UPDATE pending_sales SET attempts = attempts + 1, last_error = ? WHERE id = ?", (str(exc), queue_id))
                    connection.commit()
        return synced
    finally:
        _SYNC_LOCK.release()

def start_background_sync(interval_seconds: int = 10) -> threading.Thread:
    if interval_seconds < 2: interval_seconds = 2
    init_queue()
    def _worker() -> None:
        while True:
            try:
                sync_pending_sales(batch_size=25)
            except Exception:
                pass
            time.sleep(interval_seconds)
    thread = threading.Thread(target=_worker, name="producto1-sales-sync", daemon=True)
    thread.start()
    return thread

# --- FUNCIONES DE MESAS PAUSADAS LOCALES ---
def create_local_open_account(mesa: str, empleado: str, carrito_json: str) -> int:
    if not mesa: raise ValueError("mesa es obligatoria.")
    if not empleado: raise ValueError("empleado es obligatorio.")
    init_queue()
    with _get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO local_open_accounts (mesa, empleado, carrito_json) VALUES (?, ?, ?)",
            (str(mesa).strip(), str(empleado).strip(), carrito_json)
        )
        connection.commit()
        return int(cursor.lastrowid)

def get_local_open_accounts() -> list[dict[str, Any]]:
    init_queue()
    with _get_connection() as connection:
        rows = connection.execute("SELECT id, mesa, empleado, carrito_json FROM local_open_accounts ORDER BY id ASC").fetchall()
    accounts = []
    for row in rows:
        accounts.append({
            "id": int(row["id"]),
            "mesa": row["mesa"],
            "empleado": row["empleado"],
            "carrito_json": row["carrito_json"] 
        })
    return accounts

def update_local_open_account(account_id: int, mesa: str, empleado: str, carrito_json: str) -> bool:
    if not account_id: raise ValueError("account_id es obligatorio.")
    if not mesa: raise ValueError("mesa es obligatoria.")
    if not empleado: raise ValueError("empleado es obligatorio.")
    init_queue()
    with _get_connection() as connection:
        cursor = connection.execute(
            "UPDATE local_open_accounts SET mesa = ?, empleado = ?, carrito_json = ? WHERE id = ?",
            (str(mesa).strip(), str(empleado).strip(), carrito_json, int(account_id))
        )
        connection.commit()
        return cursor.rowcount > 0

def delete_local_open_account(account_id: int) -> bool:
    if not account_id: raise ValueError("account_id es obligatorio.")
    init_queue()
    with _get_connection() as connection:
        cursor = connection.execute("DELETE FROM local_open_accounts WHERE id = ?", (int(account_id),))
        connection.commit()
        return cursor.rowcount > 0