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

sys.path.append(str(Path(__file__).parent / "modulos"))

import streamlit as st
import pandas as pd

from inventario import Inventario, Producto, MovimientoStock, FACTORES_CONVERSION, UNIDADES_PESO, convertir
from servicios import RegistroServicios, Servicio
from recetario import Recetario, Receta, Menu
from compras import GestorCompras
from exportador import exportar_todo
from persistencia import guardar_sesion, cargar_sesion
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

    resultado = cargar_sesion(RUTA_SESION) if Path(RUTA_SESION).exists() else None
    if resultado:
        inv, serv, rec, comp, informes = resultado
    else:
        inv, serv, rec, comp = Inventario(), RegistroServicios(), Recetario(), GestorCompras()
        informes = ArchivoInformes()

    st.session_state.inventario = inv
    st.session_state.registro_servicios = serv
    st.session_state.recetario = rec
    st.session_state.gestor_compras = comp
    st.session_state.archivo_informes = informes
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

    serv.agregar_servicio(Servicio(date.today() + timedelta(days=3), time(21, 0), 8, "Menú del día"))

    pan = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})
    rec.agregar_receta(pan)
    rec.agregar_receta(ensalada)
    rec.agregar_menu(Menu("Menú del día", [pan, ensalada]))


# ---------- Lotes: piezas de interfaz compartidas ----------

def _num(valor: float) -> str:
    """Número sin decimales sobrantes para mostrar: 2.0 -> '2', 0.30000001 -> '0.3'."""
    return f"{round(valor, 3):g}"


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
    if st.checkbox("¿Este lote tiene fecha de caducidad?", key=k("tiene_fecha")):
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
            "Caducidad": l.fecha_caducidad.strftime("%d/%m/%Y") if l.fecha_caducidad else "—", "Estado": estado,
        }
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

def _filas_inventario(productos: list) -> list[dict]:
    return [{
        "Nombre": p.nombre, "Categoría": p.categoria, "Stock": p.stock, "Unidad": p.unidad,
        "Mínimo": p.stock_minimo, "Precio medio (€)": round(p.precio_unitario, 2), "Proveedor habitual": p.proveedor,
        "Próxima caducidad": p.fecha_caducidad.strftime("%d/%m/%Y") if p.fecha_caducidad else "—",
        "Lotes": len(p.lotes),
        "Tipo": p.tipo_descripcion() or "—",
        # Siempre texto: si la columna mezcla números y "—", Streamlit
        # tiene que corregir los tipos por su cuenta (y avisa en la consola).
        "Peso/unidad (kg)": f"{round(p.peso_unitario, 2):g}" if p.peso_unitario else "—",
    } for p in productos]


def _campo_peso(etiqueta: str, clave: str, valor_kg: float = 0.0) -> Optional[float]:
    """Número + desplegable kg/g. Devuelve el peso en kg, o None si se deja a 0."""
    c1, c2 = st.columns([3, 1])
    unidad = c2.selectbox("Unidad del peso", UNIDADES_PESO, key=f"{clave}_unidad")
    valor_inicial = convertir(valor_kg, "kg", unidad) if valor_kg else 0.0
    valor = c1.number_input(etiqueta, min_value=0.0, value=float(valor_inicial), step=0.1, key=f"{clave}_{unidad}")
    return convertir(valor, unidad, "kg") if valor > 0 else None


def pagina_inventario() -> None:
    st.header("📦 Inventario")
    inv = st.session_state.inventario

    if inv.productos:
        vista = st.radio(
            "Mostrar", ["Todos", "Solo productos con merma y sus derivados"], horizontal=True, key="inv_vista"
        )
        productos = list(inv.productos.values())
        if vista != "Todos":
            productos = [p for p in productos if p.tiene_merma or p.origen or p.es_subproducto]
        st.dataframe(_filas_inventario(productos), width="stretch", hide_index=True)
        st.caption("Cada compra es un lote con su precio, proveedor y caducidad: los verás en la pestaña 'Lotes'.")
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
        bajo_minimo = inv.productos_bajo_minimo()
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

    with tab_add:
        _pestana_anadir(inv)
    with tab_edit:
        _pestana_editar(inv)
    with tab_stock:
        _pestana_stock(inv)
    with tab_lotes:
        _pestana_lotes(inv)
    with tab_limpiar:
        _pestana_limpiar(inv)
    with tab_limpiezas:
        _pestana_limpiezas(inv)


def _pestana_anadir(inv: Inventario) -> None:
    # "Versión" del formulario: al añadir un producto se incrementa, las keys
    # cambian y los campos aparecen vacíos otra vez (lo que hacía clear_on_submit).
    v = st.session_state.setdefault("add_version", 0)

    nombre = st.text_input("Nombre", key=f"add_nombre_{v}")
    categoria = st.text_input("Categoría", key=f"add_categoria_{v}")
    c1, c2 = st.columns(2)
    stock = c1.number_input("Stock inicial (será su primer lote)", min_value=0.0, step=0.1, key=f"add_stock_{v}")
    unidad = c2.selectbox("Unidad", Producto.UNIDADES_VALIDAS, key=f"add_unidad_{v}")

    tiene_merma = False
    peso_unitario = None
    if unidad in UNIDADES_PESO + ("unidades",):
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
    if stock > 0:
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
                    tiene_merma=tiene_merma, peso_unitario=peso_unitario,
                ))
                avisar("success", f"Producto '{nombre}' añadido.")
                st.session_state.add_version += 1
                st.rerun()
            except ValueError as e:
                st.error(str(e))


def _pestana_editar(inv: Inventario) -> None:
    if not inv.productos:
        st.info("No hay productos para editar.")
        return
    nombre_sel = st.selectbox("Producto a editar", list(inv.productos.keys()), key="editar_select")
    producto = inv.buscar_producto(nombre_sel)
    # Las keys incluyen `nombre_sel`: si no, Streamlit reutilizaría el
    # valor que ya tuviera guardado bajo esa key (el del producto
    # anterior) en vez de tomar el `value` nuevo que le pasamos aquí.
    k = lambda campo: f"edit_{campo}_{nombre_sel}"
    st.caption(
        "Aquí se corrigen los datos generales del producto. La cantidad, el precio, el proveedor "
        "y la caducidad de cada compra se corrigen en la pestaña 'Lotes'."
    )

    nuevo_nombre = st.text_input("Nombre", value=producto.nombre, key=k("nombre"))
    categoria = st.text_input("Categoría", value=producto.categoria, key=k("categoria"))
    c1, c2 = st.columns(2)
    stock_minimo = c1.number_input("Stock mínimo", value=float(producto.stock_minimo), min_value=0.0, step=0.1, key=k("stock_minimo"))
    proveedor = c2.text_input("Proveedor habitual", value=producto.proveedor, key=k("proveedor"))

    tiene_merma = producto.tiene_merma
    peso_unitario = None
    if producto.unidad in UNIDADES_PESO + ("unidades",):
        tiene_merma = st.checkbox("Producto con merma (se limpia o despieza)", value=producto.tiene_merma, key=k("merma"))
        if tiene_merma and producto.unidad == "unidades":
            peso_unitario = _campo_peso(
                "Peso por unidad de referencia (se propone al registrar compras)", k("peso"),
                producto.peso_unitario_referencia or producto.peso_unitario or 0.0,
            )
    if producto.tipo_descripcion() in ("Subproducto",) or producto.origen:
        st.caption(f"Este producto sale de una limpieza ({producto.tipo_descripcion()}).")

    if st.button("Guardar cambios", type="primary", key=k("boton")):
        recetas_afectadas = []
        if nuevo_nombre != producto.nombre:
            recetas_afectadas = [
                r for r in st.session_state.recetario.recetas.values()
                if producto.nombre in r.ingredientes_por_comensal
            ]
        nombre_original = producto.nombre
        try:
            exito = inv.editar_producto(
                nombre_sel,
                nuevo_nombre=nuevo_nombre if nuevo_nombre != producto.nombre else None,
                categoria=categoria, proveedor=proveedor, stock_minimo=stock_minimo,
                tiene_merma=tiene_merma, peso_unitario=peso_unitario,
            )
            if exito:
                if recetas_afectadas:
                    for receta in recetas_afectadas:
                        cantidad = receta.ingredientes_por_comensal.pop(nombre_original)
                        receta.ingredientes_por_comensal[nuevo_nombre] = cantidad
                    nombres = ", ".join(r.nombre for r in recetas_afectadas)
                    avisar("info", f"🔄 Recetas actualizadas: {nombres}")
                avisar("success", "Producto actualizado.")
                st.rerun()
            else:
                st.error(f"No se ha guardado: ya existe otro producto llamado '{nuevo_nombre}'.")
        except ValueError as e:
            st.error(str(e))


def _pestana_stock(inv: Inventario) -> None:
    if not inv.productos:
        st.info("No hay productos.")
        return
    nombre_sel = st.selectbox("Producto", list(inv.productos.keys()), key="stock_select")
    producto = inv.buscar_producto(nombre_sel)
    k = lambda campo: f"stock_{campo}_{nombre_sel}"

    es_entrada = st.radio(
        "Tipo de movimiento", ["Entrada (compra)", "Salida"], horizontal=True, key=k("tipo")
    ) == "Entrada (compra)"
    cantidad = st.number_input(f"Cantidad ({producto.unidad})", min_value=0.0, step=0.1, key=k("cantidad"))

    if es_entrada:
        st.caption("Cada compra se guarda como un lote nuevo, con su precio, proveedor y caducidad.")
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


def _pestana_lotes(inv: Inventario) -> None:
    if not inv.productos:
        st.info("No hay productos.")
        return
    nombre_sel = st.selectbox("Producto", list(inv.productos.keys()), key="lotes_select")
    producto = inv.buscar_producto(nombre_sel)
    if not producto.lotes:
        st.info(f"No queda ningún lote de '{nombre_sel}'.")
        return

    st.dataframe(_filas_lotes(producto), width="stretch", hide_index=True)
    st.caption(
        f"Total: {_num(producto.stock)} {producto.unidad} · valor {producto.valor_total()} € · "
        f"precio medio {_num(producto.precio_unitario)} €/{producto.unidad}"
    )

    st.subheader("Corregir o desechar un lote")
    lote_id = _elegir_lote(producto, "Lote", f"lotes_lote_{nombre_sel}")
    lote = producto.buscar_lote(lote_id)
    k = lambda campo: f"lotes_{campo}_{nombre_sel}_{lote.id}"
    st.caption(
        "Corregir sirve para arreglar un dato mal apuntado o un recuento, y no queda en el historial. "
        "Para registrar algo que se ha gastado o tirado, usa una salida en 'Actualizar stock'."
    )
    c1, c2 = st.columns(2)
    cantidad = c1.number_input(f"Cantidad ({producto.unidad})", min_value=0.0, value=float(lote.cantidad), step=0.1, key=k("cantidad"))
    precio = c2.number_input("Precio (€)", min_value=0.0, value=float(lote.precio_unitario), step=0.1, key=k("precio"))
    proveedor = st.text_input("Proveedor", value=lote.proveedor, key=k("proveedor"))
    peso = None
    if producto.unidad == "unidades":
        peso = _campo_peso("Peso en bruto de cada unidad", k("peso"), lote.peso_unitario or 0.0)
    tiene_fecha = st.checkbox("¿Tiene fecha de caducidad?", value=lote.fecha_caducidad is not None, key=k("tiene_fecha"))
    fecha = st.date_input(
        "Fecha de caducidad", value=lote.fecha_caducidad or date.today(), key=k("fecha"), disabled=not tiene_fecha
    )

    b1, b2 = st.columns(2)
    if b1.button("Guardar corrección", type="primary", key=k("guardar")):
        try:
            inv.editar_lote(
                nombre_sel, lote.id, cantidad=cantidad, precio_unitario=precio, proveedor=proveedor,
                fecha_caducidad=fecha if tiene_fecha else None, borrar_fecha_caducidad=not tiene_fecha,
                peso_unitario=peso,
            )
            avisar("success", f"Lote {lote.id} de '{nombre_sel}' corregido.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if b2.button("🗑️ Desechar este lote entero (desperdicio)", key=k("desechar")):
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


def _texto_reparto(fila: dict) -> str:
    if not fila["reparto"]:
        return "—"
    partes = [f"{_num(cantidad)} {fila['unidad']} del lote {lote_id}" for lote_id, cantidad in fila["reparto"]]
    if fila["sin_asignar"] > 1e-9:
        partes.append(f"⚠️ {_num(fila['sin_asignar'])} {fila['unidad']} sin lote elegido")
    return " + ".join(partes)


def pagina_servicios() -> None:
    st.header("📅 Servicios")
    serv = st.session_state.registro_servicios
    inv = st.session_state.inventario
    rec = st.session_state.recetario

    if serv.servicios:
        filas = [{
            "ID": s.id, "Fecha": s.fecha.strftime("%d/%m/%Y"), "Hora": s.hora.strftime("%H:%M"),
            "Comensales": s.comensales, "Menú": s.menu, "Estado": s.estado, "Notas": s.notas,
        } for s in sorted(serv.servicios, key=lambda s: (s.fecha, s.hora))]
        st.dataframe(filas, width="stretch", hide_index=True)
    else:
        st.info("No hay servicios registrados.")

    st.divider()
    tab_add, tab_cancel, tab_completar = st.tabs(["➕ Añadir servicio", "🚫 Cancelar servicio", "✅ Completar servicio"])

    with tab_add:
        with st.form("form_add_servicio", clear_on_submit=True):
            c1, c2 = st.columns(2)
            fecha = c1.date_input("Fecha")
            hora = c2.time_input("Hora")
            comensales = st.number_input("Comensales", min_value=1, step=1)
            menu_nombre = st.text_input("Nombre del menú")
            notas = st.text_area("Notas (opcional)")
            enviado = st.form_submit_button("Añadir servicio", type="primary")
            if enviado:
                try:
                    serv.agregar_servicio(Servicio(fecha, hora, int(comensales), menu_nombre, notas))
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
                st.caption(f"Se descontará para {servicio.comensales} comensales (motivo: consumo):")
                st.dataframe([{
                    "Ingrediente": f["ingrediente"],
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

            if st.button("Completar servicio", type="primary"):
                if filas is None:
                    servicio.completar()
                    avisar("warning", f"Servicio #{servicio.id} completado sin descontar stock (menú no encontrado).")
                    st.rerun()
                try:
                    rec.completar_servicio(servicio, inv, elecciones)
                except ValueError as e:
                    st.error(str(e))
                else:
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


# ---------- Página: Recetario ----------

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
            st.write(f"{m}  💶 {m.costo_por_comensal(inv)}€/comensal")

    with tab_crear_receta:
        if not inv.productos:
            st.warning("El inventario está vacío. Añade productos primero.")
        else:
            nombre_ing = st.selectbox("Ingrediente", list(inv.productos.keys()), key="ing_select")
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
            if st.button("Crear menú", type="primary"):
                if not nombre_menu or not recetas_elegidas:
                    st.error("Indica un nombre y al menos una receta.")
                else:
                    recetas_obj = [rec.recetas[n] for n in recetas_elegidas]
                    rec.agregar_menu(Menu(nombre_menu, recetas_obj))
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


# ---------- Página: Exportar / Backup ----------

def pagina_exportar() -> None:
    st.header("📁 Exportar y backup")

    st.subheader("Exportar a Excel")
    if st.button("Generar Excel", type="primary"):
        carpeta = str(_carpeta_base() / "datos")
        ruta = exportar_todo(
            st.session_state.inventario, st.session_state.registro_servicios,
            st.session_state.gestor_compras, carpeta,
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

    periodo = st.selectbox("Periodo", PERIODOS_VALIDOS, index=1, key="periodo_metricas")
    desde, hasta = rango_desde_periodo(periodo)
    st.caption(f"Del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}")

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
        if not resumen:
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
        nombre = st.selectbox("Producto", list(inv.productos.keys()), key="metricas_consumo_producto")
        cantidad = metricas.cantidad_consumida(nombre, desde, hasta)
        st.metric(f"Consumido de {nombre}", f"{cantidad} {inv.buscar_producto(nombre).unidad}")

    with tab_desperdicio:
        nombre2 = st.selectbox("Producto", list(inv.productos.keys()), key="metricas_desperdicio_producto")
        cantidad2 = metricas.cantidad_desperdiciada(nombre2, desde, hasta)
        st.metric(f"Desperdiciado de {nombre2}", f"{cantidad2} {inv.buscar_producto(nombre2).unidad}")
        valor_total = metricas.valor_desperdiciado_total(desde, hasta)
        st.metric("Valor total desperdiciado (todos los productos)", f"{valor_total} €")

    with tab_ranking:
        ranking = metricas.productos_mas_consumidos(desde, hasta, top=10)
        if not ranking:
            st.info("No hay datos de consumo en este periodo.")
        else:
            df_ranking = pd.DataFrame(ranking, columns=["Producto", "Cantidad consumida"]).set_index("Producto")
            st.bar_chart(df_ranking)
            st.dataframe(df_ranking.reset_index(), width="stretch", hide_index=True)

    with tab_gasto:
        gasto = metricas.gasto_por_categoria(desde, hasta)
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
    ["Dashboard", "Inventario", "Servicios", "Recetario", "Compras", "Métricas", "Exportar / Backup"],
)

st.sidebar.divider()
if st.sidebar.button("💾 Guardar sesión"):
    guardar_sesion(
        st.session_state.inventario, st.session_state.registro_servicios,
        st.session_state.recetario, st.session_state.gestor_compras,
        st.session_state.archivo_informes, RUTA_SESION,
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
elif pagina == "Recetario":
    pagina_recetario()
elif pagina == "Compras":
    pagina_compras()
elif pagina == "Métricas":
    pagina_metricas()
elif pagina == "Exportar / Backup":
    pagina_exportar()
