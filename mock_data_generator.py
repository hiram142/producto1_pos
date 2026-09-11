"""Generador de datos de prueba para Producto 1."""

import random
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import tomli as toml_parser # Usamos el parser compatible con Streamlit
try:
    import tomllib as toml_parser
except ImportError:
    import toml as toml_parser

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

# ============================================================
# CONFIGURACIÓN
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
SECRETS_PATH = BASE_DIR / ".streamlit" / "secrets.toml"
TIMEZONE = "America/Mexico_City"
NUM_SALES = 150
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
PAYMENT_METHODS = ["Efectivo", "Tarjeta", "Transferencia"]
RANDOM_SEED = 42

# ============================================================
# SECRETS Y CONEXIÓN
# ============================================================
def load_secrets() -> dict:
    if not SECRETS_PATH.exists():
        raise FileNotFoundError(f"No se encontró secrets.toml en: {SECRETS_PATH}")
    with SECRETS_PATH.open("rb") as file:
        return toml_parser.load(file)

def get_google_client(secrets: dict) -> gspread.Client:
    credentials = Credentials.from_service_account_info(
        secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(credentials)

# ============================================================
# LECTURA DE DATOS
# ============================================================
def get_active_employees(spreadsheet: gspread.Spreadsheet) -> pd.DataFrame:
    df = pd.DataFrame(spreadsheet.worksheet("Empleados").get_all_records())
    active_mask = df["activo"].astype(str).str.upper().isin({"TRUE", "1"})
    return df.loc[active_mask].copy()

def get_active_products(spreadsheet: gspread.Spreadsheet) -> pd.DataFrame:
    df = pd.DataFrame(spreadsheet.worksheet("Productos").get_all_records())
    
    # Limpiar precios por si tienen símbolos de moneda (como el parche que hicimos)
    df["precio"] = (
        df["precio"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .astype(float)
    )
    
    active_mask = df["activo"].astype(str).str.upper().isin({"TRUE", "1"})
    return df.loc[active_mask].copy()

# ============================================================
# GENERACIÓN DE VENTAS
# ============================================================
def generate_sales(employees: pd.DataFrame, products: pd.DataFrame) -> pd.DataFrame:
    now = datetime.now(ZoneInfo(TIMEZONE))
    employee_names = employees["nombre"].astype(str).tolist()
    product_records = products[["producto", "precio"]].to_dict(orient="records")
    
    rows = []
    for _ in range(NUM_SALES):
        product = random.choice(product_records)
        quantity = random.randint(1, 4)
        unit_price = float(product["precio"])
        seconds_ago = random.randint(0, 72 * 60 * 60) # Últimas 72 horas
        sale_datetime = now - timedelta(seconds=seconds_ago)
        
        # Estructura EXACTA de Claudia
        rows.append({
            "id_venta": f"V-{sale_datetime:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}",
            "timestamp": sale_datetime.isoformat(timespec="seconds"),
            "fecha": sale_datetime.strftime("%Y-%m-%d"),
            "empleado": random.choice(employee_names),
            "producto": str(product["producto"]),
            "cantidad": quantity,
            "precio_unitario": round(unit_price, 2),
            "total": round(quantity * unit_price, 2),
            "metodo_pago": random.choice(PAYMENT_METHODS),
        })
        
    return pd.DataFrame(rows).sort_values("timestamp")

# ============================================================
# MAIN
# ============================================================
def main() -> None:
    print("Iniciando inyección de 150 ventas de prueba...")
    secrets = load_secrets()
    client = get_google_client(secrets)
    spreadsheet = client.open_by_key(secrets["app"]["spreadsheet_id"])
    
    employees = get_active_employees(spreadsheet)
    products = get_active_products(spreadsheet)
    
    sales_df = generate_sales(employees, products)
    
    # Orden exacto de las 9 columnas
    expected_columns = [
        "id_venta", "timestamp", "fecha", "empleado", 
        "producto", "cantidad", "precio_unitario", "total", "metodo_pago"
    ]
    
    values = sales_df[expected_columns].astype(str).values.tolist()
    spreadsheet.worksheet("Ventas").append_rows(values, value_input_option="USER_ENTERED")
    print("✅ 150 ventas inyectadas exitosamente en Google Sheets.")

if __name__ == "__main__":
    main()