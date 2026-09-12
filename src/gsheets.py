"""Acceso a Google Sheets. Único módulo que conoce la persistencia."""

from __future__ import annotations
import json
import uuid
from typing import Any
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from src.config import TTL_CATALOGO

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_PRODUCTS = "Productos"
SHEET_EMPLOYEES = "Empleados"
SHEET_SALES = "Ventas"
SHEET_OPEN_ACCOUNTS = "Cuentas_Abiertas"
SHEET_CASH_CLOSINGS = "Cierres_Caja"

VENTAS_COLUMNS = [
    "id_venta", "fecha", "empleado", "producto", "cantidad", 
    "precio_unitario", "subtotal", "metodo_pago", "monto_efectivo", 
    "monto_tarjeta", "monto_transferencia", "telefono_cliente"
]

EMPLEADOS_COLUMNS = ["id", "nombre", "pin", "activo"]
CUENTAS_ABIERTAS_COLUMNS = ["id_cuenta", "nombre_cuenta", "empleado", "carrito_json"]
CIERRES_CAJA_COLUMNS = [
    "id_cierre", "empleado", "inicio_turno", "efectivo_inicial", "fin_turno", 
    "efectivo_reportado", "efectivo_esperado", "diferencia"
]

@st.cache_resource(show_spinner=False)
def get_client() -> gspread.Client:
    try:
        info = dict(st.secrets["gcp_service_account"])
    except KeyError as exc:
        raise RuntimeError("Faltan secrets [gcp_service_account].") from exc
    return gspread.authorize(Credentials.from_service_account_info(info, scopes=SCOPES))

@st.cache_resource(show_spinner=False)
def get_worksheet(nombre: str) -> gspread.Worksheet:
    return get_client().open_by_key(st.secrets["app"]["spreadsheet_id"]).worksheet(nombre)

@st.cache_data(ttl=TTL_CATALOGO, show_spinner=False)
def read_df(nombre: str) -> pd.DataFrame:
    return pd.DataFrame(get_worksheet(nombre).get_all_records())

def read_df_live(nombre: str) -> pd.DataFrame:
    return pd.DataFrame(get_worksheet(nombre).get_all_records())

def append_rows(nombre: str, filas: list[list[Any]]) -> None:
    if not filas: return
    get_worksheet(nombre).append_rows(filas, value_input_option="USER_ENTERED")
    read_df.clear()

def get_employees() -> pd.DataFrame:
    employees = read_df(SHEET_EMPLOYEES)
    return employees if not employees.empty else pd.DataFrame(columns=EMPLEADOS_COLUMNS)

def get_active_employees() -> pd.DataFrame:
    employees = get_employees()
    if employees.empty: return employees
    active_mask = employees["activo"].astype(str).str.strip().str.upper().isin({"TRUE", "1", "SI", "YES"})
    return employees.loc[active_mask].copy()

def validate_employee_pin(employee_name: str, pin: str) -> bool:
    if not employee_name or not pin: return False
    employees = get_active_employees()
    employee = employees[employees["nombre"].astype(str).str.strip() == str(employee_name).strip()]
    if employee.empty: return False
    stored_pin = str(employee.iloc[0]["pin"]).replace(".0", "").strip()
    return str(pin).strip() == stored_pin

def serialize_cart(cart: list[dict[str, Any]]) -> str:
    return json.dumps(cart, ensure_ascii=False, separators=(",", ":"))

def deserialize_cart(carrito_json: str) -> list[dict[str, Any]]:
    if not carrito_json: return []
    return json.loads(carrito_json)

def get_open_accounts(employee: str = None) -> pd.DataFrame:
    accounts = read_df_live(SHEET_OPEN_ACCOUNTS)
    if accounts.empty: return pd.DataFrame(columns=CUENTAS_ABIERTAS_COLUMNS)
    if employee is not None:
        accounts = accounts[accounts["empleado"].astype(str).str.strip() == str(employee).strip()].copy()
    return accounts

def create_open_account(employee: str, cart: list[dict[str, Any]], nombre_cuenta: str = "Sin nombre") -> str:
    account_id = str(uuid.uuid4())
    append_rows(SHEET_OPEN_ACCOUNTS, [[account_id, nombre_cuenta, employee, serialize_cart(cart)]])
    return account_id

def update_open_account(account_id: str, cart: list[dict[str, Any]]) -> bool:
    worksheet = get_worksheet(SHEET_OPEN_ACCOUNTS)
    values = worksheet.get_all_values()
    if len(values) <= 1: return False
    headers = [str(h).strip().lower() for h in values[0]]
    if "id_cuenta" not in headers or "carrito_json" not in headers: return False
    id_column, cart_column = headers.index("id_cuenta"), headers.index("carrito_json")
    
    target_row = next((i for i, row in enumerate(values[1:], 2) if len(row) > id_column and str(row[id_column]).strip() == str(account_id).strip()), None)
    if target_row is None: return False
    worksheet.update_cell(target_row, cart_column + 1, serialize_cart(cart))
    return True

def delete_open_account(account_id: str) -> bool:
    worksheet = get_worksheet(SHEET_OPEN_ACCOUNTS)
    values = worksheet.get_all_values()
    if len(values) <= 1: return False
    headers = [str(h).strip().lower() for h in values[0]]
    if "id_cuenta" not in headers: return False
    id_column = headers.index("id_cuenta")
    
    target_row = next((i for i, row in enumerate(values[1:], 2) if len(row) > id_column and str(row[id_column]).strip() == str(account_id).strip()), None)
    if target_row is None: return False
    worksheet.delete_rows(target_row)
    return True

def create_cash_closing(empleado: str, inicio_turno: str, efectivo_inicial: float, efectivo_reportado: float, efectivo_esperado: float, fin_turno: str) -> str:
    id_cierre = str(uuid.uuid4())
    diferencia = round(float(efectivo_reportado) - float(efectivo_esperado), 2)
    row = [id_cierre, empleado, inicio_turno, round(float(efectivo_inicial), 2), fin_turno, round(float(efectivo_reportado), 2), round(float(efectivo_esperado), 2), diferencia]
    append_rows(SHEET_CASH_CLOSINGS, [row])
    return id_cierre

def health_check() -> tuple[bool, str]:
    """Diagnóstico rápido de conexión."""
    try:
        titulo = get_client().open_by_key(st.secrets["app"]["spreadsheet_id"]).title
        return True, titulo
    except Exception as exc:
        return False, str(exc)

def get_sales_for_report() -> pd.DataFrame:

    worksheet = get_worksheet(SHEET_SALES)
    
    headers = worksheet.row_values(1)
    if headers != VENTAS_COLUMNS:
        raise ValueError(
            "La hoja Ventas debe tener las 12 columnas "
            "esperadas, en el orden definido."
        )

    records = worksheet.get_all_records(
        numericise_ignore=["all"],
    )

    return pd.DataFrame(records, columns=VENTAS_COLUMNS)