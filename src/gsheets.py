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