"""Generación de reportes de negocio independientes de la persistencia."""

from decimal import Decimal, InvalidOperation
from typing import Literal

import pandas as pd

PAYMENT_COLUMNS = [
    "monto_efectivo",
    "monto_tarjeta",
    "monto_transferencia",
]

def _to_cents(value: object) -> int:
    """Espera importes sin símbolos ni separadores de miles."""
    text = str(value).strip()
    if not text:
        return 0

    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Importe inválido: {value!r}") from exc

    if not amount.is_finite():
        raise ValueError(f"Importe no finito: {value!r}")

    cents = amount * 100
    if cents != cents.to_integral_value():
        raise ValueError(f"Importe con más de dos decimales: {value!r}")

    return int(cents)

def sales_report_csv(
    sales: pd.DataFrame,
    *,
    payment_layout: Literal["por_linea", "repetido_por_ticket"] = "por_linea",
    date_format: str = "%Y-%m-%d %H:%M:%S",
) -> bytes:
    """Genera un CSV diario, sin impuestos."""
    output_columns = [
        "fecha",
        "numero_ventas",
        "ingresos",
        *PAYMENT_COLUMNS,
    ]

    if payment_layout not in {"por_linea", "repetido_por_ticket"}:
        raise ValueError("Distribución de pagos desconocida.")

    required = {"id_venta", "fecha", "subtotal", *PAYMENT_COLUMNS}
    missing = required.difference(sales.columns)
    if missing:
        raise ValueError(f"Faltan columnas: {sorted(missing)}")

    if sales.empty:
        return pd.DataFrame(columns=output_columns).to_csv(index=False).encode("utf-8-sig")

    df = sales.copy()

    if df["id_venta"].isna().any():
        raise ValueError("Hay ventas sin identificador.")

    df["id_venta"] = df["id_venta"].astype(str).str.strip()
    if df["id_venta"].eq("").any():
        raise ValueError("Hay ventas con identificador vacío.")

    dates = pd.to_datetime(df["fecha"], format=date_format, errors="coerce")
    if dates.isna().any():
        raise ValueError("Hay ventas sin fecha o con formato inválido.")

    df["dia"] = dates.dt.strftime("%Y-%m-%d")

    for column in ["subtotal", *PAYMENT_COLUMNS]:
        df[column] = df[column].map(_to_cents)

    grouped = df.groupby("id_venta", sort=False)

    if grouped["dia"].nunique().gt(1).any():
        raise ValueError("Un mismo id_venta aparece en días distintos.")

    tickets = grouped.agg(
        fecha=("dia", "first"),
        ingresos=("subtotal", "sum"),
    )

    if payment_layout == "por_linea":
        payments = grouped[PAYMENT_COLUMNS].sum()
    else:
        variation = grouped[PAYMENT_COLUMNS].nunique(dropna=False)
        if variation.gt(1).any().any():
            raise ValueError("Los pagos no son iguales en todas las filas del ticket.")
        payments = grouped[PAYMENT_COLUMNS].first()

    tickets = tickets.join(payments)

    mismatch = (tickets[PAYMENT_COLUMNS].sum(axis=1) != tickets["ingresos"])
    if mismatch.any():
        ids = tickets.index[mismatch].tolist()[:5]
        raise ValueError(f"Pagos y subtotales no coinciden en estas ventas: {ids}")

    daily = tickets.groupby("fecha", sort=True).agg(
        numero_ventas=("ingresos", "size"),
        ingresos=("ingresos", "sum"),
        monto_efectivo=("monto_efectivo", "sum"),
        monto_tarjeta=("monto_tarjeta", "sum"),
        monto_transferencia=("monto_transferencia", "sum"),
    ).reset_index()

    def format_cents(value: int) -> str:
        value = int(value)
        sign = "-" if value < 0 else ""
        whole, fraction = divmod(abs(value), 100)
        return f"{sign}{whole}.{fraction:02d}"

    for column in ["ingresos", *PAYMENT_COLUMNS]:
        daily[column] = daily[column].map(format_cents)

    return daily[output_columns].to_csv(index=False).encode("utf-8-sig")