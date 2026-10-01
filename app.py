"""
app.py — Interfaz gráfica (Streamlit)
---------------------------------------
Interfaz web para la app de gestión del restaurante. Reutiliza EXACTAMENTE
la misma lógica que main.py (los módulos en modulos/) — no duplica ni
reescribe nada de Producto, Inventario, Servicio, Receta, Menu, etc.
Esto es posible porque esos módulos nunca han sabido nada de consolas ni
de print()/input(): son independientes de la interfaz.

Para ejecutarla:
    pip install streamlit
    streamlit run app.py

Conceptos nuevos en este archivo:
- Streamlit ejecuta TODO el script de arriba a abajo cada vez que
  interactúas con algo (un botón, un formulario...). Por eso los datos
  no pueden vivir en variables normales -- se perderían en cada
  interacción. En su lugar usamos `st.session_state`, un diccionario
  especial que SÍ sobrevive entre ejecuciones.
- st.form agrupa varios campos para que se envíen todos juntos al pulsar
  un botón, en vez de recargar la página en cada campo individual.
"""

import sys
from pathlib import Path
from datetime import date, time, timedelta
from typing import Optional

# insert(0, ...) y no append(): así Python busca PRIMERO en nuestra carpeta
# modulos/. Si el ordenador tuviera instalada una librería con el mismo
# nombre que uno de nuestros módulos, se usaría la nuestra y no la otra.
sys.path.insert(0, str(Path(__file__).parent / "modulos"))

import streamlit as st
import pandas as pd

from inventario import Inventario, Producto, MovimientoStock, FACTORES_CONVERSION, UNIDADES_PESO, convertir
from servicios import RegistroServicios, Servicio
from recetario import Recetario, Receta, Menu
from compras import GestorCompras
from exportador import exportar_todo
from persistencia import guardar_sesion, cargar_sesion, Sesion
from gastos import Gasto, RegistroGastos, resumen_servicio
from materiales import Material, RegistroMaterial, lista_de_carga
import historial
from metricas import Metricas, ArchivoInformes, rango_desde_periodo, rango_mes_calendario, PERIODOS_VALIDOS, NOMBRES_MESES

def _carpeta_base() -> Path:
    """
    Dónde deben vivir los datos que tienen que SOBREVIVIR entre
    arranques (la sesión guardada, los excels exportados...).

    - Ejecución normal (python app.py / streamlit run app.py): la
      carpeta donde vive este script, como hasta ahora.
    - Ejecución empaquetada con PyInstaller (sys.frozen es True): la
      carpeta donde vive el propio .exe -- NUNCA la carpeta temporal
      donde PyInstaller descomprime el programa en cada arranque, que
      es distinta cada vez y se borra sola.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


RUTA_SESION = str(_carpeta_base() / "datos" / "sesion.json")

# set_page_config DEBE ser el primer comando de Streamlit del script.
st.set_page_config(page_title="Gestión Restaurante", page_icon="🍽️", layout="wide")

# --- Estilo visual ---
# CSS inyectado a mano: Streamlit no permite tipografías personalizadas ni
# este nivel de detalle solo con config.toml. Los selectores usan los
# atributos data-testid de Streamlit (más estables que sus clases internas,
# que cambian de una versión a otra). Si algo no se aplica bien en tu
# versión de Streamlit, inspecciona el elemento en el navegador (clic
# derecho -> Inspeccionar) para ver el atributo real y ajustar el selector.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600;700&display=swap');

:root {
    --bg-elevated: #262320;
    --border: #3A352E;
    --text-dim: #A79E8E;
    --brass: #B58B4C;
    --brass-hover: #C89D5E;
    --sage: #8CA37E;
    --ember: #C1543A;
}

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

h1, h2, h3 {
    font-family: 'Fraunces', serif !important;
    font-weight: 500 !important;
    letter-spacing: -0.01em;
}

/* Barra lateral */
[data-testid="stSidebar"] {
    background-color: #15130F;
    border-right: 1px solid var(--border);
}

/* Botones */
.stButton > button, [data-testid="stFormSubmitButton"] > button {
    border-radius: 6px;
    border: 1px solid var(--border);
    font-weight: 500;
    transition: background-color 0.15s ease, border-color 0.15s ease;
}
.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] > button[kind="primary"] {
    background-color: var(--brass);
    border-color: var(--brass);
    color: #1C1A17;
}
.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] > button[kind="primary"]:hover {
    background-color: var(--brass-hover);
    border-color: var(--brass-hover);
}

/* Métricas (Dashboard, Compras) */
[data-testid="stMetric"] {
    background-color: var(--bg-elevated);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1rem 1.2rem;
}
[data-testid="stMetricValue"] {
    font-family: 'Fraunces', serif;
    color: var(--brass);
}
[data-testid="stMetricLabel"] {
    color: var(--text-dim);
}

/* Tarjetas con borde (recomendador del recetario) */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 8px !important;
    border-color: var(--border) !important;
}

/* Pestañas */
[data-testid="stTabs"] [aria-selected="true"] {
    color: var(--brass) !important;
    border-bottom-color: var(--brass) !important;
}

/* Avisos (success/warning/error/info) */
[data-testid="stAlert"] {
    border-radius: 6px;
    border: 1px solid var(--border);
}

hr { border-color: var(--border) !important; }
</style>
""", unsafe_allow_html=True)


# ---------- Estado de la sesión ----------

def avisar(tipo: str, texto: str) -> None:
    """
    Guarda un aviso para mostrarlo en la SIGUIENTE ejecución del script.

    Por qué hace falta: st.rerun() vuelve a ejecutar todo el script desde
    cero, y cualquier st.success()/st.warning() mostrado justo antes se
    borra sin que dé tiempo a leerlo. Guardándolo en session_state (que sí
    sobrevive al rerun) y mostrándolo al principio de la página, el aviso
    aparece DESPUÉS de recargar. tipo: "success", "warning", "error" o "info".
    """
    st.session_state.setdefault("avisos", []).append((tipo, texto))


def mostrar_avisos() -> None:
    """Muestra (y vacía) los avisos pendientes de la ejecución anterior."""
    for tipo, texto in st.session_state.pop("avisos", []):
        getattr(st, tipo)(texto)


def inicializar_estado() -> None:
    """
    Se ejecuta en CADA rerun del script, pero el 'if "inventario" not in
    st.session_state' hace que el contenido solo se ejecute la PRIMERA
    vez -- las siguientes veces, los objetos ya existen y se reutilizan
    tal cual, con lo que el usuario haya cambiado hasta ahora.
    """
    if "inventario" in st.session_state:
        return

    sesion = cargar_sesion(RUTA_SESION) if Path(RUTA_SESION).exists() else None
    if sesion is None:
        sesion = Sesion(Inventario(), RegistroServicios(), Recetario(), GestorCompras(), ArchivoInformes())

    st.session_state.inventario = sesion.inventario
    st.session_state.registro_servicios = sesion.registro_servicios
    st.session_state.recetario = sesion.recetario
    st.session_state.gestor_compras = sesion.gestor_compras
    st.session_state.archivo_informes = sesion.archivo_informes
    st.session_state.registro_gastos = sesion.registro_gastos
    st.session_state.registro_material = sesion.registro_material
    st.session_state.ultima_exportacion = None
    st.session_state.receta_ingredientes = {}  # ingredientes acumulados al crear una receta


def cargar_datos_ejemplo() -> None:
    inv = st.session_state.inventario
    serv = st.session_state.registro_servicios
    rec = st.session_state.recetario

    inv.agregar_producto(Producto("Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2))
    inv.agregar_producto(Producto("Aceite de oliva", "Aceites", 20, "litros", 4.5, "Oleícola Andaluza", stock_minimo=5))
    inv.agregar_producto(Producto(
        "Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local",
        stock_minimo=2, fecha_caducidad=date.today() + timedelta(days=1),
    ))
    # Producto con merma comprado por unidades: 2 patas de ~7 kg en bruto, a 45 € cada una.
    inv.agregar_producto(Producto(
        "Pata de cerdo", "Carnes", 2, "unidades", 45, "Carnicería Pepe", tiene_merma=True, peso_unitario=7
    ))
    # Producto con DOS lotes: dos compras con distinta caducidad, proveedor y precio.
    secreto = Producto(
        "Secreto ibérico", "Carnes", 1, "kg", 14, "Carnicería Pepe", stock_minimo=0.5,
        fecha_caducidad=date.today() + timedelta(days=3),
    )
    secreto.nuevo_lote(0.8, 15, "Ibéricos Sierra", date.today() + timedelta(days=9), procedencia="inicial")
    inv.agregar_producto(secreto)
    # Consumibles: se gastan pero no se comen (lista aparte, sin caducidad).
    inv.agregar_producto(Producto(
        "Servilletas de papel", "Desechables", 500, "unidades", 0.02, "Hostelería Total", stock_minimo=200,
        tipo="consumible",
    ))
    inv.agregar_producto(Producto(
        "Vasos desechables", "Desechables", 150, "unidades", 0.05, "Hostelería Total", stock_minimo=100,
        tipo="consumible",
    ))

    serv.agregar_servicio(Servicio(date.today() + timedelta(days=3), time(21, 0), 8, "Menú del día"))

    pan = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})
    rec.agregar_receta(pan)
    rec.agregar_receta(ensalada)
    # Material reutilizable: sale a los servicios y vuelve.
    mat = st.session_state.registro_material
    for nombre, categoria, unidades, precio in (
        ("Plato llano", "Vajilla", 60, 3.5), ("Copa de vino", "Cristalería", 48, 2.8), ("Tenedor", "Cubertería", 80, 1.2),
    ):
        if nombre not in mat.materiales:
            mat.agregar_material(Material(nombre, categoria, unidades, precio, "Hostelería Total"))
    rec.agregar_menu(Menu(
        "Menú del día", [pan, ensalada], {"Servilletas de papel": 2, "Vasos desechables": 1},
        {"Plato llano": 2, "Copa de vino": 1, "Tenedor": 1},
    ))


# ---------- Lotes: piezas de interfaz compartidas ----------

def _num(valor: float) -> str:
    """Número sin decimales sobrantes para mostrar: 2.0 -> '2', 0.30000001 -> '0.3'."""
    return f"{round(valor, 3):g}"


def _parece_numero(texto: str) -> bool:
    try:
        float(texto.replace(",", "."))
        return True
    except ValueError:
        return False


def _texto_lote(producto: Producto, lote) -> str:
    """Texto de un lote en los desplegables. Empieza siempre por 'Lote N ·'."""
    aviso = " · ⚠️ CADUCADO" if lote.esta_caducado() else ""
    return lote.descripcion(producto.unidad) + aviso


def _elegir_lote(producto: Producto, etiqueta: str, clave: str, lotes: Optional[list] = None,
                 obligatorio_elegir: bool = False) -> Optional[int]:
    """
    Desplegable para elegir un lote (por defecto, los del producto, primero
    los que caducan antes). Devuelve el número del lote, o None si no hay
    lotes o todavía no se ha elegido ninguno.

    obligatorio_elegir=True: empieza vacío, para que el usuario lo elija a
    conciencia en vez de aceptar una sugerencia sin darse cuenta.
    """
    lotes = producto.lotes_ordenados() if lotes is None else lotes
    if not lotes:
        return None
    # Opciones como TEXTO (y un diccionario para volver al número de lote):
    # así el desplegable muestra exactamente lo que se ve aquí.
    opciones = {_texto_lote(producto, l): l.id for l in lotes}
    elegido = st.selectbox(
        etiqueta, list(opciones.keys()), key=clave,
        index=None if obligatorio_elegir else 0,
        placeholder="Elige un lote...",
    )
    return opciones.get(elegido)


def _campos_entrada(producto: Producto, k) -> dict:
    """
    Campos de un lote NUEVO (compra): precio, proveedor, caducidad y, si hace
    falta, peso por unidad. `k` construye las keys de los widgets.
    """
    unidad_txt = "unidad" if producto.unidad == "unidades" else producto.unidad
    c1, c2 = st.columns(2)
    precio = c1.number_input(
        f"Precio de este lote (€ por {unidad_txt})", min_value=0.0,
        value=float(producto.precio_referencia), step=0.1, key=k("precio"),
    )
    proveedor = c2.text_input("Proveedor de este lote", value=producto.proveedor, key=k("proveedor"))
    necesita_peso = producto.tiene_merma and producto.unidad == "unidades"
    peso = None
    if necesita_peso:
        peso = _campo_peso("Peso en bruto de cada unidad de este lote", k("peso"), producto.peso_unitario or 0.0)
    fecha = None
    if not producto.es_consumible() and st.checkbox("¿Este lote tiene fecha de caducidad?", key=k("tiene_fecha")):
        fecha = st.date_input("Fecha de caducidad de este lote", key=k("fecha"))
    return {"precio": precio, "proveedor": proveedor, "peso": peso, "fecha": fecha, "necesita_peso": necesita_peso}


def _filas_lotes(producto: Producto) -> list[dict]:
    filas = []
    for l in producto.lotes_ordenados():
        dias = l.dias_para_caducar()
        if dias is None:
            estado = "—"
        elif dias < 0:
            estado = "⚠️ Caducado"
        else:
            estado = f"Caduca en {dias} día(s)"
        fila = {
            "Lote": l.id, "Cantidad": f"{_num(l.cantidad)} {producto.unidad}", "Precio (€)": _num(l.precio_unitario),
            "Valor (€)": _num(l.valor()), "Proveedor": l.proveedor, "Entrada": l.fecha_entrada.strftime("%d/%m/%Y"),
        }
        if not producto.es_consumible():
            fila["Caducidad"] = l.fecha_caducidad.strftime("%d/%m/%Y") if l.fecha_caducidad else "—"
            fila["Estado"] = estado
        if producto.unidad == "unidades":
            fila["Peso/unidad (kg)"] = _num(l.peso_unitario) if l.peso_unitario else "—"
        filas.append(fila)
    return filas


# ---------- Página: Dashboard ----------

def pagina_dashboard() -> None:
    st.header("📊 Dashboard")
    inv = st.session_state.inventario
    serv = st.session_state.registro_servicios
    comp = st.session_state.gestor_compras

    proximos_servicios = serv.servicios_proximos()
    bajo_minimo = inv.productos_bajo_minimo()
    caducados = inv.lotes_caducados()
    proximos_caducar = inv.lotes_proximos_a_caducar()
    pendientes_compra = comp.items_pendientes()

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        with st.container(border=True):
            st.metric("📅 Servicios próximos", len(proximos_servicios))
            with st.expander("Ver detalles"):
                if not proximos_servicios:
                    st.caption("No hay servicios próximos.")
                for s in proximos_servicios:
                    st.write(str(s))

    with col2:
        with st.container(border=True):
            st.metric("⚠️ Bajo mínimo", len(bajo_minimo))
            with st.expander("Ver detalles"):
                if not bajo_minimo:
                    st.caption("Ningún producto bajo mínimo.")
                for p in bajo_minimo:
                    st.write(f"{p.nombre}: {p.stock} {p.unidad} (mínimo {p.stock_minimo})")

    with col3:
        with st.container(border=True):
            st.metric("⏳ Lotes caducados o por caducar", len(caducados) + len(proximos_caducar))
            with st.expander("Ver detalles"):
                if not caducados and not proximos_caducar:
                    st.caption("Ningún lote caducado ni próximo a caducar.")
                for p, l in caducados:
                    st.write(f"🗑️ **{p.nombre}** — {_num(l.cantidad)} {p.unidad}, caducado ({l.etiqueta()})")
                for p, l in proximos_caducar:
                    st.write(f"{p.nombre} — {_num(l.cantidad)} {p.unidad}, caduca en {l.dias_para_caducar()} día(s) ({l.etiqueta()})")

    with col4:
        with st.container(border=True):
            st.metric("🛒 Pendientes de compra", len(pendientes_compra))
            with st.expander("Ver detalles"):
                if not pendientes_compra:
                    st.caption("No hay compras pendientes.")
                for i in pendientes_compra:
                    st.write(f"{i.ingrediente}: {i.cantidad} {i.unidad} (≈{i.costo_estimado()}€)")

    # La proyección de agotamiento no encaja como un simple "recuadro con
    # lista" (cada producto tiene un número de días distinto que contar),
    # así que se muestra aparte, debajo del tablón.
    proximos_agotarse = Metricas(inv).productos_proximos_a_agotarse()
    if proximos_agotarse:
        st.divider()
        st.subheader("📉 Se agotarán pronto (según ritmo de consumo)")
        for nombre, dias in proximos_agotarse:
            st.write(f"**{nombre}**: ~{dias} día(s) al ritmo actual")

    st.divider()
    st.metric("💰 Valor total del inventario", f"{inv.valor_total_inventario()} €")


# ---------- Página: Inventario ----------

# Nota sobre st.form: dentro de un formulario, cambiar una casilla o un
# desplegable NO vuelve a ejecutar la página hasta pulsar el botón. Por eso
# los campos que aparecen o desaparecen según otra respuesta (la fecha de
# caducidad, el motivo de salida, el peso por unidad...) no funcionan bien
# dentro de un st.form. Aquí se usan widgets sueltos + un botón normal.

def _filas_inventario(productos: list, tipo: str = "alimento") -> list[dict]:
    filas = []
    for p in productos:
        fila = {
            "Nombre": p.nombre, "Categoría": p.categoria, "Stock": p.stock, "Unidad": p.unidad,
            "Mínimo": p.stock_minimo, "Precio medio (€)": round(p.precio_unitario, 2), "Proveedor habitual": p.proveedor,
            "Lotes": len(p.lotes),
        }
        if tipo == "alimento":
            fila["Próxima caducidad"] = p.fecha_caducidad.strftime("%d/%m/%Y") if p.fecha_caducidad else "—"
            fila["Tipo"] = p.tipo_descripcion() or "—"
            # Siempre texto: si la columna mezcla números y "—", Streamlit
            # tiene que corregir los tipos por su cuenta (y avisa en la consola).
            fila["Peso/unidad (kg)"] = f"{round(p.peso_unitario, 2):g}" if p.peso_unitario else "—"
        filas.append(fila)
    return filas


def _campo_peso(etiqueta: str, clave: str, valor_kg: float = 0.0) -> Optional[float]:
    """Número + desplegable kg/g. Devuelve el peso en kg, o None si se deja a 0."""
    c1, c2 = st.columns([3, 1])
    unidad = c2.selectbox("Unidad del peso", UNIDADES_PESO, key=f"{clave}_unidad")
    valor_inicial = convertir(valor_kg, "kg", unidad) if valor_kg else 0.0
    valor = c1.number_input(etiqueta, min_value=0.0, value=float(valor_inicial), step=0.1, key=f"{clave}_{unidad}")
    return convertir(valor, unidad, "kg") if valor > 0 else None


# Las dos "listas" del inventario. Todo lo de la página Inventario (tabla,
# avisos y pestañas) trabaja solo con la lista elegida arriba, para que los
# alimentos y los consumibles no se mezclen.
VISTAS_PRODUCTOS = {"🍅 Alimentos": "alimento", "🧻 Consumibles": "consumible"}
VISTAS_INVENTARIO = {**VISTAS_PRODUCTOS, "🍽️ Material": "material"}


def pagina_inventario() -> None:
    st.header("📦 Inventario")
    inv = st.session_state.inventario

    tipo = VISTAS_INVENTARIO[st.radio("Lista", list(VISTAS_INVENTARIO), horizontal=True, key="inv_tipo")]
    if tipo == "material":
        _seccion_material()
        return
    productos_tipo = inv.consumibles() if tipo == "consumible" else inv.alimentos()

    if productos_tipo:
        productos = productos_tipo
        if tipo == "alimento":
            vista = st.radio(
                "Mostrar", ["Todos", "Solo productos con merma y sus derivados"], horizontal=True, key="inv_vista"
            )
            if vista != "Todos":
                productos = [p for p in productos if p.tiene_merma or p.origen or p.es_subproducto]
        st.dataframe(_filas_inventario(productos, tipo), width="stretch", hide_index=True)
        st.caption("Cada compra es un lote con su precio y proveedor: los verás en la pestaña 'Lotes'.")
    elif tipo == "consumible":
        st.info(
            "Todavía no hay consumibles: servilletas, vasos y platos desechables, film, productos de limpieza... "
            "Añádelos en la pestaña 'Añadir producto' de esta lista."
        )
    else:
        st.info("El inventario está vacío todavía.")

    # Lotes caducados: se pueden desechar desde aquí mismo, en un clic.
    for p, l in inv.lotes_caducados():
        c1, c2 = st.columns([4, 1])
        c1.error(f"🗑️ Caducado: **{p.nombre}** — {_num(l.cantidad)} {p.unidad} ({l.etiqueta()})")
        if c2.button("Desechar lote", key=f"desechar_{p.nombre}_{l.id}"):
            if inv.desechar_lote(p.nombre, l.id):
                avisar("success", f"Lote {l.id} de '{p.nombre}' desechado ({_num(l.cantidad)} {p.unidad} a desperdicio).")
                st.rerun()

    col1, col2 = st.columns(2)
    with col1:
        bajo_minimo = [p for p in inv.productos_bajo_minimo() if p.tipo == tipo]
        if bajo_minimo:
            st.warning("⚠️ Bajo mínimo: " + ", ".join(p.nombre for p in bajo_minimo))
    with col2:
        proximos = inv.lotes_proximos_a_caducar()
        if proximos:
            detalle = ", ".join(
                f"{p.nombre} lote {l.id} ({_num(l.cantidad)} {p.unidad}, {l.dias_para_caducar()}d)" for p, l in proximos
            )
            st.warning(f"⏳ Próximos a caducar: {detalle}")

    st.divider()
    tab_add, tab_edit, tab_stock, tab_lotes, tab_limpiar, tab_limpiezas = st.tabs([
        "➕ Añadir producto", "✏️ Editar producto", "📦 Actualizar stock", "🏷️ Lotes",
        "🔪 Limpiar producto", "📜 Limpiezas",
    ])

    nombres_tipo = [p.nombre for p in productos_tipo]
    with tab_add:
        _pestana_anadir(inv, tipo)
    with tab_edit:
        _pestana_editar(inv, nombres_tipo)
    with tab_stock:
        _pestana_stock(inv, nombres_tipo)
    with tab_lotes:
        _pestana_lotes(inv, nombres_tipo)
    with tab_limpiar:
        if tipo == "consumible":
            st.info("Los consumibles no se limpian: esta pestaña es para alimentos con merma.")
        else:
            _pestana_limpiar(inv)
    with tab_limpiezas:
        _pestana_limpiezas(inv)


def _pestana_anadir(inv: Inventario, tipo: str = "alimento") -> None:
    # "Versión" del formulario: al añadir un producto se incrementa, las keys
    # cambian y los campos aparecen vacíos otra vez (lo que hacía clear_on_submit).
    v = st.session_state.setdefault("add_version", 0)
    es_consumible = tipo == "consumible"
    st.caption("Se añadirá a la lista de **consumibles**." if es_consumible else "Se añadirá a la lista de **alimentos**.")

    nombre = st.text_input("Nombre", key=f"add_nombre_{v}")
    categoria = st.text_input("Categoría", key=f"add_categoria_{v}")
    c1, c2 = st.columns(2)
    stock = c1.number_input("Stock inicial (será su primer lote)", min_value=0.0, step=0.1, key=f"add_stock_{v}")
    unidad = c2.selectbox("Unidad", Producto.UNIDADES_VALIDAS, key=f"add_unidad_{v}")

    tiene_merma = False
    peso_unitario = None
    if unidad in UNIDADES_PESO + ("unidades",) and not es_consumible:
        tiene_merma = st.checkbox(
            "Producto con merma (se limpia o despieza antes de usarse)", key=f"add_merma_{v}",
            help="Por ejemplo una pata de cerdo o un pescado entero. Solo de estos productos se pueden obtener derivados.",
        )
        if tiene_merma and unidad == "unidades":
            peso_unitario = _campo_peso("Peso en bruto de cada unidad", f"add_peso_{v}")

    c3, c4 = st.columns(2)
    precio = c3.number_input(
        f"Precio (€ por {'unidad' if unidad == 'unidades' else unidad})", min_value=0.0, step=0.1, key=f"add_precio_{v}"
    )
    stock_minimo = c4.number_input("Stock mínimo", min_value=0.0, step=0.1, key=f"add_stock_minimo_{v}")
    proveedor = st.text_input("Proveedor habitual", key=f"add_proveedor_{v}")
    fecha_caducidad = None
    # La caducidad es de cada lote: sin stock inicial no hay lote al que ponérsela
    # (se indicará al registrar la primera compra).
    if es_consumible:
        pass  # los consumibles no caducan
    elif stock > 0:
        if st.checkbox("¿Este primer lote tiene fecha de caducidad?", key=f"add_tiene_caducidad_{v}"):
            fecha_caducidad = st.date_input("Fecha de caducidad", key=f"add_fecha_{v}")
    else:
        st.caption("Sin stock inicial: la caducidad se indicará en cada compra (cada compra es un lote).")

    if st.button("Añadir producto", type="primary", key=f"add_boton_{v}"):
        nombre = nombre.strip()
        if not nombre:
            st.error("Ponle un nombre al producto.")
        elif nombre in inv.productos:
            st.error(f"Ya existe un producto llamado '{nombre}'. Para añadir otra compra usa 'Actualizar stock'.")
        else:
            try:
                inv.agregar_producto(Producto(
                    nombre, categoria, stock, unidad, precio, proveedor, stock_minimo, fecha_caducidad,
                    tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=tipo,
                ))
                avisar("success", f"{'Consumible' if es_consumible else 'Producto'} '{nombre}' añadido.")
                st.session_state.add_version += 1
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def _pestana_editar(inv: Inventario, nombres: list[str]) -> None:
    if not nombres:
        st.info("No hay productos para editar en esta lista.")
        return
    nombre_sel = st.selectbox("Producto a editar", nombres, key="editar_select")
    producto = inv.buscar_producto(nombre_sel)
    # Las keys incluyen `nombre_sel`: si no, Streamlit reutilizaría el
    # valor que ya tuviera guardado bajo esa key (el del producto
    # anterior) en vez de tomar el `value` nuevo que le pasamos aquí.
    k = lambda campo: f"edit_{campo}_{nombre_sel}"

    st.markdown("**Datos generales**")
    nuevo_nombre = st.text_input("Nombre", value=producto.nombre, key=k("nombre"))
    categoria = st.text_input("Categoría", value=producto.categoria, key=k("categoria"))
    c1, c2 = st.columns(2)
    stock_minimo = c1.number_input("Stock mínimo", value=float(producto.stock_minimo), min_value=0.0, step=0.1, key=k("stock_minimo"))
    proveedor = c2.text_input("Proveedor habitual", value=producto.proveedor, key=k("proveedor"))

    # El tipo se puede corregir (por si se dio de alta en la lista equivocada).
    tipos_texto = {"Alimento": "alimento", "Consumible": "consumible"}
    nuevo_tipo = tipos_texto[st.radio(
        "Tipo", list(tipos_texto), index=1 if producto.es_consumible() else 0, horizontal=True, key=k("tipo"),
        help="Si lo cambias, el producto pasa a la otra lista del inventario.",
    )]
    es_consumible = nuevo_tipo == "consumible"

    tiene_merma = producto.tiene_merma
    peso_unitario = None
    if producto.unidad in UNIDADES_PESO + ("unidades",) and not es_consumible:
        tiene_merma = st.checkbox("Producto con merma (se limpia o despieza)", value=producto.tiene_merma, key=k("merma"))
        if tiene_merma and producto.unidad == "unidades":
            peso_unitario = _campo_peso(
                "Peso por unidad de referencia (se propone al registrar compras)", k("peso"),
                producto.peso_unitario_referencia or producto.peso_unitario or 0.0,
            )
    if producto.tipo_descripcion() in ("Subproducto",) or producto.origen:
        st.caption(f"Este producto sale de una limpieza ({producto.tipo_descripcion()}).")

    # --- Datos de la compra (del lote) ---
    lote = None
    datos_lote = {}
    if not producto.lotes:
        st.caption("No queda stock de este producto: no hay ninguna compra (lote) que corregir.")
    else:
        st.markdown("**Datos de la compra**")
        if len(producto.lotes) == 1:
            lote = producto.lotes[0]
        else:
            lote = producto.buscar_lote(_elegir_lote(
                producto, f"Este producto tiene {len(producto.lotes)} lotes: ¿cuál corriges?", k("lote"),
            ))
        kl = lambda campo: f"edit_lote_{campo}_{nombre_sel}_{lote.id}"
        c3, c4 = st.columns(2)
        datos_lote["cantidad"] = c3.number_input(
            f"Cantidad ({producto.unidad})", min_value=0.0, value=float(lote.cantidad), step=0.1, key=kl("cantidad"),
        )
        datos_lote["precio"] = c4.number_input(
            "Precio (€)", min_value=0.0, value=float(lote.precio_unitario), step=0.1, key=kl("precio"),
        )
        datos_lote["proveedor"] = st.text_input("Proveedor de esta compra", value=lote.proveedor, key=kl("proveedor"))
        datos_lote["peso"] = None
        if producto.unidad == "unidades":
            datos_lote["peso"] = _campo_peso("Peso en bruto de cada unidad", kl("peso"), lote.peso_unitario or 0.0)
        datos_lote["tiene_fecha"] = False
        datos_lote["fecha"] = None
        if not es_consumible:
            datos_lote["tiene_fecha"] = st.checkbox(
                "¿Tiene fecha de caducidad?", value=lote.fecha_caducidad is not None, key=kl("tiene_fecha"),
            )
            datos_lote["fecha"] = st.date_input(
                "Fecha de caducidad", value=lote.fecha_caducidad or date.today(), key=kl("fecha"),
                disabled=not datos_lote["tiene_fecha"],
            )
        st.caption(
            "Corregir no es un movimiento de stock: no queda en el historial. Si algo se ha gastado o tirado, "
            "regístralo como salida en 'Actualizar stock'. Poner la cantidad a 0 elimina este lote."
        )

    if st.button("Guardar cambios", type="primary", key=k("boton")):
        # Se comprueba todo ANTES de guardar nada: o se guarda todo o nada.
        if lote is not None:
            texto = datos_lote["proveedor"].strip()
            if not texto or _parece_numero(texto):
                st.error("El proveedor de la compra debe ser texto, no puede estar vacío ni ser un número.")
                return
        nombre_original = producto.nombre
        try:
            exito = inv.editar_producto(
                nombre_sel,
                nuevo_nombre=nuevo_nombre if nuevo_nombre != producto.nombre else None,
                categoria=categoria, proveedor=proveedor, stock_minimo=stock_minimo,
                tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=nuevo_tipo,
            )
            if exito and lote is not None:
                inv.editar_lote(
                    producto.nombre, lote.id, cantidad=datos_lote["cantidad"], precio_unitario=datos_lote["precio"],
                    proveedor=datos_lote["proveedor"],
                    fecha_caducidad=datos_lote["fecha"] if datos_lote["tiene_fecha"] else None,
                    borrar_fecha_caducidad=not datos_lote["tiene_fecha"],
                    peso_unitario=datos_lote["peso"],
                )
            if exito:
                if producto.nombre != nombre_original:
                    actualizados = st.session_state.recetario.renombrar_producto(nombre_original, producto.nombre)
                    if actualizados:
                        avisar("info", f"🔄 Recetas y menús actualizados: {', '.join(actualizados)}")
                avisar("success", "Producto actualizado.")
                st.rerun()
            else:
                st.error(f"No se ha guardado: ya existe otro producto llamado '{nuevo_nombre}'.")
        except ValueError as e:
            st.error(str(e))


def _pestana_stock(inv: Inventario, nombres: list[str]) -> None:
    if not nombres:
        st.info("No hay productos en esta lista.")
        return
    nombre_sel = st.selectbox("Producto", nombres, key="stock_select")
    producto = inv.buscar_producto(nombre_sel)
    k = lambda campo: f"stock_{campo}_{nombre_sel}"

    es_entrada = st.radio(
        "Tipo de movimiento", ["Entrada (compra)", "Salida"], horizontal=True, key=k("tipo")
    ) == "Entrada (compra)"
    cantidad = st.number_input(f"Cantidad ({producto.unidad})", min_value=0.0, step=0.1, key=k("cantidad"))

    if es_entrada:
        st.caption("Cada compra se guarda como un lote nuevo, con su precio y proveedor.")
        datos = _campos_entrada(producto, k)
        if st.button("Registrar compra", type="primary", key=k("boton")):
            if cantidad <= 0:
                st.error("La cantidad debe ser mayor que 0.")
            elif datos["necesita_peso"] and datos["peso"] is None:
                st.error("Indica el peso en bruto de cada unidad de este lote.")
            elif not datos["proveedor"].strip():
                st.error("Indica el proveedor de este lote.")
            else:
                lote = inv.entrada_stock(
                    nombre_sel, cantidad, precio_unitario=datos["precio"], proveedor=datos["proveedor"],
                    fecha_caducidad=datos["fecha"], peso_unitario=datos["peso"],
                )
                if lote is None:
                    st.error("No se ha registrado la compra: revisa los datos (el proveedor debe ser texto).")
                else:
                    avisar("success", f"Compra registrada como {lote.etiqueta()} ({_num(cantidad)} {producto.unidad}).")
                    st.rerun()
        return

    if not producto.lotes:
        st.warning(f"No queda stock de '{nombre_sel}'.")
        return
    lote_id = _elegir_lote(producto, "¿De qué lote sale?", k("lote"))
    motivo = st.selectbox("Motivo de la salida", MovimientoStock.MOTIVOS_SALIDA, key=k("motivo"))
    if producto.tiene_merma:
        st.caption("Para limpiar o despiezar este producto usa la pestaña 'Limpiar producto': así queda registrado el rendimiento.")

    if st.button("Registrar salida", type="primary", key=k("boton")):
        lote = producto.buscar_lote(lote_id)
        if cantidad <= 0:
            st.error("La cantidad debe ser mayor que 0.")
        elif cantidad > lote.cantidad + 1e-9:
            st.error(
                f"No se ha registrado: en el lote {lote.id} solo hay {_num(lote.cantidad)} {producto.unidad}. "
                "Si necesitas más, haz otra salida desde otro lote."
            )
        elif inv.salida_stock(nombre_sel, cantidad, motivo, lote_id):
            avisar("success", f"Salida registrada: {_num(cantidad)} {producto.unidad} del lote {lote_id} ({motivo}).")
            st.rerun()
        else:
            st.error("No se ha podido registrar la salida.")


def _pestana_lotes(inv: Inventario, nombres: list[str]) -> None:
    if not nombres:
        st.info("No hay productos en esta lista.")
        return
    # Se abre con el primer producto que tenga lotes (no con uno vacío).
    inicial = next((i for i, n in enumerate(nombres) if inv.productos[n].lotes), 0)
    nombre_sel = st.selectbox("Producto", nombres, index=inicial, key="lotes_select")
    producto = inv.buscar_producto(nombre_sel)
    if not producto.lotes:
        st.info(f"No queda ningún lote de '{nombre_sel}'.")
        return

    st.dataframe(_filas_lotes(producto), width="stretch", hide_index=True)
    st.caption(
        f"Total: {_num(producto.stock)} {producto.unidad} · valor {producto.valor_total()} € · "
        f"precio medio {_num(producto.precio_unitario)} €/{producto.unidad}. "
        "Para corregir los datos de un lote, usa 'Editar producto'."
    )

    st.subheader("Desechar un lote")
    lote_id = _elegir_lote(producto, "Lote", f"lotes_lote_{nombre_sel}")
    lote = producto.buscar_lote(lote_id)
    if st.button("🗑️ Desechar este lote entero (desperdicio)", key=f"lotes_desechar_{nombre_sel}_{lote.id}"):
        cantidad_tirada = lote.cantidad
        if inv.desechar_lote(nombre_sel, lote.id):
            avisar("success", f"Lote {lote.id} de '{nombre_sel}' desechado ({_num(cantidad_tirada)} {producto.unidad} a desperdicio).")
            st.rerun()


def _pestana_limpiar(inv: Inventario) -> None:
    con_merma = inv.productos_con_merma()
    if not con_merma:
        st.info(
            "No hay productos con merma. Marca la casilla 'Producto con merma' al añadirlos "
            "o en 'Editar producto'."
        )
        return

    origen_nombre = st.selectbox("Producto a limpiar", [p.nombre for p in con_merma], key="limpiar_origen")
    origen = inv.buscar_producto(origen_nombre)
    if origen.stock <= 0:
        st.warning(f"No queda stock de '{origen_nombre}'.")
        return

    # Versión: tras registrar una limpieza, los campos se vacían solos.
    v = st.session_state.setdefault("limpiar_version", 0)
    lote_id = _elegir_lote(origen, "Lote a limpiar", f"limpiar_lote_{origen_nombre}_{v}")
    lote = origen.buscar_lote(lote_id)
    # La key lleva el lote: al cambiar de lote se reinician cantidad y límites.
    k = lambda campo: f"limpiar_{campo}_{origen_nombre}_{v}_{lote.id}"

    c1, c2 = st.columns(2)
    por_unidades = origen.unidad == "unidades"
    cantidad = c1.number_input(
        f"Cantidad a limpiar ({origen.unidad}, hay {_num(lote.cantidad)} en este lote)",
        min_value=0.0, max_value=float(lote.cantidad),
        value=float(min(1.0, lote.cantidad)) if por_unidades else float(lote.cantidad),
        step=1.0 if por_unidades else 0.1, key=k("cantidad"),
    )
    peso_bruto_kg = origen.peso_kg(cantidad, lote) if cantidad > 0 else 0.0
    c2.metric("Peso en bruto", f"{peso_bruto_kg:.3f} kg")
    rendimiento = inv.rendimiento_medio(origen_nombre)
    if rendimiento:
        st.caption(
            f"Rendimiento medio hasta ahora: {rendimiento:.0%} -> se esperan ~{peso_bruto_kg * rendimiento:.2f} kg limpios."
        )

    unidad_peso = st.radio("Pesos del resultado en", UNIDADES_PESO, horizontal=True, key=k("unidad"))
    c3, c4 = st.columns(2)
    sugerido = inv.producto_limpio_de(origen_nombre) or f"{origen_nombre} limpio"
    producto_limpio = c3.text_input("Producto limpio", value=sugerido, key=k("limpio"))
    peso_limpio = c4.number_input(f"Peso limpio ({unidad_peso})", min_value=0.0, step=0.1, key=k("peso_limpio"))
    fecha_caducidad = None
    if st.checkbox("Poner fecha de caducidad al producto limpio", key=k("tiene_fecha")):
        fecha_caducidad = st.date_input("Fecha de caducidad del producto limpio", key=k("fecha"))

    st.markdown("**Derivados que se aprovechan**")
    st.caption("Una fila por cada parte que se reaprovecha, con su peso. Lo que no pongas aquí se registra como merma.")
    habituales = inv.derivados_habituales(origen_nombre)
    tabla_inicial = pd.DataFrame({
        "Derivado": pd.Series(habituales, dtype="string"),
        "Peso": pd.Series([0.0] * len(habituales), dtype="float"),
    })
    tabla = st.data_editor(
        tabla_inicial, num_rows="dynamic", width="stretch", hide_index=True, key=k("derivados"),
        column_config={
            "Derivado": st.column_config.TextColumn("Derivado"),
            "Peso": st.column_config.NumberColumn(f"Peso ({unidad_peso})", min_value=0.0, step=0.01),
        },
    )
    derivados: dict[str, float] = {}
    for _, fila in tabla.iterrows():
        nombre = fila["Derivado"]
        peso = fila["Peso"]
        if pd.isna(nombre) or not str(nombre).strip() or pd.isna(peso) or peso <= 0:
            continue
        nombre = str(nombre).strip()
        derivados[nombre] = derivados.get(nombre, 0.0) + float(peso)

    if cantidad > 0 and peso_limpio > 0:
        limpio_kg = convertir(peso_limpio, unidad_peso, "kg")
        derivados_kg = convertir(sum(derivados.values()), unidad_peso, "kg")
        merma_kg = peso_bruto_kg - limpio_kg - derivados_kg
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Limpio", f"{limpio_kg:.3f} kg")
        m2.metric("Derivados", f"{derivados_kg:.3f} kg")
        m3.metric("Merma", f"{max(merma_kg, 0):.3f} kg")
        m4.metric("Rendimiento", f"{limpio_kg / peso_bruto_kg:.1%}")
        if merma_kg < -1e-6:
            st.error("El limpio más los derivados pesan más que el bruto. Revisa los pesos.")

    if st.button("Registrar limpieza", type="primary", key=k("boton")):
        try:
            limpieza = inv.limpiar_producto(
                origen_nombre, cantidad, producto_limpio, peso_limpio, derivados,
                unidad_peso=unidad_peso,
                caducidades={producto_limpio.strip(): fecha_caducidad} if fecha_caducidad else None,
                lote_id=lote.id,
            )
            avisar(
                "success",
                f"Limpieza registrada: {limpieza.peso_limpio_kg} kg de '{limpieza.producto_limpio}' "
                f"(rendimiento {limpieza.rendimiento:.1%}, merma {limpieza.merma_kg} kg).",
            )
            st.session_state.limpiar_version += 1
            st.rerun()
        except ValueError as e:
            st.error(str(e))


def _pestana_limpiezas(inv: Inventario) -> None:
    if not inv.limpiezas:
        st.info("Todavía no hay limpiezas registradas.")
        return

    st.subheader("Rendimiento medio por producto")
    filas_resumen = []
    for nombre in sorted({l.producto_origen for l in inv.limpiezas}):
        limpiezas = inv.limpiezas_de(nombre)
        bruto = sum(l.peso_bruto_kg for l in limpiezas)
        filas_resumen.append({
            "Producto": nombre,
            "Limpiezas": len(limpiezas),
            "Bruto total (kg)": round(bruto, 3),
            "Rendimiento medio": f"{inv.rendimiento_medio(nombre):.1%}",
            "Derivados aprovechados": f"{sum(sum(l.derivados_kg.values()) for l in limpiezas) / bruto:.1%}",
            "Merma media": f"{sum(l.merma_kg for l in limpiezas) / bruto:.1%}",
        })
    st.dataframe(filas_resumen, width="stretch", hide_index=True)

    st.subheader("Historial")
    st.dataframe([{
        "Fecha": l.fecha.strftime("%d/%m/%Y"),
        "Producto": l.producto_origen,
        "Lote": l.lote_origen or "—",
        "Cantidad": f"{l.cantidad_origen:g} {l.unidad_origen}",
        "Bruto (kg)": round(l.peso_bruto_kg, 3),
        "Producto limpio": l.producto_limpio,
        "Limpio (kg)": round(l.peso_limpio_kg, 3),
        "Derivados": ", ".join(f"{n} ({round(kg, 3)} kg)" for n, kg in l.derivados_kg.items()) or "—",
        "Merma (kg)": l.merma_kg,
        "Rendimiento": f"{l.rendimiento:.1%}",
        "Coste (€)": l.coste,
    } for l in reversed(inv.limpiezas)], width="stretch", hide_index=True)


# ---------- Inventario: material reutilizable ----------

def _seccion_material() -> None:
    """La lista de material del Inventario: lo que tienes, lo que está fuera y lo disponible."""
    reg = st.session_state.registro_material
    serv = st.session_state.registro_servicios

    if reg.materiales:
        st.dataframe([{
            "Material": m.nombre, "Categoría": m.categoria, "Total": m.cantidad_total,
            "En uso": reg.en_uso(m.nombre), "Disponibles": reg.disponibles(m.nombre),
            "Reposición (€/ud)": _num(m.precio_reposicion), "Proveedor": m.proveedor or "—",
        } for m in reg.materiales.values()], width="stretch", hide_index=True)
        st.caption("'En uso' es lo que ha salido a un servicio y aún no ha vuelto: sigue siendo tuyo, pero no está disponible.")
    else:
        st.info(
            "Todavía no hay material: platos, vasos, cubertería, mantelería, bandejas, chafings... "
            "Añádelo en la pestaña 'Añadir material'."
        )

    for salida in reg.salidas:
        if not salida.ha_vuelto:
            servicio = serv.buscar_por_id(salida.servicio_id)
            nombre_servicio = f"#{salida.servicio_id} {servicio.menu}" if servicio else f"#{salida.servicio_id}"
            detalle = ", ".join(f"{c} {n}" for n, c in salida.cantidades.items())
            st.warning(f"🚚 Fuera, en el servicio {nombre_servicio} (desde el {salida.fecha_salida.strftime('%d/%m/%Y')}): {detalle}")

    st.divider()
    tab_add, tab_edit, tab_reponer, tab_incidencias = st.tabs([
        "➕ Añadir material", "✏️ Editar material", "📦 Reponer o dar de baja", "💥 Roturas y pérdidas",
    ])

    with tab_add:
        v = st.session_state.setdefault("mat_version", 0)
        k = lambda campo: f"mat_add_{campo}_{v}"
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre", key=k("nombre"), placeholder="Ej: Plato llano")
        categoria = c2.text_input("Categoría", key=k("categoria"), placeholder="Ej: Vajilla")
        c3, c4 = st.columns(2)
        cantidad = c3.number_input("Unidades que tienes", min_value=0, step=1, key=k("cantidad"))
        precio = c4.number_input("Precio de reposición (€ por unidad)", min_value=0.0, step=0.5, key=k("precio"),
                                 help="Lo que cuesta reponer una unidad: es el coste que se apunta si se rompe o se pierde.")
        proveedor = st.text_input("Proveedor (opcional)", key=k("proveedor"))
        if st.button("Añadir material", type="primary", key=k("boton")):
            try:
                if reg.agregar_material(Material(nombre, categoria, int(cantidad), precio, proveedor)):
                    avisar("success", f"Material '{nombre.strip()}' añadido.")
                    st.session_state.mat_version += 1
                    st.rerun()
                else:
                    st.error(f"Ya existe un material llamado '{nombre.strip()}'.")
            except ValueError as e:
                st.error(str(e))

    if not reg.materiales:
        return
    nombres = list(reg.materiales)

    with tab_edit:
        nombre_sel = st.selectbox("Material a editar", nombres, key="mat_editar_select")
        material = reg.buscar(nombre_sel)
        k = lambda campo: f"mat_edit_{campo}_{nombre_sel}"
        c1, c2 = st.columns(2)
        nuevo_nombre = c1.text_input("Nombre", value=material.nombre, key=k("nombre"))
        categoria = c2.text_input("Categoría", value=material.categoria, key=k("categoria"))
        c3, c4 = st.columns(2)
        total = c3.number_input("Unidades que tienes (total)", min_value=0, step=1, value=material.cantidad_total, key=k("total"))
        precio = c4.number_input("Precio de reposición (€ por unidad)", min_value=0.0, step=0.5,
                                 value=float(material.precio_reposicion), key=k("precio"))
        proveedor = st.text_input("Proveedor", value=material.proveedor, key=k("proveedor"))
        st.caption("Para registrar que has comprado más o que se ha roto algo, usa 'Reponer o dar de baja'.")
        if st.button("Guardar cambios", type="primary", key=k("boton")):
            try:
                if reg.editar_material(nombre_sel, nuevo_nombre=nuevo_nombre, categoria=categoria,
                                       cantidad_total=int(total), precio_reposicion=precio, proveedor=proveedor):
                    if nuevo_nombre.strip() != nombre_sel:
                        st.session_state.recetario.renombrar_material(nombre_sel, nuevo_nombre.strip())
                    avisar("success", "Material actualizado.")
                    st.rerun()
                else:
                    st.error(f"Ya existe otro material llamado '{nuevo_nombre.strip()}'.")
            except ValueError as e:
                st.error(str(e))

    with tab_reponer:
        nombre_sel = st.selectbox("Material", nombres, key="mat_reponer_select")
        k = lambda campo: f"mat_rep_{campo}_{nombre_sel}"
        st.caption(
            f"Tienes {reg.buscar(nombre_sel).cantidad_total} · en uso {reg.en_uso(nombre_sel)} · "
            f"disponibles {reg.disponibles(nombre_sel)}"
        )
        accion = st.radio("¿Qué ha pasado?", ["He comprado más", "Se ha roto", "Se ha perdido"], horizontal=True, key=k("accion"))
        unidades = st.number_input("Unidades", min_value=0, step=1, key=k("unidades"))
        if accion != "He comprado más":
            st.caption("Una rotura o pérdida en el almacén (fuera de un servicio). Las de un servicio se apuntan al registrar su vuelta.")
        if st.button("Registrar", type="primary", key=k("boton")):
            try:
                if accion == "He comprado más":
                    if reg.reponer(nombre_sel, int(unidades)):
                        avisar("success", f"{nombre_sel}: +{int(unidades)} unidades.")
                        st.rerun()
                    else:
                        st.error("Indica cuántas unidades has comprado.")
                else:
                    tipo = "rotura" if accion == "Se ha roto" else "pérdida"
                    incidencia = reg.dar_de_baja(nombre_sel, int(unidades), tipo)
                    avisar("success", f"{tipo.capitalize()} registrada: {incidencia.cantidad} x {nombre_sel} ({incidencia.coste:.2f} €).")
                    st.rerun()
            except ValueError as e:
                st.error(str(e))

    with tab_incidencias:
        if not reg.incidencias:
            st.info("No hay roturas ni pérdidas registradas.")
        else:
            st.dataframe([{
                "Fecha": i.fecha.strftime("%d/%m/%Y"), "Tipo": i.tipo, "Material": i.material, "Unidades": i.cantidad,
                "Coste (€)": f"{i.coste:.2f}", "Dónde": f"Servicio #{i.servicio_id}" if i.servicio_id else "Almacén",
            } for i in reversed(reg.incidencias)], width="stretch", hide_index=True)
            st.metric("Coste total de roturas y pérdidas", f"{sum(i.coste for i in reg.incidencias):.2f} €")


# ---------- Servicios: salida y vuelta del material ----------

def _pestana_material_servicio(serv: RegistroServicios, rec: Recetario) -> None:
    reg = st.session_state.registro_material
    if not reg.materiales:
        st.info("No hay material registrado. Añádelo en Inventario > 🍽️ Material.")
        return
    servicios = sorted((s for s in serv.servicios if s.estado != "cancelado"), key=lambda s: (s.fecha, s.hora))
    if not servicios:
        st.info("No hay servicios.")
        return
    opciones = {}
    for s in servicios:
        fuera = " · 🚚 material fuera" if reg.salida_de(s.id) else ""
        opciones[f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}{fuera}"] = s
    servicio = opciones[st.selectbox("Servicio", list(opciones), key="material_servicio_select")]

    salida = reg.salida_de(servicio.id)
    if salida is not None:
        st.subheader("🔙 Vuelta del material")
        st.caption("Indica cuántas unidades han vuelto. De las que faltan, cuántas se han roto: el resto se apunta como pérdida.")
        vuelto, rotos = {}, {}
        for nombre, salio in salida.cantidades.items():
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"**{nombre}** · salieron {salio}")
            vuelto[nombre] = int(c2.number_input("Han vuelto", min_value=0, max_value=salio, value=salio, step=1,
                                                 key=f"vuelta_{servicio.id}_{nombre}"))
            faltan = salio - vuelto[nombre]
            rotos[nombre] = int(c3.number_input("De ellos, rotos", min_value=0, max_value=max(faltan, 0), value=0, step=1,
                                                key=f"rotos_{servicio.id}_{nombre}_{faltan}", disabled=faltan == 0))
        if st.button("Registrar vuelta", type="primary", key=f"vuelta_boton_{servicio.id}"):
            try:
                incidencias = reg.registrar_vuelta(servicio.id, vuelto, rotos)
                coste = sum(i.coste for i in incidencias)
                detalle = f" Roturas y pérdidas: {coste:.2f} €." if incidencias else " Ha vuelto todo."
                avisar("success", f"Material del servicio #{servicio.id} de vuelta.{detalle}")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        st.divider()

    st.subheader("🚚 Lista de carga" if salida is None else "🚚 Llevar más material a este servicio")
    menu = rec.buscar_menu(servicio.menu)
    sugerida = lista_de_carga(menu.materiales_por_comensal, servicio.comensales) if menu and salida is None else {}
    if sugerida:
        st.caption(f"Propuesta según el menú '{servicio.menu}' para {servicio.comensales} comensales. Puedes cambiar las cantidades.")
    carga = {}
    for m in reg.materiales.values():
        disponibles = reg.disponibles(m.nombre)
        carga[m.nombre] = int(st.number_input(
            f"{m.nombre} (disponibles: {disponibles})", min_value=0, step=1,
            value=min(sugerida.get(m.nombre, 0), max(disponibles, 0)), key=f"carga_{servicio.id}_{m.nombre}",
        ))
        if sugerida.get(m.nombre, 0) > disponibles:
            st.caption(f"⚠️ El menú pide {sugerida[m.nombre]} y solo hay {disponibles} disponibles.")
    if st.button("Registrar salida", type="primary", key=f"salida_boton_{servicio.id}"):
        try:
            reg.registrar_salida(servicio.id, carga)
            avisar("success", f"Material cargado para el servicio #{servicio.id}: ahora figura como 'en uso'.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    anteriores = [s for s in reg.salidas_de(servicio.id) if s.ha_vuelto]
    if anteriores:
        st.caption("Ya volvió: " + "; ".join(
            f"{s.fecha_vuelta.strftime('%d/%m/%Y')}: " + ", ".join(f"{s.vuelto.get(n, 0)}/{c} {n}" for n, c in s.cantidades.items())
            for s in anteriores
        ))


# ---------- Página: Servicios ----------

def _elegir_lotes_servicio(servicio: Servicio, inv: Inventario, rec: Recetario) -> dict[str, list[int]]:
    """
    Para cada ingrediente con varios lotes, el usuario elige de qué lote
    sale (se propone el que caduca antes). Si ese lote no llega, aparece
    otro desplegable, VACÍO, para que elija con qué lote completar lo que
    falta... y así hasta cubrirlo todo. Devuelve {ingrediente: [lotes en orden]}.
    """
    elecciones: dict[str, list[int]] = {}
    filas = rec.previsualizar_consumo(servicio, inv) or []
    for fila in filas:
        producto = inv.buscar_producto(fila["ingrediente"])
        # Sin nada que elegir: no existe, no hay stock, solo tiene un lote,
        # o no llega ni con todos los lotes (entonces se usan todos).
        if (producto is None or fila["a_descontar"] <= 0 or len(producto.lotes) <= 1
                or fila["necesario"] >= fila["en_stock"] - 1e-9):
            continue
        ingrediente = fila["ingrediente"]
        base = f"completar_lote_{servicio.id}_{ingrediente}"
        elegidos: list[int] = []
        primero = _elegir_lote(
            producto, f"{ingrediente}: ¿de qué lote sale? (hacen falta {_num(fila['necesario'])} {producto.unidad})",
            f"{base}_0",
        )
        elegidos.append(primero)
        while True:
            _, pendiente = inv.repartir(ingrediente, fila["necesario"], elegidos)
            restantes = [l for l in producto.lotes_ordenados() if l.id not in elegidos]
            if pendiente <= 1e-9 or not restantes:
                break
            siguiente = _elegir_lote(
                producto,
                f"Ese lote no llega: faltan {_num(pendiente)} {producto.unidad} de {ingrediente}. ¿Con qué lote lo completas?",
                f"{base}_{len(elegidos)}", lotes=restantes, obligatorio_elegir=True,
            )
            if siguiente is None:
                break  # todavía no lo ha elegido: no se podrá completar hasta hacerlo
            elegidos.append(siguiente)
        elecciones[ingrediente] = elegidos
    return elecciones


def _costes_adicionales(servicio: Servicio) -> list[dict]:
    """
    Costes que no estaban previstos y surgen al hacer el servicio (un taxi,
    hielo de última hora, una hora extra de un camarero...). Se van
    añadiendo a una lista y se guardan AL COMPLETAR el servicio.

    Si el coste es la compra de un PRODUCTO DEL INVENTARIO (5 kg de tomate
    de urgencia, de los que se usan 3), no se guarda como gasto: entra como
    compra (un lote nuevo), lo usado sale como consumo del servicio y lo
    que sobra se queda en el inventario. Así no se cuenta nada dos veces.
    """
    inv = st.session_state.inventario
    clave = f"extras_{servicio.id}"
    extras = st.session_state.setdefault(clave, [])
    st.markdown("**💶 Costes adicionales no previstos (opcional)**")
    st.caption("Se guardarán al completar el servicio y contarán en su rentabilidad.")
    for i, extra in enumerate(extras):
        c1, c2 = st.columns([5, 1])
        if extra.get("producto"):
            existente = extra.get("producto_nuevo") or inv.buscar_producto(extra["producto"])
            unidad = existente.unidad
            sobra = extra["comprada"] - extra["usada"]
            marca = " (nuevo en el inventario)" if extra.get("producto_nuevo") else ""
            c1.write(
                f"• 📦 {extra['producto']}{marca}: comprados {_num(extra['comprada'])} {unidad} por {extra['importe']:.2f} €, "
                f"usados {_num(extra['usada'])}" + (f", sobran {_num(sobra)} (al inventario)" if sobra > 0 else "")
            )
        else:
            c1.write(f"• {extra['concepto']} ({extra['categoria']}): {extra['importe']:.2f} €")
        if c2.button("Quitar", key=f"{clave}_quitar_{i}"):
            extras.pop(i)
            st.rerun()

    v = st.session_state.setdefault(f"{clave}_version", 0)
    k = lambda campo: f"{clave}_{campo}_{v}"
    es_producto = st.checkbox(
        "Es un producto del inventario (lo que sobre se queda en el inventario)", key=k("es_producto"),
    )
    nuevo = None
    if es_producto:
        opciones_producto = ["Uno que ya está en el inventario", "Uno nuevo (darlo de alta)"]
        if not inv.productos:
            opciones_producto = opciones_producto[1:]
        es_nuevo = st.radio("¿Qué producto?", opciones_producto, horizontal=True, key=k("es_nuevo")).startswith("Uno nuevo")
        ficha = None
        if es_nuevo:
            ficha = _ficha_producto_nuevo(k)
            producto = ficha["producto"]
            nombre = producto.nombre if producto else ""
        else:
            nombre = st.selectbox("Producto", list(inv.productos), key=k("producto"))
            producto = inv.buscar_producto(nombre)
        unidad = producto.unidad if producto else ficha["unidad"]
        c1, c2, c3 = st.columns(3)
        comprada = c1.number_input(f"Comprado ({unidad})", min_value=0.0, step=0.1, key=k("comprada"))
        usada = c2.number_input(f"Usado en el servicio ({unidad})", min_value=0.0, step=0.1, key=k("usada"))
        importe = c3.number_input("Importe pagado (€)", min_value=0.0, step=1.0, key=k("importe"))
        proveedor = st.text_input(
            "Dónde se compró", value=producto.proveedor if producto and not es_nuevo else "", key=k("proveedor"),
            help="Si lo dejas vacío, se usa el proveedor habitual del producto.",
        )
        fecha = None
        es_consumible = producto.es_consumible() if producto else ficha["tipo"] == "consumible"
        if not es_consumible and comprada > usada and st.checkbox(
            "Lo que sobra tiene fecha de caducidad", key=k("tiene_fecha")
        ):
            fecha = st.date_input("Fecha de caducidad", key=k("fecha"))
        if comprada > 0 and usada > comprada:
            st.error("Lo usado no puede ser más que lo comprado.")
        nuevo = {"concepto": f"{nombre} (compra no prevista)", "categoria": "Otros", "importe": importe,
                 "producto": nombre, "comprada": comprada, "usada": usada, "proveedor": proveedor,
                 "fecha_caducidad": fecha, "producto_nuevo": producto if es_nuevo else None,
                 "error_ficha": ficha["error"] if es_nuevo else None}
    else:
        c1, c2, c3 = st.columns([3, 2, 1])
        concepto = c1.text_input("Concepto", key=k("concepto"), placeholder="Ej: Taxi de vuelta")
        categoria = c2.selectbox("Categoría", Gasto.CATEGORIAS, index=len(Gasto.CATEGORIAS) - 1, key=k("categoria"))
        importe = c3.number_input("Importe (€)", min_value=0.0, step=1.0, key=k("importe"))
        nuevo = {"concepto": concepto.strip(), "categoria": categoria, "importe": importe}

    if st.button("➕ Añadir coste", key=k("anadir")):
        nuevos_pendientes = [e["producto"] for e in extras if e.get("producto_nuevo")]
        if nuevo.get("error_ficha"):
            st.error(nuevo["error_ficha"])
        elif nuevo.get("producto_nuevo") and (nuevo["producto"] in inv.productos or nuevo["producto"] in nuevos_pendientes):
            st.error(f"Ya existe un producto llamado '{nuevo['producto']}'. Elígelo en 'Uno que ya está en el inventario'.")
        elif not nuevo["concepto"]:
            st.error("Indica el concepto del coste.")
        elif nuevo["importe"] <= 0:
            st.error("El importe debe ser mayor que 0.")
        elif nuevo.get("producto") and (nuevo["comprada"] <= 0 or nuevo["usada"] > nuevo["comprada"]):
            st.error("Indica cuánto se compró (más de 0) y cuánto se usó (como mucho lo comprado).")
        else:
            extras.append(nuevo)
            st.session_state[f"{clave}_version"] = v + 1
            st.rerun()
    return extras


def _ficha_producto_nuevo(k) -> dict:
    """
    Los datos de un producto NUEVO, los mismos que en Inventario > Añadir
    producto (sin el stock ni el precio: los pone la propia compra).
    Devuelve {"producto": Producto o None, "error": texto o None, "unidad", "tipo"}.
    El producto NO se añade al inventario aquí: solo se prepara, y se añade
    al completar el servicio.
    """
    st.caption("Datos del producto nuevo (como en Inventario > Añadir producto):")
    tipos = {"Alimento": "alimento", "Consumible": "consumible"}
    tipo = tipos[st.radio("Tipo", list(tipos), horizontal=True, key=k("nuevo_tipo"))]
    c1, c2 = st.columns(2)
    nombre = c1.text_input("Nombre", key=k("nuevo_nombre"))
    categoria = c2.text_input("Categoría", key=k("nuevo_categoria"))
    c3, c4 = st.columns(2)
    unidad = c3.selectbox("Unidad", Producto.UNIDADES_VALIDAS, key=k("nuevo_unidad"))
    stock_minimo = c4.number_input("Stock mínimo", min_value=0.0, step=0.1, key=k("nuevo_stock_minimo"))
    tiene_merma, peso_unitario = False, None
    if tipo == "alimento" and unidad in UNIDADES_PESO + ("unidades",):
        tiene_merma = st.checkbox("Producto con merma (se limpia o despieza antes de usarse)", key=k("nuevo_merma"))
        if tiene_merma and unidad == "unidades":
            peso_unitario = _campo_peso("Peso en bruto de cada unidad", k("nuevo_peso"))
    proveedor = st.text_input("Proveedor habitual", key=k("nuevo_proveedor"),
                              help="Dónde se suele comprar. Se propondrá en la lista de la compra.")
    resultado = {"producto": None, "error": None, "unidad": unidad, "tipo": tipo}
    if not nombre.strip():
        resultado["error"] = "Ponle un nombre al producto nuevo."
        return resultado
    try:
        resultado["producto"] = Producto(
            nombre.strip(), categoria, 0, unidad, 0, proveedor, stock_minimo,
            tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=tipo,
        )
    except ValueError as e:
        resultado["error"] = str(e)
    return resultado


def _registrar_costes_adicionales(servicio: Servicio, extras: list[dict]) -> None:
    """
    Guarda los costes adicionales al completar el servicio: los normales como
    gastos del servicio; las compras de productos, en el inventario (ver
    Inventario.compra_para_servicio). Después vacía la lista.
    """
    gastos = st.session_state.registro_gastos
    inv = st.session_state.inventario
    for extra in extras:
        if extra.get("producto"):
            try:
                if extra.get("producto_nuevo") and extra["producto"] not in inv.productos:
                    nuevo_producto = extra["producto_nuevo"]
                    nuevo_producto.precio_referencia = round(extra["importe"] / extra["comprada"], 4)
                    inv.agregar_producto(nuevo_producto)
                inv.compra_para_servicio(
                    extra["producto"], extra["comprada"], extra["usada"], extra["importe"], servicio.id,
                    proveedor=extra["proveedor"], fecha_caducidad=extra["fecha_caducidad"],
                )
            except ValueError as e:
                avisar("error", f"No se pudo registrar la compra de '{extra['producto']}': {e}")
        else:
            gastos.agregar_gasto(Gasto(extra["concepto"], extra["categoria"], extra["importe"], servicio_id=servicio.id,
                                       notas="Coste no previsto, añadido al completar el servicio"))
    if extras:
        avisar("info", f"💶 {len(extras)} coste(s) adicional(es) registrado(s) para el servicio "
                       f"({sum(e['importe'] for e in extras):.2f} €).")
    st.session_state[f"extras_{servicio.id}"] = []


def _texto_reparto(fila: dict) -> str:
    if not fila["reparto"]:
        return "—"
    partes = [f"{_num(cantidad)} {fila['unidad']} del lote {lote_id}" for lote_id, cantidad in fila["reparto"]]
    if fila["sin_asignar"] > 1e-9:
        partes.append(f"⚠️ {_num(fila['sin_asignar'])} {fila['unidad']} sin lote elegido")
    return " + ".join(partes)


def _texto_euros(valor: Optional[float]) -> str:
    return "—" if valor is None else f"{valor:.2f} €"


def _pestana_rentabilidad(serv: RegistroServicios, inv: Inventario, rec: Recetario) -> None:
    gastos = st.session_state.registro_gastos
    material = st.session_state.registro_material
    servicios = sorted((s for s in serv.servicios if s.estado != "cancelado"), key=lambda s: (s.fecha, s.hora))
    if not servicios:
        st.info("No hay servicios.")
        return

    st.caption(
        "Coste = comida + consumibles + gastos del servicio (gasolina, personal...) + material roto o perdido. En los servicios completados es "
        "lo que salió de verdad del inventario; en los pendientes, una estimación (*) con los precios actuales."
    )
    filas = []
    for s in servicios:
        r = resumen_servicio(s, inv, rec, gastos, material)
        filas.append({
            "Servicio": f"#{s.id} · {s.fecha.strftime('%d/%m/%Y')} · {s.menu}", "Comensales": s.comensales,
            "Estado": s.estado, "Cobro (€)": _texto_euros(r["cobrado"]),
            "Coste (€)": _texto_euros(r["coste_total"]) + (" *" if r["estimado"] else ""),
            "Margen (€)": _texto_euros(r["margen"]),
            "Margen (%)": f"{r['margen_porcentaje']:.0%}" if r["margen_porcentaje"] is not None else "—",
        })
    st.dataframe(filas, width="stretch", hide_index=True)

    st.subheader("Detalle de un servicio")
    opciones = {f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}": s for s in servicios}
    servicio = opciones[st.selectbox("Servicio", list(opciones), key="rentabilidad_select")]
    r = resumen_servicio(servicio, inv, rec, gastos, material)
    m1, m2, m3 = st.columns(3)
    m1.metric("Cobro", _texto_euros(r["cobrado"]))
    m2.metric("Coste" + (" (estimado)" if r["estimado"] else ""), _texto_euros(r["coste_total"]))
    m3.metric("Margen", _texto_euros(r["margen"]),
              delta=f"{r['margen_porcentaje']:.0%}" if r["margen_porcentaje"] is not None else None)
    desglose = [
        {"Concepto": "🍅 Comida", "Importe (€)": f"{r['comida']:.2f}"},
        {"Concepto": "🧻 Consumibles", "Importe (€)": f"{r['consumibles']:.2f}"},
    ] + [{"Concepto": f"💶 {cat}", "Importe (€)": f"{imp:.2f}"} for cat, imp in r["gastos_por_categoria"].items()]
    if r["material"]:
        desglose.append({"Concepto": "🍽️ Material roto o perdido", "Importe (€)": f"{r['material']:.2f}"})
    st.dataframe(desglose, width="stretch", hide_index=True)
    gastos_servicio = gastos.gastos_de_servicio(servicio.id)
    if gastos_servicio:
        st.caption("Gastos de este servicio: " + "; ".join(f"{g.concepto} ({g.importe:.2f} €)" for g in gastos_servicio))
    else:
        st.caption("Este servicio no tiene gastos apuntados. Se añaden en la página 'Gastos'.")

    k = lambda campo: f"cobro_{campo}_{servicio.id}"
    c1, c2 = st.columns([2, 1])
    nuevo_precio = c1.number_input(
        "Precio de cobro del servicio entero (€)", min_value=0.0, step=10.0,
        value=float(servicio.precio_cobrado or 0.0), key=k("precio"),
    )
    if c2.button("Guardar precio", key=k("guardar")):
        servicio.precio_cobrado = nuevo_precio if nuevo_precio > 0 else None
        avisar("success", f"Precio de cobro del servicio #{servicio.id} guardado.")
        st.rerun()
    st.caption("Pon 0 para quitar el precio de cobro.")


def pagina_servicios() -> None:
    st.header("📅 Servicios")
    serv = st.session_state.registro_servicios
    inv = st.session_state.inventario
    rec = st.session_state.recetario

    if serv.servicios:
        filas = [{
            "ID": s.id, "Fecha": s.fecha.strftime("%d/%m/%Y"), "Hora": s.hora.strftime("%H:%M"),
            "Comensales": s.comensales, "Menú": s.menu, "Estado": s.estado,
            "Cliente": s.cliente or "—", "Lugar": s.lugar or "—",
            "Cobro (€)": _num(s.precio_cobrado) if s.precio_cobrado is not None else "—", "Notas": s.notas,
        } for s in sorted(serv.servicios, key=lambda s: (s.fecha, s.hora))]
        st.dataframe(filas, width="stretch", hide_index=True)
    else:
        st.info("No hay servicios registrados.")

    st.divider()
    tab_add, tab_cancel, tab_completar, tab_material, tab_rentabilidad = st.tabs(
        ["➕ Añadir servicio", "🚫 Cancelar servicio", "✅ Completar servicio", "🚚 Material", "💶 Rentabilidad"]
    )

    with tab_material:
        _pestana_material_servicio(serv, rec)
    with tab_rentabilidad:
        _pestana_rentabilidad(serv, inv, rec)

    with tab_add:
        with st.form("form_add_servicio", clear_on_submit=True):
            c1, c2 = st.columns(2)
            fecha = c1.date_input("Fecha")
            hora = c2.time_input("Hora")
            comensales = st.number_input("Comensales", min_value=1, step=1)
            menu_nombre = st.text_input("Nombre del menú")
            c5, c6 = st.columns(2)
            cliente = c5.text_input("Cliente (opcional)", placeholder="Ej: Familia García")
            lugar = c6.text_input("Lugar (opcional)", placeholder="Ej: Finca Los Olivos, Écija")
            notas = st.text_area("Notas (opcional)")
            c3, c4 = st.columns(2)
            precio = c3.number_input(
                "Precio de cobro (€, opcional)", min_value=0.0, step=10.0,
                help="Déjalo en 0 si no quieres indicarlo. Solo sirve para calcular el margen del servicio.",
            )
            forma_precio = c4.radio("El precio es", ["Total del servicio", "Por comensal"], horizontal=True)
            enviado = st.form_submit_button("Añadir servicio", type="primary")
            if enviado:
                precio_cobrado = None
                if precio > 0:
                    precio_cobrado = round(precio * comensales, 2) if forma_precio == "Por comensal" else precio
                try:
                    serv.agregar_servicio(Servicio(
                        fecha, hora, int(comensales), menu_nombre, notas, precio_cobrado=precio_cobrado,
                        cliente=cliente, lugar=lugar,
                    ))
                    st.success("Servicio añadido.")
                except ValueError as e:
                    st.error(str(e))

    with tab_cancel:
        if not serv.servicios:
            st.info("No hay servicios.")
        else:
            opciones = {f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}": s.id for s in serv.servicios}
            elegido = st.selectbox("Servicio a cancelar", list(opciones.keys()), key="cancelar_select")
            if st.button("Cancelar servicio"):
                serv.cancelar_servicio(opciones[elegido])
                avisar("success", "Servicio cancelado.")
                st.rerun()

    with tab_completar:
        pendientes = [s for s in serv.servicios if s.estado not in ("completado", "cancelado")]
        if not pendientes:
            st.info("No hay servicios pendientes de completar.")
        else:
            opciones2 = {f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}": s.id for s in pendientes}
            elegido2 = st.selectbox("Servicio a completar", list(opciones2.keys()), key="completar_select")
            servicio = serv.buscar_por_id(opciones2[elegido2])

            # Primero se eligen los lotes; después, la vista previa muestra
            # exactamente qué saldrá de cada uno ANTES de pulsar el botón.
            elecciones = _elegir_lotes_servicio(servicio, inv, rec)
            filas = rec.previsualizar_consumo(servicio, inv, elecciones)

            if filas is None:
                st.warning(
                    f"El menú '{servicio.menu}' no existe en el recetario: si completas el servicio, "
                    "no se descontará nada del inventario."
                )
            else:
                st.caption(f"Se descontará para {servicio.comensales} comensales (motivo: consumo). 🧻 = consumible:")
                st.dataframe([{
                    "Ingrediente": ("🧻 " if f["tipo"] == "consumible" else "") + f["ingrediente"],
                    "Necesario": f"{_num(f['necesario'])} {f['unidad']}",
                    "En stock": f"{_num(f['en_stock'])} {f['unidad']}" if f["existe"] else "no existe",
                    "Se descontará": f"{_num(f['a_descontar'])} {f['unidad']}",
                    "De qué lotes": _texto_reparto(f),
                    "Faltaba": f"{f['faltante']} {f['unidad']}" if f["faltante"] > 0 else "—",
                } for f in filas], width="stretch", hide_index=True)

                cortos = [f for f in filas if f["faltante"] > 0]
                if cortos:
                    st.warning(
                        "No hay stock suficiente de: " + ", ".join(f["ingrediente"] for f in cortos)
                        + ". Se descontará todo lo disponible de todos sus lotes (quedará a 0)."
                    )

            extras = _costes_adicionales(servicio)
            valoracion = st.text_area(
                "📝 ¿Cómo fue? (opcional)", key=f"valoracion_{servicio.id}",
                placeholder="Incidencias, qué sobró o faltó, qué cambiar la próxima vez...",
                help="Queda guardado en el historial del servicio. Se puede añadir o cambiar después.",
            )

            if st.button("Completar servicio", type="primary"):
                if filas is None:
                    servicio.completar()
                    servicio.valoracion = valoracion.strip()
                    _registrar_costes_adicionales(servicio, extras)
                    avisar("warning", f"Servicio #{servicio.id} completado sin descontar stock (menú no encontrado).")
                    st.rerun()
                try:
                    rec.completar_servicio(servicio, inv, elecciones)
                except ValueError as e:
                    st.error(str(e))
                else:
                    servicio.valoracion = valoracion.strip()
                    _registrar_costes_adicionales(servicio, extras)
                    cortos = [f["ingrediente"] for f in filas if f["faltante"] > 0]
                    if cortos:
                        avisar(
                            "warning",
                            f"Servicio #{servicio.id} completado. Stock insuficiente de: {', '.join(cortos)} "
                            "(se descontó todo lo que había).",
                        )
                    else:
                        avisar("success", f"Servicio #{servicio.id} completado y stock descontado correctamente.")
                    st.rerun()


# ---------- Página: Historial de servicios ----------

def pagina_historial() -> None:
    st.header("📜 Historial de servicios")
    serv = st.session_state.registro_servicios
    inv = st.session_state.inventario
    rec = st.session_state.recetario
    gastos = st.session_state.registro_gastos
    material = st.session_state.registro_material

    c1, c2, c3 = st.columns(3)
    periodo = c1.selectbox("Periodo", PERIODOS_VALIDOS, index=PERIODOS_VALIDOS.index("todo"), key="hist_periodo")
    menus = sorted({s.menu for s in serv.servicios})
    menu = c2.selectbox("Menú", ["Todos"] + menus, key="hist_menu")
    cliente = c3.selectbox("Cliente", ["Todos"] + historial.clientes(serv), key="hist_cliente")
    c4, c5 = st.columns([3, 1])
    texto = c4.text_input("Buscar", key="hist_texto", placeholder="Cliente, lugar, notas, valoración...")
    cancelados = c5.checkbox("Ver cancelados", key="hist_cancelados")
    desde, _ = rango_desde_periodo(periodo)
    hasta = date.max  # un servicio completado es historial aunque su fecha sea futura
    lista = historial.filtrar_servicios(
        serv, desde, hasta, None if menu == "Todos" else menu, None if cliente == "Todos" else cliente,
        texto, cancelados,
    )
    if not lista:
        st.info("No hay servicios completados con estos filtros. Los servicios aparecen aquí al completarlos.")
        return

    # --- Resumen del periodo ---
    r = historial.resumen_periodo(lista, inv, rec, gastos, material)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Servicios", r["servicios"])
    m2.metric("Comensales", r["comensales"])
    # Sin ningún servicio con precio de cobro, "0 €" confundiría: no es que no se cobrara, es que no se apuntó.
    m3.metric("Facturado", _texto_euros(r["facturado"] if r["margen"] is not None else None))
    m4.metric("Margen", _texto_euros(r["margen"]),
              delta=f"{r['margen_porcentaje']:.0%}" if r["margen_porcentaje"] is not None else None)
    detalles = [f"Coste total {r['coste']:.2f} €"]
    if r["coste_por_comensal"] is not None:
        detalles.append(f"coste medio por comensal {r['coste_por_comensal']:.2f} €")
    if r["menu_mas_repetido"]:
        detalles.append(f"menú más repetido: {r['menu_mas_repetido']}")
    if r["menu_mas_rentable"]:
        detalles.append(f"más rentable por comensal: {r['menu_mas_rentable']}")
    if r["servicios_sin_cobro"]:
        detalles.append(f"{r['servicios_sin_cobro']} sin precio de cobro (no cuentan en el margen)")
    st.caption(" · ".join(detalles))

    filas = []
    for s in lista:
        rs = resumen_servicio(s, inv, rec, gastos, material)
        filas.append({
            "Nº": s.id, "Fecha": s.fecha.strftime("%d/%m/%Y"), "Cliente": s.cliente or "—", "Lugar": s.lugar or "—",
            "Menú": s.menu, "Comensales": s.comensales, "Estado": s.estado,
            "Cobro (€)": _texto_euros(rs["cobrado"]), "Coste (€)": _texto_euros(rs["coste_total"]),
            "Margen (€)": _texto_euros(rs["margen"]),
            "Margen (%)": f"{rs['margen_porcentaje']:.0%}" if rs["margen_porcentaje"] is not None else "—",
        })
    st.dataframe(filas, width="stretch", hide_index=True)
    margenes = [(f"#{s.id} {s.fecha.strftime('%d/%m')}", resumen_servicio(s, inv, rec, gastos, material)["margen"])
                for s in reversed(lista) if s.estado == "completado"]
    margenes = [(n, m) for n, m in margenes if m is not None]
    if margenes:
        st.bar_chart(pd.DataFrame(margenes, columns=["Servicio", "Margen (€)"]).set_index("Servicio"))

    # --- Ficha de un servicio ---
    st.divider()
    st.subheader("Ficha del servicio")
    opciones = {f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}" + (f" - {s.cliente}" if s.cliente else ""): s
                for s in lista}
    servicio = opciones[st.selectbox("Servicio", list(opciones), key="hist_ficha")]
    _ficha_servicio(servicio, inv, rec, gastos, material)


def _ficha_servicio(servicio: Servicio, inv: Inventario, rec: Recetario, gastos: RegistroGastos,
                    material: RegistroMaterial) -> None:
    f = historial.ficha(servicio, inv, rec, gastos, material)
    r = f["rentabilidad"]
    k = lambda campo: f"hist_{campo}_{servicio.id}"

    completado = servicio.fecha_completado.strftime("%d/%m/%Y") if servicio.fecha_completado else "—"
    st.markdown(
        f"**{servicio.menu}** · {servicio.fecha.strftime('%d/%m/%Y')} a las {servicio.hora.strftime('%H:%M')} · "
        f"{servicio.comensales} comensales · {servicio.estado} (completado el {completado})"
    )
    if servicio.notas:
        st.caption(f"Notas: {servicio.notas}")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Cobro", _texto_euros(r["cobrado"]))
    m2.metric("Coste", _texto_euros(r["coste_total"]))
    m3.metric("Margen", _texto_euros(r["margen"]),
              delta=f"{r['margen_porcentaje']:.0%}" if r["margen_porcentaje"] is not None else None)
    m4.metric("Coste por comensal", f"{f['coste_por_comensal']:.2f} €")

    tab_gasto, tab_plan, tab_gastos, tab_material, tab_menu = st.tabs(
        ["🍅 Lo que se gastó", "📋 Previsto frente a real", "💶 Gastos", "🍽️ Material", "📖 Menú"]
    )
    with tab_gasto:
        if f["consumos"]:
            st.dataframe([{
                "Producto": ("🧻 " if c["tipo"] == "consumible" else "") + c["producto"],
                "Cantidad": f"{_num(c['cantidad'])} {c['unidad']}", "Lote": c["lote"], "Coste (€)": f"{c['coste']:.2f}",
            } for c in f["consumos"]], width="stretch", hide_index=True)
            st.caption(f"Comida {r['comida']:.2f} € · consumibles {r['consumibles']:.2f} € (a precio real de cada lote)")
        else:
            st.info("No salió nada del inventario para este servicio.")
    with tab_plan:
        if f["previsto_frente_a_real"]:
            st.dataframe([{
                "Producto": p["producto"], "Previsto": f"{_num(p['previsto'])} {p['unidad']}",
                "Real": f"{_num(p['real'])} {p['unidad']}",
                "Diferencia": "—" if abs(p["diferencia"]) < 1e-9 else f"{p['diferencia']:+g} {p['unidad']}",
            } for p in f["previsto_frente_a_real"]], width="stretch", hide_index=True)
            st.caption("Diferencia negativa: salió menos de lo que pedía el menú (normalmente faltaba stock). "
                       "Positiva: se usó más (compras de urgencia).")
        else:
            st.info("No hay datos del menú de este servicio.")
    with tab_gastos:
        if f["gastos"]:
            st.dataframe([{"Concepto": g.concepto, "Categoría": g.categoria, "Importe (€)": f"{g.importe:.2f}",
                           "Notas": g.notas} for g in f["gastos"]], width="stretch", hide_index=True)
        else:
            st.info("Este servicio no tiene gastos apuntados.")
    with tab_material:
        if f["salidas_material"]:
            for salida in f["salidas_material"]:
                estado = f"volvió el {salida.fecha_vuelta.strftime('%d/%m/%Y')}" if salida.ha_vuelto else "🚚 todavía fuera"
                st.caption(f"Salió el {salida.fecha_salida.strftime('%d/%m/%Y')} · {estado}")
                st.dataframe([{"Material": n, "Salieron": c,
                               "Volvieron": salida.vuelto.get(n, 0) if salida.ha_vuelto else "—"}
                              for n, c in salida.cantidades.items()], width="stretch", hide_index=True)
            for i in f["incidencias_material"]:
                st.write(f"💥 {i.tipo.capitalize()}: {i.cantidad} x {i.material} ({i.coste:.2f} €)")
        else:
            st.info("No se llevó material registrado a este servicio.")
    with tab_menu:
        foto = servicio.menu_completado
        if not foto:
            st.info("No hay copia del menú (el servicio se completó antes de existir el historial, o el menú no existía).")
        else:
            st.caption("Así era el menú cuando se completó el servicio (aunque después se haya cambiado).")
            for receta in foto["recetas"]:
                st.markdown(f"**{receta['nombre']}** · {receta['categoria']}")
                st.write(", ".join(f"{n} {_num(c)}/comensal" for n, c in receta["ingredientes_por_comensal"].items()))
            if foto.get("consumibles_por_comensal"):
                st.write("🧻 " + ", ".join(f"{n} {_num(c)}/comensal" for n, c in foto["consumibles_por_comensal"].items()))
            if foto.get("materiales_por_comensal"):
                st.write("🍽️ " + ", ".join(f"{n} {_num(c)}/comensal" for n, c in foto["materiales_por_comensal"].items()))

    st.markdown("**Datos del servicio**")
    c1, c2 = st.columns(2)
    cliente = c1.text_input("Cliente", value=servicio.cliente, key=k("cliente"))
    lugar = c2.text_input("Lugar", value=servicio.lugar, key=k("lugar"))
    valoracion = st.text_area("📝 ¿Cómo fue?", value=servicio.valoracion, key=k("valoracion"),
                              placeholder="Incidencias, qué sobró o faltó, qué cambiar la próxima vez...")
    if st.button("Guardar", key=k("guardar")):
        servicio.cliente, servicio.lugar, servicio.valoracion = cliente.strip(), lugar.strip(), valoracion.strip()
        avisar("success", f"Servicio #{servicio.id} actualizado.")
        st.rerun()

    st.markdown("**🔁 Repetir este servicio**")
    st.caption("Crea un servicio nuevo con el mismo menú, comensales, precio, cliente y lugar.")
    c3, c4, c5 = st.columns([2, 2, 1])
    fecha = c3.date_input("Fecha", key=k("repetir_fecha"))
    hora = c4.time_input("Hora", value=servicio.hora, key=k("repetir_hora"))
    if c5.button("Repetir", key=k("repetir")):
        nuevo = historial.repetir_servicio(st.session_state.registro_servicios, servicio, fecha, hora)
        avisar("success", f"Creado el servicio #{nuevo.id} para el {fecha.strftime('%d/%m/%Y')} (pendiente).")
        st.rerun()


# ---------- Página: Recetario ----------

def _texto_cantidades(cantidades: dict[str, float], inv: Inventario) -> str:
    partes = []
    for nombre, cantidad in cantidades.items():
        producto = inv.buscar_producto(nombre)
        partes.append(f"{nombre} {_num(cantidad)} {producto.unidad if producto else ''}".strip())
    return ", ".join(partes) or "—"


def _editor_consumibles(inv: Inventario, clave: str, actuales: dict[str, float]) -> dict[str, float]:
    """
    Elegir los consumibles de un menú y cuántos se gastan por comensal.
    Devuelve {consumible: cantidad por comensal} (sin los que estén a 0).
    """
    disponibles = [p.nombre for p in inv.consumibles()]
    if not disponibles:
        st.caption("🧻 No hay consumibles en el inventario (servilletas, vasos desechables...). Puedes añadirlos en Inventario > Consumibles.")
        return {}
    elegidos = st.multiselect(
        "🧻 Consumibles por comensal (opcional)", disponibles,
        default=[n for n in actuales if n in disponibles], key=f"{clave}_consumibles",
        help="Lo que se gasta por cada comensal y no es comida: servilletas, vasos desechables...",
    )
    resultado = {}
    for nombre in elegidos:
        unidad = inv.buscar_producto(nombre).unidad
        cantidad = st.number_input(
            f"{nombre}: cantidad por comensal ({unidad})", min_value=0.0, step=0.5,
            value=float(actuales.get(nombre, 1.0)), key=f"{clave}_cons_{nombre}",
        )
        if cantidad > 0:
            resultado[nombre] = cantidad
    return resultado


def _editor_material(clave: str, actuales: dict[str, float]) -> dict[str, float]:
    """Elegir el material que lleva un menú y cuántas unidades por comensal (para la lista de carga)."""
    reg = st.session_state.registro_material
    disponibles = list(reg.materiales)
    if not disponibles:
        st.caption("🍽️ No hay material registrado (platos, copas, cubiertos...). Puedes añadirlo en Inventario > Material.")
        return {}
    elegidos = st.multiselect(
        "🍽️ Material por comensal (opcional)", disponibles,
        default=[n for n in actuales if n in disponibles], key=f"{clave}_materiales",
        help="Platos, copas, cubiertos... por cada comensal. Sirve para proponer la lista de carga del servicio.",
    )
    resultado = {}
    for nombre in elegidos:
        cantidad = st.number_input(
            f"{nombre}: unidades por comensal", min_value=0.0, step=0.5,
            value=float(actuales.get(nombre, 1.0)), key=f"{clave}_mat_{nombre}",
        )
        if cantidad > 0:
            resultado[nombre] = cantidad
    return resultado


def _tarjeta_menu(menu: Menu, inv: Inventario, rec: Recetario) -> None:
    """Un menú: a simple vista, su comida; al entrar, el detalle de cada receta y sus consumibles."""
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"**{menu.nombre}**")
        c1.caption("Recetas: " + (", ".join(r.nombre for r in menu.recetas) or "—"))
        c2.metric("Comida por comensal", f"{menu.costo_por_comensal(inv)} €")
        st.write("Ingredientes por comensal: " + _texto_cantidades(menu.ingredientes_por_comensal(), inv))

        with st.expander("🔎 Ver detalle del menú"):
            for receta in menu.recetas:
                st.markdown(f"**{receta.nombre}** · {receta.categoria} · {receta.costo_por_comensal(inv)} €/comensal")
                filas = []
                for nombre, cantidad in receta.ingredientes_por_comensal.items():
                    producto = inv.buscar_producto(nombre)
                    filas.append({
                        "Ingrediente": nombre,
                        "Por comensal": f"{_num(cantidad)} {producto.unidad if producto else ''}",
                        "Coste (€)": _num(cantidad * producto.precio_unitario) if producto else "—",
                    })
                st.dataframe(filas, width="stretch", hide_index=True)

            st.markdown("**🧻 Consumibles**")
            if menu.consumibles_por_comensal:
                st.dataframe([{
                    "Consumible": nombre,
                    "Por comensal": f"{_num(cantidad)} {inv.buscar_producto(nombre).unidad if inv.buscar_producto(nombre) else ''}",
                    "Coste (€)": _num(cantidad * inv.buscar_producto(nombre).precio_unitario) if inv.buscar_producto(nombre) else "—",
                } for nombre, cantidad in menu.consumibles_por_comensal.items()], width="stretch", hide_index=True)
            else:
                st.caption("Este menú no tiene consumibles.")
            total = round(menu.costo_por_comensal(inv) + menu.costo_consumibles_por_comensal(inv), 2)
            st.caption(
                f"Coste por comensal: comida {menu.costo_por_comensal(inv)} € + consumibles "
                f"{menu.costo_consumibles_por_comensal(inv)} € = **{total} €**"
            )

            st.markdown("**🍽️ Material**")
            if menu.materiales_por_comensal:
                st.dataframe([{"Material": nombre, "Unidades por comensal": _num(cantidad)}
                              for nombre, cantidad in menu.materiales_por_comensal.items()], width="stretch", hide_index=True)
                st.caption("No es un coste: el material vuelve. Sirve para proponer la lista de carga de cada servicio.")
            else:
                st.caption("Este menú no tiene material asignado.")

            st.markdown("**Cambiar los consumibles del menú**")
            nuevos = _editor_consumibles(inv, f"menu_{menu.nombre}", menu.consumibles_por_comensal)
            if inv.consumibles() and st.button("Guardar consumibles", key=f"menu_{menu.nombre}_guardar"):
                menu.consumibles_por_comensal = nuevos
                avisar("success", f"Consumibles del menú '{menu.nombre}' guardados.")
                st.rerun()

            st.markdown("**Cambiar el material del menú**")
            nuevo_material = _editor_material(f"menu_{menu.nombre}", menu.materiales_por_comensal)
            if st.session_state.registro_material.materiales and st.button(
                "Guardar material", key=f"menu_{menu.nombre}_guardar_material"
            ):
                menu.materiales_por_comensal = nuevo_material
                avisar("success", f"Material del menú '{menu.nombre}' guardado.")
                st.rerun()


def pagina_recetario() -> None:
    st.header("👩‍🍳 Recetario")
    inv = st.session_state.inventario
    rec = st.session_state.recetario

    tab_recetas, tab_menus, tab_crear_receta, tab_crear_menu, tab_recomendar = st.tabs(
        ["Recetas", "Menús", "➕ Crear receta", "➕ Crear menú", "🔥 Recomendador"]
    )

    with tab_recetas:
        if not rec.recetas:
            st.info("No hay recetas todavía.")
        for r in rec.recetas.values():
            st.write(f"{r}  💶 {r.costo_por_comensal(inv)}€/comensal")

    with tab_menus:
        if not rec.menus:
            st.info("No hay menús todavía.")
        for m in rec.menus.values():
            _tarjeta_menu(m, inv, rec)

    with tab_crear_receta:
        if not inv.alimentos():
            st.warning("No hay alimentos en el inventario. Añade productos primero.")
        else:
            # Las recetas solo llevan alimentos: los consumibles van en el menú.
            nombre_ing = st.selectbox("Ingrediente", [p.nombre for p in inv.alimentos()], key="ing_select")
            producto_ing = inv.buscar_producto(nombre_ing)

            # Misma razón que en "Editar producto": la key incluye
            # `nombre_ing` para que cambiar de ingrediente cuente como un
            # campo distinto. Aquí es aún más importante, porque sin esto
            # el radio podría arrastrar un valor ("g") que ya no es una
            # opción válida al cambiar a un ingrediente en litros/ml.
            if producto_ing.unidad in ("kg", "g"):
                unidad_elegida = st.radio(
                    "Unidad para esta cantidad", ("kg", "g"), key=f"unidad_ing_{nombre_ing}", horizontal=True
                )
            elif producto_ing.unidad in ("litros", "ml"):
                unidad_elegida = st.radio(
                    "Unidad para esta cantidad", ("litros", "ml"), key=f"unidad_ing_{nombre_ing}", horizontal=True
                )
            else:
                unidad_elegida = producto_ing.unidad
                st.caption(f"'{producto_ing.nombre}' está en '{producto_ing.unidad}', sin conversión.")

            cantidad_ing = st.number_input(
                f"Cantidad por comensal (en {unidad_elegida})",
                min_value=0.0, step=0.01, key=f"cantidad_ing_{nombre_ing}",
            )

            if st.button("➕ Añadir ingrediente a la receta"):
                if unidad_elegida != producto_ing.unidad:
                    factor = FACTORES_CONVERSION[(unidad_elegida, producto_ing.unidad)]
                    cantidad_final = round(cantidad_ing * factor, 6)
                else:
                    cantidad_final = cantidad_ing
                st.session_state.receta_ingredientes[producto_ing.nombre] = cantidad_final
                st.rerun()

            if st.session_state.receta_ingredientes:
                st.write("Ingredientes añadidos hasta ahora:")
                st.json(st.session_state.receta_ingredientes)

            with st.form("form_finalizar_receta"):
                nombre_receta = st.text_input("Nombre de la receta")
                categoria_receta = st.text_input("Categoría")
                crear = st.form_submit_button("Guardar receta", type="primary")
                if crear:
                    if not st.session_state.receta_ingredientes:
                        st.error("Añade al menos un ingrediente antes de guardar.")
                    elif not nombre_receta:
                        st.error("Ponle un nombre a la receta.")
                    else:
                        rec.agregar_receta(Receta(nombre_receta, categoria_receta, dict(st.session_state.receta_ingredientes)))
                        st.session_state.receta_ingredientes = {}
                        avisar("success", f"Receta '{nombre_receta}' creada.")
                        st.rerun()

    with tab_crear_menu:
        if not rec.recetas:
            st.warning("Crea al menos una receta primero.")
        else:
            nombre_menu = st.text_input("Nombre del menú", key="nombre_menu_input")
            recetas_elegidas = st.multiselect("Recetas a incluir", list(rec.recetas.keys()), key="recetas_multiselect")
            consumibles = _editor_consumibles(inv, "nuevo_menu", {})
            materiales = _editor_material("nuevo_menu", {})
            if st.button("Crear menú", type="primary"):
                if not nombre_menu or not recetas_elegidas:
                    st.error("Indica un nombre y al menos una receta.")
                else:
                    recetas_obj = [rec.recetas[n] for n in recetas_elegidas]
                    rec.agregar_menu(Menu(nombre_menu, recetas_obj, consumibles, materiales))
                    avisar("success", f"Menú '{nombre_menu}' creado.")
                    st.rerun()

    with tab_recomendar:
        if not rec.menus:
            st.info("No hay menús todavía.")
        else:
            c1, c2 = st.columns(2)
            dias = c1.slider("Ventana de caducidad (días)", 1, 30, 7, key="dias_recomendar")
            comensales = c2.number_input("Comensales a comprobar", min_value=1, value=4, step=1, key="comensales_recomendar")

            for menu, puntuacion in rec.recomendar_menus(inv, dias):
                puede = menu.se_puede_preparar(inv, int(comensales))
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    col1.markdown(f"**{menu.nombre}**")
                    col2.metric("Urgencia", f"{puntuacion:.1f}")

                    if puede:
                        st.success("✅ Se puede preparar ya")
                    else:
                        st.warning("🛒 Faltaría comprar algo")

                    riesgo = menu.ingredientes_en_riesgo(inv, dias)
                    if riesgo:
                        detalle = ", ".join(f"{p.nombre} ({p.dias_para_caducar()}d)" for p in riesgo)
                        st.caption(f"⏳ Por caducidad: {detalle}")

                    exceso = menu.ingredientes_en_exceso(inv)
                    if exceso:
                        detalle = ", ".join(f"{p.nombre} ({p.stock} sobre mínimo {p.stock_minimo})" for p in exceso)
                        st.caption(f"📦 Por exceso de stock: {detalle}")


# ---------- Página: Compras ----------

def pagina_compras() -> None:
    st.header("🛒 Compras")
    comp = st.session_state.gestor_compras
    inv = st.session_state.inventario
    rec = st.session_state.recetario
    serv = st.session_state.registro_servicios

    with st.form("form_generar_compra"):
        dias = st.number_input("Servicios de cuántos días hacia adelante", min_value=1, value=7, step=1)
        generar = st.form_submit_button("Generar lista de compra", type="primary")
        if generar:
            servicios = serv.servicios_proximos(int(dias))
            if not servicios:
                st.info("No hay servicios próximos en ese rango.")
            else:
                avisos = comp.generar_lista_desde_servicios(servicios, rec, inv)
                avisar("success", "Lista de compra generada/actualizada.")
                for aviso in avisos:
                    avisar("info", aviso)
                st.rerun()

    st.divider()
    pendientes = comp.items_pendientes()
    if not pendientes:
        st.success("No hay compras pendientes 🎉")
    else:
        agrupado = comp.agrupar_por_proveedor()
        for proveedor, items in agrupado.items():
            st.subheader(f"📋 {proveedor}")
            filas = [
                {"Ingrediente": i.ingrediente, "Cantidad": i.cantidad, "Unidad": i.unidad, "Coste (€)": i.costo_estimado()}
                for i in items
            ]
            st.dataframe(filas, width="stretch", hide_index=True)

        st.metric("💰 Coste total pendiente", f"{comp.costo_total_pendiente()} €")

        st.divider()
        nombre_marcar = st.selectbox("Marcar como comprado", [i.ingrediente for i in pendientes], key="marcar_comprado_select")
        item_marcar = next((i for i in comp.items if i.ingrediente == nombre_marcar and not i.comprado), None)

        if item_marcar is not None:
            st.caption(f"Cantidad calculada como necesaria: {item_marcar.cantidad} {item_marcar.unidad}")
            # key incluye nombre_marcar: si no, al cambiar de producto en el
            # selectbox de arriba, este campo seguiría mostrando la cantidad
            # del producto anterior (el mismo "gotcha" que ya vimos en Editar
            # producto y en Crear receta).
            cantidad_real = st.number_input(
                f"Cantidad realmente comprada (en {item_marcar.unidad})",
                min_value=0.0, value=float(item_marcar.cantidad), step=0.1,
                key=f"cantidad_real_{nombre_marcar}",
            )
            producto_marcar = inv.buscar_producto(nombre_marcar)
            if producto_marcar is None:
                st.warning(f"'{nombre_marcar}' no existe en el inventario: créalo antes en Inventario.")
                return
            st.caption("La compra entra en el inventario como un lote nuevo.")
            k = lambda campo: f"compra_{campo}_{nombre_marcar}"
            datos = _campos_entrada(producto_marcar, k)
            if st.button("Marcar como comprado y reponer inventario"):
                if datos["necesita_peso"] and datos["peso"] is None:
                    st.error("Indica el peso en bruto de cada unidad de este lote.")
                elif cantidad_real <= 0:
                    st.error("La cantidad comprada debe ser mayor que 0.")
                elif not datos["proveedor"].strip():
                    st.error("Indica el proveedor de este lote.")
                else:
                    lote = inv.entrada_stock(
                        nombre_marcar, cantidad_real, precio_unitario=datos["precio"], proveedor=datos["proveedor"],
                        fecha_caducidad=datos["fecha"], peso_unitario=datos["peso"],
                    )
                    if lote is None:
                        st.error("No se ha registrado la compra: revisa los datos (el proveedor debe ser texto).")
                    else:
                        comp.marcar_comprado(nombre_marcar, cantidad_comprada=cantidad_real)
                        avisar(
                            "success",
                            f"'{nombre_marcar}' marcado como comprado y repuesto en inventario "
                            f"(+{cantidad_real} {item_marcar.unidad}, {lote.etiqueta()}).",
                        )
                        st.rerun()


# ---------- Página: Gastos ----------

def pagina_gastos() -> None:
    st.header("💶 Gastos")
    st.caption(
        "Lo que se paga y no es inventario: gasolina, peajes, personal extra, alquileres, lavandería, seguros... "
        "Si un gasto es de un servicio concreto, asócialo: así cuenta en su coste y en su margen."
    )
    gastos = st.session_state.registro_gastos
    serv = st.session_state.registro_servicios

    tab_nuevo, tab_lista = st.tabs(["➕ Registrar gasto", "📋 Gastos registrados"])

    with tab_nuevo:
        v = st.session_state.setdefault("gasto_version", 0)
        k = lambda campo: f"gasto_{campo}_{v}"
        c1, c2 = st.columns(2)
        concepto = c1.text_input("Concepto", key=k("concepto"), placeholder="Ej: Gasolina boda García")
        categoria = c2.selectbox("Categoría", Gasto.CATEGORIAS, key=k("categoria"))
        c3, c4 = st.columns(2)
        importe = c3.number_input("Importe (€)", min_value=0.0, step=1.0, key=k("importe"))
        fecha = c4.date_input("Fecha", key=k("fecha"))
        general = "Gasto general del negocio (no es de un servicio)"
        opciones = {general: None}
        for s in sorted(serv.servicios, key=lambda s: (s.fecha, s.hora), reverse=True):
            if s.estado != "cancelado":
                opciones[f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}"] = s.id
        servicio_id = opciones[st.selectbox("¿De qué servicio es?", list(opciones), key=k("servicio"))]
        notas = st.text_input("Notas (opcional)", key=k("notas"), placeholder="Ej: 120 km ida y vuelta")
        if st.button("Registrar gasto", type="primary", key=k("boton")):
            try:
                gastos.agregar_gasto(Gasto(concepto, categoria, importe, fecha, servicio_id, notas))
                avisar("success", f"Gasto registrado: {concepto} ({importe:.2f} €).")
                st.session_state.gasto_version += 1
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    with tab_lista:
        periodo = st.selectbox("Periodo", PERIODOS_VALIDOS, index=1, key="gastos_periodo")
        desde, hasta = rango_desde_periodo(periodo)
        lista = gastos.gastos_en_rango(desde, hasta)
        if not lista:
            st.info("No hay gastos registrados en este periodo.")
            return
        st.dataframe([{
            "Nº": g.id, "Fecha": g.fecha.strftime("%d/%m/%Y"), "Concepto": g.concepto, "Categoría": g.categoria,
            "Importe (€)": f"{g.importe:.2f}", "Servicio": f"#{g.servicio_id}" if g.servicio_id else "General",
            "Notas": g.notas,
        } for g in reversed(lista)], width="stretch", hide_index=True)
        por_categoria = gastos.total_por_categoria(desde, hasta)
        st.metric("Total del periodo", f"{sum(por_categoria.values()):.2f} €")
        st.bar_chart(pd.DataFrame(list(por_categoria.items()), columns=["Categoría", "Gasto (€)"]).set_index("Categoría"))

        st.subheader("Eliminar un gasto")
        textos_gasto = {f"#{g.id} - {g.fecha.strftime('%d/%m/%Y')} - {g.concepto} ({g.importe:.2f} €)": g.id for g in reversed(lista)}
        elegido = st.selectbox("Gasto", list(textos_gasto), key="gasto_eliminar_select")
        if st.button("🗑️ Eliminar este gasto", key="gasto_eliminar_boton"):
            gastos.eliminar_gasto(textos_gasto[elegido])
            avisar("success", "Gasto eliminado.")
            st.rerun()


# ---------- Página: Exportar / Backup ----------

def pagina_exportar() -> None:
    st.header("📁 Exportar y backup")

    st.subheader("Exportar a Excel")
    if st.button("Generar Excel", type="primary"):
        carpeta = str(_carpeta_base() / "datos")
        ruta = exportar_todo(
            st.session_state.inventario, st.session_state.registro_servicios,
            st.session_state.gestor_compras, carpeta,
            st.session_state.registro_gastos, st.session_state.recetario, st.session_state.registro_material,
        )
        st.session_state.ultima_exportacion = ruta
        st.success(f"Exportado a {ruta}")

    if st.session_state.get("ultima_exportacion"):
        with open(st.session_state.ultima_exportacion, "rb") as f:
            st.download_button("⬇️ Descargar Excel", f, file_name=Path(st.session_state.ultima_exportacion).name)

    st.divider()
    st.subheader("Backup a Google Drive")
    st.caption("Necesita credentials.json configurado junto a app.py (ver instrucciones en google_drive_backup.py).")
    if st.button("Subir a Google Drive"):
        if not st.session_state.get("ultima_exportacion"):
            st.error("Exporta a Excel primero.")
        else:
            try:
                from google_drive_backup import subir_archivo
                subir_archivo(st.session_state.ultima_exportacion)
                st.success("Subido a Google Drive.")
            except ImportError:
                st.error("Faltan librerías. En tu terminal: pip install google-auth-oauthlib google-api-python-client")
            except FileNotFoundError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Error al subir a Google Drive: {e}")


# ---------- Página: Métricas ----------

def pagina_metricas() -> None:
    st.header("📊 Métricas")
    inv = st.session_state.inventario
    metricas = Metricas(inv)

    c1, c2 = st.columns(2)
    periodo = c1.selectbox("Periodo", PERIODOS_VALIDOS, index=1, key="periodo_metricas")
    tipo = VISTAS_PRODUCTOS[c2.radio("Productos", list(VISTAS_PRODUCTOS), horizontal=True, key="metricas_tipo")]
    desde, hasta = rango_desde_periodo(periodo)
    st.caption(f"Del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}")
    nombres_tipo = [p.nombre for p in (inv.consumibles() if tipo == "consumible" else inv.alimentos())]

    if not inv.historial:
        st.info(
            "Todavía no hay movimientos de stock registrados. Usa 'Actualizar stock' "
            "en Inventario (entradas y salidas) para empezar a generar datos."
        )
        return

    tab_consumo, tab_desperdicio, tab_ranking, tab_gasto, tab_merma = st.tabs(
        ["Consumo por producto", "Desperdicio por producto", "🏆 Más consumidos", "💰 Gasto por categoría", "🦴 Merma"]
    )

    with tab_merma:
        # La merma va aparte del desperdicio: el hueso es inevitable, lo que
        # caduca en la cámara no.
        resumen = metricas.resumen_limpiezas(desde, hasta)
        if tipo == "consumible":
            st.info("Los consumibles no tienen merma.")
        elif not resumen:
            st.info("No hay limpiezas registradas en este periodo.")
        else:
            st.metric("Merma total del periodo", f"{metricas.merma_total_kg(desde, hasta)} kg")
            st.dataframe([{
                "Producto": nombre,
                "Limpiezas": fila["limpiezas"],
                "Bruto (kg)": fila["bruto_kg"],
                "Limpio (kg)": fila["limpio_kg"],
                "Derivados (kg)": fila["derivados_kg"],
                "Merma (kg)": fila["merma_kg"],
                "Rendimiento": f"{fila['rendimiento']:.1%}",
            } for nombre, fila in resumen.items()], width="stretch", hide_index=True)
            df_merma = pd.DataFrame(
                {nombre: [fila["limpio_kg"], fila["derivados_kg"], fila["merma_kg"]] for nombre, fila in resumen.items()},
                index=["Limpio", "Derivados", "Merma"],
            ).T
            st.bar_chart(df_merma)

    with tab_consumo:
        if not nombres_tipo:
            st.info("No hay productos en esta lista.")
        else:
            nombre = st.selectbox("Producto", nombres_tipo, key="metricas_consumo_producto")
            cantidad = metricas.cantidad_consumida(nombre, desde, hasta)
            st.metric(f"Consumido de {nombre}", f"{cantidad} {inv.buscar_producto(nombre).unidad}")

    with tab_desperdicio:
        if nombres_tipo:
            nombre2 = st.selectbox("Producto", nombres_tipo, key="metricas_desperdicio_producto")
            cantidad2 = metricas.cantidad_desperdiciada(nombre2, desde, hasta)
            st.metric(f"Desperdiciado de {nombre2}", f"{cantidad2} {inv.buscar_producto(nombre2).unidad}")
        valor_total = metricas.valor_desperdiciado_total(desde, hasta, tipo)
        st.metric("Valor total desperdiciado (toda esta lista)", f"{valor_total} €")

    with tab_ranking:
        ranking = metricas.productos_mas_consumidos(desde, hasta, top=10, tipo=tipo)
        if not ranking:
            st.info("No hay datos de consumo en este periodo.")
        else:
            df_ranking = pd.DataFrame(ranking, columns=["Producto", "Cantidad consumida"]).set_index("Producto")
            st.bar_chart(df_ranking)
            st.dataframe(df_ranking.reset_index(), width="stretch", hide_index=True)

    with tab_gasto:
        gasto = metricas.gasto_por_categoria(desde, hasta, tipo)
        por_tipo = metricas.gasto_por_tipo(desde, hasta)
        st.caption(
            f"Gasto en compras del periodo: alimentos {por_tipo['alimento']} € · consumibles {por_tipo['consumible']} €"
        )
        if not gasto:
            st.info("No hay compras registradas en este periodo.")
        else:
            df_gasto = pd.DataFrame(list(gasto.items()), columns=["Categoría", "Gasto (€)"]).set_index("Categoría")
            st.bar_chart(df_gasto)
            st.dataframe(df_gasto.reset_index(), width="stretch", hide_index=True)
            st.metric("Gasto total", f"{round(sum(gasto.values()), 2)} €")

    st.divider()
    st.subheader("📁 Informes mensuales guardados")
    st.caption(
        "A diferencia de arriba (últimos N días desde hoy), esto compara MESES DE "
        "CALENDARIO archivados -- pensado para comparar la misma época en años distintos."
    )
    archivo = st.session_state.archivo_informes

    tab_generar, tab_ver, tab_comparar = st.tabs(["➕ Generar informe", "📋 Ver guardados", "⚖️ Comparar dos meses"])

    with tab_generar:
        c1, c2 = st.columns(2)
        año_gen = c1.number_input("Año", min_value=2000, max_value=2100, value=date.today().year, step=1, key="informe_año_gen")
        mes_gen = c2.selectbox(
            "Mes", list(range(1, 13)), index=date.today().month - 1,
            format_func=lambda m: NOMBRES_MESES[m].capitalize(), key="informe_mes_gen",
        )
        if st.button("Generar y guardar informe", type="primary"):
            archivo.generar_informe(inv, int(año_gen), mes_gen)
            avisar("success", f"Informe de {NOMBRES_MESES[mes_gen].capitalize()} {año_gen} generado y guardado.")
            st.rerun()

    with tab_ver:
        informes = archivo.listar_informes()
        if not informes:
            st.info("No hay informes guardados todavía.")
        else:
            filas = [{
                "Mes": f"{NOMBRES_MESES[i.mes].capitalize()} {i.año}",
                "Gasto total (€)": i.gasto_total,
                "Desperdicio (€)": i.valor_desperdiciado_total,
            } for i in informes]
            st.dataframe(filas, width="stretch", hide_index=True)

    with tab_comparar:
        informes = archivo.listar_informes()
        if len(informes) < 2:
            st.info("Necesitas al menos 2 informes guardados para poder comparar.")
        else:
            opciones = {f"{NOMBRES_MESES[i.mes].capitalize()} {i.año}": (i.año, i.mes) for i in informes}
            nombres_opciones = list(opciones.keys())
            c1, c2 = st.columns(2)
            elegido1 = c1.selectbox("Primer mes", nombres_opciones, key="comparar_mes_1")
            elegido2 = c2.selectbox("Segundo mes", nombres_opciones, index=min(1, len(nombres_opciones) - 1), key="comparar_mes_2")

            if st.button("Comparar"):
                año1, mes1 = opciones[elegido1]
                año2, mes2 = opciones[elegido2]
                resultado = archivo.comparar(año1, mes1, año2, mes2)

                if resultado:
                    c3, c4, c5 = st.columns(3)
                    c3.metric(f"Gasto — {elegido1}", f"{resultado['gasto_total_1']} €")
                    c4.metric(
                        f"Gasto — {elegido2}", f"{resultado['gasto_total_2']} €",
                        delta=f"{resultado['diferencia_gasto_total']:+} €", delta_color="inverse",
                    )
                    c5.metric(
                        "Diferencia en desperdicio", f"{resultado['diferencia_desperdicio']:+} €",
                        delta_color="inverse",
                    )

                    st.write("Gasto por categoría en ambos meses:")
                    informe1 = archivo.buscar_informe(año1, mes1)
                    informe2 = archivo.buscar_informe(año2, mes2)
                    categorias = sorted(set(informe1.gasto_por_categoria) | set(informe2.gasto_por_categoria))
                    df_comparacion = pd.DataFrame({
                        elegido1: [informe1.gasto_por_categoria.get(c, 0) for c in categorias],
                        elegido2: [informe2.gasto_por_categoria.get(c, 0) for c in categorias],
                    }, index=categorias)
                    st.bar_chart(df_comparacion)

                    st.write("Diferencia de gasto por categoría (segundo mes menos primero):")
                    filas_diff = [
                        {"Categoría": cat, "Diferencia (€)": diff}
                        for cat, diff in resultado["diferencia_por_categoria"].items()
                    ]
                    st.dataframe(filas_diff, width="stretch", hide_index=True)


# ---------- Programa principal ----------

inicializar_estado()

st.sidebar.markdown(
    """
    <div style="padding: 0.3rem 0 1.2rem 0;">
        <div style="font-family: 'Fraunces', serif; font-size: 1.6rem; font-weight: 500; color: #EDE6D9;">
            🍽️ Gestión Restaurante
        </div>
        <div style="font-size: 0.85rem; color: #A79E8E; margin-top: 0.1rem;">
            Cocina, sala y almacén
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
pagina = st.sidebar.radio(
    "Navegación",
    ["Dashboard", "Inventario", "Servicios", "Historial", "Recetario", "Compras", "Gastos", "Métricas", "Exportar / Backup"],
)

st.sidebar.divider()
if st.sidebar.button("💾 Guardar sesión"):
    guardar_sesion(
        st.session_state.inventario, st.session_state.registro_servicios,
        st.session_state.recetario, st.session_state.gestor_compras,
        st.session_state.archivo_informes, RUTA_SESION, st.session_state.registro_gastos,
        st.session_state.registro_material,
    )
    st.sidebar.success("Sesión guardada")

if st.sidebar.button("🧪 Cargar datos de ejemplo"):
    cargar_datos_ejemplo()
    st.sidebar.success("Datos de ejemplo cargados")
    st.rerun()

mostrar_avisos()

if pagina == "Dashboard":
    pagina_dashboard()
elif pagina == "Inventario":
    pagina_inventario()
elif pagina == "Servicios":
    pagina_servicios()
elif pagina == "Historial":
    pagina_historial()
elif pagina == "Recetario":
    pagina_recetario()
elif pagina == "Compras":
    pagina_compras()
elif pagina == "Gastos":
    pagina_gastos()
elif pagina == "Métricas":
    pagina_metricas()
elif pagina == "Exportar / Backup":
    pagina_exportar()
