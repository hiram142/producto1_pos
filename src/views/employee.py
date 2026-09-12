import urllib.parse
import uuid
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

from src.gsheets import (
    append_rows, create_open_account, delete_open_account,
    get_open_accounts, read_df, read_df_live, update_open_account, validate_employee_pin
)

def _ahora() -> datetime:
    return datetime.now(ZoneInfo(st.secrets["app"].get("timezone", "America/Mexico_City")))

def _reset_ticket(nueva_mesa: str = "") -> None:
    version = st.session_state.get("ticket_version", 0) + 1
    st.session_state["ticket_version"] = version
    if nueva_mesa:
        st.session_state[f"mesa_input_{version}"] = nueva_mesa

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
            if linea["cantidad"] <= 0: carrito.remove(linea)
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
    if st.button("‹ No soy yo"):
        st.session_state.pop("empleado_seleccionado", None)
        st.rerun()

    with st.form("form_pin", clear_on_submit=True):
        pin_ingresado = st.text_input("PIN", type="password", max_chars=8)
        if st.form_submit_button("Entrar", type="primary", use_container_width=True):
            if validate_employee_pin(seleccionado, pin_ingresado):
                st.session_state["empleado_actual"] = seleccionado
                st.session_state.pop("empleado_seleccionado", None)
                st.rerun()
            else:
                st.error("PIN incorrecto.")

def _panel_lateral(empleado: str) -> None:
    with st.sidebar:
        st.markdown(f"#### 👤 {empleado}")
        if st.button("🔒 Salir", use_container_width=True):
            st.session_state.pop("empleado_actual", None)
            st.rerun()

        st.divider()
        st.markdown("#### ⏸️ Tus cuentas pendientes")
        cuentas_df = get_open_accounts(empleado)

        if cuentas_df.empty:
            st.caption("No tienes cuentas en pausa.")
            return

        for _, cuenta in cuentas_df.iterrows():
            cuenta_id = cuenta.get("id_cuenta", "")
            mesa = cuenta.get("nombre_cuenta", "Sin nombre")
            try:
                carrito_guardado = json.loads(cuenta.get("carrito_json", "[]"))
            except:
                carrito_guardado = []
                
            with st.container(border=True):
                st.write(f"**{mesa}**")
                n_items = sum(linea.get("cantidad", 0) for linea in carrito_guardado)
                st.caption(f"{n_items} artículos pendientes")
                
                if st.button("▶️ Retomar Pedido", key=f"retomar_{cuenta_id}", use_container_width=True):
                    if "carrito" not in st.session_state: st.session_state["carrito"] = []
                    st.session_state["carrito"] = list(carrito_guardado)
                    st.session_state["cuenta_actual_id"] = cuenta_id
                    _reset_ticket(mesa)
                    st.rerun()

def render() -> None:
    empleados = read_df("Empleados")
    productos = read_df("Productos")

    if empleados.empty or productos.empty:
        st.warning("Faltan datos en las hojas Empleados o Productos.")
        return

    if "empleado_actual" not in st.session_state or not st.session_state["empleado_actual"]:
        _pantalla_bloqueo(empleados)
        return

    empleado = st.session_state["empleado_actual"]
    _panel_lateral(empleado)

    if "mensaje_flash" in st.session_state and st.session_state["mensaje_flash"]:
        st.success(st.session_state.pop("mensaje_flash"))

    st.markdown("### 🧾 Pedido nuevo")
    productos["precio"] = productos["precio"].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).astype(float)
    
    if "carrito" not in st.session_state:
        st.session_state["carrito"] = []
    carrito: list[dict] = st.session_state["carrito"]
    
    catalogo = productos.loc[productos["activo"].astype(str).str.upper().isin(["TRUE", "1", "SI", "YES"])]
    if "categoria" not in catalogo.columns: catalogo["categoria"] = "Platillos"

    st.caption("Selecciona una categoría:")
    tabs = st.tabs(["🍔 Platillos", "🥤 Bebidas", "🍰 Postres"])
    categorias = ["Platillos", "Bebidas", "Postres"]

    for tab, cat in zip(tabs, categorias):
        with tab:
            cat_df = catalogo[catalogo["categoria"].astype(str).str.strip().str.lower() == cat.lower()]
            for fila in cat_df.itertuples():
                if st.button(f"{fila.producto}\n\n${float(fila.precio):,.0f}", key=f"btn_{fila.producto}", use_container_width=True):
                    _agregar_al_carrito(carrito, str(fila.producto), float(fila.precio))
                    st.rerun()

    if not carrito: return

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

    ticket_version = st.session_state.get("ticket_version", 0)
    mesa_actual = st.text_input("🪑 Mesa / cliente", key=f"mesa_input_{ticket_version}")
    telefono_cliente = st.text_input("📱 WhatsApp del cliente (opcional - solo para enviar ticket)", key=f"telefono_input_{ticket_version}")

    st.markdown("##### 💳 Método de pago")
    metodos = ["Efectivo", "Tarjeta", "Transferencia", "Mixto"]
    metodo = st.radio("Selecciona cómo pagan", metodos, horizontal=True, label_visibility="collapsed")

    if metodo == "Efectivo":
        efectivo, tarjeta, transferencia = total, 0.0, 0.0
    elif metodo == "Tarjeta":
        efectivo, tarjeta, transferencia = 0.0, total, 0.0
    elif metodo == "Transferencia":
        efectivo, tarjeta, transferencia = 0.0, 0.0, total
    else:
        st.caption("Escribe un monto y lo demás se calculará solo:")
        
        # Parámetros en enteros (0 y 50) para evitar que el input pida decimales
        efectivo_input = st.number_input("Monto en Efectivo ($)", min_value=0, value=0, step=50)
        efectivo = min(float(efectivo_input), float(total))
        
        if efectivo_input > total:
            st.info(f"🪙 Cambio a entregar: **${efectivo_input - total:,.0f}**")
            
        resto1 = round(total - efectivo, 2)
        tarjeta_input = st.number_input("Monto en Tarjeta ($)", min_value=0, value=int(resto1), step=50)
        tarjeta = min(float(tarjeta_input), resto1)
        
        transferencia = round(resto1 - tarjeta, 2)
        if transferencia > 0:
            st.caption(f"💡 El resto (${transferencia:,.2f}) se registra como Transferencia.")

    col_pausar, col_cobrar = st.columns(2)
    
    if col_pausar.button("📥 Pausar", use_container_width=True):
        cuenta_id = st.session_state.get("cuenta_actual_id")
        nombre_final = mesa_actual.strip() or f"Mesa de {empleado}"
        if cuenta_id: update_open_account(cuenta_id, list(carrito))
        else: create_open_account(empleado, list(carrito), nombre_final)
        
        st.session_state["carrito"] = []
        st.session_state.pop("cuenta_actual_id", None)
        st.session_state["mensaje_flash"] = f"Pedido '{nombre_final}' pausado."
        _reset_ticket()
        st.rerun()

    if col_cobrar.button("💵 Cobrar y Cerrar", type="primary", use_container_width=True):
        ts = _ahora()
        id_venta = f"V-{ts:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"
        tel_limpio = "".join(filter(str.isdigit, telefono_cliente))
        
        filas = []
        for idx, linea in enumerate(carrito):
            filas.append([
                id_venta, ts.strftime("%Y-%m-%d %H:%M:%S"), empleado, linea["producto"], linea["cantidad"], 
                round(linea["precio_unitario"], 2), round(linea["cantidad"] * linea["precio_unitario"], 2), 
                metodo, efectivo if idx == 0 else 0.0, tarjeta if idx == 0 else 0.0, 
                transferencia if idx == 0 else 0.0, tel_limpio
            ])

        append_rows("Ventas", filas)
        cuenta_id = st.session_state.get("cuenta_actual_id")
        if cuenta_id: delete_open_account(cuenta_id)

        st.success(f"Venta registrada exitosamente · ${total:,.2f}", icon="✅")
        st.balloons()
        
        if tel_limpio:
            mensaje = f"Recibo {id_venta}\nTotal: ${total:,.2f}\n¡Gracias por tu compra!"
            st.link_button("📲 Enviar recibo por WhatsApp", f"https://wa.me/52{tel_limpio}?text={urllib.parse.quote(mensaje)}", use_container_width=True)

        st.session_state["carrito"] = []
        st.session_state.pop("cuenta_actual_id", None)
        _reset_ticket()