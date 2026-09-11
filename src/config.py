"""Constantes compartidas. Un solo lugar para tocar nombres de hojas y columnas."""

SHEET_VENTAS = "Ventas"
SHEET_PRODUCTOS = "Productos"
SHEET_EMPLEADOS = "Empleados"

COLUMNAS_VENTAS = [
    "id_venta", "timestamp", "fecha", "empleado",
    "producto", "cantidad", "precio_unitario", "total", "metodo_pago",
]

METODOS_PAGO = ["Efectivo", "Tarjeta", "Transferencia"]

# TTL de caché en segundos para datos que casi no cambian (catálogo, empleados).
TTL_CATALOGO = 600
