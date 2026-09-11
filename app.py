"""Producto 1 — POS + Dashboard. Punto de entrada."""

import streamlit as st

from src.gsheets import health_check
from src.views import employee, owner

st.set_page_config(
    page_title="Producto 1 · POS",
    page_icon="🧾",
    layout="centered",          # mejor para móvil; el dashboard cambia a wide
    initial_sidebar_state="collapsed",
)

VISTAS = {
    "🧾 Registrar venta": "empleado",
    "📊 Dashboard del dueño": "dueno",
}


def _sidebar() -> str:
    with st.sidebar:
        st.title("Producto 1")
        etiqueta = st.radio("Vista", list(VISTAS.keys()), label_visibility="collapsed")

        st.divider()
        ok, detalle = health_check()
        if ok:
            st.success(f"Conectado: {detalle}", icon="✅")
        else:
            st.error("Sin conexión a Google Sheets", icon="🚫")
            with st.expander("Detalle técnico"):
                st.code(detalle, language="text")

    return VISTAS[etiqueta]


def _gate_dueno() -> bool:
    """PIN del dueño guardado en st.session_state para no pedirlo en cada rerun."""
    if st.session_state.get("es_dueno"):
        return True

    st.subheader("🔒 Acceso del administrador")
    with st.form("login_dueno"):
        pin = st.text_input("PIN", type="password", max_chars=8)
        if st.form_submit_button("Entrar", use_container_width=True):
            if pin and pin == str(st.secrets["app"]["owner_pin"]):
                st.session_state["es_dueno"] = True
                st.rerun()
            else:
                st.error("PIN incorrecto.")
    return False


def main() -> None:
    vista = _sidebar()

    if vista == "empleado":
        employee.render()
    elif _gate_dueno():
        owner.render()


if __name__ == "__main__":
    main()