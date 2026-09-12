"""Dashboard del dueño. Lee siempre en vivo, sin caché."""

from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

from src.config import SHEET_VENTAS
from src.gsheets import read_df_live

def render() -> None:
    st.markdown("### 📊 Panel de Control")
    
    # Lumina: Fijamos la zona horaria exacta para los cortes de caja
    hoy_mexico = datetime.now(ZoneInfo("America/Mexico_City")).date()
    
    # Claudia: Selector de fecha dinámico
    col_fecha, col_btn = st.columns([3, 1])
    with col_fecha:
        fecha_seleccionada = st.date_input("📅 Fecha de consulta", value=hoy_mexico)
    with col_btn:
        st.write("") # Espaciador vertical
        if st.button("🔄 Actualizar", use_container_width=True):
            st.rerun()

    ventas = read_df_live(SHEET_VENTAS)
    if ventas.empty:
        st.info("Todavía no hay ventas registradas en la base de datos.")
        return

    # Limpieza de datos
    ventas["total"] = pd.to_numeric(ventas["total"], errors="coerce").fillna(0)
    
    # Filtramos la tabla usando la fecha del calendario
    dia = ventas.loc[ventas["fecha"].astype(str) == str(fecha_seleccionada)]

    if dia.empty:
        st.warning(f"No hay ventas registradas para el {fecha_seleccionada}.")
        return

    # Cálculos del día
    caja = float(dia["total"].sum())
    tickets = dia["id_venta"].nunique()

    st.metric("💰 Ingresos del día", f"${caja:,.2f}")
    col_a, col_b = st.columns(2)
    col_a.metric("Tickets cobrados", tickets)
    col_b.metric("Ticket promedio", f"${caja / tickets:,.2f}" if tickets else "$0.00")

    st.divider()
    st.markdown(f"#### 🏆 Ventas por empleado ({fecha_seleccionada})")
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