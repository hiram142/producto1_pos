"""Dashboard del dueño. Lee siempre en vivo, sin caché."""

from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

from src.gsheets import read_df_live, get_sales_for_report
from src.reportes import sales_report_csv

def render() -> None:
    st.markdown("### 📊 Panel de Control")
    
    hoy_mexico = datetime.now(ZoneInfo("America/Mexico_City")).date()
    
    col_fecha, col_btn = st.columns([3, 1])
    with col_fecha:
        fecha_seleccionada = st.date_input("📅 Fecha de consulta", value=hoy_mexico)
    with col_btn:
        st.write("")
        if st.button("🔄 Actualizar", use_container_width=True):
            st.rerun()

    ventas = read_df_live("Ventas")
    if ventas.empty:
        st.info("Todavía no hay ventas registradas en la base de datos.")
        return

    if "subtotal" not in ventas.columns:
        st.error("⚠️ Falta la columna 'subtotal' en tu hoja de Ventas de Google Sheets.")
        return

    # ----------------------------------------
    # SECCIÓN: MÉTRICAS DEL DÍA
    # ----------------------------------------
    ventas["subtotal"] = pd.to_numeric(ventas["subtotal"], errors="coerce").fillna(0)
    dia = ventas.loc[ventas["fecha"].astype(str).str.startswith(str(fecha_seleccionada))]

    if dia.empty:
        st.warning(f"No hay ventas registradas para el {fecha_seleccionada}.")
    else:
        caja = float(dia["subtotal"].sum())
        tickets = dia["id_venta"].nunique()

        st.metric("💰 Ingresos del día", f"${caja:,.2f}")
        col_a, col_b = st.columns(2)
        col_a.metric("Tickets cobrados", tickets)
        col_b.metric("Ticket promedio", f"${caja / tickets:,.2f}" if tickets else "$0.00")

        st.divider()
        st.markdown(f"#### 🏆 Ventas por empleado ({fecha_seleccionada})")
        leaderboard = dia.groupby("empleado")["subtotal"].sum().sort_values(ascending=False).rename("Ventas")
        st.bar_chart(leaderboard, horizontal=True)

        st.markdown("#### 🧮 Cuadre de caja por método de pago")
        st.dataframe(
            dia.groupby("metodo_pago")["subtotal"].sum().reset_index(),
            use_container_width=True,
            hide_index=True,
        )
        
    # ----------------------------------------
    # SECCIÓN: CONTABILIDAD Y EXPORTACIÓN
    # ----------------------------------------
    st.divider()
    st.markdown("### 📁 Exportación Contable")
    st.caption("Genera un archivo CSV con el formato exacto de ingresos diarios para el contador.")
    
    try:
        ventas_reporte = get_sales_for_report()
        if not ventas_reporte.empty:
            csv_data = sales_report_csv(
                ventas_reporte,
                payment_layout="por_linea",
                date_format="%Y-%m-%d %H:%M:%S",
            )

            st.download_button(
                label="📥 Descargar Reporte CSV",
                data=csv_data,
                file_name=f"ingresos_contables_{hoy_mexico.strftime('%Y%m%d')}.csv",
                mime="text/csv",
                type="primary",
                use_container_width=True
            )
        else:
            st.info("No hay datos suficientes para generar el reporte.")
            
    except Exception as exc:
        st.error("Falta crear el archivo src/reportes.py o actualizar gsheets.py con la función de reporte.")
        st.code(str(exc), language="text")