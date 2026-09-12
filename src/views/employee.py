import urllib.parse
import uuid
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st

from src.gsheets import (
    append_rows, create_cash_closing, create_open_account, delete_open_account,
    get_open_accounts, read_df, read_df_live, update_open_account, validate_employee_pin
)

PESOS_POR_PUNTO = 10

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

def _resumen_lealtad(telefono: str) -> tuple[int, float]:
    ventas = read_df_live("Ventas")
    if ventas.empty or "telefono_cliente" not in ventas.columns: return 0, 0.0
    propias = ventas.loc[ventas["telefono_cliente"].astype(str) == telefono]
    if propias.empty: return 0, 0.0
    return int(propias["id_venta"].nunique()), float(pd.to_numeric(propias["subtotal"], errors="coerce").fillna(0).sum())

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
        col_salir, col_corte = st.columns(2)
        if col_salir.button("🔒 Salir", use_container_width=True):
            st.session_state.pop("empleado_actual", None)
            st.rerun()
        if col_corte.button("🧮 Corte", use_container_width=True):
            st.session_state["modo_corte_caja"] = True
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
                    st.session_state["carrito"] = list(carrito_guardado)
                    st.session_state["cuenta_actual_id"] = cuenta_id
                    _reset_ticket(mesa)
                    st.rerun()

def _pantalla_corte_caja(empleado: str) -> None:
    st.markdown("### 🧮 Corte de caja (ciego)")
    if st.button("‹ Volver al punto de venta"):
        st.session_state["modo_corte_caja"] = False
        st.rerun()

    st.caption("Cuenta el efectivo físico del cajón ANTES de ver cuánto debería haber.")
    fondo_inicial = st.number_input("Fondo inicial de caja", min_value=0.0, step=50.0, value=0.0)

    with st.form("form_corte"):
        contado = st.number_input("💵 Efectivo físico contado", min_value=0.0, step=10.0)
        if st.form_submit_button("Confirmar conteo", type="primary", use_container_width=True):
            ventas = read_df_live("Ventas")
            esperado = fondo_inicial
            if not ventas.empty and "monto_efectivo" in ventas.columns:
                hoy_str = _ahora().strftime("%Y-%m-%d")
                efectivo_col = pd.to_numeric(ventas["monto_efectivo"], errors="coerce").fillna(0)
                hoy_mask = ventas["fecha"].astype(str).str.startswith(hoy_str)
                esperado += float(efectivo_col.loc[hoy_mask].sum())

            diferencia = round(contado - esperado, 2)
            col_a, col_b = st.columns(2)
            col_a.metric("Efectivo esperado", f"${esperado:,.2f}")
            col_b.metric("Diferencia", f"${diferencia:,.2f}")

            if diferencia == 0: st.success("Cuadra exacto. 🎉")
            elif diferencia > 0: st.info("Sobra efectivo.")
            else: st.warning("Falta efectivo.")

            create_cash_closing(
                empleado=empleado,
                inicio_turno=_ahora().strftime("%Y-%m-%d 00:00:00"),
                efectivo_inicial=fondo_inicial,
                efectivo_reportado=contado,
                efectivo_esperado=esperado,
                fin_turno=_ahora().strftime("%Y-%m-%d %H:%M:%S")
            )

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
    _panel_lateral(empleado)

    if st.session_state.get("modo_corte_caja"):
        _pantalla_corte_caja(empleado)
        return

    if st.session_state.get("mensaje_flash"):
        st.success(st.session_state.pop("mensaje_flash"))

    st.markdown("### 🧾 Pedido nuevo")
    productos["precio"] = productos["precio"].astype(str).str.replace("$", "", regex=False).str.replace(",", "", regex=False).astype(float)
    carrito: list[dict] = st.session_state.setdefault("carrito", [])
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
    telefono_cliente = st.text_input("📱 WhatsApp del cliente (opcional)", key=f"telefono_input_{ticket_version}")

    pct_efectivo = st.slider("Efectivo", 0, 100, 100, format="%d%%")
    efectivo = round(total * pct_efectivo / 100, 2)
    resto = round(total - efectivo, 2)
    tarjeta = round(resto * st.slider("Del resto, tarjeta", 0, 100, 100, format="%d%%") / 100, 2) if resto > 0 else 0.0
    transferencia = round(resto - tarjeta, 2)

    st.caption(f"Efectivo: ${efectivo:,.2f} | Tarjeta: ${tarjeta:,.2f} | Transf: ${transferencia:,.2f}")
    metodo_pago_label = "Mixto" if sum(1 for m in [efectivo, tarjeta, transferencia] if m > 0) > 1 else ("Efectivo" if efectivo else "Tarjeta" if tarjeta else "Transferencia")

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
        
        _, gasto_historico = _resumen_lealtad(tel_limpio) if tel_limpio else (0, 0)
        puntos = int((gasto_historico + total) // PESOS_POR_PUNTO) if tel_limpio else 0

        filas = []
        for idx, linea in enumerate(carrito):
            filas.append([
                id_venta, ts.strftime("%Y-%m-%d %H:%M:%S"), empleado, linea["producto"], linea["cantidad"], 
                round(linea["precio_unitario"], 2), round(linea["cantidad"] * linea["precio_unitario"], 2), 
                metodo_pago_label, efectivo if idx == 0 else 0.0, tarjeta if idx == 0 else 0.0, 
                transferencia if idx == 0 else 0.0, tel_limpio, puntos if idx == 0 else 0
            ])

        append_rows("Ventas", filas)
        cuenta_id = st.session_state.get("cuenta_actual_id")
        if cuenta_id: delete_open_account(cuenta_id)

        st.success(f"Venta registrada exitosamente · ${total:,.2f}", icon="✅")
        st.balloons()
        
        if tel_limpio:
            mensaje = f"Recibo {id_venta}\nTotal: ${total:,.2f}\n¡Llevas {puntos} puntos acumulados!"
            st.link_button("📲 Enviar recibo por WhatsApp", f"https://wa.me/52{tel_limpio}?text={urllib.parse.quote(mensaje)}", use_container_width=True)

        st.session_state["carrito"] = []
        st.session_state.pop("cuenta_actual_id", None)
        _reset_ticket()