"""Vista de venta, optimizada para pantalla de teléfono."""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from src.config import COLUMNAS_VENTAS, METODOS_PAGO, SHEET_EMPLEADOS, SHEET_PRODUCTOS, SHEET_VENTAS
from src.gsheets import append_rows, read_df


def _ahora() -> datetime:
    return datetime.now(ZoneInfo(st.secrets["app"].get("timezone", "UTC")))


def render() -> None:
    st.markdown("### 🧾 Pedido nuevo ")

    empleados = read_df(SHEET_EMPLEADOS)
    productos = read_df(SHEET_PRODUCTOS)
    if empleados.empty or productos.empty:
        st.warning("Faltan datos en las hojas Empleados o Productos.")
        return

    # --- LIMPIEZA ---
    # Remueve símbolos de moneda y comas enviados por Google Sheets 
    # para evitar errores matemáticos de conversión.
    productos["precio"] = (
        productos["precio"]
        .astype(str)
        .str.replace("$", "", regex=False)
        .str.replace(",", "", regex=False)
        .astype(float)
    )
    # --------------------------

    activos = empleados.loc[empleados["activo"].astype(str).str.lower() == "true", "nombre"]
    empleado = st.selectbox("Empleado", activos.tolist(), key="empleado_actual")
    

    carrito: dict[str, int] = st.session_state.setdefault("carrito", {})
    catalogo = productos.loc[productos["activo"].astype(str).str.lower() == "true"]

    st.caption("Toca un producto para agregarlo")
    columnas = st.columns(2)
    for i, fila in enumerate(catalogo.itertuples()):
        with columnas[i % 2]:
            if st.button(
                f"{fila.producto}\n${float(fila.precio):,.0f}",
                key=f"btn_{fila.producto}",
                use_container_width=True,
            ):
                carrito[fila.producto] = carrito.get(fila.producto, 0) + 1
                st.rerun()

    if not carrito:
        st.info("Carrito vacío.")
        return

    st.divider()
    precios = catalogo.set_index("producto")["precio"].astype(float).to_dict()
    total = 0.0
    for producto, cantidad in list(carrito.items()):
        subtotal = precios[producto] * cantidad
        total += subtotal
        col_a, col_b = st.columns([4, 1])
        col_a.write(f"**{cantidad} ×** {producto} — ${subtotal:,.2f}")
        if col_b.button("➖", key=f"quitar_{producto}", use_container_width=True):
            carrito[producto] -= 1
            if carrito[producto] <= 0:
                del carrito[producto]
            st.rerun()

    st.metric("Total a cobrar", f"${total:,.2f}")
    metodo = st.radio("Método de pago", METODOS_PAGO, horizontal=True, index=None)

    if st.button("✅ Registrar venta", type="primary", use_container_width=True, disabled=not metodo):
        ts = _ahora()
        id_venta = f"V-{ts:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
        filas = [
            [
                id_venta, ts.isoformat(timespec="seconds"), ts.strftime("%Y-%m-%d"),
                empleado, producto, cantidad, precios[producto],
                round(precios[producto] * cantidad, 2), metodo,
            ]
            for producto, cantidad in carrito.items()
        ]
        assert all(len(f) == len(COLUMNAS_VENTAS) for f in filas)

        try:
            append_rows(SHEET_VENTAS, filas)
        except Exception as exc:  # noqa: BLE001
            st.error("No se pudo registrar la venta. No cierres la pantalla.")
            st.code(str(exc), language="text")
            return

        st.session_state["carrito"] = {}
        st.success(f"Venta {id_venta} registrada · ${total:,.2f} en {metodo}", icon="✅")
        st.balloons()
