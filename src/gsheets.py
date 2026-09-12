"""Acceso a Google Sheets. Único módulo que conoce la persistencia."""

from __future__ import annotations

from typing import Any

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

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
import pandas as pd
import json
import uuid

# ============================================================
# AUTENTICACIÓN DE EMPLEADOS (Versión Simplificada)
# ============================================================
def get_employees() -> pd.DataFrame:
    worksheet = get_worksheet("Empleados")
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=["id", "nombre", "pin", "activo"])
    return pd.DataFrame(records)

def get_active_employees() -> pd.DataFrame:
    employees = get_employees()
    if employees.empty:
        return employees
    active_mask = employees["activo"].astype(str).str.strip().str.upper().isin({"TRUE", "1", "SI", "SÍ", "YES"})
    return employees.loc[active_mask].copy()

def validate_employee_pin(employee_name: str, pin: str) -> bool:
    if not pin:
        return False
    employees = get_active_employees()
    employee = employees[employees["nombre"].astype(str) == str(employee_name)]
    if employee.empty:
        return False
    stored_pin = str(employee.iloc[0]["pin"]).replace(".0", "").strip()
    provided_pin = str(pin).strip()
    return provided_pin == stored_pin

# ============================================================
# CUENTAS ABIERTAS (Blindadas y dinámicas)
# ============================================================
def serialize_cart(cart: list) -> str:
    return json.dumps(cart, ensure_ascii=False, separators=(",", ":"))

def deserialize_cart(carrito_json: str) -> list:
    if not carrito_json: return []
    return json.loads(carrito_json)

def get_open_accounts(employee: str = None) -> pd.DataFrame:
    worksheet = get_worksheet("Cuentas_Abiertas")
    records = worksheet.get_all_records()
    if not records:
        return pd.DataFrame(columns=["id_cuenta", "empleado", "carrito_json"])
    
    accounts = pd.DataFrame(records)
    accounts.columns = [str(c).strip().lower() for c in accounts.columns]
    
    if employee is not None and "empleado" in accounts.columns:
        accounts = accounts[accounts["empleado"].astype(str).str.strip() == str(employee).strip()].copy()
    return accounts

def create_open_account(employee: str, cart: list, nombre_cuenta: str = "Sin nombre") -> str:
    worksheet = get_worksheet("Cuentas_Abiertas")
    account_id = str(uuid.uuid4())
    cart_json = serialize_cart(cart)
    
    headers = [str(h).strip().lower() for h in worksheet.row_values(1)]
    row_data = [""] * len(headers)
    
    for i, h in enumerate(headers):
        if h == "id_cuenta": row_data[i] = account_id
        elif h == "empleado": row_data[i] = employee
        elif h == "carrito_json": row_data[i] = cart_json
        elif h == "nombre_cuenta": row_data[i] = nombre_cuenta
        
    if len(headers) == 0:
        row_data = [account_id, nombre_cuenta, employee, cart_json]
        
    worksheet.append_row(row_data, value_input_option="RAW")
    return account_id

def update_open_account(account_id: str, cart: list) -> bool:
    worksheet = get_worksheet("Cuentas_Abiertas")
    all_values = worksheet.get_all_values()
    if len(all_values) <= 1: return False
    
    headers = [str(h).strip().lower() for h in all_values[0]]
    if "id_cuenta" not in headers or "carrito_json" not in headers: return False
        
    id_column = headers.index("id_cuenta")
    cart_column = headers.index("carrito_json")
    
    target_row = None
    for row_number, row in enumerate(all_values[1:], start=2):
        if len(row) > id_column and str(row[id_column]).strip() == str(account_id).strip():
            target_row = row_number
            break
            
    if target_row is None: return False
    worksheet.update_cell(target_row, cart_column + 1, serialize_cart(cart))
    return True

def delete_open_account(account_id: str) -> bool:
    worksheet = get_worksheet("Cuentas_Abiertas")
    all_values = worksheet.get_all_values()
    if len(all_values) <= 1: return False
    
    headers = [str(h).strip().lower() for h in all_values[0]]
    if "id_cuenta" not in headers: return False
    
    id_column = headers.index("id_cuenta")
    
    target_row = None
    for row_number, row in enumerate(all_values[1:], start=2):
        if len(row) > id_column and str(row[id_column]).strip() == str(account_id).strip():
            target_row = row_number
            break
            
    if target_row is None: return False
    worksheet.delete_rows(target_row)
    return True