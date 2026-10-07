"""Comprobaciones puntuales de la revisión final (rama temporal; no forma parte del programa)."""
import sys, traceback
from pathlib import Path
from streamlit.testing.v1 import AppTest
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "modulos"))

def app():
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60); at.run(); return at

def ir(at, p): at.sidebar.radio[0].set_value(p).run()

def caso(nombre, f):
    print(f"\n=== {nombre} ===")
    try:
        f()
    except Exception:
        traceback.print_exc()

def editar_tras_salida():
    at = app()
    [b for b in at.sidebar.button if "ejemplo" in b.label][0].click().run()
    inv = at.session_state["inventario"]
    ir(at, "Inventario")
    n = "Aceite de oliva"
    at.selectbox(key="editar_select").select(n).run()
    print("stock inicial:", inv.buscar_producto(n).stock)
    at.selectbox(key="stock_select").select(n).run()
    at.radio(key=f"stock_tipo_{n}").set_value("Salida").run()
    at.number_input(key=f"stock_cantidad_{n}").set_value(5.0)
    at.button(key=f"stock_boton_{n}").click().run()
    print("stock tras salida de 5:", inv.buscar_producto(n).stock)
    lote = inv.buscar_producto(n).lotes[0]
    w = at.number_input(key=f"edit_lote_cantidad_{n}_{lote.id}")
    print("campo 'Cantidad' en Editar producto muestra:", w.value)
    at.number_input(key=f"edit_stock_minimo_{n}").set_value(6.0)
    at.button(key=f"edit_boton_{n}").click().run()
    print("stock tras guardar SOLO el stock mínimo:", inv.buscar_producto(n).stock, "(debería ser 15)")

def unidad_receta():
    at = app()
    [b for b in at.sidebar.button if "ejemplo" in b.label][0].click().run()
    inv = at.session_state["inventario"]
    from inventario import Producto
    inv.agregar_producto(Producto("Azafrán", "Especias", 50, "g", 2, "Especias SA"))
    ir(at, "Recetario")
    at.selectbox(key="ing_select").select("Azafrán").run()
    r = at.radio(key="unidad_ing_Azafrán")
    print("unidad propuesta para un producto en gramos:", r.value, "opciones:", r.options)

def anadir_servicio_refresca():
    at = app()
    ir(at, "Servicios")
    from inventario import Producto
    antes = len(at.dataframe)
    form_inputs = [w for w in at.text_input if w.label == "Nombre del menú"]
    form_inputs[0].input("Menú X")
    [b for b in at.button if b.label == "Añadir servicio"][0].click().run()
    print("servicios registrados:", len(at.session_state["registro_servicios"].servicios),
          "| tablas visibles antes/después:", antes, len(at.dataframe),
          "| textos info:", [i.value for i in at.info][:2])

caso("Editar producto tras una salida de stock", editar_tras_salida)
caso("Unidad propuesta al añadir un ingrediente en gramos", unidad_receta)
caso("Añadir servicio: ¿se refresca la tabla?", anadir_servicio_refresca)
