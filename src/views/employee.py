import uuid
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st

from src.gsheets import (
    append_rows,
    create_open_account,
    delete_open_account,
    get_open_accounts,
    read_df,
    update_open_account,
    validate_employee_pin,
)

def _ahora() -> datetime:
    return datetime.now(ZoneInfo("America/Mexico_City"))

def _agregar_al_carrito(carrito: list[dict], producto: str, precio_unitario: float) -> None:
    for linea in carrito:
        if linea["producto"] == producto:
            linea["cantidad"] += 1
            return
    carrito.append({"producto": producto, "cantidad": 1, "precio_unitario": precio_unitario})

def _quitar_del_carrito(carrito: list[dict], producto: str) -> None:
    for linea in list(carrito):
        if linea["producto"] == producto:
            linea["cantidad"] -= 1
            if linea["cantidad"] <= 0:
                carrito.remove(linea)
            return

def _total_carrito(carrito: list[dict]) -> float:
    return sum(linea["cantidad"] * linea["precio_unitario"] for linea in carrito)

def _pantalla_bloqueo(empleados_df) -> None:
    st.markdown("### 🔒 ¿Quién eres?")
    
    activos = empleados_df.loc[empleados_df["activo"].astype(str).str.strip().str.upper().isin(["TRUE", "1", "SI", "YES"])]
    seleccionado = st.session_state.get("empleado_seleccionado")

    if not seleccionado:
        st.caption("Toca tu nombre para continuar")
        columnas = st.columns(2)
        for i, nombre in enumerate(activos["nombre"].astype(str).tolist()):
            with columnas[i % 2]:
                if st.button(nombre, key=f"sel_emp_{nombre}", use_container_width=True):
                    st.session_state["empleado_seleccionado"] = nombre
                    st.rerun()
        return

    st.write(f"👤 **{seleccionado}**")
    if st.button("‹ No soy yo", use_container_width=False):
        st.session_state.pop("empleado_seleccionado", None)
        st.rerun()

    with st.form("form_pin", clear_on_submit=True):
        pin_ingresado = st.text_input("PIN", type="password", max_chars=4)
        entrar = st.form_submit_button("Entrar", type="primary", use_container_width=True)

    if entrar:
        if validate_employee_pin(seleccionado, pin_ingresado):
            st.session_state["empleado_actual"] = seleccionado
            st.session_state.pop("empleado_seleccionado", None)
            st.rerun()
        else:
            st.error("PIN incorrecto.")

def _panel_cuentas_abiertas(empleado: str) -> None:
    with st.sidebar:
        st.markdown(f"#### 👤 {empleado}")
        if st.button("🔒 Cerrar sesión", use_container_width=True):
            st.session_state.pop("empleado_actual", None)
            st.session_state["carrito"] = []
            st.session_state.pop("cuenta_actual_id", None)
            st.rerun()

        st.divider()
        st.markdown("#### ⏸️ Tus cuentas pendientes")

        cuentas_df = get_open_accounts(empleado)

        if cuentas_df.empty:
            st.caption("No tienes cuentas en pausa.")
            return

        for _, cuenta in cuentas_df.iterrows():
            cuenta_id = cuenta["id_cuenta"]
            carrito_guardado = json.loads(cuenta["carrito_json"])
            
            with st.container(border=True):
                st.write(f"**Orden: {cuenta_id[:6].upper()}**")
                n_items = sum(linea.get("cantidad", 0) for linea in carrito_guardado)
                st.caption(f"{n_items} artículos pendientes")
                
                if st.button("▶️ Retomar Pedido", key=f"retomar_{cuenta_id}", use_container_width=True):
                    st.session_state["carrito"] = list(carrito_guardado)
                    st.session_state["cuenta_actual_id"] = cuenta_id
                    st.rerun()

def render() -> None:
    empleados = read_df("Empleados")
    productos = read_df("Productos")

    if empleados.empty or productos.empty:
        st.warning("Faltan datos en las hojas Empleados o Productos.")
        return

    if not st.session_state.get("empleado_actual"):
        _pantalla_bloqueo(empleados)
        return

    empleado = st.session_state["empleado_actual"]
    _panel_cuentas_abiertas(empleado)

    if st.session_state.get("mensaje_flash"):
        st.success(st.session_state.pop("mensaje_flash"))

    st.markdown("### 🧾 Pedido nuevo")
    
    productos["precio"] = productos["precio"].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).astype(float)

    carrito: list[dict] = st.session_state.setdefault("carrito", [])
    catalogo = productos.loc[productos["activo"].astype(str).str.strip().str.upper().isin(["TRUE", "1", "SI", "YES"])]

    st.caption("Toca un producto para agregarlo")
    columnas = st.columns(2)
    for i, fila in enumerate(catalogo.itertuples()):
        with columnas[i % 2]:
            if st.button(f"{fila.producto}\n${float(fila.precio):,.0f}", key=f"btn_{fila.producto}", use_container_width=True):
                _agregar_al_carrito(carrito, str(fila.producto), float(fila.precio))
                st.rerun()

    if not carrito:
        st.info("Carrito vacío. Selecciona productos del menú.")
        return

    st.divider()
    total = _total_carrito(carrito)
    for linea in list(carrito):
        subtotal = linea["cantidad"] * linea["precio_unitario"]
        col_a, col_b = st.columns([4, 1])
        col_a.write(f"**{linea['cantidad']} ×** {linea['producto']} — ${subtotal:,.2f}")
        if col_b.button("➖", key=f"quitar_{linea['producto']}", use_container_width=True):
            _quitar_del_carrito(carrito, linea["producto"])
            st.rerun()

    st.metric("Total a cobrar", f"${total:,.2f}")

    metodos_pago = ["Efectivo", "Tarjeta", "Transferencia"]
    metodo = st.radio("Método de pago", metodos_pago, horizontal=True, index=None)

    col_pausar, col_cobrar = st.columns(2)
    pausar = col_pausar.button("📥 Pausar", use_container_width=True)
    cobrar = col_cobrar.button("💵 Cobrar y Cerrar", type="primary", use_container_width=True, disabled=not metodo)

    if pausar:
        cuenta_id = st.session_state.get("cuenta_actual_id")
        try:
            if cuenta_id:
                update_open_account(cuenta_id, list(carrito))
            else:
                create_open_account(empleado, list(carrito))
        except Exception as exc:
            st.error("No se pudo pausar el pedido.")
            st.code(str(exc), language="text")
            return

        st.session_state["carrito"] = []
        st.session_state.pop("cuenta_actual_id", None)
        st.session_state["mensaje_flash"] = "Pedido guardado en tus cuentas pendientes."
        st.rerun()

    if cobrar:
        ts = _ahora()
        id_venta = f"V-{ts:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
        
        filas = [
            [
                id_venta, ts.isoformat(timespec="seconds"), ts.strftime("%Y-%m-%d"),
                empleado, linea["producto"], linea["cantidad"], linea["precio_unitario"],
                round(linea["cantidad"] * linea["precio_unitario"], 2), metodo
            ]
            for linea in carrito
        ]

        try:
            append_rows("Ventas", filas)
        except Exception as exc:
            st.error("Error de conexión al registrar la venta.")
            st.code(str(exc), language="text")
            return

        cuenta_id = st.session_state.get("cuenta_actual_id")
        if cuenta_id:
            delete_open_account(cuenta_id)

        st.session_state["carrito"] = []
        st.session_state.pop("cuenta_actual_id", None)
        read_df.clear()
        
        st.success(f"Venta registrada exitosamente · ${total:,.2f} pagado con {metodo}", icon="✅")
        st.balloons()