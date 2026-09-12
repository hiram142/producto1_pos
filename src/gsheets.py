"""Acceso a Google Sheets. Único módulo que conoce la persistencia."""

from __future__ import annotations

from typing import Any

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from sympy import python

from src.config import TTL_CATALOGO

# URLs limpias sin el error de formato Markdown de la IA
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource(show_spinner=False)
def get_client() -> gspread.Client:
    """Cliente autenticado. cache_resource: una sola sesión HTTP por proceso."""
    try:
        info = dict(st.secrets["gcp_service_account"])
    except KeyError as exc:
        raise RuntimeError(
            "Faltan los secrets [gcp_service_account]. "
            "Revisa .streamlit/secrets.toml en local o los Secrets de Streamlit Cloud."
        ) from exc

    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def get_worksheet(nombre: str) -> gspread.Worksheet:
    """Handle a una hoja concreta, cacheado para no reabrir el spreadsheet en cada rerun."""
    spreadsheet_id = st.secrets["app"]["spreadsheet_id"]
    return get_client().open_by_key(spreadsheet_id).worksheet(nombre)

@st.cache_data(ttl=TTL_CATALOGO, show_spinner=False)
def read_df(nombre: str) -> pd.DataFrame:
    """Lectura cacheada. Úsala para catálogo y empleados."""
    registros = get_worksheet(nombre).get_all_records()
    return pd.DataFrame(registros)

def read_df_live(nombre: str) -> pd.DataFrame:
    """Lectura SIN caché. Úsala solo en el dashboard del dueño."""
    registros = get_worksheet(nombre).get_all_records()
    return pd.DataFrame(registros)

def append_rows(nombre: str, filas: list[list[Any]]) -> None:
    """Escribe una o varias filas e invalida la caché de lectura."""
    get_worksheet(nombre).append_rows(filas, value_input_option="USER_ENTERED")
    read_df.clear()

def health_check() -> tuple[bool, str]:
    """Diagnóstico rápido de conexión para mostrar en el sidebar."""
    try:
        titulo = get_client().open_by_key(st.secrets["app"]["spreadsheet_id"]).title
        return True, titulo
    except Exception as exc:  # noqa: BLE001 - queremos el mensaje crudo en diagnóstico
        return False, str(exc)
    
import hashlib
import json
import uuid
from typing import Any

import pandas as pd


# ============================================================
# AUTENTICACIÓN DE EMPLEADOS
# ============================================================

def hash_pin(pin: str) -> str:
    """
    Genera el hash SHA-256 de un PIN.

    Nunca guardamos el PIN directamente en Google Sheets.
    """

    return hashlib.sha256(
        pin.strip().encode("utf-8")
    ).hexdigest()


def get_employees(spreadsheet) -> pd.DataFrame:
    """
    Obtiene todos los empleados desde la pestaña 'Empleados'.
    """

    worksheet = spreadsheet.worksheet("Empleados")

    records = worksheet.get_all_records()

    if not records:
        return pd.DataFrame(
            columns=[
                "id",
                "nombre",
                "pin_hash",
                "activo",
            ]
        )

    return pd.DataFrame(records)


def get_active_employees(spreadsheet) -> pd.DataFrame:
    """
    Obtiene únicamente empleados activos.
    """

    employees = get_employees(
        spreadsheet
    )

    if employees.empty:
        return employees

    required_columns = {
        "id",
        "nombre",
        "pin_hash",
        "activo",
    }

    missing = (
        required_columns
        - set(employees.columns)
    )

    if missing:
        raise ValueError(
            "Faltan columnas en 'Empleados': "
            f"{sorted(missing)}"
        )

    active_mask = (
        employees["activo"]
        .astype(str)
        .str.strip()
        .str.upper()
        .isin(
            {
                "TRUE",
                "1",
                "SI",
                "SÍ",
                "YES",
            }
        )
    )

    return employees.loc[
        active_mask
    ].copy()


def validate_employee_pin(
    spreadsheet,
    employee_name: str,
    pin: str,
) -> bool:
    """
    Valida el PIN de un empleado contra el hash
    almacenado en Google Sheets.

    Devuelve True únicamente si:
    - el empleado existe,
    - está activo,
    - y el PIN coincide.
    """

    if not pin:
        return False

    employees = get_active_employees(
        spreadsheet
    )

    employee = employees[
        employees["nombre"].astype(str)
        == str(employee_name)
    ]

    if employee.empty:
        return False

    stored_hash = str(
        employee.iloc[0]["pin_hash"]
    ).strip().lower()

    provided_hash = hash_pin(
        pin
    ).lower()

    return provided_hash == stored_hash


# ============================================================
# CUENTAS ABIERTAS
# ============================================================

OPEN_ACCOUNTS_SHEET = "Cuentas_Abiertas"

OPEN_ACCOUNTS_COLUMNS = [
    "id_cuenta",
    "empleado",
    "carrito_json",
]


def get_open_accounts_sheet(spreadsheet):
    """
    Devuelve la pestaña 'Cuentas_Abiertas'.

    La pestaña debe existir antes de usar estas funciones.
    """

    return spreadsheet.worksheet(
        OPEN_ACCOUNTS_SHEET
    )


def ensure_open_accounts_sheet(
    spreadsheet,
):
    """
    Crea la pestaña 'Cuentas_Abiertas' si todavía no existe
    y escribe sus encabezados.

    Esta función debe utilizarse durante la configuración
    inicial del sistema, no en cada venta.
    """

    try:
        worksheet = spreadsheet.worksheet(
            OPEN_ACCOUNTS_SHEET
        )

    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=OPEN_ACCOUNTS_SHEET,
            rows=100,
            cols=len(
                OPEN_ACCOUNTS_COLUMNS
            ),
        )

        worksheet.update(
            "A1",
            [OPEN_ACCOUNTS_COLUMNS],
            value_input_option="RAW",
        )

        return worksheet

    # Comprobamos que la estructura existente sea correcta.
    header = worksheet.row_values(1)

    if header != OPEN_ACCOUNTS_COLUMNS:
        raise ValueError(
            "La pestaña 'Cuentas_Abiertas' "
            "no tiene las columnas esperadas.\n"
            f"Esperadas: {OPEN_ACCOUNTS_COLUMNS}\n"
            f"Encontradas: {header}"
        )

    return worksheet


def serialize_cart(
    cart: list[dict[str, Any]],
) -> str:
    """
    Convierte el carrito Python a JSON.

    Se mantiene una representación compacta y legible.
    """

    if not isinstance(cart, list):
        raise TypeError(
            "El carrito debe ser una lista de productos."
        )

    return json.dumps(
        cart,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def deserialize_cart(
    carrito_json: str,
) -> list[dict[str, Any]]:
    """
    Convierte carrito_json nuevamente a una lista Python.
    """

    if not carrito_json:
        return []

    try:
        cart = json.loads(
            carrito_json
        )

    except json.JSONDecodeError as error:
        raise ValueError(
            "El carrito almacenado contiene "
            "JSON inválido."
        ) from error

    if not isinstance(cart, list):
        raise ValueError(
            "El carrito almacenado debe ser "
            "un arreglo JSON."
        )

    return cart


def create_open_account(
    spreadsheet,
    employee: str,
    cart: list[dict[str, Any]],
) -> str:
    """
    Crea una nueva cuenta abierta.

    Cada cuenta recibe un UUID único.

    Devuelve:
        id_cuenta
    """

    if not employee:
        raise ValueError(
            "El empleado es obligatorio."
        )

    worksheet = get_open_accounts_sheet(
        spreadsheet
    )

    account_id = str(
        uuid.uuid4()
    )

    cart_json = serialize_cart(
        cart
    )

    worksheet.append_row(
        [
            account_id,
            employee,
            cart_json,
        ],
        value_input_option="RAW",
    )

    return account_id


def get_open_accounts(
    spreadsheet,
    employee: str | None = None,
) -> pd.DataFrame:
    """
    Obtiene todas las cuentas abiertas.

    Si employee está especificado, devuelve únicamente
    las cuentas pertenecientes a ese empleado.
    """

    worksheet = get_open_accounts_sheet(
        spreadsheet
    )

    records = worksheet.get_all_records()

    if not records:
        return pd.DataFrame(
            columns=OPEN_ACCOUNTS_COLUMNS
        )

    accounts = pd.DataFrame(
        records,
        columns=OPEN_ACCOUNTS_COLUMNS,
    )

    if employee is not None:
        accounts = accounts[
            accounts["empleado"].astype(str)
            == str(employee)
        ].copy()

    return accounts


def get_open_account(
    spreadsheet,
    account_id: str,
):
    """
    Busca una cuenta abierta por su ID.

    Devuelve un diccionario o None.
    """

    if not account_id:
        return None

    accounts = get_open_accounts(
        spreadsheet
    )

    if accounts.empty:
        return None

    account = accounts[
        accounts["id_cuenta"].astype(str)
        == str(account_id)
    ]

    if account.empty:
        return None

    row = account.iloc[0]

    return {
        "id_cuenta": str(
            row["id_cuenta"]
        ),
        "empleado": str(
            row["empleado"]
        ),
        "carrito": deserialize_cart(
            str(row["carrito_json"])
        ),
    }


def update_open_account(
    spreadsheet,
    account_id: str,
    cart: list[dict[str, Any]],
) -> bool:
    """
    Actualiza el carrito de una cuenta abierta existente.

    Devuelve True si se actualizó correctamente.
    """

    if not account_id:
        raise ValueError(
            "account_id es obligatorio."
        )

    worksheet = get_open_accounts_sheet(
        spreadsheet
    )

    all_values = worksheet.get_all_values()

    if len(all_values) <= 1:
        return False

    headers = all_values[0]

    try:
        id_column = headers.index(
            "id_cuenta"
        )
        cart_column = headers.index(
            "carrito_json"
        )

    except ValueError as error:
        raise ValueError(
            "No se encontraron las columnas "
            "'id_cuenta' y/o 'carrito_json'."
        ) from error

    target_row = None

    for row_number, row in enumerate(
        all_values[1:],
        start=2,
    ):

        if (
            len(row) > id_column
            and row[id_column] == account_id
        ):
            target_row = row_number
            break

    if target_row is None:
        return False

    cart_json = serialize_cart(
        cart
    )

    # Actualizamos únicamente la celda
    # correspondiente al carrito.
    worksheet.update_cell(
        target_row,
        cart_column + 1,
        cart_json,
    )

    return True


def delete_open_account(
    spreadsheet,
    account_id: str,
) -> bool:
    """
    Elimina una cuenta abierta.

    Debe llamarse cuando la cuenta se convierta
    definitivamente en una venta cobrada o cuando
    el usuario la descarte.
    """

    if not account_id:
        raise ValueError(
            "account_id es obligatorio."
        )

    worksheet = get_open_accounts_sheet(
        spreadsheet
    )

    all_values = worksheet.get_all_values()

    if len(all_values) <= 1:
        return False

    headers = all_values[0]

    try:
        id_column = headers.index(
            "id_cuenta"
        )

    except ValueError as error:
        raise ValueError(
            "No se encontró la columna "
            "'id_cuenta'."
        ) from error

    target_row = None

    for row_number, row in enumerate(
        all_values[1:],
        start=2,
    ):

        if (
            len(row) > id_column
            and row[id_column] == account_id
        ):
            target_row = row_number
            break

    if target_row is None:
        return False

    worksheet.delete_rows(
        target_row
    )

    return True

