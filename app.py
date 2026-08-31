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

sys.path.append(str(Path(__file__).parent / "modulos"))

import streamlit as st
import pandas as pd

from inventario import Inventario, Producto, MovimientoStock, FACTORES_CONVERSION
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

    serv.agregar_servicio(Servicio(date.today() + timedelta(days=3), time(21, 0), 8, "Menú del día"))

    pan = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})
    rec.agregar_receta(pan)
    rec.agregar_receta(ensalada)
    rec.agregar_menu(Menu("Menú del día", [pan, ensalada]))


# ---------- Página: Dashboard ----------

def pagina_dashboard() -> None:
    st.header("📊 Dashboard")
    inv = st.session_state.inventario
    serv = st.session_state.registro_servicios
    comp = st.session_state.gestor_compras

    proximos_servicios = serv.servicios_proximos()
    bajo_minimo = inv.productos_bajo_minimo()
    proximos_caducar = inv.productos_proximos_a_caducar()
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
            st.metric("⏳ Próximos a caducar", len(proximos_caducar))
            with st.expander("Ver detalles"):
                if not proximos_caducar:
                    st.caption("Ningún producto próximo a caducar.")
                for p in proximos_caducar:
                    st.write(f"{p.nombre}: caduca en {p.dias_para_caducar()} día(s)")

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

def pagina_inventario() -> None:
    st.header("📦 Inventario")
    inv = st.session_state.inventario

    if inv.productos:
        filas = [{
            "Nombre": p.nombre, "Categoría": p.categoria, "Stock": p.stock, "Unidad": p.unidad,
            "Mínimo": p.stock_minimo, "Precio (€)": p.precio_unitario, "Proveedor": p.proveedor,
            "Caducidad": p.fecha_caducidad.strftime("%d/%m/%Y") if p.fecha_caducidad else "—",
        } for p in inv.productos.values()]
        st.dataframe(filas, use_container_width=True, hide_index=True)
    else:
        st.info("El inventario está vacío todavía.")

    col1, col2 = st.columns(2)
    with col1:
        bajo_minimo = inv.productos_bajo_minimo()
        if bajo_minimo:
            st.warning("⚠️ Bajo mínimo: " + ", ".join(p.nombre for p in bajo_minimo))
    with col2:
        proximos = inv.productos_proximos_a_caducar()
        if proximos:
            detalle = ", ".join(f"{p.nombre} ({p.dias_para_caducar()}d)" for p in proximos)
            st.warning(f"⏳ Próximos a caducar: {detalle}")

    st.divider()
    tab_add, tab_edit, tab_stock = st.tabs(["➕ Añadir producto", "✏️ Editar producto", "📦 Actualizar stock"])

    with tab_add:
        with st.form("form_add_producto", clear_on_submit=True):
            nombre = st.text_input("Nombre", key="add_nombre")
            categoria = st.text_input("Categoría", key="add_categoria")
            c1, c2 = st.columns(2)
            stock = c1.number_input("Stock inicial", min_value=0.0, step=0.1, key="add_stock")
            unidad = c2.selectbox("Unidad", Producto.UNIDADES_VALIDAS, key="add_unidad")
            c3, c4 = st.columns(2)
            precio = c3.number_input("Precio unitario (€)", min_value=0.0, step=0.1, key="add_precio")
            stock_minimo = c4.number_input("Stock mínimo", min_value=0.0, step=0.1, key="add_stock_minimo")
            proveedor = st.text_input("Proveedor", key="add_proveedor")
            tiene_caducidad = st.checkbox("¿Tiene fecha de caducidad?", key="add_tiene_caducidad")
            fecha_caducidad = st.date_input("Fecha de caducidad", key="add_fecha") if tiene_caducidad else None
            enviado = st.form_submit_button("Añadir producto", type="primary")

            if enviado:
                try:
                    inv.agregar_producto(Producto(
                        nombre, categoria, stock, unidad, precio, proveedor, stock_minimo, fecha_caducidad
                    ))
                    st.success(f"Producto '{nombre}' añadido.")
                except ValueError as e:
                    st.error(str(e))

    with tab_edit:
        if not inv.productos:
            st.info("No hay productos para editar.")
        else:
            nombre_sel = st.selectbox("Producto a editar", list(inv.productos.keys()), key="editar_select")
            producto = inv.buscar_producto(nombre_sel)
            # Las keys incluyen `nombre_sel`: si no, Streamlit reutilizaría el
            # valor que ya tuviera guardado bajo esa key (el del producto
            # anterior) en vez de tomar el `value` nuevo que le pasamos aquí.
            with st.form(f"form_editar_producto_{nombre_sel}"):
                nuevo_nombre = st.text_input("Nombre", value=producto.nombre, key=f"edit_nombre_{nombre_sel}")
                categoria = st.text_input("Categoría", value=producto.categoria, key=f"edit_categoria_{nombre_sel}")
                c1, c2 = st.columns(2)
                stock = c1.number_input("Stock", value=float(producto.stock), min_value=0.0, step=0.1, key=f"edit_stock_{nombre_sel}")
                stock_minimo = c2.number_input("Stock mínimo", value=float(producto.stock_minimo), min_value=0.0, step=0.1, key=f"edit_stock_minimo_{nombre_sel}")
                precio = st.number_input("Precio unitario (€)", value=float(producto.precio_unitario), min_value=0.0, step=0.1, key=f"edit_precio_{nombre_sel}")
                proveedor = st.text_input("Proveedor", value=producto.proveedor, key=f"edit_proveedor_{nombre_sel}")

                tiene_fecha_actual = producto.fecha_caducidad is not None
                tiene_fecha = st.checkbox(
                    "¿Tiene fecha de caducidad?", value=tiene_fecha_actual, key=f"edit_tiene_fecha_{nombre_sel}"
                )
                nueva_fecha = st.date_input(
                    "Fecha de caducidad",
                    value=producto.fecha_caducidad if tiene_fecha_actual else date.today(),
                    key=f"edit_fecha_{nombre_sel}",
                    disabled=not tiene_fecha,
                )

                guardar = st.form_submit_button("Guardar cambios", type="primary")

                if guardar:
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
                            categoria=categoria, stock=stock, precio_unitario=precio,
                            proveedor=proveedor, stock_minimo=stock_minimo,
                            # Si se desmarca la casilla, se BORRA la fecha (no
                            # se ignora) -- misma idea que en main.py: None es
                            # ambiguo aquí, así que hay un parámetro aparte.
                            fecha_caducidad=nueva_fecha if tiene_fecha else None,
                            borrar_fecha_caducidad=not tiene_fecha,
                        )
                        if exito:
                            if recetas_afectadas:
                                for receta in recetas_afectadas:
                                    cantidad = receta.ingredientes_por_comensal.pop(nombre_original)
                                    receta.ingredientes_por_comensal[nuevo_nombre] = cantidad
                                nombres = ", ".join(r.nombre for r in recetas_afectadas)
                                st.info(f"🔄 Recetas actualizadas: {nombres}")
                            st.success("Producto actualizado.")
                            st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    with tab_stock:
        if not inv.productos:
            st.info("No hay productos.")
        else:
            nombre_sel2 = st.selectbox("Producto", list(inv.productos.keys()), key="stock_select")
            with st.form("form_actualizar_stock"):
                cantidad = st.number_input("Cantidad", min_value=0.0, step=0.1)
                es_entrada = st.radio("Tipo de movimiento", ["Entrada (compra)", "Salida"]) == "Entrada (compra)"
                nueva_fecha = None
                motivo = None
                if es_entrada:
                    renovar = st.checkbox("Renovar fecha de caducidad con este lote")
                    if renovar:
                        nueva_fecha = st.date_input("Nueva fecha de caducidad", key="nueva_fecha_stock")
                else:
                    motivo = st.selectbox(
                        "Motivo de la salida", MovimientoStock.MOTIVOS_SALIDA, key="motivo_salida_stock"
                    )
                enviado2 = st.form_submit_button("Actualizar stock", type="primary")
                if enviado2:
                    inv.actualizar_stock(
                        nombre_sel2, cantidad, sumar=es_entrada,
                        nueva_fecha_caducidad=nueva_fecha, motivo_salida=motivo,
                    )
                    st.success("Stock actualizado.")
                    st.rerun()


# ---------- Página: Servicios ----------

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
        st.dataframe(filas, use_container_width=True, hide_index=True)
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
                st.success("Servicio cancelado.")
                st.rerun()

    with tab_completar:
        pendientes = [s for s in serv.servicios if s.estado not in ("completado", "cancelado")]
        if not pendientes:
            st.info("No hay servicios pendientes de completar.")
        else:
            opciones2 = {f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}": s.id for s in pendientes}
            elegido2 = st.selectbox("Servicio a completar", list(opciones2.keys()), key="completar_select")
            st.caption("Al completar, se descuentan del inventario los ingredientes del menú (motivo: consumo).")

            if st.button("Completar servicio", type="primary"):
                servicio = serv.buscar_por_id(opciones2[elegido2])
                menu = rec.buscar_menu(servicio.menu)

                if menu is None:
                    st.warning(f"No se encontró el menú '{servicio.menu}' en el recetario. No se ha tocado el inventario.")
                    servicio.completar()
                    st.success(f"Servicio #{servicio.id} completado (sin descuento de stock).")
                else:
                    necesarios = menu.calcular_ingredientes_totales(servicio.comensales)
                    fallidos = []
                    for ingrediente, cantidad in necesarios.items():
                        if inv.buscar_producto(ingrediente) is None:
                            fallidos.append(ingrediente)
                            continue
                        exito = inv.actualizar_stock(ingrediente, cantidad, sumar=False, motivo_salida="consumo")
                        if not exito:
                            fallidos.append(ingrediente)
                    servicio.completar()

                    if fallidos:
                        st.warning(f"Servicio #{servicio.id} completado, pero no se pudo descontar: {', '.join(fallidos)}")
                    else:
                        st.success(f"Servicio #{servicio.id} completado y stock descontado correctamente.")
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
                        st.success(f"Receta '{nombre_receta}' creada.")
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
                    st.success(f"Menú '{nombre_menu}' creado.")
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
                comp.generar_lista_desde_servicios(servicios, rec, inv)
                st.success("Lista de compra generada/actualizada.")
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
            st.dataframe(filas, use_container_width=True, hide_index=True)

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
            if st.button("Marcar como comprado y reponer inventario"):
                comp.marcar_comprado(nombre_marcar, cantidad_comprada=cantidad_real)
                inv.actualizar_stock(nombre_marcar, cantidad_real, sumar=True)
                st.success(f"'{nombre_marcar}' marcado como comprado y repuesto en inventario (+{cantidad_real} {item_marcar.unidad}).")
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

    tab_consumo, tab_desperdicio, tab_ranking, tab_gasto = st.tabs(
        ["Consumo por producto", "Desperdicio por producto", "🏆 Más consumidos", "💰 Gasto por categoría"]
    )

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
            st.dataframe(df_ranking.reset_index(), use_container_width=True, hide_index=True)

    with tab_gasto:
        gasto = metricas.gasto_por_categoria(desde, hasta)
        if not gasto:
            st.info("No hay compras registradas en este periodo.")
        else:
            df_gasto = pd.DataFrame(list(gasto.items()), columns=["Categoría", "Gasto (€)"]).set_index("Categoría")
            st.bar_chart(df_gasto)
            st.dataframe(df_gasto.reset_index(), use_container_width=True, hide_index=True)
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
        mes_gen = c2.selectbox("Mes", list(range(1, 13)), format_func=lambda m: NOMBRES_MESES[m].capitalize(), key="informe_mes_gen")
        if st.button("Generar y guardar informe", type="primary"):
            archivo.generar_informe(inv, int(año_gen), mes_gen)
            st.success(f"Informe de {NOMBRES_MESES[mes_gen].capitalize()} {año_gen} generado y guardado.")
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
            st.dataframe(filas, use_container_width=True, hide_index=True)

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
                    st.dataframe(filas_diff, use_container_width=True, hide_index=True)


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
