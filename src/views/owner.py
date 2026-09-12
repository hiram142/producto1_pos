"""Dashboard del dueño. Lee siempre en vivo, sin caché."""

from __future__ import annotations

from datetime import datetime
import importlib
import importlib as st
from zoneinfo import ZoneInfo

import pandas as pd
st = importlib.import_module("streamlit")

from src.config import SHEET_VENTAS
from src.gsheets import read_df_live


def render() -> None:
    st.markdown("### 📊 Panel de datos ")
    if st.button("🔄 Actualizar", use_container_width=False):
        st.rerun()

    ventas = read_df_live(SHEET_VENTAS)
    if ventas.empty:
        st.info("Todavía no hay ventas registradas.")
        return

    ventas["total"] = pd.to_numeric(ventas["total"], errors="coerce").fillna(0)
    hoy = datetime.now(ZoneInfo(st.secrets["app"].get("timezone", "UTC"))).strftime("%Y-%m-%d")
    dia = ventas.loc[ventas["fecha"].astype(str) == hoy]

    caja = float(dia["total"].sum())
    tickets = dia["id_venta"].nunique()

    st.metric("💰 Caja de hoy", f"${caja:,.2f}")
    col_a, col_b = st.columns(2)
    col_a.metric("Tickets", tickets)
    col_b.metric("Ticket promedio", f"${caja / tickets:,.2f}" if tickets else "$0.00")

    st.divider()
    st.markdown("#### 🏆 Ventas por empleado (hoy)")
    leaderboard = (
        dia.groupby("empleado")["total"].sum().sort_values(ascending=False).rename("Ventas")
    )
    st.bar_chart(leaderboard, horizontal=True)

    st.markdown("#### 🧮 Cuadre de caja por método de pago")
    st.dataframe(
        dia.groupby("metodo_pago")["total"].sum().reset_index(),
        use_container_width=True,
        hide_index=True,
    )
