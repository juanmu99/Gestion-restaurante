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

import os
import re
import threading
import sys
from pathlib import Path
from datetime import date, datetime, time, timedelta
from typing import Optional

# insert(0, ...) y no append(): así Python busca PRIMERO en nuestra carpeta
# modulos/. Si el ordenador tuviera instalada una librería con el mismo
# nombre que uno de nuestros módulos, se usaría la nuestra y no la otra.
sys.path.insert(0, str(Path(__file__).parent / "modulos"))

import streamlit as st
import pandas as pd

from inventario import (
    TIPOS_IVA, IVA_POR_DEFECTO, nombre_iva, precio_a_coste,
)
from inventario import Inventario, PrecioCompra, Producto, MovimientoStock, FACTORES_CONVERSION, UNIDADES_PESO, convertir
from servicios import RegistroServicios, Servicio
from recetario import Recetario, Receta, Menu, _coste_de_filas
from compras import GestorCompras
from exportador import exportar_todo
from persistencia import (
    Sesion, SesionIlegible, carpeta_datos, cargar_sesion_segura, escribir_sesion, firma, sesion_a_dict,
    copia_antes_de_empezar_de_cero, sesion_vacia, listar_copias, cargar_sesion,
)
from gastos import Gasto, RegistroGastos, resumen_servicio, resumen_periodo, NOTA_COSTE_AL_COMPLETAR
from materiales import Material, RegistroMaterial, lista_de_carga
import historial
from metricas import trimestre
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


CARPETA_DATOS = carpeta_datos(_carpeta_base())
RUTA_SESION = str(CARPETA_DATOS / "sesion.json")

# set_page_config DEBE ser el primer comando de Streamlit del script.
st.set_page_config(page_title="Gestión Catering", page_icon="🍽️", layout="wide")

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

def vaciar_campos(prefijo: str, conservar: tuple = ()) -> None:
    """
    Vacía los campos de un formulario (los widgets cuya key empieza por
    `prefijo`) para que, tras registrar algo, no se queden escritos los
    datos de la vez anterior. Borrar su valor guardado en session_state
    hace que, en la siguiente recarga, vuelvan a su valor inicial.
    """
    for clave in list(st.session_state.keys()):
        if isinstance(clave, str) and clave.startswith(prefijo) and clave not in conservar:
            del st.session_state[clave]


def avisar(tipo: str, texto: str) -> None:
    """
    Guarda un aviso para mostrarlo en la SIGUIENTE ejecución del script.

    Por qué hace falta: st.rerun() vuelve a ejecutar todo el script desde
    cero, y cualquier st.success()/st.warning() mostrado justo antes se
    borra sin que dé tiempo a leerlo. Guardándolo en session_state (que sí
    sobrevive al rerun) y mostrándolo al principio de la página, el aviso
    aparece DESPUÉS de recargar. tipo: "success", "warning", "error" o "info".
    """
    st.session_state.setdefault("avisos", []).append((tipo, _es(texto)))


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

    try:
        sesion, aviso = cargar_sesion_segura(RUTA_SESION)
    except SesionIlegible as error:
        # No se arranca vacío encima de los datos: se para aquí (y no se guarda nada).
        st.error(f"❌ {error}")
        st.stop()
    if aviso:
        avisar("warning", aviso)
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
    # Guardado automático: huella de lo último guardado y fecha del archivo en
    # disco en ese momento (para notar si OTRA ventana del programa lo cambió).
    st.session_state._firma_guardada = firma(_datos_sesion())
    st.session_state._mtime_guardado = _mtime_sesion()
    st.session_state._hora_guardado = None


def _datos_sesion() -> dict:
    ss = st.session_state
    return sesion_a_dict(ss.inventario, ss.registro_servicios, ss.recetario, ss.gestor_compras, ss.archivo_informes,
                         ss.registro_gastos, ss.registro_material)


def _mtime_sesion() -> Optional[float]:
    ruta = Path(RUTA_SESION)
    return ruta.stat().st_mtime if ruta.exists() else None


def autoguardar(zona) -> None:
    """
    GUARDADO AUTOMÁTICO: se ejecuta al final de cada vuelta del programa. Si
    los datos han cambiado desde el último guardado, se escriben en disco
    (de forma segura, con copia: ver persistencia.escribir_sesion).

    Si el archivo lo ha cambiado OTRA ventana del programa desde la última
    vez, no se sobrescribe sin preguntar: se avisa en la barra lateral.
    `zona` es el hueco de la barra lateral donde se muestra el estado.
    """
    ss = st.session_state
    datos = _datos_sesion()
    huella = firma(datos)
    if huella != ss._firma_guardada:
        if _mtime_sesion() != ss._mtime_guardado:
            with zona.container():
                st.error("⚠️ Los datos se han cambiado desde **otra ventana** del programa. Para no perder nada, "
                         "esta ventana ha dejado de guardar.")
                if st.button("🔄 Cargar los datos de la otra ventana (se pierde lo de esta)", key="conflicto_recargar"):
                    for clave in list(ss.keys()):
                        del ss[clave]
                    st.rerun()
                if st.button("💾 Guardar los de esta ventana (se pierde lo de la otra)", key="conflicto_guardar"):
                    ss._mtime_guardado = _mtime_sesion()
                    st.rerun()
            return
        try:
            escribir_sesion(datos, RUTA_SESION)
        except OSError as error:
            zona.error(f"❌ No se han podido guardar los cambios: {error}. Comprueba que hay espacio en el disco.")
            return
        ss._firma_guardada = huella
        ss._mtime_guardado = _mtime_sesion()
        ss._hora_guardado = datetime.now()
    # Hora del último guardado: el de esta ventana o, si aún no ha guardado
    # nada, la del archivo en disco.
    cuando = ss._hora_guardado or (datetime.fromtimestamp(ss._mtime_guardado) if ss._mtime_guardado else None)
    if cuando is None:
        zona.caption("💾 Los cambios se guardan solos")
    else:
        dia = "hoy" if cuando.date() == date.today() else cuando.strftime("%d/%m/%Y")
        zona.caption(f"💾 Los cambios se guardan solos · último guardado: {dia} a las {cuando:%H:%M:%S}")


def _app_vacia() -> bool:
    """True si todavía no hay ningún dato (ni productos, ni recetas, ni servicios, ni gastos, ni material)."""
    ss = st.session_state
    return not (ss.inventario.productos or ss.recetario.recetas or ss.recetario.menus
                or ss.registro_servicios.servicios or ss.registro_gastos.gastos or ss.registro_material.materiales)


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
    # Historial de precios: compras de meses anteriores (solo para el ejemplo).
    # El tomate está ahora más caro de lo habitual y la harina, más barata:
    # aparecen en el Dashboard, en "Precios fuera de lo habitual".
    if len(inv.precios_de("Tomate")) <= 1:
        for nombre, proveedor, dias, cantidad, unidad, precio in (
            ("Tomate", "Huerta Local", 75, 5, "kg", 1.6), ("Tomate", "Frutas Paco", 40, 4, "kg", 1.75),
            ("Harina de trigo", "Harinas del Sur", 90, 10, "kg", 1.6), ("Harina de trigo", "Harinas del Sur", 45, 10, "kg", 1.5),
            ("Aceite de oliva", "Oleícola Andaluza", 120, 20, "litros", 4.3),
            ("Aceite de oliva", "Mayorista Sur", 60, 10, "litros", 4.6),
        ):
            inv.historial_precios.append(
                PrecioCompra(nombre, date.today() - timedelta(days=dias), proveedor, cantidad, unidad, precio)
            )
    # Consumibles: se gastan pero no se comen (lista aparte, sin caducidad).
    inv.agregar_producto(Producto(
        "Servilletas de papel", "Desechables", 500, "unidades", 0.02, "Hostelería Total", stock_minimo=200,
        tipo="consumible",
    ))
    inv.agregar_producto(Producto(
        "Vasos desechables", "Desechables", 150, "unidades", 0.05, "Hostelería Total", stock_minimo=100,
        tipo="consumible",
    ))

    # Limpieza y mantenimiento: se gastan a mano, no por comensal. Las bayetas
    # están por debajo del mínimo (la lista de la compra las repone).
    inv.agregar_producto(Producto(
        "Lejía", "Limpieza", 4, "litros", 1.1, "Droguería Central", stock_minimo=2, tipo="mantenimiento",
        fecha_caducidad=date.today() + timedelta(days=180),
    ))
    inv.agregar_producto(Producto(
        "Bayetas", "Limpieza", 6, "unidades", 0.6, "Droguería Central", stock_minimo=10, tipo="mantenimiento",
    ))
    serv.agregar_servicio(Servicio(date.today() + timedelta(days=3), time(21, 0), 8, "Menú del día"))

    pan = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005}, vida_util_dias=3)
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
    # Una elaboración BASE (sofrito) con su fórmula, y una preparación hecha:
    # se pensaba sacar 1 kg y salieron 0,9 kg.
    if "Cebolla dulce" not in inv.productos:
        inv.agregar_producto(Producto("Cebolla dulce", "Verduras", 5, "kg", 1.3, "Huerta Local",
                                      fecha_caducidad=date.today() + timedelta(days=12)))
    if "Pimiento rojo" not in inv.productos:
        inv.agregar_producto(Producto("Pimiento rojo", "Verduras", 2, "kg", 2.4, "Huerta Local",
                                         fecha_caducidad=date.today() + timedelta(days=8)))
    if "Sofrito" not in inv.productos:
        inv.definir_base(
            "Sofrito", "Elaboraciones", "kg", 1, {"Cebolla dulce": 1.5, "Pimiento rojo": 0.3}, vida_util_dias=4,
            notas="Pochar a fuego lento unos 40 min, sin que llegue a dorarse.\nSe congela bien en raciones de 250 g.",
        )
        rec.preparar_base("Sofrito", 1, 0.9, inv)
    ensalada.poner_nota("Aliñar justo antes de servir para que el tomate no suelte agua.")
    # Una elaboración ya preparada: 4 raciones de ensalada hechas hoy.
    if not inv.elaboraciones.tandas_de("Ensalada de tomate"):
        inv.elaboraciones.nueva_tanda("Ensalada de tomate", 4, 0.24, ensalada.caducidad_propuesta(date.today()))


# ---------- Anotaciones (bloc de notas de bases, recetas y menús) ----------

def _saltos(texto: str) -> str:
    """Respeta los saltos de línea de una nota al mostrarla (en Markdown, un salto simple no cuenta)."""
    return texto.replace("\n", "  \n")


def _texto_fecha_nota(fecha: Optional[date]) -> str:
    return f"Editada el {fecha.strftime('%d/%m/%Y')}" if fecha else ""


def _mostrar_nota(objeto, titulo: str = "📝 Anotaciones") -> None:
    """Enseña la nota (si tiene), en solo lectura."""
    if objeto.notas:
        st.info(f"**{titulo}**\n\n{_saltos(objeto.notas)}")
        st.caption(_texto_fecha_nota(objeto.notas_fecha))


def _editor_nota(objeto, clave: str, nombre: str) -> None:
    """Desplegable para escribir, cambiar o borrar la nota de una base, receta o menú."""
    etiqueta = "📝 Anotaciones" + (" ✏️" if objeto.notas else "")
    with st.expander(etiqueta):
        texto = st.text_area(
            f"Anotaciones de '{nombre}'", value=objeto.notas, key=f"nota_{clave}", height=120,
            placeholder="Lo que quieras explicar a tus compañeros: cómo se hace, trucos, alérgenos, emplatado...",
        )
        if objeto.notas_fecha:
            st.caption(_texto_fecha_nota(objeto.notas_fecha))
        if st.button("Guardar nota", key=f"nota_guardar_{clave}"):
            objeto.poner_nota(texto)
            avisar("success", f"Nota de '{nombre}' guardada." if objeto.notas else f"Nota de '{nombre}' borrada.")
            st.rerun()


def _notas_de_menu(nombre: str, notas: str, recetas: list[tuple[str, str]]) -> None:
    """Las notas de un menú y de sus recetas, juntas (para el servicio)."""
    if not notas and not any(n for _, n in recetas):
        return
    with st.expander("📝 Anotaciones del menú y sus recetas"):
        if notas:
            st.markdown(f"**{nombre}**")
            st.markdown(_saltos(notas))
        for receta, nota in recetas:
            if nota:
                st.markdown(f"**{receta}**")
                st.markdown(_saltos(nota))


# ---------- Lotes: piezas de interfaz compartidas ----------

def _es(texto: str) -> str:
    """
    Pone la coma decimal española en un texto ya escrito: '2.5 kg' -> '2,5 kg'.
    Solo cambia un punto ENTRE dos cifras, así que no toca fechas (12/10/2026),
    horas (21:00) ni nombres de archivo.
    """
    return re.sub(r"(?<=\d)\.(?=\d)", ",", texto)


def _num(valor: float) -> str:
    """Número sin decimales sobrantes para mostrar, con coma: 2.0 -> '2', 0.30000001 -> '0,3'."""
    return _es(f"{round(valor, 3):g}")


def _eur(valor: float) -> str:
    """Un importe en euros con 2 decimales, al estilo español: 1234.5 -> '1.234,50'."""
    return f"{valor:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def _dec(valor: float, decimales: int = 1) -> str:
    """Un número con `decimales` decimales fijos y coma: 2.345 -> '2,3'."""
    return f"{valor:.{decimales}f}".replace(".", ",")


def _pct(valor: float, decimales: int = 1) -> str:
    """Un tanto por uno como porcentaje con coma: 0.643 -> '64,3%'."""
    return f"{valor:.{decimales}%}".replace(".", ",")


def _boton_confirmado(etiqueta: str, clave: str, contenedor=None, pregunta: str = "¿Seguro?") -> bool:
    """
    Un botón que pide confirmación: el primer clic pregunta (✔️ Sí / ✖️ No) y
    solo el "Sí" devuelve True. Para lo que no se puede deshacer con un clic
    (desechar un lote, eliminar un gasto...).
    """
    contenedor = contenedor or st
    pedido = f"_confirmar_{clave}"
    if not st.session_state.get(pedido):
        if contenedor.button(etiqueta, key=clave):
            st.session_state[pedido] = True
            st.rerun()
        return False
    contenedor.markdown(f"**{pregunta}**")
    si, no = contenedor.columns(2)
    if si.button("✔️ Sí", key=f"{clave}_si", type="primary"):
        st.session_state[pedido] = False
        return True
    if no.button("✖️ No", key=f"{clave}_no"):
        st.session_state[pedido] = False
        st.rerun()
    return False


def _precio(valor: float) -> str:
    """
    Un precio para mostrar: con 2 decimales como mucho si es de 1 € o más
    (4.5, 14.99), y con las cifras necesarias si es pequeño, como los precios
    por gramo o mililitro (0.0125, 0.00062), que con 2 decimales saldrían 0,00.
    """
    if valor is None:
        return "—"
    if valor == 0 or abs(valor) >= 1:
        return _es(f"{_num(round(valor, 2))}")
    return _es(f"{valor:.3g}")


def _parece_numero(texto: str) -> bool:
    try:
        float(texto.replace(",", "."))
        return True
    except ValueError:
        return False


def _texto_lote(producto: Producto, lote) -> str:
    """Texto de un lote en los desplegables. Empieza siempre por 'Lote N ·'."""
    aviso = " · ⚠️ CADUCADO" if lote.esta_caducado() else ""
    return _es(lote.descripcion(producto.unidad)) + aviso


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


AVISO_FISCAL = (
    "⚠️ Es una **estimación orientativa** a partir de lo registrado en el programa. La aplicación **no sustituye "
    "a un gestor o asesor fiscal**: para tus declaraciones, consulta siempre con él."
)


def _huella(*valores) -> str:
    """Código corto que cambia si cambia cualquiera de los valores (para las keys de los widgets)."""
    import hashlib
    return hashlib.md5(repr(valores).encode("utf-8")).hexdigest()[:8]


def _criterio_rentabilidad() -> str:
    """'sin IVA' o 'con IVA': cómo se calcula el coste de los servicios para su margen (Ajustes)."""
    return "sin IVA" if st.session_state.inventario.iva_recuperable else "con IVA"


def _elegir_iva(clave: str, actual: float = IVA_POR_DEFECTO, contenedor=None,
                etiqueta: str = "IVA de este producto") -> float:
    """Desplegable con los tipos de IVA (21 % por defecto). Devuelve el porcentaje."""
    contenedor = contenedor or st
    nombres = list(TIPOS_IVA)
    actual_nombre = nombre_iva(actual)
    return TIPOS_IVA[contenedor.selectbox(
        etiqueta, nombres, index=nombres.index(actual_nombre) if actual_nombre in nombres else 0,
        key=clave, help="21 % es el general. Muchos alimentos llevan el 10 % o el 4 % (pan, leche, huevos, fruta, "
                        "verdura...). 'Sin IVA' para lo que no lo lleva.",
    )]


def _campo_precio(unidad: str, cantidad: Optional[float], k, referencia: float = 0.0, contenedor=None,
                  iva: float = 0.0) -> Optional[float]:
    """
    El precio de una compra, como prefiera quien la apunta: por unidad (€/kg,
    €/litro, €/unidad) o el TOTAL pagado (lo que pone el ticket). Con el
    total, el programa calcula el precio por unidad y lo enseña antes de
    guardar. Devuelve el precio POR UNIDAD (None si falta algún dato).
    """
    contenedor = contenedor or st
    unidad_txt = {"unidades": "unidad", "litros": "litro"}.get(unidad, unidad)
    incluye_iva = False
    if iva > 0:
        incluye_iva = contenedor.radio(
            "El precio que escribo", (f"Con IVA incluido ({_num(iva)} %)", "Sin IVA"), horizontal=True,
            key=k("con_iva"), help="Como venga en el ticket (con IVA) o en la factura (sin IVA): el programa "
                                   "guarda las dos cosas por separado.",
        ) != "Sin IVA"
    modo = contenedor.radio(
        "¿Cómo indicas el precio?", (f"Por {unidad_txt}", "Total pagado"), horizontal=True, key=k("modo_precio"),
        help="Si compras una caja o un paquete, pon el total que has pagado y el programa calcula el precio por "
             f"{unidad_txt}.",
    )
    pista = f"La última compra fue a {_num(referencia)} € por {unidad_txt}." if referencia else None
    # El precio empieza vacío: es el de ESTA compra, y no debe darse por bueno sin mirarlo.
    if modo.startswith("Por"):
        precio = contenedor.number_input(
            f"Precio de este lote (€ por {unidad_txt})", min_value=0.0, value=None, placeholder="Precio de esta compra",
            step=0.1, key=k("precio"), help=pista,
        )
        return _precio_con_iva(precio, incluye_iva, iva, unidad_txt, contenedor)
    total = contenedor.number_input(
        "Total pagado por esta compra (€)", min_value=0.0, value=None, placeholder="Lo que pone el ticket",
        step=0.5, key=k("precio_total"), help=pista,
    )
    if total is None:
        return None
    if not cantidad or cantidad <= 0:
        contenedor.caption("Indica la cantidad comprada para calcular el precio por " + unidad_txt + ".")
        return None
    precio = total / cantidad  # sin redondear: redondear perdía dinero en gramos o mililitros
    contenedor.caption(f"= **{_precio(precio)} € por {unidad_txt}** ({_num(total)} € / {_num(cantidad)} {unidad})")
    return _precio_con_iva(precio, incluye_iva, iva, unidad_txt, contenedor)


def _precio_con_iva(precio: Optional[float], incluye_iva: bool, iva: float, unidad_txt: str, contenedor) -> Optional[float]:
    """Pasa el precio escrito (con o sin IVA) al coste que usa el programa, y enseña el desglose."""
    if precio is None or iva <= 0:
        return precio
    base = precio / (1 + iva / 100) if incluye_iva else precio
    contenedor.caption(
        f"Pagado (con IVA): **{_precio(base * (1 + iva / 100))} €** por {unidad_txt} = "
        f"{_precio(base)} € sin IVA + {_precio(base * iva / 100)} € de IVA ({_num(iva)} %)."
    )
    return precio_a_coste(precio, incluye_iva, iva)


def _campos_entrada(producto: Producto, k, cantidad: Optional[float] = None) -> dict:
    """
    Campos de un lote NUEVO (compra): precio, proveedor, caducidad y, si hace
    falta, peso por unidad. `k` construye las keys de los widgets.
    `cantidad`: lo comprado, para calcular el precio por unidad si se indica el total.
    """
    c1, c2 = st.columns(2)
    with c1:
        precio = _campo_precio(producto.unidad, cantidad, k, producto.precio_referencia, iva=producto.iva)
    proveedor = c2.text_input("Proveedor de este lote", value=producto.proveedor, key=k("proveedor"))
    necesita_peso = producto.tiene_merma and producto.unidad == "unidades"
    peso = None
    if necesita_peso:
        peso = _campo_peso("Peso en bruto de cada unidad de este lote", k("peso"))
        if producto.peso_unitario:
            st.caption(f"La última vez: {_num(producto.peso_unitario)} kg por unidad.")
    fecha = None
    # En los alimentos la caducidad viene MARCADA y con una fecha propuesta (lo
    # que duró la última compra, o 7 días): sin caducidad no hay avisos. Si de
    # verdad no caduca (sal, aceite...), se desmarca.
    if not producto.es_consumible() and st.checkbox(
        "¿Este lote tiene fecha de caducidad?", value=producto.es_alimento(), key=k("tiene_fecha"),
        help="Desmárcalo si este producto no caduca.",
    ):
        fecha = st.date_input("Fecha de caducidad de este lote", value=producto.caducidad_propuesta_compra(),
                              key=k("fecha"), format="DD/MM/YYYY")
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
            "Lote": str(l.id), "Cantidad": f"{_num(l.cantidad)} {producto.unidad}",
            "Precio (€, con IVA)": _precio(l.precio_unitario), "IVA": nombre_iva(l.iva).split(" (")[0],
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

def _guia_primer_uso() -> None:
    """Mientras no hay ningún servicio: los 4 pasos para empezar, con un botón a cada pantalla."""
    ss = st.session_state
    pasos = [
        ("Añade tus productos", "Lo que compras: alimentos, consumibles (servilletas, vasos...) y limpieza. "
         "Pestaña ➕ Añadir producto.", "Inventario", bool(ss.inventario.productos)),
        ("Crea tus recetas", "Cada plato con sus ingredientes por comensal. Pestaña ➕ Crear receta.",
         "Recetario", bool(ss.recetario.recetas)),
        ("Junta las recetas en menús", "Lo que ofreces en un servicio, con sus consumibles y material. "
         "Pestaña ➕ Crear menú.", "Recetario", bool(ss.recetario.menus)),
        ("Apunta tu primer servicio", "Fecha, comensales, menú y, si quieres, el precio de cobro. "
         "Pestaña ➕ Añadir servicio.", "Servicios", bool(ss.registro_servicios.servicios)),
    ]
    with st.container(border=True):
        st.subheader("👋 Para empezar")
        st.caption("Cuatro pasos y el programa ya calcula la lista de la compra, el stock y la rentabilidad de cada "
                   "servicio. Esta guía desaparece cuando apuntas tu primer servicio.")
        siguiente = next((i for i, p in enumerate(pasos) if not p[3]), None)
        for i, (titulo, texto, pagina, hecho) in enumerate(pasos):
            c1, c2 = st.columns([5, 1])
            marca = "✅" if hecho else ("👉" if i == siguiente else "⬜")
            c1.markdown(f"{marca} **{i + 1}. {titulo}** — {texto}")
            c2.button(f"Ir a {pagina}", key=f"guia_{i}", on_click=_ir, args=(pagina,),
                      type="primary" if i == siguiente else "secondary")
        if _app_vacia():
            st.caption("¿Solo quieres probarlo? Carga los datos de ejemplo (botón 🧪 de la barra lateral) y, cuando "
                       "termines, bórralos en Ajustes › Empezar de cero.")


def _dashboard_hoy(serv: RegistroServicios) -> None:
    """Lo primero del Dashboard: servicios pasados sin completar, los de hoy y el dinero del mes."""
    for s in serv.pasados_sin_completar():
        st.warning(f"⚠️ El servicio **{_texto_servicio(s)}** ya pasó y sigue **{s.estado}**: complétalo (o cancélalo) "
                   "en Servicios. Mientras tanto no se descuenta su stock ni cuenta su coste real.")

    hoy = serv.servicios_de_hoy()
    st.subheader(f"📅 Hoy, {date.today().strftime('%d/%m/%Y')}")
    if not hoy:
        st.caption("No hay servicios hoy.")
    for s in hoy:
        donde = " · ".join(x for x in (s.cliente, s.lugar) if x)
        hecho = " · ✅ completado" if s.estado == "completado" else (" · ✔️ confirmado" if s.estado == "confirmado" else "")
        st.markdown(f"**{s.hora.strftime('%H:%M')}** · {s.comensales} comensales · {s.menu}"
                    + (f" · {donde}" if donde else "") + hecho)

    desde, hasta = rango_desde_periodo("este mes")
    r = resumen_periodo(serv.servicios, st.session_state.inventario, st.session_state.recetario,
                        st.session_state.registro_gastos, st.session_state.registro_material, desde, hasta)
    st.subheader(f"💶 {NOMBRES_MESES[date.today().month].capitalize()}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Facturado", f"{_eur(r['facturado'])} €", help="Lo cobrado (sin IVA) de los servicios completados este mes.")
    m2.metric("Margen", f"{_eur(r['margen'])} €",
              help="Cobro menos coste de los servicios completados este mes que tienen precio de cobro.")
    m3.metric("Compras", f"{_eur(r['compras'])} €", help="Lo pagado este mes en compras de productos (con IVA).")
    m4.metric("Gastos", f"{_eur(r['gastos'])} €", help="Gasolina, personal, alquileres... apuntados este mes.")
    detalle = f"{r['servicios']} servicio(s) completado(s) este mes"
    if r["sin_cobro"]:
        detalle += f", {r['sin_cobro']} sin precio de cobro (no cuentan en facturado ni margen)"
    st.caption(detalle + ".")
    st.divider()


def pagina_dashboard() -> None:
    st.header("📊 Dashboard")
    inv = st.session_state.inventario
    serv = st.session_state.registro_servicios
    comp = st.session_state.gestor_compras

    proximos_servicios = serv.servicios_proximos()
    bajo_minimo = inv.productos_bajo_minimo()
    caducados = inv.lotes_caducados()
    proximos_caducar = inv.lotes_proximos_a_caducar()
    tandas_caducadas = inv.elaboraciones.caducadas()
    tandas_proximas = inv.elaboraciones.proximas_a_caducar()
    pendientes_compra = comp.items_pendientes()

    if not serv.servicios:
        _guia_primer_uso()
    _dashboard_hoy(serv)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        with st.container(border=True):
            st.metric("📅 Servicios próximos", len(proximos_servicios))
            with st.expander("Ver detalles"):
                if not proximos_servicios:
                    st.caption("No hay servicios próximos.")
                for s in proximos_servicios:
                    st.write(_es(str(s)))

    with col2:
        with st.container(border=True):
            st.metric("⚠️ Bajo mínimo", len(bajo_minimo))
            with st.expander("Ver detalles"):
                if not bajo_minimo:
                    st.caption("Ningún producto bajo mínimo.")
                for p in bajo_minimo:
                    st.write(f"{p.nombre}: {_num(p.stock)} {p.unidad} (mínimo {_num(p.stock_minimo)})")

    with col3:
        with st.container(border=True):
            st.metric("⏳ Caducidad", help="Lotes y tandas caducados o que caducan en los próximos 7 días.", value=
                      len(caducados) + len(proximos_caducar) + len(tandas_caducadas) + len(tandas_proximas))
            with st.expander("Ver detalles"):
                if not (caducados or proximos_caducar or tandas_caducadas or tandas_proximas):
                    st.caption("Nada caducado ni próximo a caducar.")
                for t in tandas_caducadas:
                    st.write(f"🗑️ **🥘 {t.receta}** — {_num(t.raciones)} raciones, caducada ({t.etiqueta()})")
                for t in tandas_proximas:
                    st.write(f"🥘 {t.receta} — {_num(t.raciones)} raciones, caduca en {t.dias_para_caducar()} día(s)")
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
                    st.write(f"{i.ingrediente}: {_num(i.cantidad)} {i.unidad} (≈{_eur(i.costo_estimado())} €)")

    # La proyección de agotamiento no encaja como un simple "recuadro con
    # lista" (cada producto tiene un número de días distinto que contar),
    # así que se muestra aparte, debajo del tablón.
    proximos_agotarse = Metricas(inv).productos_proximos_a_agotarse()
    if proximos_agotarse:
        st.divider()
        st.subheader("📉 Se agotarán pronto (según ritmo de consumo)")
        for nombre, dias in proximos_agotarse:
            st.write(f"**{nombre}**: ~{_num(dias)} día(s) al ritmo actual")

    avisos_precio = inv.avisos_precios()
    st.divider()
    st.subheader("💶 Precios fuera de lo habitual")
    if not avisos_precio:
        st.caption(
            f"Ninguna compra de los últimos {inv.DIAS_AVISO_PRECIO} días se separa más de un "
            f"{inv.UMBRAL_AVISO_PRECIO:.0%} de su precio habitual."
        )
    for a in avisos_precio:
        unidad_txt = "unidad" if a["unidad"] == "unidades" else a["unidad"]
        texto = (
            f"**{a['producto']}**: {_num(a['precio'])} €/{unidad_txt} el {a['fecha'].strftime('%d/%m/%Y')} "
            f"({a['proveedor']}), un **{abs(a['variacion']):.0%} {'más caro' if a['variacion'] > 0 else 'más barato'}** "
            f"de lo habitual ({_num(a['habitual'])} €/{unidad_txt}, media de {a['compras_anteriores']} compra(s) anterior(es))."
        )
        (st.warning if a["variacion"] > 0 else st.success)(("📈 " if a["variacion"] > 0 else "📉 ") + texto)
    if avisos_precio:
        st.caption("Lo habitual es la media de las compras anteriores de los últimos "
                   f"{inv.VENTANA_PRECIO_HABITUAL} días. El detalle está en Inventario > 📈 Historial de precios.")

    st.divider()
    st.metric("💰 Valor total del inventario", f"{_eur(inv.valor_total_inventario())} €",
              help="Lo que vale lo que tienes, a precio de compra (con IVA): productos "
                   f"{_eur(inv.valor_productos())} € + raciones ya preparadas {_eur(inv.valor_tandas())} €.")


# ---------- Página: Inventario ----------

# Nota sobre st.form: dentro de un formulario, cambiar una casilla o un
# desplegable NO vuelve a ejecutar la página hasta pulsar el botón. Por eso
# los campos que aparecen o desaparecen según otra respuesta (la fecha de
# caducidad, el motivo de salida, el peso por unidad...) no funcionan bien
# dentro de un st.form. Aquí se usan widgets sueltos + un botón normal.

_ICONO_TIPO = {"consumible": "🧻 ", "mantenimiento": "🧽 "}


def _filas_inventario(productos: list, tipo: str = "alimento") -> list[dict]:
    filas = []
    for p in productos:
        fila = {
            "Nombre": p.nombre, "Categoría": p.categoria, "Stock": _num(p.stock), "Unidad": p.unidad,
            "Mínimo": _num(p.stock_minimo), "Precio medio (€, con IVA)": _precio(p.precio_unitario),
            "IVA": nombre_iva(p.iva).split(" (")[0], "Proveedor habitual": p.proveedor,
            "Lotes": len(p.lotes),
        }
        if tipo == "mantenimiento":
            fila["Próxima caducidad"] = p.fecha_caducidad.strftime("%d/%m/%Y") if p.fecha_caducidad else "—"
        if tipo == "alimento":
            fila["Próxima caducidad"] = p.fecha_caducidad.strftime("%d/%m/%Y") if p.fecha_caducidad else "—"
            fila["Tipo"] = p.tipo_descripcion() or "—"
            # Siempre texto: si la columna mezcla números y "—", Streamlit
            # tiene que corregir los tipos por su cuenta (y avisa en la consola).
            fila["Peso/unidad (kg)"] = f"{_num(round(p.peso_unitario, 2))}" if p.peso_unitario else "—"
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
VISTAS_PRODUCTOS = {"🍅 Alimentos": "alimento", "🧻 Consumibles": "consumible", "🧽 Limpieza y mantenimiento": "mantenimiento"}
VISTAS_INVENTARIO = {**VISTAS_PRODUCTOS, "🥘 Elaboraciones": "elaboracion", "🍽️ Material": "material"}


def pagina_inventario() -> None:
    st.header("📦 Inventario")
    inv = st.session_state.inventario

    tipo = VISTAS_INVENTARIO[st.radio("Lista", list(VISTAS_INVENTARIO), horizontal=True, key="inv_tipo")]
    if tipo == "material":
        _seccion_material()
        return
    if tipo == "elaboracion":
        _seccion_elaboraciones()
        return
    productos_tipo = inv.productos_de(tipo)

    if tipo == "mantenimiento":
        st.caption("No van en recetas ni en menús: lo que se gasta se apunta a mano en 'Actualizar stock' (para un "
                   "servicio o en general). Si bajan del mínimo, la lista de la compra los repone.")
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
            "Todavía no hay consumibles: servilletas, vasos y platos desechables, film... "
            "Añádelos en la pestaña 'Añadir producto' de esta lista."
        )
    elif tipo == "mantenimiento":
        st.info(
            "Todavía no hay productos de limpieza y mantenimiento: lejía, lavavajillas, bayetas, bolsas de basura, "
            "gas para los hornillos, pilas... Añádelos en la pestaña 'Añadir producto' de esta lista."
        )
    else:
        st.info("El inventario está vacío todavía.")

    # Lotes caducados: se pueden desechar desde aquí mismo, en un clic.
    for p, l in inv.lotes_caducados():
        c1, c2 = st.columns([4, 1])
        c1.error(f"🗑️ Caducado: **{p.nombre}** — {_num(l.cantidad)} {p.unidad} ({l.etiqueta()})")
        if _boton_confirmado("Desechar lote", f"desechar_{p.nombre}_{l.id}", c2, "¿Desecharlo?"):
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
    tab_add, tab_edit, tab_stock, tab_lotes, tab_precios, tab_limpiar, tab_limpiezas = st.tabs([
        "➕ Añadir producto", "✏️ Editar producto", "📦 Actualizar stock", "🏷️ Lotes", "📈 Historial de precios",
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
    with tab_precios:
        _pestana_precios(inv, nombres_tipo)
    with tab_limpiar:
        if tipo != "alimento":
            st.info("Esta pestaña es para alimentos con merma (se limpian o despiezan).")
        else:
            _pestana_limpiar(inv)
    with tab_limpiezas:
        _pestana_limpiezas(inv)


def _pestana_anadir(inv: Inventario, tipo: str = "alimento") -> None:
    # "Versión" del formulario: al añadir un producto se incrementa, las keys
    # cambian y los campos aparecen vacíos otra vez (lo que hacía clear_on_submit).
    v = st.session_state.setdefault("add_version", 0)
    es_consumible = tipo == "consumible"
    es_alimento = tipo == "alimento"
    lista = {"alimento": "alimentos", "consumible": "consumibles", "mantenimiento": "limpieza y mantenimiento"}[tipo]
    st.caption(f"Se añadirá a la lista de **{lista}**.")

    nombre = st.text_input("Nombre", key=f"add_nombre_{v}")
    categoria = st.text_input("Categoría", key=f"add_categoria_{v}")
    if inv.categorias():
        st.caption("Categorías que ya tienes: " + ", ".join(inv.categorias())
                   + ". Si escribes una igual con otras mayúsculas, se usa la que ya existe.")
    c1, c2 = st.columns(2)
    stock = c1.number_input("Stock inicial (será su primer lote)", min_value=0.0, step=0.1, key=f"add_stock_{v}")
    unidad = c2.selectbox("Unidad", Producto.UNIDADES_VALIDAS, key=f"add_unidad_{v}")

    tiene_merma = False
    peso_unitario = None
    if unidad in UNIDADES_PESO + ("unidades",) and es_alimento:
        tiene_merma = st.checkbox(
            "Producto con merma (se limpia o despieza antes de usarse)", key=f"add_merma_{v}",
            help="Por ejemplo una pata de cerdo o un pescado entero. Solo de estos productos se pueden obtener derivados.",
        )
        if tiene_merma and unidad == "unidades":
            peso_unitario = _campo_peso("Peso en bruto de cada unidad", f"add_peso_{v}")

    iva = _elegir_iva(f"add_iva_{v}")
    c3, c4 = st.columns(2)
    with c3:
        precio = _campo_precio(unidad, stock, lambda campo: f"add_{campo}_{v}", iva=iva)
    stock_minimo = c4.number_input("Stock mínimo", min_value=0.0, step=0.1, key=f"add_stock_minimo_{v}")
    proveedor = st.text_input("Proveedor habitual", key=f"add_proveedor_{v}")
    fecha_caducidad = None
    # La caducidad es de cada lote: sin stock inicial no hay lote al que ponérsela
    # (se indicará al registrar la primera compra).
    if es_consumible:
        pass  # los consumibles no caducan
    elif stock > 0:
        if st.checkbox("¿Este primer lote tiene fecha de caducidad?", key=f"add_tiene_caducidad_{v}"):
            fecha_caducidad = st.date_input("Fecha de caducidad", key=f"add_fecha_{v}", format="DD/MM/YYYY")
    else:
        st.caption("Sin stock inicial: la caducidad se indicará en cada compra (cada compra es un lote).")

    if st.button("Añadir producto", type="primary", key=f"add_boton_{v}"):
        nombre = nombre.strip()
        repetido = next((n for n in inv.productos if n.lower() == nombre.lower()), None)
        if not nombre:
            st.error("Ponle un nombre al producto.")
        elif repetido is not None:
            otro = inv.buscar_producto(repetido)
            lista = {"alimento": "Alimentos", "consumible": "Consumibles", "mantenimiento": "Limpieza y mantenimiento"}
            st.error(f"Ya existe un producto llamado '{repetido}' (en la lista {lista[otro.tipo]}). "
                     "Para añadir otra compra usa 'Actualizar stock' en esa lista.")
        elif stock > 0 and precio is None:
            # Sin precio, el lote entraba a 0 € y todo lo que saliera de él costaría 0 €.
            st.error("Indica el precio de este stock inicial (lo que te costó).")
        else:
            precio = precio or 0.0
            try:
                inv.agregar_producto(Producto(
                    nombre, categoria, stock, unidad, precio, proveedor, stock_minimo, fecha_caducidad,
                    tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=tipo, iva=iva,
                ))
                avisar("success", f"{Producto.NOMBRES_TIPOS[tipo] if not es_alimento else 'Producto'} '{nombre}' añadido.")
                st.session_state.add_version += 1
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))


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
    # Los campos que se rellenan con datos del producto llevan su "huella" en
    # la key: si el producto cambia en otra pestaña (una compra cambia el peso
    # de referencia...), se vuelven a rellenar y al guardar no se deshace nada.
    huella_p = _huella(producto.nombre, producto.categoria, producto.stock_minimo, producto.proveedor, producto.iva,
                       producto.tipo, producto.tiene_merma, producto.peso_unitario_referencia, producto.peso_unitario)
    kv = lambda campo: f"edit_{campo}_{nombre_sel}_{huella_p}"

    st.markdown("**Datos generales**")
    nuevo_nombre = st.text_input("Nombre", value=producto.nombre, key=kv("nombre"))
    categoria = st.text_input("Categoría", value=producto.categoria, key=kv("categoria"))
    c1, c2 = st.columns(2)
    stock_minimo = c1.number_input("Stock mínimo", value=float(producto.stock_minimo), min_value=0.0, step=0.1, key=kv("stock_minimo"))
    proveedor = c2.text_input("Proveedor habitual", value=producto.proveedor, key=kv("proveedor"))
    nuevo_iva = _elegir_iva(kv("iva"), producto.iva)
    if abs(nuevo_iva - producto.iva) > 1e-9:
        st.caption("El IVA nuevo se aplica a las compras de aquí en adelante: cada compra ya hecha conserva el suyo. "
                   "Para corregir el de una compra ya hecha: 📈 Historial de precios › Corregir o anular una compra.")

    # El tipo se puede corregir (por si se dio de alta en la lista equivocada).
    tipos_texto = {nombre: tipo for tipo, nombre in Producto.NOMBRES_TIPOS.items()}
    nuevo_tipo = tipos_texto[st.radio(
        "Tipo", list(tipos_texto), index=Producto.TIPOS.index(producto.tipo), horizontal=True, key=kv("tipo"),
        help="Si lo cambias, el producto pasa a otra lista del inventario.",
    )]
    es_consumible = nuevo_tipo == "consumible"
    if nuevo_tipo != producto.tipo:
        problema_tipo = st.session_state.recetario.problema_cambio_tipo(producto.nombre, nuevo_tipo)
        if problema_tipo:
            st.error(f"No se puede cambiar el tipo: {problema_tipo}")
        elif es_consumible and any(l.fecha_caducidad for l in producto.lotes):
            st.warning("Los consumibles no tienen caducidad: al guardar se quitarán las fechas de caducidad de sus "
                       "lotes.")

    tiene_merma = producto.tiene_merma
    peso_unitario = None
    if nuevo_tipo != "alimento":
        tiene_merma = False
    elif producto.unidad in UNIDADES_PESO + ("unidades",):
        tiene_merma = st.checkbox("Producto con merma (se limpia o despieza)", value=producto.tiene_merma, key=kv("merma"))
        if tiene_merma and producto.unidad == "unidades":
            peso_unitario = _campo_peso(
                "Peso por unidad de referencia (se propone al registrar compras)", kv("peso"),
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
        # La "huella" del lote va en la key: si el lote cambia desde otra
        # pestaña (una salida, una compra corregida...), los campos se
        # vuelven a rellenar con los datos ACTUALES. Sin ella, Streamlit
        # conservaría los valores de antes y al guardar se deshaceria el cambio.
        huella = _huella(lote.cantidad, lote.precio_base, lote.iva, lote.proveedor, lote.fecha_caducidad, lote.peso_unitario)
        kl = lambda campo: f"edit_lote_{campo}_{nombre_sel}_{lote.id}_{huella}"
        c3, c4 = st.columns(2)
        datos_lote["cantidad"] = c3.number_input(
            f"Cantidad ({producto.unidad})", min_value=0.0, value=float(lote.cantidad), step=0.1, key=kl("cantidad"),
        )
        datos_lote["precio"] = c4.number_input(
            "Precio (€, con IVA)", min_value=0.0, value=float(lote.precio_unitario), step=0.1,
            key=kl("precio"), help=f"IVA de esta compra: {nombre_iva(lote.iva)}.",
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
                disabled=not datos_lote["tiene_fecha"], format="DD/MM/YYYY")
        st.caption(
            "Corregir no es un movimiento de stock: no queda en el historial. Si algo se ha gastado o tirado, "
            "regístralo como salida en 'Actualizar stock'. Poner la cantidad a 0 elimina este lote."
        )
        # ¿Cambia la cantidad? Puede ser un recuento o un error al apuntar la compra.
        datos_lote["compra"] = None
        compra_lote = next((c for c in inv.precios_de(producto.nombre) if c.lote_id == lote.id), None)
        if compra_lote is not None and abs(datos_lote["cantidad"] - lote.cantidad) > 1e-9:
            es_error = st.radio(
                "¿Por qué cambia la cantidad?",
                ("Es un recuento: en el lote queda esto",
                 "Fue un error al apuntar la compra: se compró otra cantidad"),
                key=kl("motivo_cantidad"),
            ).startswith("Fue un error")
            if es_error:
                comprada = round(compra_lote.cantidad + datos_lote["cantidad"] - lote.cantidad, 6)
                datos_lote["compra"] = (compra_lote, comprada)
                if comprada > 0:
                    st.caption(
                        f"La compra pasará de {_num(compra_lote.cantidad)} a {_num(comprada)} {producto.unidad}: "
                        "se corrige también su gasto en Métricas, su IVA y el historial de precios."
                    )
            else:
                st.caption("Solo cambia lo que queda en el lote: la compra (gasto, IVA, historial de precios) no se toca.")
        datos_lote["corregir_registrado"] = False
        if (abs(datos_lote["precio"] - lote.precio_unitario) > 1e-9
                or datos_lote["proveedor"].strip() != lote.proveedor):
            datos_lote["corregir_registrado"] = _pregunta_corregir_registrado(
                inv.usos_del_lote(producto.nombre, lote.id), kl("corregir"), producto.unidad,
            )

    if st.button("Guardar cambios", type="primary", key=k("boton")):
        # Se comprueba todo ANTES de guardar nada: o se guarda todo o nada.
        if lote is not None:
            texto = datos_lote["proveedor"].strip()
            if not texto or _parece_numero(texto):
                st.error("El proveedor de la compra debe ser texto, no puede estar vacío ni ser un número.")
                return
            if datos_lote["compra"] is not None and datos_lote["compra"][1] <= 0:
                st.error("La cantidad comprada no puede quedar en 0 o menos. Si la compra no existió, anúlala en "
                         "📈 Historial de precios.")
                return
        nombre_original = producto.nombre
        if nuevo_tipo != producto.tipo and st.session_state.recetario.problema_cambio_tipo(producto.nombre, nuevo_tipo):
            st.error("No se ha guardado nada: el tipo no se puede cambiar (mira el aviso de arriba).")
            return
        try:
            exito = inv.editar_producto(
                nombre_sel,
                nuevo_nombre=nuevo_nombre if nuevo_nombre != producto.nombre else None,
                categoria=categoria, proveedor=proveedor, stock_minimo=stock_minimo,
                tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=nuevo_tipo, iva=nuevo_iva,
            )
            if exito and lote is not None:
                cantidad_lote = datos_lote["cantidad"]
                if datos_lote["compra"] is not None:
                    # Error al apuntar la compra: se corrige la compra, y el lote con ella.
                    compra_lote, comprada = datos_lote["compra"]
                    inv.corregir_compra(compra_lote, cantidad=comprada)
                    cantidad_lote = None
                inv.editar_lote(
                    producto.nombre, lote.id, cantidad=cantidad_lote, precio_unitario=datos_lote["precio"],
                    proveedor=datos_lote["proveedor"],
                    fecha_caducidad=datos_lote["fecha"] if datos_lote["tiene_fecha"] else None,
                    borrar_fecha_caducidad=not datos_lote["tiene_fecha"],
                    peso_unitario=datos_lote["peso"], corregir_registrado=datos_lote["corregir_registrado"],
                )
            if exito:
                if producto.nombre != nombre_original:
                    actualizados = st.session_state.recetario.renombrar_producto(nombre_original, producto.nombre)
                    st.session_state.gestor_compras.renombrar_producto(nombre_original, producto.nombre)
                    if actualizados:
                        avisar("info", f"🔄 Recetas y menús actualizados: {', '.join(actualizados)}")
                avisar("success", "Producto actualizado.")
                st.rerun()
            else:
                st.error(f"No se ha guardado: ya existe otro producto llamado '{nuevo_nombre}'.")
        except ValueError as e:
            st.error(_es(str(e)))

    st.divider()
    _borrar_producto(inv, producto)


def _borrar_producto(inv: Inventario, producto: Producto) -> None:
    """Borrar un producto que ya no se usa (con confirmación). Va al final de 'Editar producto'."""
    nombre = producto.nombre
    with st.expander(f"🗑️ Borrar el producto '{nombre}'"):
        usos = st.session_state.recetario.donde_se_usa_producto(nombre) + inv.donde_se_usa(nombre)
        if usos:
            st.caption(f"No se puede borrar: se usa en {'; '.join(usos)}. Quítalo de ahí antes.")
            return
        if producto.stock > 0:
            st.warning(f"Quedan {_num(producto.stock)} {producto.unidad}: se quitarán sin contar como desperdicio. "
                       "Si se han tirado, regístralo antes como salida (desperdicio).")
        st.caption("Su historial (compras, consumos, precios) se conserva, para no descuadrar los meses pasados.")
        confirmar = st.checkbox(f"Sí, quiero borrar '{nombre}'", key=f"borrar_producto_confirmar_{nombre}")
        if st.button("Borrar producto", key=f"borrar_producto_{nombre}", disabled=not confirmar):
            try:
                inv.borrar_producto(nombre, st.session_state.recetario.donde_se_usa_producto(nombre))
                st.session_state.gestor_compras.quitar_producto(nombre)
                avisar("success", f"Producto '{nombre}' borrado.")
                vaciar_campos("editar_select")
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))


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
        datos = _campos_entrada(producto, k, cantidad)
        # Si este producto está pendiente en la lista de la compra, se ofrece
        # marcarlo también allí (si no, seguiría apareciendo como pendiente).
        pendiente = st.session_state.gestor_compras.pendiente_de(nombre_sel)
        marcar_en_lista = False
        if pendiente is not None:
            st.info(f"🛒 '{nombre_sel}' está pendiente en la lista de la compra ({_num(pendiente.cantidad)} {pendiente.unidad}).")
            marcar_en_lista = st.checkbox("Marcarlo también como comprado en la lista de la compra", value=True,
                                          key=k("marcar_lista"))
        if st.button("Registrar compra", type="primary", key=k("boton")):
            if cantidad <= 0:
                st.error("La cantidad debe ser mayor que 0.")
            elif datos["precio"] is None:
                st.error("Indica el precio de esta compra.")
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
                    if marcar_en_lista:
                        st.session_state.gestor_compras.marcar_comprado(nombre_sel, cantidad_comprada=cantidad)
                        avisar("info", f"🛒 '{nombre_sel}' marcado como comprado en la lista de la compra.")
                    vaciar_campos("stock_", conservar=("stock_select", k("tipo")))
                    st.rerun()
        return

    if not producto.lotes:
        st.warning(f"No queda stock de '{nombre_sel}'.")
        return
    lote_id = _elegir_lote(producto, "¿De qué lote sale?", k("lote"))
    motivo = st.selectbox("Motivo de la salida", MovimientoStock.MOTIVOS_SALIDA, key=k("motivo"))
    servicio_id = None
    if producto.es_mantenimiento() and motivo == "consumo":
        servicios = sorted(
            (s for s in st.session_state.registro_servicios.servicios if s.estado != "cancelado"),
            key=lambda s: (s.fecha, s.hora), reverse=True,
        )
        opciones = {"General (no es de ningún servicio)": None}
        opciones.update({f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}" + (f" ({s.cliente})" if s.cliente else ""): s.id
                         for s in servicios})
        servicio_id = opciones[st.selectbox(
            "¿Para qué servicio?", list(opciones), key=k("servicio"),
            help="Si es para un servicio (lo que te llevas a un evento), su coste cuenta en la rentabilidad de ese "
                 "servicio. Si no, es un gasto general del negocio.",
        )]
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
        elif inv.salida_stock(nombre_sel, cantidad, motivo, lote_id, servicio_id=servicio_id):
            para = f", servicio #{servicio_id}" if servicio_id else ""
            avisar("success", f"Salida registrada: {_num(cantidad)} {producto.unidad} del lote {lote_id} ({motivo}{para}).")
            vaciar_campos("stock_", conservar=("stock_select", k("tipo")))
            st.rerun()
        else:
            st.error("No se ha podido registrar la salida.")


def _texto_usos(usos: dict, unidad: str) -> list[str]:
    """Qué hay ya registrado con un lote, en frases cortas (para avisar antes de corregir su precio)."""
    lineas = []
    if usos["compra"] is not None:
        lineas.append("su **compra** (cuenta como dinero gastado en Métricas)")
    for servicio_id, valor in usos["servicios"].items():
        lineas.append(f"lo que salió para el **servicio #{servicio_id}** ({_eur(valor)} € con el precio actual)")
    otras = [m for m in usos["salidas"] if m.servicio_id is None and m not in usos["derivados"]]
    for m in otras:
        lineas.append(f"una salida de {_num(m.cantidad)} {unidad} el {m.fecha.strftime('%d/%m/%Y')} ({m.motivo})")
    return lineas


def _pregunta_corregir_registrado(usos: dict, clave: str, unidad: str, preguntar: bool = True) -> bool:
    """
    Al corregir el precio (o el proveedor) de una compra: avisa de lo que ya
    está registrado con ella y pregunta si se corrige también. Devuelve True
    si hay que corregirlo.
    """
    lineas = _texto_usos(usos, unidad)
    derivados = usos["derivados"]
    if not usos["salidas"]:
        if lineas:
            st.caption("Se corregirá también su compra en Métricas y en el historial de precios.")
        return True
    st.info("Con este lote ya se ha registrado:\n\n" + "\n".join(f"- {l}" for l in lineas)
            if lineas else "De este lote ya ha salido algo.")
    if derivados:
        st.warning(
            "⚠️ De este lote también salió algo para **elaborar o limpiar** ("
            + ", ".join(f"{_num(m.cantidad)} {unidad} el {m.fecha.strftime('%d/%m/%Y')}" for m in derivados)
            + "). Esas tandas, elaboraciones base o productos limpios ya tienen su coste calculado y **no se "
              "recalculan**: si es importante, corrige su precio a mano."
        )
    if not preguntar:
        return True
    return st.radio(
        "¿Qué hacemos con lo ya registrado?",
        ("Corregirlo también (coste de los servicios, Métricas e historial de precios)",
         "Dejarlo como estaba (solo cambia lo que salga a partir de ahora)"),
        key=clave,
    ).startswith("Corregirlo")


def _pestana_precios(inv: Inventario, nombres: list[str]) -> None:
    con_compras = [n for n in nombres if inv.precios_de(n)]
    if not con_compras:
        st.info("Todavía no hay compras registradas de los productos de esta lista.")
        return
    nombre = st.selectbox("Producto", con_compras, key="precios_select")
    producto = inv.buscar_producto(nombre)
    unidad_txt = "unidad" if producto.unidad == "unidades" else producto.unidad
    compras = inv.precios_de(nombre)

    st.caption("Los precios medios y la gráfica son lo pagado (con IVA).")
    st.markdown("**Por proveedor** (del más barato al más caro, de media)")
    st.dataframe([{
        "Proveedor": f["proveedor"], "Compras": f["compras"],
        f"Precio medio (€/{unidad_txt})": _precio(f["medio"]),
        "Mínimo": _precio(f["minimo"]), "Máximo": _precio(f["maximo"]),
        "Última compra": f"{_precio(f['ultimo'])} € ({f['fecha_ultima'].strftime('%d/%m/%Y')})",
    } for f in inv.resumen_precios_por_proveedor(nombre)], width="stretch", hide_index=True)

    if len(compras) > 1:
        st.markdown(f"**Evolución del precio** (€/{unidad_txt})")
        serie: dict[str, dict[str, float]] = {}
        for c in compras:
            serie.setdefault(c.proveedor, {})[c.fecha.isoformat()] = c.precio_unitario
        st.line_chart(serie)

    st.markdown("**Todas las compras** (de la más reciente a la más antigua)")
    st.dataframe([{
        "Fecha": c.fecha.strftime("%d/%m/%Y"), "Proveedor": c.proveedor,
        "Cantidad": f"{_num(c.cantidad)} {c.unidad}", f"Precio sin IVA (€/{unidad_txt})": _precio(c.precio_base),
        "IVA": nombre_iva(c.iva).split(" (")[0], f"Precio con IVA (€/{unidad_txt})": _precio(c.precio_con_iva),
        "Total pagado (€)": f"{_eur(c.total)}", "Lote": str(c.lote_id or "—"),
        "Origen": "Stock inicial" if c.origen == "inicial" else "Compra",
    } for c in reversed(compras)], width="stretch", hide_index=True)

    with st.expander("✏️ Corregir o anular una compra"):
        st.caption("Para arreglar una compra mal apuntada (precio, cantidad, proveedor o IVA), aunque ese lote ya "
                   "se haya gastado. Se corrige también lo que ya salió de él (coste de los servicios, Métricas...).")
        opciones = {
            f"{c.fecha.strftime('%d/%m/%Y')} · {c.proveedor} · {_num(c.cantidad)} {c.unidad} a {_num(c.precio_unitario)} €"
            + (f" · lote {c.lote_id}" if c.lote_id else ""): c
            for c in reversed(compras)
        }
        compra = opciones[st.selectbox("Compra", list(opciones), key=f"corregir_compra_{nombre}")]
        huella = _huella(compra.precio_base, compra.iva, compra.proveedor, compra.cantidad)
        kc = lambda campo: f"corregir_compra_{campo}_{nombre}_{compra.lote_id}_{compra.fecha.isoformat()}_{huella}"
        lote = producto.buscar_lote(compra.lote_id) if compra.lote_id is not None else None
        c1, c2 = st.columns(2)
        nuevo_precio = c1.number_input(f"Precio correcto (€/{unidad_txt}, con IVA)", min_value=0.0, step=0.1,
                                       value=float(compra.precio_unitario), key=kc("precio"))
        nuevo_proveedor = c2.text_input("Proveedor", value=compra.proveedor, key=kc("proveedor"))
        c3, c4 = st.columns(2)
        nueva_cantidad = c3.number_input(
            f"Cantidad comprada ({producto.unidad})", min_value=0.0, step=0.1, value=float(compra.cantidad),
            key=kc("cantidad"), disabled=compra.lote_id is not None and lote is None,
            help="Lo que se compró de verdad. Lo que queda en el lote se ajusta en la diferencia.",
        )
        if compra.lote_id is not None and lote is None:
            c3.caption("Ese lote ya se gastó entero: su cantidad ya no se puede corregir.")
        nuevo_iva = _elegir_iva(kc("iva"), compra.iva, contenedor=c4, etiqueta="IVA de esta compra")
        cambia_precio = abs(nuevo_precio - compra.precio_unitario) > 1e-9
        cambia_proveedor = nuevo_proveedor.strip() != compra.proveedor
        cambia_cantidad = abs(nueva_cantidad - compra.cantidad) > 1e-9
        cambia_iva = abs(nuevo_iva - compra.iva) > 1e-9
        iva_producto = False
        if cambia_iva:
            st.caption(f"Se mantiene lo que pagaste ({_precio(nuevo_precio)} €/{unidad_txt}, con IVA): se recalculan "
                       "la parte sin IVA y el IVA soportado.")
            iva_producto = abs(nuevo_iva - producto.iva) > 1e-9 and st.checkbox(
                f"Usar también el {nombre_iva(nuevo_iva).split(' (')[0]} en las próximas compras de '{nombre}'",
                value=True, key=kc("iva_producto"),
            )
        if cambia_cantidad and lote is not None:
            queda = lote.cantidad + nueva_cantidad - compra.cantidad
            st.caption(f"En el lote {lote.id} quedarán {_num(max(queda, 0))} {producto.unidad} "
                       f"(ahora {_num(lote.cantidad)}).")
        cambia = cambia_precio or cambia_proveedor or cambia_cantidad or cambia_iva
        if (cambia_precio or cambia_proveedor or cambia_iva) and compra.lote_id is not None:
            _pregunta_corregir_registrado(inv.usos_del_lote(nombre, compra.lote_id), kc("pregunta"), producto.unidad,
                                          preguntar=False)
        if st.button("Guardar corrección", key=kc("guardar"), disabled=not cambia):
            try:
                inv.corregir_compra(
                    compra,
                    precio_unitario=nuevo_precio if cambia_precio or cambia_iva else None,
                    proveedor=nuevo_proveedor if cambia_proveedor else None,
                    cantidad=nueva_cantidad if cambia_cantidad else None,
                    iva=nuevo_iva if cambia_iva else None, iva_tambien_producto=iva_producto,
                )
                avisar("success", f"Compra corregida: {_num(compra.cantidad)} {producto.unidad} a "
                                  f"{_precio(compra.precio_unitario)} €/{unidad_txt} ({compra.proveedor}, "
                                  f"{nombre_iva(compra.iva).split(' (')[0]}).")
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))

        st.divider()
        posible, motivo = inv.se_puede_anular(compra)
        if not posible:
            st.caption(f"🗑️ Anular esta compra: {motivo}")
        else:
            confirmar = st.checkbox(
                "Esta compra no existió (o está apuntada dos veces): quiero anularla", key=kc("anular_confirmar"),
            )
            if st.button("🗑️ Anular compra", key=kc("anular"), disabled=not confirmar):
                inv.anular_compra(compra)
                avisar("success", f"Compra anulada: se han quitado el lote {compra.lote_id} de '{nombre}', su gasto "
                                  "y su línea del historial de precios.")
                st.rerun()


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
    if _boton_confirmado("🗑️ Desechar este lote entero (desperdicio)", f"lotes_desechar_{nombre_sel}_{lote.id}",
                         pregunta=f"¿Desechar el lote {lote.id} entero ({_num(lote.cantidad)} {producto.unidad})?"):
        cantidad_tirada = lote.cantidad
        if inv.desechar_lote(nombre_sel, lote.id):
            avisar("success", f"Lote {lote.id} de '{nombre_sel}' desechado ({_num(cantidad_tirada)} {producto.unidad} a desperdicio).")
            st.rerun()


def _tabla_derivados(nombres: list, pesos: list) -> pd.DataFrame:
    return pd.DataFrame({"Derivado": pd.Series(nombres, dtype="string"), "Peso": pd.Series(pesos, dtype="float")})


def _convertir_pesos_limpieza(k) -> None:
    """Al cambiar la unidad (kg <-> g) en Limpiar producto, convierte el peso limpio y los de los derivados."""
    ss = st.session_state
    nueva, anterior = ss[k("unidad")], ss.get(k("unidad_anterior"), UNIDADES_PESO[0])
    if nueva == anterior:
        return
    factor = convertir(1, anterior, nueva)
    if ss.get(k("peso_limpio")) is not None:
        ss[k("peso_limpio")] = round(ss[k("peso_limpio")] * factor, 6)
    tabla = ss.get(k("derivados_ultima"), ss.get(k("derivados_base")))
    if tabla is not None:
        tabla = tabla.copy()
        tabla["Peso"] = (tabla["Peso"] * factor).round(6)
        ss[k("derivados_base")] = tabla
        ss[k("derivados_version")] = ss.get(k("derivados_version"), 0) + 1
    ss[k("unidad_anterior")] = nueva


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
    # Todo empieza VACÍO (value=None): así nada parece "ya rellenado" de una
    # limpieza anterior y no se registra nada sin haberlo escrito a propósito.
    cantidad = c1.number_input(
        f"Cantidad a limpiar ({origen.unidad}, hay {_num(lote.cantidad)} en este lote)",
        min_value=0.0, max_value=float(lote.cantidad), value=None, placeholder="0",
        step=1.0 if por_unidades else 0.1, key=k("cantidad"),
    ) or 0.0
    peso_bruto_kg = origen.peso_kg(cantidad, lote) if cantidad > 0 else 0.0
    c2.metric("Peso en bruto", f"{_num(peso_bruto_kg)} kg")
    rendimiento = inv.rendimiento_medio(origen_nombre)
    if rendimiento:
        st.caption(
            f"Rendimiento medio hasta ahora: {rendimiento:.0%} -> se esperan ~{_num(peso_bruto_kg * rendimiento)} kg limpios."
        )

    # Al cambiar kg <-> g, lo ya escrito se CONVIERTE (8 kg pasan a 8000 g),
    # en vez de quedarse el mismo número con otra unidad.
    unidad_peso = st.radio("Pesos del resultado en", UNIDADES_PESO, horizontal=True, key=k("unidad"),
                           on_change=_convertir_pesos_limpieza, args=(k,))
    st.session_state[k("unidad_anterior")] = unidad_peso
    c3, c4 = st.columns(2)
    # El producto limpio se ELIGE entre los que ya salen de este bruto, para
    # no crear duplicados por una errata ("Carne cerdo limpia"). Solo si es
    # nuevo se escribe el nombre.
    NUEVO = "➕ Producto limpio nuevo…"
    existentes = [p.nombre for p in inv.productos.values() if p.origen == origen_nombre]
    if existentes:
        elegido = c3.selectbox("Producto limpio", existentes + [NUEVO], index=None,
                               placeholder="Elige el producto limpio...", key=k("limpio_select"))
    else:
        elegido = NUEVO
    if elegido == NUEVO:
        producto_limpio = c3.text_input("Nombre del producto limpio nuevo", key=k("limpio"),
                                        placeholder=f"Ej: {origen_nombre} limpio")
    else:
        producto_limpio = elegido or ""
    peso_limpio = c4.number_input(f"Peso limpio ({unidad_peso})", min_value=0.0, value=None, placeholder="0",
                                  step=0.1, key=k("peso_limpio")) or 0.0
    fecha_caducidad = None
    if st.checkbox("Poner fecha de caducidad al producto limpio", key=k("tiene_fecha")):
        fecha_caducidad = st.date_input("Fecha de caducidad del producto limpio", key=k("fecha"), format="DD/MM/YYYY")

    st.markdown("**Derivados que se aprovechan**")
    st.caption("Una fila por cada parte que se reaprovecha, con su peso. Lo que no pongas aquí se registra como merma.")
    # La tabla empieza vacía. Los derivados de la última vez solo se añaden
    # si se pide con el botón (y entonces con peso 0, para escribirlo), SIN
    # borrar las filas que ya estuvieran escritas.
    ss = st.session_state
    if k("derivados_base") not in ss:
        ss[k("derivados_base")] = _tabla_derivados([], [])
        ss[k("derivados_version")] = 0
    habituales = inv.derivados_habituales(origen_nombre)
    escritos = set(ss.get(k("derivados_ultima"), ss[k("derivados_base")])["Derivado"].dropna().astype(str).str.strip())
    faltan = [h for h in habituales if h not in escritos]
    if faltan:
        c5, c6 = st.columns([3, 1])
        c5.caption("La última vez se aprovechó: " + ", ".join(habituales))
        if c6.button("Añadir los de la última vez", key=k("boton_habituales")):
            actual = ss.get(k("derivados_ultima"), ss[k("derivados_base")])
            ss[k("derivados_base")] = pd.concat([actual, _tabla_derivados(faltan, [0.0] * len(faltan))],
                                                ignore_index=True)
            ss[k("derivados_version")] += 1
            st.rerun()
    tabla = st.data_editor(
        ss[k("derivados_base")], num_rows="dynamic", width="stretch", hide_index=True,
        key=k(f"derivados_{ss[k('derivados_version')]}"),
        column_config={
            "Derivado": st.column_config.TextColumn("Derivado"),
            "Peso": st.column_config.NumberColumn(f"Peso ({unidad_peso})", min_value=0.0, step=0.01),
        },
    )
    ss[k("derivados_ultima")] = tabla  # lo que hay escrito ahora (para convertir o añadir filas sin perderlas)
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
        m1.metric("Limpio", f"{_num(limpio_kg)} kg")
        m2.metric("Derivados", f"{_num(derivados_kg)} kg")
        m3.metric("Merma", f"{_num(max(merma_kg, 0))} kg")
        m4.metric("Rendimiento", f"{_pct(limpio_kg / peso_bruto_kg)}")
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
                f"Limpieza registrada: {_num(limpieza.peso_limpio_kg)} kg de '{limpieza.producto_limpio}' "
                f"(rendimiento {_pct(limpieza.rendimiento)}, merma {_num(limpieza.merma_kg)} kg).",
            )
            st.session_state.limpiar_version += 1
            st.rerun()
        except ValueError as e:
            st.error(_es(str(e)))


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
            "Bruto total (kg)": _num(bruto),
            "Rendimiento medio": f"{_pct(inv.rendimiento_medio(nombre))}",
            "Derivados aprovechados": f"{_pct(sum(sum(l.derivados_kg.values()) for l in limpiezas) / bruto)}",
            "Merma media": f"{_pct(sum(l.merma_kg for l in limpiezas) / bruto)}",
        })
    st.dataframe(filas_resumen, width="stretch", hide_index=True)

    st.subheader("Historial")
    st.dataframe([{
        "Fecha": l.fecha.strftime("%d/%m/%Y"),
        "Producto": l.producto_origen,
        "Lote": str(l.lote_origen or "—"),
        "Cantidad": f"{_num(l.cantidad_origen)} {l.unidad_origen}",
        "Bruto (kg)": _num(l.peso_bruto_kg),
        "Producto limpio": l.producto_limpio,
        "Limpio (kg)": _num(l.peso_limpio_kg),
        "Derivados": ", ".join(f"{n} ({_num(kg)} kg)" for n, kg in l.derivados_kg.items()) or "—",
        "Merma (kg)": _num(l.merma_kg),
        "Rendimiento": f"{_pct(l.rendimiento)}",
        "Coste (€)": _eur(l.coste),
    } for l in reversed(inv.limpiezas)], width="stretch", hide_index=True)


# ---------- Inventario: elaboraciones (recetas preparadas por adelantado) ----------

def _seccion_elaboraciones() -> None:
    inv = st.session_state.inventario
    rec = st.session_state.recetario
    reg = inv.elaboraciones

    if reg.tandas:
        filas = []
        for t in sorted(reg.tandas, key=lambda t: (t.receta, t.fecha_caducidad or date.max)):
            dias = t.dias_para_caducar()
            estado = "—" if dias is None else ("⚠️ Caducada" if dias < 0 else f"Caduca en {dias} día(s)")
            filas.append({
                "Receta": t.receta, "Tanda": t.id, "Raciones": f"{_num(t.raciones)} de {_num(t.raciones_iniciales)}",
                "Preparada": t.fecha_preparacion.strftime("%d/%m/%Y"),
                "Caducidad": t.fecha_caducidad.strftime("%d/%m/%Y") if t.fecha_caducidad else "—", "Estado": estado,
                "Coste/ración (€)": f"{_eur(t.coste_por_racion)}", "Valor (€)": f"{_eur(t.valor())}",
            })
        st.dataframe(filas, width="stretch", hide_index=True)
        st.caption("Recetas preparadas por adelantado. Al completar un servicio se pueden usar en vez de los ingredientes.")
    else:
        st.info("No hay elaboraciones. Prepara una receta por adelantado en la pestaña 'Preparar'.")

    for t in reg.caducadas():
        c1, c2 = st.columns([4, 1])
        c1.error(f"🗑️ Caducada: **{t.receta}** — {_num(t.raciones)} raciones ({t.etiqueta()})")
        if _boton_confirmado("Desechar", f"desechar_tanda_{t.id}", c2, "¿Desecharla?"):
            uso = reg.desechar(t.id)
            avisar("success", f"Tanda {t.id} de '{t.receta}' desechada ({_num(uso.raciones)} raciones, {_eur(uso.coste)} € a desperdicio).")
            st.rerun()
    proximas = reg.proximas_a_caducar()
    if proximas:
        st.warning("⏳ Próximas a caducar: " + ", ".join(
            f"{t.receta} tanda {t.id} ({_num(t.raciones)} raciones, {t.dias_para_caducar()}d)" for t in proximas
        ))

    st.divider()
    tab_preparar, tab_bases, tab_corregir = st.tabs(
        ["➕ Preparar", "🧪 Preparaciones de bases", "✏️ Corregir o desechar una tanda"]
    )

    with tab_preparar:
        que = st.radio(
            "¿Qué preparas?", ("Un plato (raciones)", "Una elaboración base (kg / litros)"),
            horizontal=True, key="elab_que",
            help="Un plato se guarda como una tanda de raciones. Una elaboración base (sofrito, fondo, salsa...) "
                 "entra en el inventario como un alimento más, y las recetas la usan como ingrediente.",
        )
        if que.startswith("Un plato"):
            if not rec.recetas:
                st.info("No hay recetas. Créalas en el Recetario.")
            else:
                _preparar_elaboracion(inv, rec)
        elif not inv.bases():
            st.info("No hay elaboraciones base. Créalas en Recetario > 🧪 Elaboraciones base.")
        else:
            _preparar_base(inv, rec)

    with tab_bases:
        preparaciones = sorted(reg.preparaciones_base, key=lambda p: p.fecha, reverse=True)
        if not preparaciones:
            st.info("Todavía no se ha preparado ninguna elaboración base.")
        else:
            st.dataframe([{
                "Fecha": p.fecha.strftime("%d/%m/%Y"), "Elaboración": p.producto,
                "Prevista": f"{_num(p.prevista)} {p.unidad}", "Obtenida": f"{_num(p.obtenida)} {p.unidad}",
                "Diferencia": f"{p.diferencia:+g} {p.unidad}",
                "Coste (€)": f"{_eur(p.coste)}", "Coste/unidad (€)": _precio(p.coste_por_unidad),
                "Lote": str(p.lote_id or "—"),
            } for p in preparaciones], width="stretch", hide_index=True)
            st.caption("Prevista = lo que debía salir según la fórmula. Obtenida = lo que salió de verdad.")

    with tab_corregir:
        if not reg.tandas:
            st.info("No hay tandas.")
            return
        opciones = {f"{t.receta} · {_es(t.descripcion())}": t for t in sorted(reg.tandas, key=lambda t: (t.receta, t.id))}
        tanda = opciones[st.selectbox("Tanda", list(opciones), key="elab_corregir_select")]
        huella = _huella(tanda.raciones, tanda.fecha_caducidad)  # ver _pestana_editar
        k = lambda campo: f"elab_corr_{campo}_{tanda.id}_{huella}"
        st.caption("Corregir sirve para arreglar un dato mal apuntado. No cuenta como consumo ni como desperdicio.")
        c1, c2 = st.columns(2)
        raciones = c1.number_input("Raciones que quedan", min_value=0.0, step=1.0, value=float(tanda.raciones), key=k("raciones"))
        caducidad = c2.date_input("Caducidad", value=tanda.fecha_caducidad, key=k("caducidad"), format="DD/MM/YYYY")
        b1, b2 = st.columns(2)
        if b1.button("Guardar corrección", type="primary", key=k("guardar")):
            try:
                reg.corregir(tanda.id, raciones=raciones, fecha_caducidad=caducidad)
            except ValueError as e:
                st.error(_es(str(e)))
            else:
                avisar("success", f"Tanda {tanda.id} de '{tanda.receta}' corregida.")
                st.rerun()
        if _boton_confirmado("🗑️ Desechar la tanda entera (desperdicio)", k("desechar"), b2,
                             f"¿Desechar las {_num(tanda.raciones)} raciones?"):
            uso = reg.desechar(tanda.id)
            avisar("success", f"Tanda {tanda.id} de '{tanda.receta}' desechada ({_num(uso.raciones)} raciones, {_eur(uso.coste)} €).")
            st.rerun()


def _preparar_elaboracion(inv: Inventario, rec: Recetario) -> None:
    v = st.session_state.setdefault("elab_version", 0)
    nombre = st.selectbox("Receta", list(rec.recetas), key=f"elab_receta_{v}")
    receta = rec.recetas[nombre]
    k = lambda campo: f"elab_{campo}_{nombre}_{v}"
    _mostrar_nota(receta)
    c1, c2, c3 = st.columns(3)
    raciones = c1.number_input("Raciones", min_value=0.0, step=1.0, value=None, placeholder="0", key=k("raciones")) or 0.0
    fecha_prep = c2.date_input("Preparada el", value=date.today(), max_value=date.today(), key=k("fecha_prep"),
                               format="DD/MM/YYYY")
    propuesta = receta.caducidad_propuesta(fecha_prep)
    # La key lleva la fecha de preparación: si se cambia, se vuelve a proponer la caducidad.
    caducidad = c3.date_input("Caduca el", value=propuesta, min_value=fecha_prep, key=k(f"caducidad_{fecha_prep.isoformat()}"), format="DD/MM/YYYY")
    if receta.vida_util_dias is not None:
        st.caption(f"'{nombre}' dura {_texto_vida(receta.vida_util_dias)} una vez hecha: se propone la caducidad según eso.")
    else:
        st.caption(f"'{nombre}' no tiene vida útil: indica la caducidad a mano (puedes ponérsela a la receta en el Recetario).")

    if raciones <= 0:
        return
    filas = rec.previsualizar_elaboracion(nombre, raciones, inv)
    elecciones = _elegir_lotes(filas, inv, k("lote"))
    filas = rec.previsualizar_elaboracion(nombre, raciones, inv, elecciones)
    st.dataframe([{
        "Ingrediente": f["ingrediente"], "Necesario": f"{_num(f['necesario'])} {f['unidad']}",
        "En stock": f"{_num(f['en_stock'])} {f['unidad']}" if f["existe"] else "no existe",
        "De qué lotes": _texto_reparto(f),
        "Falta": f"{_num(f['faltante'])} {f['unidad']}" if f["faltante"] > 0 else "—",
    } for f in filas], width="stretch", hide_index=True)
    _aviso_caducados(filas)
    if any(f["faltante"] > 1e-9 or not f["existe"] for f in filas):
        st.warning("No hay ingredientes suficientes para tantas raciones.")

    if st.button("Preparar", type="primary", key=k("boton")):
        if caducidad is None:
            st.error("Indica la fecha de caducidad de esta tanda.")
            return
        try:
            tanda = rec.preparar_elaboracion(nombre, raciones, inv, elecciones, caducidad, fecha_prep)
            avisar("success", f"Preparadas {_num(raciones)} raciones de '{nombre}' ({tanda.etiqueta()}, "
                              f"{_eur(tanda.coste_por_racion)} €/ración).")
            st.session_state.elab_version = v + 1
            st.rerun()
        except ValueError as e:
            st.error(_es(str(e)))


def _preparar_base(inv: Inventario, rec: Recetario) -> None:
    v = st.session_state.setdefault("base_version", 0)
    nombre = st.selectbox("Elaboración base", [p.nombre for p in inv.bases()], key=f"base_preparar_{v}")
    producto = inv.buscar_producto(nombre)
    k = lambda campo: f"base_{campo}_{nombre}_{v}"
    _mostrar_nota(producto)
    f = producto.formula
    st.caption(
        f"Fórmula: para {_num(f['cantidad'])} {producto.unidad} → "
        + ", ".join(f"{_num(c)} {inv.buscar_producto(i).unidad if inv.buscar_producto(i) else ''} de {i}"
                    for i, c in f["ingredientes"].items())
    )
    c1, c2, c3 = st.columns(3)
    prevista = c1.number_input(f"Cantidad a preparar ({producto.unidad})", min_value=0.0, step=0.5, value=None,
                               placeholder="0", key=k("prevista")) or 0.0
    fecha_prep = c2.date_input("Preparada el", value=date.today(), max_value=date.today(), key=k("fecha_prep"),
                               format="DD/MM/YYYY")
    caducidad = c3.date_input("Caduca el", value=producto.caducidad_propuesta(fecha_prep),
                              min_value=fecha_prep, key=k(f"caducidad_{fecha_prep.isoformat()}"), format="DD/MM/YYYY")
    if producto.vida_util_dias is None:
        st.caption(f"'{nombre}' no tiene vida útil: indica la caducidad a mano (puedes ponérsela en el Recetario).")
    if prevista <= 0:
        return
    filas = rec.previsualizar_base(nombre, prevista, inv)
    elecciones = _elegir_lotes(filas, inv, k("lote"))
    filas = rec.previsualizar_base(nombre, prevista, inv, elecciones)
    st.dataframe([{
        "Ingrediente": fi["ingrediente"], "Necesario": f"{_num(fi['necesario'])} {fi['unidad']}",
        "En stock": f"{_num(fi['en_stock'])} {fi['unidad']}" if fi["existe"] else "no existe",
        "De qué lotes": _texto_reparto(fi),
        "Falta": f"{_num(fi['faltante'])} {fi['unidad']}" if fi["faltante"] > 0 else "—",
    } for fi in filas], width="stretch", hide_index=True)
    _aviso_caducados(filas)
    if any(fi["faltante"] > 1e-9 or not fi["existe"] for fi in filas):
        st.warning("No hay ingredientes suficientes para preparar tanto.")

    obtenida = st.number_input(
        f"¿Cuánto ha salido de verdad? ({producto.unidad})", min_value=0.0, step=0.1, value=None,
        placeholder=_num(prevista), key=k("obtenida"),
        help="Lo que ha salido realmente. Puede ser más o menos de lo previsto: queda apuntada la diferencia.",
    )
    if st.button("Preparar", type="primary", key=k("boton")):
        if not obtenida:
            st.error("Indica cuánto ha salido de verdad.")
            return
        if caducidad is None:
            st.error("Indica la fecha de caducidad.")
            return
        try:
            prep = rec.preparar_base(nombre, prevista, obtenida, inv, elecciones, caducidad, fecha_prep)
            avisar("success", f"Preparado '{nombre}': previsto {_num(prevista)}, obtenido {_num(obtenida)} "
                              f"{producto.unidad} (diferencia {prep.diferencia:+g}). Coste {_eur(prep.coste)} € "
                              f"({_precio(prep.coste_por_unidad)} €/{producto.unidad}).")
            st.session_state.base_version = v + 1
            st.rerun()
        except ValueError as e:
            st.error(_es(str(e)))


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
                st.error(_es(str(e)))

    if not reg.materiales:
        return
    nombres = list(reg.materiales)

    with tab_edit:
        nombre_sel = st.selectbox("Material a editar", nombres, key="mat_editar_select")
        material = reg.buscar(nombre_sel)
        huella = _huella(material.nombre, material.categoria, material.cantidad_total, material.precio_reposicion,
                         material.proveedor)  # ver _pestana_editar
        k = lambda campo: f"mat_edit_{campo}_{nombre_sel}_{huella}"
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
                st.error(_es(str(e)))

        with st.expander(f"🗑️ Borrar el material '{nombre_sel}'"):
            if reg.en_uso(nombre_sel):
                st.caption(f"No se puede borrar: hay {reg.en_uso(nombre_sel)} unidades fuera en algún servicio. "
                           "Registra antes su vuelta (Servicios › Material).")
            else:
                menus = [m.nombre for m in st.session_state.recetario.menus.values()
                         if nombre_sel in m.materiales_por_comensal]
                if menus:
                    st.caption(f"Se quitará también de estos menús: {', '.join(menus)}.")
                st.caption("Sus roturas y pérdidas se conservan (siguen contando en el coste de sus servicios).")
                confirmar = st.checkbox(f"Sí, quiero borrar '{nombre_sel}'", key=k("borrar_confirmar"))
                if st.button("Borrar material", key=k("borrar"), disabled=not confirmar):
                    try:
                        reg.borrar_material(nombre_sel)
                        quitado = st.session_state.recetario.quitar_material(nombre_sel)
                        avisar("success", f"Material '{nombre_sel}' borrado."
                                          + (f" Quitado de los menús: {', '.join(quitado)}." if quitado else ""))
                        vaciar_campos("mat_editar_select")
                        st.rerun()
                    except ValueError as e:
                        st.error(_es(str(e)))

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
                        vaciar_campos(k("unidades"))
                        st.rerun()
                    else:
                        st.error("Indica cuántas unidades has comprado.")
                else:
                    tipo = "rotura" if accion == "Se ha roto" else "pérdida"
                    incidencia = reg.dar_de_baja(nombre_sel, int(unidades), tipo)
                    avisar("success", f"{tipo.capitalize()} registrada: {incidencia.cantidad} x {nombre_sel} ({_eur(incidencia.coste)} €).")
                    vaciar_campos(k("unidades"))
                    st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))

    with tab_incidencias:
        if not reg.incidencias:
            st.info("No hay roturas ni pérdidas registradas.")
        else:
            st.dataframe([{
                "Fecha": i.fecha.strftime("%d/%m/%Y"), "Tipo": i.tipo, "Material": i.material, "Unidades": i.cantidad,
                "Coste (€)": f"{_eur(i.coste)}", "Dónde": f"Servicio #{i.servicio_id}" if i.servicio_id else "Almacén",
            } for i in reversed(reg.incidencias)], width="stretch", hide_index=True)
            st.metric("Coste total de roturas y pérdidas", f"{_eur(sum(i.coste for i in reg.incidencias))} €")


# ---------- Servicios: salida y vuelta del material ----------

def _pestana_material_servicio(serv: RegistroServicios, rec: Recetario) -> None:
    reg = st.session_state.registro_material
    if not reg.materiales:
        st.info("No hay material registrado. Añádelo en Inventario > 🍽️ Material.")
        return
    # Un servicio cancelado solo aparece si tiene material fuera: para poder registrar su vuelta.
    servicios = sorted((s for s in serv.servicios if s.estado != "cancelado" or reg.salida_de(s.id)),
                       key=lambda s: (s.fecha, s.hora))
    if not servicios:
        st.info("No hay servicios.")
        return
    opciones = {}
    for s in servicios:
        fuera = " · 🚚 material fuera" if reg.salida_de(s.id) else ""
        cancelado = " · ❌ cancelado" if s.estado == "cancelado" else ""
        opciones[f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}{cancelado}{fuera}"] = s
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
                detalle = f" Roturas y pérdidas: {_eur(coste)} €." if incidencias else " Ha vuelto todo."
                avisar("success", f"Material del servicio #{servicio.id} de vuelta.{detalle}")
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))
        st.divider()
    if servicio.estado == "cancelado":
        st.caption("Este servicio está cancelado: solo se puede registrar la vuelta de su material.")
        return

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
            vaciar_campos(f"carga_{servicio.id}_")
            st.rerun()
        except ValueError as e:
            st.error(_es(str(e)))

    anteriores = [s for s in reg.salidas_de(servicio.id) if s.ha_vuelto]
    if anteriores:
        st.caption("Ya volvió: " + "; ".join(
            f"{s.fecha_vuelta.strftime('%d/%m/%Y')}: " + ", ".join(f"{s.vuelto.get(n, 0)}/{c} {n}" for n, c in s.cantidades.items())
            for s in anteriores
        ))


# ---------- Página: Servicios ----------

def _elegir_lotes_servicio(
    servicio: Servicio, inv: Inventario, rec: Recetario, plan: Optional[dict] = None,
) -> dict[str, list[int]]:
    """Elegir los lotes de los ingredientes de un servicio (ver _elegir_lotes)."""
    return _elegir_lotes(rec.previsualizar_consumo(servicio, inv, None, plan) or [], inv, f"completar_lote_{servicio.id}")


def _elegir_lotes(filas: list[dict], inv: Inventario, prefijo: str) -> dict[str, list[int]]:
    """
    Para cada ingrediente con varios lotes, el usuario elige de qué lote
    sale (se propone el bueno que caduca antes; los caducados van al final
    y se marcan). Si ese lote no llega, aparece
    otro desplegable, VACÍO, para que elija con qué lote completar lo que
    falta... y así hasta cubrirlo todo. Devuelve {ingrediente: [lotes en orden]}.
    Lo usan completar un servicio y preparar una elaboración.
    """
    elecciones: dict[str, list[int]] = {}
    for fila in filas:
        producto = inv.buscar_producto(fila["ingrediente"])
        # Sin nada que elegir: no existe, no hay stock, solo tiene un lote,
        # o no llega ni con todos los lotes (entonces se usan todos).
        if (producto is None or fila["a_descontar"] <= 0 or len(producto.lotes) <= 1
                or fila["necesario"] >= fila["en_stock"] - 1e-9):
            continue
        ingrediente = fila["ingrediente"]
        base = f"{prefijo}_{ingrediente}"
        elegidos: list[int] = []
        # Primero los lotes buenos (el que caduca antes, propuesto); los caducados, al final.
        primero = _elegir_lote(
            producto, f"{ingrediente}: ¿de qué lote sale? (hacen falta {_num(fila['necesario'])} {producto.unidad})",
            f"{base}_0", lotes=producto.lotes_para_usar(),
        )
        elegidos.append(primero)
        while True:
            _, pendiente = inv.repartir(ingrediente, fila["necesario"], elegidos)
            restantes = [l for l in producto.lotes_para_usar() if l.id not in elegidos]
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


def _elegir_tandas_servicio(servicio: Servicio, inv: Inventario, rec: Recetario) -> dict[str, list[int]]:
    """
    Para cada receta del menú de la que haya raciones PREPARADAS, el usuario
    elige de qué tanda salen (se propone la que caduca antes y no habrá
    caducado el día del servicio), o no usarlas. Si la tanda no llega, puede
    completar con otra tanda o hacer el resto con ingredientes en crudo.
    Devuelve {receta: [tandas en orden]} (lista vacía = no usar).
    """
    menu = rec.buscar_menu(servicio.menu)
    if menu is None:
        return {}
    plan: dict[str, list[int]] = {}
    NO_USAR = "No usar raciones preparadas"
    CRUDO = "El resto, con ingredientes en crudo"
    titulo_puesto = False
    for receta in menu.recetas:
        tandas = inv.elaboraciones.tandas_de(receta.nombre)
        if not tandas:
            continue
        if not titulo_puesto:
            st.markdown("**🥘 Raciones ya preparadas**")
            titulo_puesto = True

        def texto(t) -> str:
            aviso = " · ⚠️ caducada ese día" if t.esta_caducada(servicio.fecha) else ""
            return _es(t.descripcion()) + aviso

        opciones = {texto(t): t.id for t in tandas}
        validas = [texto(t) for t in tandas if not t.esta_caducada(servicio.fecha)]
        lista = [NO_USAR] + list(opciones)
        base = f"completar_tanda_{servicio.id}_{receta.nombre}"
        primera = st.selectbox(
            f"{receta.nombre}: ¿usar raciones preparadas? (hacen falta {servicio.comensales})", lista,
            # Si ya hay una elección guardada (al volver al paso 1), manda esa: no se pasa otra por defecto.
            index=0 if f"{base}_0" in st.session_state else (lista.index(validas[0]) if validas else 0),
            key=f"{base}_0",
        )
        elegidas: list[int] = [] if primera == NO_USAR else [opciones[primera]]
        while elegidas:
            _, faltan = inv.elaboraciones.repartir(receta.nombre, servicio.comensales, elegidas)
            otras = [t for t in tandas if t.id not in elegidas]
            if faltan <= 1e-9 or not otras:
                break
            siguiente = st.selectbox(
                f"Esa tanda no llega: faltan {_num(faltan)} raciones de {receta.nombre}. ¿Cómo las completas?",
                [CRUDO] + [texto(t) for t in otras], key=f"{base}_{len(elegidas)}",
            )
            if siguiente == CRUDO:
                break
            elegidas.append(opciones[siguiente])
        plan[receta.nombre] = elegidas
    return plan


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
                f"• 📦 {extra['producto']}{marca}: comprados {_num(extra['comprada'])} {unidad} por {_eur(extra['importe'])} €, "
                f"usados {_num(extra['usada'])}" + (f", sobran {_num(sobra)} (al inventario)" if sobra > 0 else "")
            )
        else:
            c1.write(f"• {extra['concepto']} ({extra['categoria']}): {_eur(extra['importe'])} €")
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
        importe_con_iva = st.radio(
            "El importe es", ("Con IVA incluido", "Sin IVA"), horizontal=True, key=k("importe_iva"),
            help="Como venga en el ticket o la factura: el programa separa el IVA según el tipo del producto.",
        ) != "Sin IVA"
        proveedor = st.text_input(
            "Dónde se compró", value=producto.proveedor if producto and not es_nuevo else "", key=k("proveedor"),
            help="Si lo dejas vacío, se usa el proveedor habitual del producto.",
        )
        fecha = None
        es_consumible = producto.es_consumible() if producto else ficha["tipo"] == "consumible"
        if not es_consumible and comprada > usada and st.checkbox(
            "Lo que sobra tiene fecha de caducidad", key=k("tiene_fecha")
        ):
            fecha = st.date_input("Fecha de caducidad", key=k("fecha"), format="DD/MM/YYYY")
        if comprada > 0 and usada > comprada:
            st.error("Lo usado no puede ser más que lo comprado.")
        st.session_state[f"{clave}_sin_anadir"] = comprada > 0 or importe > 0 or (es_nuevo and bool(nombre))
        nuevo = {"concepto": f"{nombre} (compra no prevista)", "categoria": "Otros", "importe": importe,
                 "producto": nombre, "comprada": comprada, "usada": usada, "proveedor": proveedor,
                 "fecha_caducidad": fecha, "producto_nuevo": producto if es_nuevo else None,
                 "importe_incluye_iva": importe_con_iva,
                 "error_ficha": ficha["error"] if es_nuevo else None}
    else:
        c1, c2, c3 = st.columns([3, 2, 1])
        concepto = c1.text_input("Concepto", key=k("concepto"), placeholder="Ej: Taxi de vuelta")
        categoria = c2.selectbox("Categoría", Gasto.CATEGORIAS, index=len(Gasto.CATEGORIAS) - 1, key=k("categoria"))
        importe = c3.number_input("Importe (€, con IVA)", min_value=0.0, step=1.0, key=k("importe"))
        iva = _iva_gasto(categoria, k("iva"))
        st.session_state[f"{clave}_sin_anadir"] = bool(concepto.strip()) or importe > 0
        nuevo = {"concepto": concepto.strip(), "categoria": categoria, "importe": importe, "iva": iva}

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
            st.session_state[f"{clave}_sin_anadir"] = False
            st.rerun()
    return extras


def _coste_sin_anadir(servicio: Servicio) -> bool:
    """True si hay un coste adicional escrito pero sin pulsar '➕ Añadir coste' (se perdería al completar)."""
    return bool(st.session_state.get(f"extras_{servicio.id}_sin_anadir"))


def _iva_gasto(categoria: str, clave: str, contenedor=None) -> float:
    """IVA de un gasto: 21 % por defecto; 'Sin IVA' para personal y seguros (se puede cambiar)."""
    return _elegir_iva(f"{clave}_{categoria}", Gasto.iva_propuesto(categoria),
                       contenedor=contenedor, etiqueta="IVA de este gasto")


def _ficha_producto_nuevo(k) -> dict:
    """
    Los datos de un producto NUEVO, los mismos que en Inventario > Añadir
    producto (sin el stock ni el precio: los pone la propia compra).
    Devuelve {"producto": Producto o None, "error": texto o None, "unidad", "tipo"}.
    El producto NO se añade al inventario aquí: solo se prepara, y se añade
    al completar el servicio.
    """
    st.caption("Datos del producto nuevo (como en Inventario > Añadir producto):")
    tipos = {nombre: tipo for tipo, nombre in Producto.NOMBRES_TIPOS.items()}
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
    iva = _elegir_iva(k("nuevo_iva"))
    resultado = {"producto": None, "error": None, "unidad": unidad, "tipo": tipo}
    if not nombre.strip():
        resultado["error"] = "Ponle un nombre al producto nuevo."
        return resultado
    try:
        resultado["producto"] = Producto(
            nombre.strip(), categoria, 0, unidad, 0, proveedor, stock_minimo,
            tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=tipo, iva=iva,
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
                    nuevo_producto.precio_referencia = extra["importe"] / extra["comprada"]
                    inv.agregar_producto(nuevo_producto)
                inv.compra_para_servicio(
                    extra["producto"], extra["comprada"], extra["usada"], extra["importe"], servicio.id,
                    proveedor=extra["proveedor"], fecha_caducidad=extra["fecha_caducidad"],
                    importe_incluye_iva=extra.get("importe_incluye_iva", True),
                )
            except ValueError as e:
                avisar("error", f"No se pudo registrar la compra de '{extra['producto']}': {e}")
        else:
            gastos.agregar_gasto(Gasto(extra["concepto"], extra["categoria"], extra["importe"], servicio_id=servicio.id,
                                       notas=NOTA_COSTE_AL_COMPLETAR,
                                       iva=extra.get("iva")))
    if extras:
        avisar("info", f"💶 {len(extras)} coste(s) adicional(es) registrado(s) para el servicio "
                       f"({_eur(sum(e['importe'] for e in extras))} €).")
    st.session_state[f"extras_{servicio.id}"] = []


def _texto_reparto(fila: dict) -> str:
    if not fila["reparto"]:
        return "—"
    caducados = {lote_id for lote_id, _, _ in fila.get("caducados", [])}
    partes = [f"{_num(cantidad)} {fila['unidad']} del lote {lote_id}" + (" ⚠️ CADUCADO" if lote_id in caducados else "")
              for lote_id, cantidad in fila["reparto"]]
    if fila["sin_asignar"] > 1e-9:
        partes.append(f"⚠️ {_num(fila['sin_asignar'])} {fila['unidad']} sin lote elegido")
    return " + ".join(partes)


def _aviso_caducados(filas: list[dict]) -> None:
    """Aviso en rojo si se va a gastar algo de un lote YA caducado (no se prohíbe: lo decide quien usa el programa)."""
    partes = [
        f"{_num(cantidad)} {f['unidad']} de {f['ingrediente']} (lote {lote_id}, caducó el {caduca.strftime('%d/%m/%Y')})"
        for f in filas for lote_id, cantidad, caduca in f.get("caducados", [])
    ]
    if partes:
        st.error("⚠️ Vas a usar producto **CADUCADO**: " + "; ".join(partes)
                 + ". Si no quieres, elige otro lote (si lo hay) o desecha ese lote en el Inventario.")


def _texto_euros(valor: Optional[float]) -> str:
    return "—" if valor is None else f"{_eur(valor)} €"


def _pestana_rentabilidad(serv: RegistroServicios, inv: Inventario, rec: Recetario) -> None:
    gastos = st.session_state.registro_gastos
    material = st.session_state.registro_material
    servicios = sorted((s for s in serv.servicios if s.estado != "cancelado"), key=lambda s: (s.fecha, s.hora))
    if not servicios:
        st.info("No hay servicios.")
        return

    st.caption(
        f"Para el margen, lo comprado cuenta {_criterio_rentabilidad()} (Ajustes); el cobro, sin IVA. "
        "Coste = comida + consumibles + limpieza y mantenimiento + gastos del servicio (gasolina, personal...) + material roto o perdido. En los servicios completados es "
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
        {"Concepto": "🍅 Comida", "Importe (€)": f"{_eur(r['comida'])}"},
        {"Concepto": "🧻 Consumibles", "Importe (€)": f"{_eur(r['consumibles'])}"},
        {"Concepto": "🧽 Limpieza y mantenimiento", "Importe (€)": f"{_eur(r['mantenimiento'])}"},
    ] + [{"Concepto": f"💶 {cat}", "Importe (€)": f"{_eur(imp)}"} for cat, imp in r["gastos_por_categoria"].items()]
    if r["material"]:
        desglose.append({"Concepto": "🍽️ Material roto o perdido", "Importe (€)": f"{_eur(r['material'])}"})
    st.dataframe(desglose, width="stretch", hide_index=True)
    if r["sin_iva"]:
        st.caption(
            f"Comida, consumibles, limpieza y gastos van **sin IVA**, porque el negocio lo recupera (Ajustes). IVA "
            f"de lo comprado y los gastos de este servicio: **{_eur(r['iva_recuperable'])} €** (lo pagado fue "
            f"{_eur(r['comida'] + r['consumibles'] + r['mantenimiento'] + r['gastos'] + r['iva_recuperable'])} €)."
        )
    else:
        st.caption("Comida, consumibles y limpieza van **con IVA** (lo pagado), porque el negocio no lo recupera (Ajustes).")
    gastos_servicio = gastos.gastos_de_servicio(servicio.id)
    if gastos_servicio:
        st.caption("Gastos de este servicio: " + "; ".join(f"{g.concepto} ({_eur(g.importe)} €)" for g in gastos_servicio))
    else:
        st.caption("Este servicio no tiene gastos apuntados. Se añaden en la página 'Gastos'.")

    k = lambda campo: f"cobro_{campo}_{servicio.id}"
    c1, c2 = st.columns([2, 1])
    nuevo_precio = c1.number_input(
        "Precio de cobro del servicio entero (€, sin IVA)", min_value=0.0, step=10.0,
        value=float(servicio.precio_cobrado or 0.0), key=k("precio"),
    )
    if c2.button("Guardar precio", key=k("guardar")):
        servicio.precio_cobrado = nuevo_precio if nuevo_precio > 0 else None
        avisar("success", f"Precio de cobro del servicio #{servicio.id} guardado.")
        st.rerun()
    st.caption("Pon 0 para quitar el precio de cobro.")


def _texto_servicio(s: Servicio) -> str:
    """'#3 · 12/10/2026 21:00 · Menú del día · García' (para los desplegables de servicios)."""
    cliente = f" · {s.cliente}" if s.cliente else ""
    return f"#{s.id} · {s.fecha.strftime('%d/%m/%Y')} {s.hora.strftime('%H:%M')} · {s.menu}{cliente}"


# Vida útil: vacío = sin indicar (no se propone caducidad); 0 = el mismo día.
TEXTO_VIDA_UTIL = "días (vacío = sin indicar, 0 = el mismo día)"


def _texto_vida(dias: int) -> str:
    """'3 día(s)', o 'solo el mismo día' si es 0."""
    return "solo el mismo día" if dias == 0 else f"{dias} día(s)"


def _texto_servicio_estado(s: Servicio) -> str:
    """Como _texto_servicio(), con el estado al final: '#3 · 12/10/2026 21:00 · Menú del día · García · confirmado'."""
    return f"{_texto_servicio(s)} · {s.estado}"


def _cercanos_primero(servicios) -> list:
    """Los servicios ordenados por cercanía a hoy (hoy, mañana, ayer...), para los desplegables."""
    hoy = date.today()
    return sorted(servicios, key=lambda s: (abs((s.fecha - hoy).days), s.fecha, s.hora))


def _pestana_editar_servicio(serv: RegistroServicios, rec: Recetario) -> None:
    """Cambiar los datos de un servicio que todavía no se ha hecho (pendiente o confirmado)."""
    editables = _cercanos_primero(s for s in serv.servicios if s.estado in ("pendiente", "confirmado"))
    if not editables:
        st.info("No hay servicios pendientes que editar. (Uno completado o cancelado ya no se edita.)")
        return
    opciones = {_texto_servicio_estado(s): s for s in editables}
    elegido = st.selectbox("Servicio a editar", list(opciones), index=None, placeholder="Elige el servicio...",
                           key="editar_servicio_select")
    if not elegido:
        return
    s = opciones[elegido]
    # La huella en las keys: si el servicio cambia (desde aquí o desde otra
    # pestaña), los campos se vuelven a rellenar con sus datos actuales.
    huella = _huella(s.fecha, s.hora, s.comensales, s.menu, s.notas, s.cliente, s.lugar, s.precio_cobrado, s.estado)
    k = lambda campo: f"editar_servicio_{campo}_{s.id}_{huella}"
    c1, c2 = st.columns(2)
    fecha = c1.date_input("Fecha", value=s.fecha, format="DD/MM/YYYY", key=k("fecha"))
    hora = c2.time_input("Hora", value=s.hora, key=k("hora"))
    c3, c4 = st.columns(2)
    comensales = c3.number_input("Comensales", min_value=1, step=1, value=int(s.comensales), key=k("comensales"))
    menus = list(rec.menus)
    menu = c4.selectbox("Menú", menus, index=menus.index(s.menu) if s.menu in menus else None,
                        placeholder="Elige el menú...", key=k("menu"))
    c5, c6 = st.columns(2)
    cliente = c5.text_input("Cliente", value=s.cliente, key=k("cliente"))
    lugar = c6.text_input("Lugar", value=s.lugar, key=k("lugar"))
    notas = st.text_area("Notas", value=s.notas, key=k("notas"))
    c7, c8 = st.columns(2)
    precio = c7.number_input("Precio de cobro (€, total del servicio, sin IVA; 0 = sin indicar)", min_value=0.0,
                             step=10.0, value=float(s.precio_cobrado or 0.0), key=k("precio"))
    confirmado = c8.checkbox("✔️ Confirmado por el cliente", value=s.estado == "confirmado", key=k("confirmado"))
    if comensales != s.comensales and s.precio_cobrado:
        st.caption("Ojo: el precio de cobro es el total del servicio. Si cobras por comensal, cámbialo también.")
    if st.button("Guardar cambios", type="primary", key=k("guardar")):
        if not menu:
            st.error("Elige el menú del servicio.")
            return
        try:
            s.editar(fecha=fecha, hora=hora, comensales=int(comensales), menu=menu, notas=notas, cliente=cliente,
                     lugar=lugar, precio_cobrado=precio if precio > 0 else None, quitar_precio=precio <= 0,
                     estado="confirmado" if confirmado else "pendiente")
            avisar("success", f"Servicio #{s.id} actualizado.")
            st.rerun()
        except ValueError as e:
            st.error(_es(str(e)))


def _arreglar_menus_inexistentes(serv: RegistroServicios, rec: Recetario) -> None:
    """Servicios pendientes cuyo menú ya no existe (o se escribió mal): se avisa y se deja elegir otro."""
    malos = [s for s in serv.servicios if s.estado in ("pendiente", "confirmado") and rec.buscar_menu(s.menu) is None]
    for s in malos:
        with st.container(border=True):
            st.warning(f"⚠️ El servicio **{_texto_servicio(s)}** tiene un menú que no existe en el Recetario "
                       f"(«{s.menu}»): no cuenta en la lista de la compra ni en la rentabilidad.")
            if rec.menus:
                c1, c2 = st.columns([3, 1])
                nuevo = c1.selectbox("Menú correcto", list(rec.menus), index=None, placeholder="Elige el menú...",
                                     key=f"arreglar_menu_{s.id}")
                if c2.button("Cambiar menú", key=f"arreglar_menu_boton_{s.id}", disabled=not nuevo):
                    s.menu = nuevo
                    avisar("success", f"Menú del servicio #{s.id} cambiado a «{nuevo}».")
                    st.rerun()


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
    _arreglar_menus_inexistentes(serv, rec)

    st.divider()
    tab_add, tab_editar, tab_cancel, tab_completar, tab_material, tab_rentabilidad = st.tabs(
        ["➕ Añadir servicio", "✏️ Editar servicio", "🚫 Cancelar servicio", "✅ Completar servicio", "🚚 Material",
         "💶 Rentabilidad"]
    )

    with tab_editar:
        _pestana_editar_servicio(serv, rec)
    with tab_material:
        _pestana_material_servicio(serv, rec)
    with tab_rentabilidad:
        _pestana_rentabilidad(serv, inv, rec)

    with tab_add:
        if not rec.menus:
            st.info("Para añadir un servicio, crea antes su menú en el Recetario.")
        # Sin clear_on_submit: si falta algo, lo escrito no se borra; al añadir
        # bien, la "versión" de las keys cambia y el formulario sale vacío.
        vs = st.session_state.setdefault("servicio_form_version", 0)
        ks = lambda campo: f"servicio_{campo}_{vs}"
        with st.form("form_add_servicio"):
            c1, c2 = st.columns(2)
            fecha = c1.date_input("Fecha", format="DD/MM/YYYY", key=ks("fecha"))
            hora = c2.time_input("Hora", key=ks("hora"))
            comensales = st.number_input("Comensales", min_value=1, step=1, key=ks("comensales"))
            # El menú se ELIGE de los que existen: escrito a mano, una tilde o
            # un espacio de más dejaban el servicio fuera de todos los cálculos.
            menu_nombre = st.selectbox("Menú", list(rec.menus), index=None, placeholder="Elige el menú...",
                                       key=ks("menu"))
            c5, c6 = st.columns(2)
            cliente = c5.text_input("Cliente (opcional)", placeholder="Ej: Familia García", key=ks("cliente"))
            lugar = c6.text_input("Lugar (opcional)", placeholder="Ej: Finca Los Olivos, Écija", key=ks("lugar"))
            notas = st.text_area("Notas (opcional)", key=ks("notas"))
            c3, c4 = st.columns(2)
            precio = c3.number_input(
                "Precio de cobro (€, sin IVA, opcional)", min_value=0.0, step=10.0, key=ks("precio"),
                help="Déjalo en 0 si no quieres indicarlo. Solo sirve para calcular el margen del servicio.",
            )
            forma_precio = c4.radio("El precio es", ["Total del servicio", "Por comensal"], horizontal=True,
                                    key=ks("forma_precio"))
            enviado = st.form_submit_button("Añadir servicio", type="primary")
            if enviado:
                precio_cobrado = None
                if precio > 0:
                    precio_cobrado = round(precio * comensales, 2) if forma_precio == "Por comensal" else precio
                if not menu_nombre:
                    st.error("Elige el menú del servicio.")
                else:
                    try:
                        nuevo = Servicio(
                            fecha, hora, int(comensales), menu_nombre, notas, precio_cobrado=precio_cobrado,
                            cliente=cliente, lugar=lugar,
                        )
                        serv.agregar_servicio(nuevo)
                        st.session_state.servicio_form_version = vs + 1
                        avisar("success", f"Servicio #{nuevo.id} añadido: {fecha.strftime('%d/%m/%Y')}, "
                                          f"{int(comensales)} comensales, {menu_nombre}.")
                        st.rerun()  # para que la tabla de arriba y las demás pestañas ya lo vean
                    except ValueError as e:
                        st.error(_es(str(e)))

    with tab_cancel:
        # Solo los que aún no se han hecho: uno completado ya gastó su stock y sus costes son reales.
        cancelables = _cercanos_primero(s for s in serv.servicios if s.estado in ("pendiente", "confirmado"))
        if not cancelables:
            st.info("No hay servicios pendientes que cancelar.")
        else:
            opciones = {_texto_servicio_estado(s): s.id for s in cancelables}
            elegido = st.selectbox("Servicio a cancelar", list(opciones.keys()), key="cancelar_select",
                                   index=None, placeholder="Elige el servicio...")
            confirmar = st.checkbox("Sí, quiero cancelar este servicio (no se puede deshacer)", key="cancelar_confirmar")
            if elegido and st.session_state.registro_material.salida_de(opciones[elegido]):
                st.warning("🚚 Este servicio tiene material fuera. Al cancelarlo seguirá 'en uso' hasta que registres "
                           "su vuelta en Servicios › Material.")
            if st.button("Cancelar servicio", disabled=not (elegido and confirmar)):
                serv.cancelar_servicio(opciones[elegido])
                avisar("success", f"Servicio {elegido} cancelado.")
                if st.session_state.registro_material.salida_de(opciones[elegido]):
                    avisar("warning", "🚚 Recuerda registrar la vuelta de su material (Servicios › Material).")
                vaciar_campos("cancelar_")
                st.rerun()

    with tab_completar:
        pendientes = [s for s in serv.servicios if s.estado not in ("completado", "cancelado")]
        if not pendientes:
            st.info("No hay servicios pendientes de completar.")
        else:
            opciones2 = {_texto_servicio_estado(s): s.id for s in _cercanos_primero(pendientes)}
            elegido2 = st.selectbox("Servicio a completar", list(opciones2.keys()), key="completar_select")
            _completar_por_pasos(serv.buscar_por_id(opciones2[elegido2]), inv, rec)


PASOS_COMPLETAR = ("1. Raciones y lotes", "2. Costes adicionales", "3. ¿Cómo fue?", "4. Resumen y confirmar")


def _completar_por_pasos(servicio: Servicio, inv: Inventario, rec: Recetario) -> None:
    """
    Completar un servicio en 4 pasos (antes era una sola pantalla muy larga).
    No se toca nada hasta pulsar "Completar servicio" en el último paso. Lo
    elegido en cada paso se guarda al pasar al siguiente, y se recupera al
    volver atrás.
    """
    ss = st.session_state
    sid = servicio.id
    clave_paso = f"_completar_paso_{sid}"
    paso = ss.setdefault(clave_paso, 1)
    st.progress(paso / len(PASOS_COMPLETAR), text=" → ".join(
        f"**{p}**" if i + 1 == paso else p for i, p in enumerate(PASOS_COMPLETAR)))

    def ir(nuevo: int) -> None:
        ss[clave_paso] = nuevo
        st.rerun()

    menu_servicio = rec.buscar_menu(servicio.menu)
    if paso == 1:
        if menu_servicio is not None:
            _notas_de_menu(menu_servicio.nombre, menu_servicio.notas, [(r.nombre, r.notas) for r in menu_servicio.recetas])
        # Lo elegido la otra vez (si se vuelve atrás) se recupera antes de dibujar los desplegables.
        for clave, valor in ss.get(f"_completar_widgets_{sid}", {}).items():
            if clave not in ss:
                ss[clave] = valor
        plan = _elegir_tandas_servicio(servicio, inv, rec)
        elecciones = _elegir_lotes_servicio(servicio, inv, rec, plan)
        filas = rec.previsualizar_consumo(servicio, inv, elecciones, plan)
        if filas is None:
            st.warning(f"El menú '{servicio.menu}' no existe en el recetario: si completas el servicio, "
                       "no se descontará nada del inventario.")
        else:
            _tabla_consumo(servicio, inv, rec, filas, plan)
        if st.button("Siguiente →", type="primary", key=f"completar_siguiente_1_{sid}"):
            pendientes = [f["ingrediente"] for f in (filas or []) if f["sin_asignar"] > 1e-9]
            if pendientes:
                st.error("Elige de qué otro lote sale lo que falta de: " + ", ".join(pendientes) + ".")
                return
            ss[f"_completar_plan_{sid}"] = plan
            ss[f"_completar_elecciones_{sid}"] = elecciones
            ss[f"_completar_widgets_{sid}"] = {
                k: v for k, v in ss.items()
                if isinstance(k, str) and k.startswith((f"completar_tanda_{sid}_", f"completar_lote_{sid}_"))
            }
            ir(2)
        return

    plan = ss.get(f"_completar_plan_{sid}")
    elecciones = ss.get(f"_completar_elecciones_{sid}")
    if paso == 2:
        _costes_adicionales(servicio)
        c1, c2 = st.columns(2)
        if c1.button("← Atrás", key=f"completar_atras_2_{sid}"):
            ir(1)
        if c2.button("Siguiente →", type="primary", key=f"completar_siguiente_2_{sid}"):
            if _coste_sin_anadir(servicio):
                st.error("Tienes un coste adicional escrito sin añadir: pulsa '➕ Añadir coste' o bórralo antes de "
                         "seguir (si no, se perdería).")
                return
            ir(3)
        return

    if paso == 3:
        valoracion = st.text_area(
            "📝 ¿Cómo fue? (opcional)", value=ss.get(f"_completar_valoracion_{sid}", ""), key=f"valoracion_{sid}",
            placeholder="Incidencias, qué sobró o faltó, qué cambiar la próxima vez...",
            help="Queda guardado en el historial del servicio. Se puede añadir o cambiar después.",
        )
        c1, c2 = st.columns(2)
        if c1.button("← Atrás", key=f"completar_atras_3_{sid}"):
            ss[f"_completar_valoracion_{sid}"] = valoracion
            ir(2)
        if c2.button("Siguiente →", type="primary", key=f"completar_siguiente_3_{sid}"):
            ss[f"_completar_valoracion_{sid}"] = valoracion
            ir(4)
        return

    # --- Paso 4: resumen y confirmar ---
    filas = rec.previsualizar_consumo(servicio, inv, elecciones, plan)
    extras = ss.get(f"extras_{sid}", [])
    valoracion = ss.get(f"_completar_valoracion_{sid}", "")
    st.markdown(f"**Servicio {_texto_servicio_estado(servicio)}** · {servicio.comensales} comensales")
    coste_inventario = 0.0
    if filas is None:
        st.warning("El menú no existe en el recetario: no se descontará nada del inventario.")
    else:
        _tabla_consumo(servicio, inv, rec, filas, plan)
        coste_inventario = _coste_de_filas(filas, inv)[0] + sum(
            r * inv.elaboraciones.buscar(t).coste_por_racion
            for p in rec.plan_elaboraciones(servicio, inv, plan).values() for t, r in p["reparto"]
            if inv.elaboraciones.buscar(t)
        )
    coste_extras = sum(e["importe"] for e in extras)
    st.markdown("**💶 Costes adicionales**: " + (", ".join(f"{e['concepto']} ({_eur(e['importe'])} €)" for e in extras)
                                                if extras else "ninguno"))
    st.markdown(f"**📝 ¿Cómo fue?**: {valoracion.strip() or '—'}")
    st.metric("Coste del servicio (lo pagado, con IVA)", f"{_eur(coste_inventario + coste_extras)} €",
              help="Lo que sale del inventario (a precio de cada lote), las raciones ya preparadas y los costes "
                   "adicionales. Los gastos que ya tuviera apuntados el servicio se suman aparte en la rentabilidad.")
    st.caption("Hasta que pulses 'Completar servicio' no se toca nada.")

    c1, c2 = st.columns(2)
    if c1.button("← Atrás", key=f"completar_atras_4_{sid}"):
        ir(3)
    if not c2.button("Completar servicio", type="primary", key=f"completar_boton_{sid}"):
        return
    if filas is None:
        servicio.completar()
    else:
        try:
            rec.completar_servicio(servicio, inv, elecciones, plan)
        except ValueError as e:
            st.error(_es(str(e)) + " Vuelve al paso 1 para revisarlo.")
            return
    servicio.valoracion = valoracion.strip()
    _registrar_costes_adicionales(servicio, extras)
    for clave in [k for k in ss.keys() if isinstance(k, str) and k.startswith(
            (f"_completar_paso_{sid}", f"_completar_plan_{sid}", f"_completar_elecciones_{sid}",
             f"_completar_widgets_{sid}", f"_completar_valoracion_{sid}"))]:
        del ss[clave]
    cortos = [f["ingrediente"] for f in (filas or []) if f["faltante"] > 0]
    if filas is None:
        avisar("warning", f"Servicio #{sid} completado sin descontar stock (menú no encontrado).")
    elif cortos:
        avisar("warning", f"Servicio #{sid} completado. Stock insuficiente de: {', '.join(cortos)} "
                          "(se descontó todo lo que había).")
    else:
        avisar("success", f"Servicio #{sid} completado y stock descontado correctamente.")
    st.rerun()


def _tabla_consumo(servicio: Servicio, inv: Inventario, rec: Recetario, filas: list[dict], plan) -> None:
    """Lo que se descontará al completar: raciones preparadas, tabla por ingrediente y avisos."""
    for receta_plan, p in rec.plan_elaboraciones(servicio, inv, plan).items():
        if p["reparto"]:
            detalle = " + ".join(f"{_num(r)} de la tanda {t}" for t, r in p["reparto"])
            st.write(f"🥘 **{receta_plan}**: {detalle} raciones ya preparadas"
                     + (f"; las otras {_num(p['restantes'])} con ingredientes." if p["restantes"] > 0 else "."))
    st.caption(f"Se descontará para {servicio.comensales} comensales (motivo: consumo). 🧻 = consumible:")
    st.dataframe([{
        "Ingrediente": ("🧻 " if f["tipo"] == "consumible" else "") + f["ingrediente"],
        "Necesario": f"{_num(f['necesario'])} {f['unidad']}",
        "En stock": f"{_num(f['en_stock'])} {f['unidad']}" if f["existe"] else "no existe",
        "Se descontará": f"{_num(f['a_descontar'])} {f['unidad']}",
        "De qué lotes": _texto_reparto(f),
        "Faltaba": f"{_num(f['faltante'])} {f['unidad']}" if f["faltante"] > 0 else "—",
    } for f in filas], width="stretch", hide_index=True)
    _aviso_caducados(filas)
    cortos = [f for f in filas if f["faltante"] > 0]
    if cortos:
        st.warning("No hay stock suficiente de: " + ", ".join(f["ingrediente"] for f in cortos)
                   + ". Se descontará todo lo disponible de todos sus lotes (quedará a 0).")


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
    detalles = [f"Coste total {_eur(r['coste'])} €"]
    if r["coste_por_comensal"] is not None:
        detalles.append(f"coste medio por comensal {_eur(r['coste_por_comensal'])} €")
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
    m4.metric("Coste por comensal", f"{_eur(f['coste_por_comensal'])} €")

    tab_gasto, tab_plan, tab_gastos, tab_material, tab_menu = st.tabs(
        ["🍅 Lo que se gastó", "📋 Previsto frente a real", "💶 Gastos", "🍽️ Material", "📖 Menú"]
    )
    with tab_gasto:
        if f["consumos"]:
            # La tabla y el resumen de debajo, con el MISMO criterio de IVA que la
            # rentabilidad (antes la tabla iba con IVA y el resumen sin él: no cuadraban).
            criterio = "sin IVA" if r["sin_iva"] else "con IVA"
            st.dataframe([{
                "Producto": _ICONO_TIPO.get(c["tipo"], "") + c["producto"],
                "Cantidad": f"{_num(c['cantidad'])} {c['unidad']}", "Lote": c["lote"],
                f"Coste (€, {criterio})": _eur(c["coste_sin_iva"] if r["sin_iva"] else c["coste"]),
                **({"Pagado (€, con IVA)": _eur(c["coste"])} if r["sin_iva"] else {}),
            } for c in f["consumos"]], width="stretch", hide_index=True)
            st.caption(f"Comida {_eur(r['comida'])} € · consumibles {_eur(r['consumibles'])} € · limpieza y mantenimiento "
                       f"{_eur(r['mantenimiento'])} € ({criterio}, a precio real de cada lote"
                       + (", como en la rentabilidad: el negocio recupera el IVA)" if r["sin_iva"] else ")"))
        else:
            st.info("No salió nada del inventario para este servicio.")
    with tab_plan:
        if f["previsto_frente_a_real"]:
            st.dataframe([{
                "Producto": p["producto"], "Previsto": f"{_num(p['previsto'])} {p['unidad']}",
                "Real": f"{_num(p['real'])} {p['unidad']}",
                "Diferencia": "—" if abs(p["diferencia"]) < 1e-9 else f"{_es(format(p['diferencia'], '+g'))} {p['unidad']}",
            } for p in f["previsto_frente_a_real"]], width="stretch", hide_index=True)
            st.caption("Diferencia negativa: salió menos de lo que pedía el menú (normalmente faltaba stock). "
                       "Positiva: se usó más (compras de urgencia).")
        else:
            st.info("No hay datos del menú de este servicio.")
    with tab_gastos:
        if f["gastos"]:
            st.dataframe([{"Concepto": g.concepto, "Categoría": g.categoria, "Importe (€)": f"{_eur(g.importe)}",
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
                st.write(f"💥 {i.tipo.capitalize()}: {i.cantidad} x {i.material} ({_eur(i.coste)} €)")
        else:
            st.info("No se llevó material registrado a este servicio.")
    with tab_menu:
        foto = servicio.menu_completado
        if not foto:
            st.info("No hay copia del menú (el servicio se completó antes de existir el historial, o el menú no existía).")
        else:
            st.caption("Así era el menú cuando se completó el servicio (aunque después se haya cambiado).")
            _notas_de_menu(foto["nombre"], foto.get("notas", ""),
                           [(r["nombre"], r.get("notas", "")) for r in foto["recetas"]])
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
    fecha = c3.date_input("Fecha", key=k("repetir_fecha"), format="DD/MM/YYYY")
    hora = c4.time_input("Hora", value=servicio.hora, key=k("repetir_hora"))
    if c5.button("Repetir", key=k("repetir")):
        nuevo = historial.repetir_servicio(st.session_state.registro_servicios, servicio, fecha, hora)
        avisar("success", f"Creado el servicio #{nuevo.id} para el {fecha.strftime('%d/%m/%Y')} (pendiente).")
        st.rerun()

    if servicio.estado == "completado":
        _deshacer_servicio(servicio, inv, rec, gastos)


def _deshacer_servicio(servicio: Servicio, inv: Inventario, rec: Recetario, gastos: RegistroGastos) -> None:
    """Deshacer un servicio completado (por ejemplo, completado por error), con confirmación."""
    k = lambda campo: f"deshacer_{campo}_{servicio.id}"
    with st.expander("↩️ Deshacer este servicio (volver a pendiente)"):
        st.write(
            "Si lo completaste por error: el servicio vuelve a **pendiente**, lo que salió del inventario vuelve a "
            "sus lotes y las raciones preparadas a sus tandas (su consumo desaparece de Métricas y de la "
            "rentabilidad), y se quitan los costes adicionales que se añadieron al completarlo."
        )
        st.caption("Las compras no previstas de productos se quedan (fueron reales): solo vuelve al stock lo que se "
                   "usó. La valoración se conserva y las roturas de material no se tocan.")
        salidas = inv.salidas_de_servicio(servicio.id)
        faltan = sorted({m.producto_nombre for m in salidas if m.producto_nombre not in inv.productos})
        if faltan:
            st.caption(f"No se puede deshacer: estos productos ya no existen: {', '.join(faltan)}.")
            return
        confirmar = st.checkbox(f"Sí, quiero deshacer el servicio #{servicio.id}", key=k("confirmar"))
        if st.button("Deshacer servicio", key=k("boton"), disabled=not confirmar):
            try:
                r = rec.deshacer_completar(servicio, inv, gastos)
            except ValueError as e:
                st.error(_es(str(e)))
                return
            detalle = f"{r['salidas']} salida(s) devuelta(s) al inventario"
            if r["raciones"]:
                detalle += f", {_num(r['raciones'])} raciones a sus tandas"
            if r["gastos"]:
                detalle += f", {len(r['gastos'])} coste(s) adicional(es) quitado(s)"
            avisar("success", f"Servicio #{servicio.id} deshecho: vuelve a estar pendiente ({detalle}).")
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
        default=[n for n in actuales if n in disponibles], key=f"{clave}_consumibles", placeholder="Elige consumibles...",
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
        default=[n for n in actuales if n in disponibles], key=f"{clave}_materiales", placeholder="Elige el material...",
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


def _editar_receta(inv: Inventario, rec: Recetario) -> None:
    """Cambiar las cantidades, quitar o añadir ingredientes, cambiar la categoría o borrar una receta."""
    st.markdown("**✏️ Editar o borrar una receta**")
    nombre = st.selectbox("Receta", list(rec.recetas), index=None, placeholder="Elige la receta...",
                          key="editar_receta_select")
    if not nombre:
        return
    receta = rec.recetas[nombre]
    huella = _huella(receta.categoria, sorted(receta.ingredientes_por_comensal.items()))
    k = lambda campo: f"editar_receta_{campo}_{nombre}_{huella}"
    categoria = st.text_input("Categoría", value=receta.categoria, key=k("categoria"))
    st.caption("Cantidad por comensal, en la unidad de cada producto. Pon 0 para quitar un ingrediente.")
    nuevos: dict[str, float] = {}
    for ingrediente, cantidad in receta.ingredientes_por_comensal.items():
        producto = inv.buscar_producto(ingrediente)
        unidad = producto.unidad if producto else "?"
        nuevos[ingrediente] = st.number_input(
            f"{ingrediente} ({unidad})", min_value=0.0, step=0.01, format="%g", value=float(cantidad),
            key=k(f"ing_{ingrediente}"),
        )
    otros = [p.nombre for p in inv.alimentos() if p.nombre not in receta.ingredientes_por_comensal]
    if otros:
        c1, c2 = st.columns([2, 1])
        anadir = c1.selectbox("Añadir otro ingrediente (opcional)", otros, index=None, placeholder="Elige...",
                              key=k("anadir"))
        if anadir:
            nuevos[anadir] = c2.number_input(f"Cantidad ({inv.buscar_producto(anadir).unidad})", min_value=0.0,
                                             step=0.01, format="%g", key=k(f"anadir_cantidad_{anadir}"))
    quitados = [n for n, c in nuevos.items() if c <= 0 and n in receta.ingredientes_por_comensal]
    if quitados:
        st.caption("Se quitarán: " + ", ".join(quitados))
    menus = rec.menus_con_receta(nombre)
    if menus:
        st.caption(f"Los cambios se verán en los menús que la llevan ({', '.join(menus)}). Los servicios ya hechos "
                   "no cambian: guardan cómo era el menú.")
    if st.button("Guardar cambios", type="primary", key=k("guardar")):
        try:
            rec.editar_receta(nombre, ingredientes=nuevos, categoria=categoria)
            avisar("success", f"Receta '{nombre}' actualizada.")
            st.rerun()
        except ValueError as e:
            st.error(_es(str(e)))

    with st.expander(f"🗑️ Borrar la receta '{nombre}'"):
        if menus:
            st.caption(f"No se puede borrar: está en estos menús: {', '.join(menus)}. Quítala de ellos antes.")
            return
        confirmar = st.checkbox(f"Sí, quiero borrar la receta '{nombre}'", key=k("borrar_confirmar"))
        if st.button("Borrar receta", key=k("borrar"), disabled=not confirmar):
            try:
                rec.eliminar_receta(nombre, inv)
                avisar("success", f"Receta '{nombre}' borrada.")
                vaciar_campos("editar_receta_")
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))


def _tarjeta_menu(menu: Menu, inv: Inventario, rec: Recetario) -> None:
    """Un menú: a simple vista, su comida; al entrar, el detalle de cada receta y sus consumibles."""
    with st.container(border=True):
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"**{menu.nombre}**")
        c1.caption("Recetas: " + (", ".join(r.nombre for r in menu.recetas) or "—"))
        c2.metric("Comida por comensal", f"{_eur(menu.costo_por_comensal(inv))} €")
        st.write("Ingredientes por comensal: " + _texto_cantidades(menu.ingredientes_por_comensal(), inv))
        _editor_nota(menu, f"menu_{menu.nombre}", menu.nombre)

        with st.expander("🔎 Ver detalle del menú"):
            for receta in menu.recetas:
                st.markdown(f"**{receta.nombre}** · {receta.categoria} · {receta.costo_por_comensal(inv)} €/comensal")
                if receta.notas:
                    st.caption(f"📝 {_saltos(receta.notas)}")
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
                f"Coste por comensal: comida {_eur(menu.costo_por_comensal(inv))} € + consumibles "
                f"{_eur(menu.costo_consumibles_por_comensal(inv))} € = **{_eur(total)} €**"
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

        with st.expander("✏️ Cambiar las recetas o borrar el menú"):
            actuales = [r.nombre for r in menu.recetas]
            recetas = st.multiselect(
                "Recetas del menú", list(rec.recetas), default=[r for r in actuales if r in rec.recetas],
                key=f"menu_{menu.nombre}_recetas_{_huella(actuales)}", placeholder="Elige las recetas...",
            )
            if st.button("Guardar recetas", key=f"menu_{menu.nombre}_guardar_recetas", disabled=recetas == actuales):
                try:
                    rec.editar_recetas_menu(menu.nombre, recetas)
                    avisar("success", f"Recetas del menú '{menu.nombre}' guardadas.")
                    st.rerun()
                except ValueError as e:
                    st.error(_es(str(e)))
            st.caption("Los servicios ya hechos no cambian: guardan cómo era el menú al hacerlos.")

            st.markdown("**🗑️ Borrar el menú**")
            usan = [s for s in st.session_state.registro_servicios.servicios
                    if s.menu == menu.nombre and s.estado in ("pendiente", "confirmado")]
            if usan:
                st.caption("No se puede borrar: lo usan estos servicios pendientes: "
                           + ", ".join(_texto_servicio(s) for s in usan) + ". Cámbiales el menú antes "
                           "(Servicios › Editar servicio).")
            else:
                confirmar = st.checkbox(f"Sí, quiero borrar el menú '{menu.nombre}'", key=f"menu_{menu.nombre}_borrar_confirmar")
                if st.button("Borrar menú", key=f"menu_{menu.nombre}_borrar", disabled=not confirmar):
                    try:
                        rec.eliminar_menu(menu.nombre, st.session_state.registro_servicios.servicios)
                        avisar("success", f"Menú '{menu.nombre}' borrado.")
                        st.rerun()
                    except ValueError as e:
                        st.error(_es(str(e)))


def pagina_recetario() -> None:
    st.header("👩‍🍳 Recetario")
    inv = st.session_state.inventario
    rec = st.session_state.recetario

    tab_recetas, tab_menus, tab_crear_receta, tab_crear_menu, tab_bases, tab_recomendar = st.tabs(
        ["Recetas", "Menús", "➕ Crear receta", "➕ Crear menú", "🧪 Elaboraciones base", "🔥 Recomendador"]
    )

    with tab_bases:
        _pestana_bases(inv)

    with tab_recetas:
        if not rec.recetas:
            st.info("No hay recetas todavía.")
        for r in rec.recetas.values():
            vida = f" · ⏳ dura {_texto_vida(r.vida_util_dias)} una vez hecha" if r.vida_util_dias is not None else ""
            st.write(f"{_es(str(r))}  💶 {_eur(r.costo_por_comensal(inv))} €/comensal{vida}")
            _editor_nota(r, f"receta_{r.nombre}", r.nombre)
        if rec.recetas:
            st.markdown("**⏳ Vida útil de una receta**")
            st.caption("Cuántos días dura el plato una vez preparado. Sirve para proponer la caducidad de cada elaboración. "
                       "Vacío = sin indicar; 0 = se toma el mismo día que se prepara.")
            c1, c2, c3 = st.columns([2, 1, 1])
            nombre_vida = c1.selectbox("Receta", list(rec.recetas), key="vida_receta")
            receta_vida = rec.recetas[nombre_vida]
            dias_vida = c2.number_input(TEXTO_VIDA_UTIL, min_value=0, step=1, value=receta_vida.vida_util_dias,
                                        placeholder="sin indicar", key=f"vida_dias_{nombre_vida}")
            if c3.button("Guardar", key=f"vida_guardar_{nombre_vida}"):
                receta_vida.vida_util_dias = None if dias_vida is None else int(dias_vida)
                avisar("success", f"Vida útil de '{nombre_vida}' guardada.")
                st.rerun()

        if rec.recetas:
            st.divider()
            _editar_receta(inv, rec)

    with tab_menus:
        if not rec.menus:
            st.info("No hay menús todavía.")
        for m in list(rec.menus.values()):
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
                # Se propone la unidad del propio producto (antes siempre "kg":
                # escribir 5 para un azafrán en gramos guardaba 5.000 g).
                unidad_elegida = st.radio(
                    "Unidad para esta cantidad", ("kg", "g"), key=f"unidad_ing_{nombre_ing}", horizontal=True,
                    index=("kg", "g").index(producto_ing.unidad),
                )
            elif producto_ing.unidad in ("litros", "ml"):
                unidad_elegida = st.radio(
                    "Unidad para esta cantidad", ("litros", "ml"), key=f"unidad_ing_{nombre_ing}", horizontal=True,
                    index=("litros", "ml").index(producto_ing.unidad),
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
                vaciar_campos(f"cantidad_ing_{nombre_ing}")
                st.rerun()

            if st.session_state.receta_ingredientes:
                st.write("Ingredientes añadidos hasta ahora:")
                st.dataframe([{
                    "Ingrediente": n,
                    "Por comensal": f"{_num(c)} {inv.buscar_producto(n).unidad if inv.buscar_producto(n) else ''}",
                } for n, c in st.session_state.receta_ingredientes.items()], width="stretch", hide_index=True)
                if st.button("Empezar de nuevo (quitar los ingredientes añadidos)", key="receta_vaciar"):
                    st.session_state.receta_ingredientes = {}
                    st.rerun()

            # Sin clear_on_submit: si falta algo, lo escrito NO se borra. Al
            # guardar bien, se cambia la "versión" de las keys y el formulario sale vacío.
            vr = st.session_state.setdefault("receta_form_version", 0)
            with st.form("form_finalizar_receta"):
                nombre_receta = st.text_input("Nombre de la receta", key=f"receta_nombre_{vr}")
                categoria_receta = st.text_input("Categoría", key=f"receta_categoria_{vr}")
                vida_util = st.number_input(
                    f"Vida útil una vez hecha (opcional) — {TEXTO_VIDA_UTIL}", min_value=0, step=1, value=None,
                    placeholder="sin indicar",
                    help="Cuántos días dura el plato preparado. Sirve para proponer la caducidad de las elaboraciones.",
                    key=f"receta_vida_{vr}",
                )
                notas_receta = st.text_area("Anotaciones (opcional)", key=f"receta_notas_{vr}",
                                            placeholder="Cómo se hace, trucos, emplatado... para tus compañeros")
                crear = st.form_submit_button("Guardar receta", type="primary")
                if crear:
                    if not st.session_state.receta_ingredientes:
                        st.error("Añade al menos un ingrediente antes de guardar.")
                    elif not nombre_receta:
                        st.error("Ponle un nombre a la receta.")
                    else:
                        nueva = Receta(nombre_receta, categoria_receta, dict(st.session_state.receta_ingredientes),
                                       vida_util_dias=None if vida_util is None else int(vida_util))
                        nueva.poner_nota(notas_receta)
                        try:
                            rec.agregar_receta(nueva)
                        except ValueError as e:
                            st.error(_es(str(e)))
                        else:
                            st.session_state.receta_ingredientes = {}
                            st.session_state.receta_form_version = vr + 1
                            avisar("success", f"Receta '{nueva.nombre}' creada.")
                            st.rerun()

    with tab_crear_menu:
        if not rec.recetas:
            st.warning("Crea al menos una receta primero.")
        else:
            nombre_menu = st.text_input("Nombre del menú", key="nombre_menu_input")
            recetas_elegidas = st.multiselect("Recetas a incluir", list(rec.recetas.keys()), key="recetas_multiselect",
                                              placeholder="Elige las recetas...")
            consumibles = _editor_consumibles(inv, "nuevo_menu", {})
            materiales = _editor_material("nuevo_menu", {})
            notas_menu = st.text_area("Anotaciones (opcional)", key="nuevo_menu_notas",
                                      placeholder="Lo que quieras explicar a tus compañeros sobre este menú")
            if st.button("Crear menú", type="primary"):
                if not nombre_menu or not recetas_elegidas:
                    st.error("Indica un nombre y al menos una receta.")
                else:
                    recetas_obj = [rec.recetas[n] for n in recetas_elegidas]
                    nuevo_menu = Menu(nombre_menu, recetas_obj, consumibles, materiales)
                    nuevo_menu.poner_nota(notas_menu)
                    try:
                        rec.agregar_menu(nuevo_menu)
                    except ValueError as e:
                        st.error(_es(str(e)))
                    else:
                        avisar("success", f"Menú '{nuevo_menu.nombre}' creado.")
                        for prefijo in ("nombre_menu_input", "recetas_multiselect", "nuevo_menu_"):
                            vaciar_campos(prefijo)
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
                    col2.metric("Urgencia", f"{_dec(puntuacion)}")

                    if puede:
                        st.success("✅ Se puede preparar ya")
                    else:
                        st.warning("🛒 Faltaría comprar algo")

                    riesgo = menu.ingredientes_en_riesgo(inv, dias)
                    if riesgo:
                        detalle = ", ".join(f"{p.nombre} ({p.dias_para_caducar_bueno()}d)" for p in riesgo)
                        st.caption(f"⏳ Por caducidad: {detalle}")

                    exceso = menu.ingredientes_en_exceso(inv)
                    if exceso:
                        detalle = ", ".join(f"{p.nombre} ({_num(p.stock_bueno)} sobre mínimo {_num(p.stock_minimo)})" for p in exceso)
                        st.caption(f"📦 Por exceso de stock: {detalle}")


def _editor_formula(inv: Inventario, clave: str, actuales: dict[str, float], excluir: str = "") -> dict[str, float]:
    """Elegir los ingredientes de una elaboración base y cuánto lleva de cada uno (en su unidad)."""
    disponibles = [p.nombre for p in inv.alimentos() if p.nombre != excluir]
    elegidos = st.multiselect(
        "Ingredientes", disponibles, default=[n for n in actuales if n in disponibles], key=f"{clave}_ingredientes",
        placeholder="Elige los ingredientes...",
        help="Pueden ser otras elaboraciones base (un fondo dentro de una salsa).",
    )
    resultado = {}
    for nombre in elegidos:
        unidad = inv.buscar_producto(nombre).unidad
        cantidad = st.number_input(
            f"{nombre} ({unidad})", min_value=0.0, step=0.1,
            value=float(actuales[nombre]) if nombre in actuales else None, placeholder="0",
            key=f"{clave}_cant_{nombre}",
        )
        if cantidad:
            resultado[nombre] = cantidad
    return resultado


PAGINAS = ["Dashboard", "Inventario", "Servicios", "Historial", "Recetario", "Compras", "Gastos", "Métricas",
           "Exportar / Backup", "Ajustes"]


def _ir(pagina: str, **campos) -> None:
    """
    Para los botones que llevan a otra pantalla (on_click): cambia la página
    del menú lateral y, si se indican, deja elegidos algunos campos de esa
    pantalla (por ejemplo, la elaboración base que se quiere preparar).
    """
    st.session_state["pagina_nav"] = pagina
    for clave, valor in campos.items():
        st.session_state[clave] = valor


def _ir_a_preparar_base(nombre: str) -> None:
    v = st.session_state.get("base_version", 0)
    _ir("Inventario", inv_tipo="🥘 Elaboraciones", elab_que="Una elaboración base (kg / litros)",
        **{f"base_preparar_{v}": nombre})


def _pestana_bases(inv: Inventario) -> None:
    st.caption(
        "Sofritos, fondos, salsas, masas... Se preparan con una fórmula y entran en el inventario como un "
        "alimento más (en Alimentos aparecen como 'Elaboración base'), así que las recetas pueden usarlas "
        "como ingrediente. Se preparan en Inventario > 🥘 Elaboraciones (o con el botón 'Preparar' de cada una)."
    )
    bases = inv.bases()
    if bases:
        st.dataframe([{
            "Elaboración": b.nombre, "Fórmula": f"para {_num(b.formula['cantidad'])} {b.unidad}",
            "Ingredientes": ", ".join(f"{_num(c)} {inv.buscar_producto(i).unidad if inv.buscar_producto(i) else ''} {i}"
                                      for i, c in b.formula["ingredientes"].items()),
            "Vida útil": _texto_vida(b.vida_util_dias) if b.vida_util_dias is not None else "—",
            "En stock": f"{_num(b.stock)} {b.unidad}",
            "Coste estimado": f"{_precio(inv.coste_estimado_base(b.nombre))} €/{b.unidad}",
        } for b in bases], width="stretch", hide_index=True)
        for b in bases:
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{b.nombre}** · en stock {_num(b.stock)} {b.unidad}")
            c2.button("🥄 Preparar", key=f"ir_preparar_{b.nombre}", on_click=_ir_a_preparar_base, args=(b.nombre,),
                      help="Lleva a Inventario > 🥘 Elaboraciones con esta base ya elegida.")
            _editor_nota(b, f"base_{b.nombre}", b.nombre)

    modo = st.radio("¿Qué quieres hacer?", ("➕ Crear una nueva", "✏️ Editar una fórmula"), horizontal=True, key="base_modo",
                    label_visibility="collapsed")
    if modo.startswith("➕"):
        if not inv.alimentos():
            st.warning("No hay alimentos en el inventario. Añade productos primero.")
            return
        v = st.session_state.setdefault("base_nueva_version", 0)
        k = lambda campo: f"base_nueva_{campo}_{v}"
        c1, c2 = st.columns(2)
        nombre = c1.text_input("Nombre (ej: Sofrito, Fondo oscuro)", key=k("nombre"))
        categoria = c2.text_input("Categoría", value="Elaboraciones", key=k("categoria"))
        c1, c2, c3, c4 = st.columns(4)
        unidad = c1.selectbox("Unidad", ("kg", "g", "litros", "ml"), key=k("unidad"))
        cantidad = c2.number_input(f"La fórmula da (en {unidad})", min_value=0.0, step=0.5, value=None,
                                   placeholder="0", key=k("cantidad"),
                                   help="Para cuánta cantidad son los ingredientes de abajo.")
        vida = c3.number_input(f"Vida útil — {TEXTO_VIDA_UTIL}", min_value=0, step=1, value=None,
                               placeholder="sin indicar", key=k("vida"))
        minimo = c4.number_input("Stock mínimo", min_value=0.0, step=0.5, key=k("minimo"))
        st.markdown("**Ingredientes** para esa cantidad")
        ingredientes = _editor_formula(inv, k("formula"), {})
        notas = st.text_area("Anotaciones (opcional)", key=k("notas"),
                             placeholder="Cómo se hace, trucos, conservación... para tus compañeros")
        if st.button("Crear elaboración base", type="primary", key=k("crear")):
            try:
                inv.definir_base(nombre, categoria, unidad, cantidad or 0, ingredientes,
                                 None if vida is None else int(vida), minimo, notas)
                avisar("success", f"Elaboración base '{nombre.strip()}' creada. Prepárala en Inventario > 🥘 Elaboraciones.")
                st.session_state.base_nueva_version = v + 1
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))
    else:
        if not bases:
            st.info("Todavía no hay elaboraciones base.")
            return
        nombre = st.selectbox("Elaboración base", [b.nombre for b in bases], key="base_editar_select")
        producto = inv.buscar_producto(nombre)
        v = st.session_state.setdefault("base_editar_version", 0)
        k = lambda campo: f"base_editar_{campo}_{nombre}_{v}"
        c1, c2 = st.columns(2)
        cantidad = c1.number_input(f"La fórmula da (en {producto.unidad})", min_value=0.0, step=0.5,
                                   value=float(producto.formula["cantidad"]), key=k("cantidad"))
        vida = c2.number_input(f"Vida útil — {TEXTO_VIDA_UTIL}", min_value=0, step=1,
                               value=producto.vida_util_dias, placeholder="sin indicar", key=k("vida"))
        ingredientes = _editor_formula(inv, k("formula"), producto.formula["ingredientes"], excluir=nombre)
        if st.button("Guardar fórmula", type="primary", key=k("guardar")):
            try:
                inv.editar_formula(nombre, cantidad, ingredientes, None if vida is None else int(vida))
                avisar("success", f"Fórmula de '{nombre}' guardada.")
                st.session_state.base_editar_version = v + 1
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))


# ---------- Página: Compras ----------

def _anadir_a_mano(comp: GestorCompras, inv: Inventario) -> None:
    """Añadir a la lista algo que no sale de ningún servicio (papel de horno, hielo...)."""
    with st.expander("➕ Añadir algo a mano"):
        v = st.session_state.setdefault("a_mano_version", 0)
        k = lambda campo: f"a_mano_{campo}_{v}"
        OTRO = "✏️ Otra cosa (no está en el inventario)"
        elegido = st.selectbox("¿Qué?", [OTRO] + list(inv.productos), index=None, placeholder="Elige o escribe...",
                               key=k("producto"))
        producto = inv.buscar_producto(elegido) if elegido and elegido != OTRO else None
        nombre = producto.nombre if producto else (st.text_input("Nombre", key=k("nombre")) if elegido == OTRO else "")
        c1, c2 = st.columns(2)
        if producto:
            unidad = producto.unidad
            c1.caption(f"Unidad: {unidad} · proveedor habitual: {producto.proveedor}")
        else:
            unidad = c1.selectbox("Unidad", Producto.UNIDADES_VALIDAS, key=k("unidad"))
        cantidad = c2.number_input(f"Cantidad ({unidad})", min_value=0.0, step=1.0, key=k("cantidad"))
        if st.button("Añadir a la lista", key=k("boton"), disabled=not elegido):
            try:
                comp.agregar_a_mano(nombre, cantidad, unidad, producto.proveedor if producto else "Sin proveedor",
                                    producto.precio_unitario if producto else 0.0)
                avisar("success", f"Añadido a la lista: {_num(cantidad)} {unidad} de {nombre.strip()}.")
                st.session_state.a_mano_version = v + 1
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))
        st.caption("Lo añadido a mano se respeta al volver a generar la lista (se suma a lo que pidan los servicios).")


def _cambiar_lista_compra(comp: GestorCompras, pendientes: list) -> None:
    """Cambiar la cantidad de un artículo pendiente o quitarlo de la lista."""
    with st.expander("✏️ Cambiar la cantidad o quitar algo de la lista"):
        nombre = st.selectbox("Artículo", [i.ingrediente for i in pendientes], key="lista_cambiar_select")
        item = comp.pendiente_de(nombre)
        if item is None:
            return
        c1, c2, c3 = st.columns([2, 1, 1])
        cantidad = c1.number_input(f"Cantidad ({item.unidad})", min_value=0.0, step=1.0, value=float(item.cantidad),
                                   key=f"lista_cantidad_{nombre}_{_huella(item.cantidad)}")
        if c2.button("Guardar cantidad", key=f"lista_guardar_{nombre}"):
            try:
                comp.cambiar_cantidad(nombre, cantidad)
                avisar("success", f"Cantidad de '{nombre}' cambiada a {_num(cantidad)} {item.unidad}.")
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))
        if c3.button("🗑️ Quitar", key=f"lista_quitar_{nombre}"):
            comp.quitar_pendiente(nombre)
            avisar("success", f"'{nombre}' quitado de la lista.")
            st.rerun()
        st.caption("Si vuelves a generar la lista, lo que piden los servicios se recalcula (y podría volver a salir).")


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
                avisar("info", "No hay servicios próximos en ese rango: solo se revisa la limpieza y el mantenimiento.")
            avisos = comp.generar_lista_desde_servicios(servicios, rec, inv)
            avisar("success", "Lista de compra generada/actualizada.")
            for aviso in avisos:
                avisar("warning" if aviso.startswith("⚠️") else "info", aviso)
            st.rerun()

    _anadir_a_mano(comp, inv)

    st.divider()
    pendientes = comp.items_pendientes()
    if not pendientes:
        st.success("No hay compras pendientes 🎉")
    else:
        agrupado = comp.agrupar_por_proveedor()
        for proveedor, items in agrupado.items():
            st.subheader(f"📋 {proveedor}")
            filas = [
                {"Ingrediente": i.ingrediente, "Cantidad": _num(i.cantidad), "Unidad": i.unidad,
                 "Coste (€)": _eur(i.costo_estimado()), "Para qué": i.motivo()}
                for i in items
            ]
            st.dataframe(filas, width="stretch", hide_index=True)

        st.metric("💰 Coste total pendiente", f"{_eur(comp.costo_total_pendiente())} €")
        _cambiar_lista_compra(comp, pendientes)

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
                key=f"cantidad_real_{nombre_marcar}_{_huella(item_marcar.cantidad)}",
            )
            producto_marcar = inv.buscar_producto(nombre_marcar)
            if producto_marcar is None:
                st.info(f"'{nombre_marcar}' no está en el inventario: al marcarlo como comprado no entra stock. "
                        "Si quieres controlar su stock, créalo antes en Inventario.")
                if st.button("Marcar como comprado", key=f"marcar_sin_inventario_{nombre_marcar}"):
                    comp.marcar_comprado(nombre_marcar, cantidad_comprada=cantidad_real)
                    avisar("success", f"'{nombre_marcar}' marcado como comprado.")
                    st.rerun()
                return
            st.caption("La compra entra en el inventario como un lote nuevo.")
            k = lambda campo: f"compra_{campo}_{nombre_marcar}"
            datos = _campos_entrada(producto_marcar, k, cantidad_real)
            if st.button("Marcar como comprado y reponer inventario"):
                if datos["precio"] is None:
                    st.error("Indica el precio de esta compra.")
                elif datos["necesita_peso"] and datos["peso"] is None:
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
                            f"(+{_num(cantidad_real)} {item_marcar.unidad}, {lote.etiqueta()}).",
                        )
                        vaciar_campos("compra_")
                        vaciar_campos("cantidad_real_")
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
        importe = c3.number_input("Importe pagado (€, con IVA)", min_value=0.0, step=1.0, key=k("importe"),
                                  help="Lo que pone el ticket o la factura.")
        fecha = c4.date_input("Fecha", key=k("fecha"), format="DD/MM/YYYY")
        iva = _iva_gasto(categoria, k("iva"))
        if importe > 0 and iva:
            base = importe / (1 + iva / 100)
            st.caption(f"{_eur(importe)} € = {_eur(base)} € sin IVA + {_eur(importe - base)} € de IVA.")
        general = "Gasto general del negocio (no es de un servicio)"
        opciones = {general: None}
        for s in sorted(serv.servicios, key=lambda s: (s.fecha, s.hora), reverse=True):
            if s.estado != "cancelado":
                opciones[f"#{s.id} - {s.fecha.strftime('%d/%m/%Y')} - {s.menu}"] = s.id
        servicio_id = opciones[st.selectbox("¿De qué servicio es?", list(opciones), key=k("servicio"))]
        notas = st.text_input("Notas (opcional)", key=k("notas"), placeholder="Ej: 120 km ida y vuelta")
        if st.button("Registrar gasto", type="primary", key=k("boton")):
            try:
                gastos.agregar_gasto(Gasto(concepto, categoria, importe, fecha, servicio_id, notas, iva=iva))
                avisar("success", f"Gasto registrado: {concepto} ({_eur(importe)} €).")
                st.session_state.gasto_version += 1
                st.rerun()
            except ValueError as e:
                st.error(_es(str(e)))

    with tab_lista:
        periodo = st.selectbox("Periodo", PERIODOS_VALIDOS, index=1, key="gastos_periodo")
        desde, hasta = rango_desde_periodo(periodo)
        if periodo != "todo":
            st.caption(f"Del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}.")
        # "todo" incluye también los gastos con fecha futura; los demás periodos los
        # muestran aparte (marcados), sin sumarlos al total.
        hasta_total = date.max if periodo == "todo" else hasta
        lista = gastos.gastos_en_rango(desde, hasta_total)
        futuros = [g for g in gastos.gastos_en_rango(hasta + timedelta(days=1), date.max) if g not in lista]
        if not lista and not futuros:
            st.info("No hay gastos registrados en este periodo.")
            return
        st.dataframe([{
            "Nº": g.id, "Fecha": g.fecha.strftime("%d/%m/%Y") + (" 📅 futuro" if g.fecha > date.today() else ""),
            "Concepto": g.concepto, "Categoría": g.categoria,
            "Importe (€)": f"{_eur(g.importe)}",
            "IVA": "no desglosado" if g.iva is None else nombre_iva(g.iva).split(" (")[0],
            "Servicio": f"#{g.servicio_id}" if g.servicio_id else "General",
            "Notas": g.notas,
        } for g in list(reversed(futuros)) + list(reversed(lista))], width="stretch", hide_index=True)
        if futuros:
            st.caption(f"📅 {len(futuros)} gasto(s) con fecha futura ({_eur(sum(g.importe for g in futuros))} €): "
                       "salen en la lista, pero no suman en el total de este periodo (sí en 'todo').")
        por_categoria = gastos.total_por_categoria(desde, hasta_total)
        st.metric("Total del periodo", f"{_eur(sum(por_categoria.values()))} €")
        st.bar_chart(pd.DataFrame(list(por_categoria.items()), columns=["Categoría", "Gasto (€)"]).set_index("Categoría"))

        st.subheader("Eliminar un gasto")
        textos_gasto = {f"#{g.id} - {g.fecha.strftime('%d/%m/%Y')} - {g.concepto} ({_eur(g.importe)} €)": g.id
                        for g in list(reversed(futuros)) + list(reversed(lista))}
        elegido = st.selectbox("Gasto", list(textos_gasto), key="gasto_eliminar_select")
        if _boton_confirmado("🗑️ Eliminar este gasto", f"gasto_eliminar_boton_{textos_gasto[elegido]}",
                             pregunta=f"¿Eliminar el gasto {elegido}?"):
            gastos.eliminar_gasto(textos_gasto[elegido])
            avisar("success", "Gasto eliminado.")
            st.rerun()


# ---------- Página: Exportar / Backup ----------

def _restaurar_copia() -> None:
    """Volver a una copia de seguridad (con confirmación y copia previa de lo que hay ahora)."""
    copias = listar_copias(RUTA_SESION)
    with st.expander("⏪ Restaurar una copia de seguridad"):
        if not copias:
            st.caption("Todavía no hay copias de seguridad.")
            return
        st.caption("Vuelve a dejar los datos como estaban en una copia. Antes se guarda una copia de lo que hay "
                   "ahora (en «copias», empezando por «antes_de_restaurar»), así siempre se puede volver atrás.")

        def texto(c: dict) -> str:
            r = c["resumen"]
            contenido = (f"{r['productos']} productos, {r['recetas']} recetas, {r['servicios']} servicios"
                         if r else "⚠️ no se puede leer")
            return f"{c['fecha']:%d/%m/%Y %H:%M} · {c['tipo']} · {contenido}"

        opciones = {texto(c): c for c in copias}
        elegida = st.selectbox("Copia", list(opciones), index=None, placeholder="Elige una copia...",
                               key="restaurar_select")
        if not elegida:
            return
        copia = opciones[elegida]
        if copia["resumen"] is None:
            st.error("Esa copia está dañada: no se puede restaurar.")
            return
        st.warning("Se sustituirán TODOS los datos actuales por los de esa copia.")
        confirmar = st.checkbox("Sí, quiero restaurar esta copia", key="restaurar_confirmar")
        if st.button("⏪ Restaurar", key="restaurar_boton", disabled=not confirmar):
            try:
                sesion = cargar_sesion(str(copia["ruta"]))
            except Exception as error:  # noqa: BLE001 -- una copia que no se puede abrir no toca nada
                st.error(f"No se ha podido abrir esa copia ({error}). No se ha cambiado nada.")
                return
            try:
                antes = copia_antes_de_empezar_de_cero(_datos_sesion(), RUTA_SESION, motivo="restaurar")
            except OSError as error:
                st.error(f"No se ha restaurado nada: no se ha podido hacer la copia de lo actual ({error}).")
                return
            _poner_sesion(sesion)
            avisar("success", f"Copia restaurada ({copia['fecha']:%d/%m/%Y %H:%M}). Lo que había antes está "
                              f"guardado en: {antes}")
            st.rerun()


def pagina_exportar() -> None:
    st.header("📁 Exportar y backup")

    st.subheader("Dónde se guardan tus datos")
    st.write("Los cambios se guardan **solos**, al momento. Además, cada día se deja una copia de seguridad con fecha "
             f"(se conservan las últimas 30). Todo está en esta carpeta:")
    st.code(str(CARPETA_DATOS), language=None)
    st.caption("Para tener una copia fuera del ordenador, copia esa carpeta entera a un pendrive o a la nube de vez en cuando.")
    if os.name == "nt" and st.button("📂 Abrir la carpeta de datos"):
        CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
        os.startfile(CARPETA_DATOS)  # solo existe en Windows

    _restaurar_copia()

    st.divider()
    st.subheader("Exportar a Excel")
    if st.button("Generar Excel", type="primary"):
        carpeta = str(CARPETA_DATOS)
        ruta = exportar_todo(
            st.session_state.inventario, st.session_state.registro_servicios,
            st.session_state.gestor_compras, carpeta,
            st.session_state.registro_gastos, st.session_state.recetario, st.session_state.registro_material,
        )
        st.session_state.ultima_exportacion = ruta
        st.success(f"Exportado a {ruta}")

    if st.session_state.get("ultima_exportacion") and Path(st.session_state.ultima_exportacion).exists():
        with open(st.session_state.ultima_exportacion, "rb") as f:
            st.download_button("⬇️ Descargar Excel", f, file_name=Path(st.session_state.ultima_exportacion).name)

    st.divider()
    st.subheader("Backup a Google Drive")
    st.caption("Opcional y avanzado: necesita un archivo credentials.json de Google junto al programa. "
               "Para tener una copia de tus datos basta con copiar la carpeta de datos de arriba.")
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
                st.error(_es(str(e)))
            except Exception as e:
                st.error(f"Error al subir a Google Drive: {e}")


# ---------- Página: Métricas ----------

def _pestana_iva(metricas: Metricas, inv: Inventario) -> None:
    hoy = date.today()
    c1, c2 = st.columns(2)
    año = int(c1.number_input("Año", min_value=2000, max_value=2100, value=hoy.year, step=1, key="iva_año"))
    t = c2.selectbox("Trimestre", ("1T (ene-mar)", "2T (abr-jun)", "3T (jul-sep)", "4T (oct-dic)"),
                     index=(hoy.month - 1) // 3, key="iva_trimestre")
    desde, hasta = trimestre(date(año, 3 * int(t[0]) - 2, 1))
    resumen = metricas.resumen_iva(desde, hasta, st.session_state.registro_servicios.servicios,
                                   st.session_state.registro_gastos.gastos)
    st.caption(f"Del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}.")

    st.markdown("**IVA pagado en las compras y los gastos** (soportado)")
    if resumen["soportado_por_tipo"]:
        st.dataframe([{"Tipo": nombre_iva(tipo), "IVA pagado (€)": f"{_eur(importe)}"}
                      for tipo, importe in resumen["soportado_por_tipo"].items()], width="stretch", hide_index=True)
        if resumen["soportado_gastos"]:
            st.caption(f"Incluye {_eur(resumen['soportado_gastos'])} € de IVA de los gastos (gasolina, alquileres...).")
    else:
        st.caption("No hay compras ni gastos con IVA en este trimestre.")
    if resumen["gastos_sin_desglose"]:
        st.caption(f"⚠️ {resumen['gastos_sin_desglose']} gasto(s) de este trimestre se apuntaron sin desglosar el IVA "
                   "(antes de existir ese dato): no cuentan aquí.")

    if inv.iva_recuperable:
        st.markdown("**IVA cobrado a los clientes** (repercutido)")
        st.write(
            f"{resumen['servicios_cobrados']} servicio(s) completado(s) con precio de cobro: {_eur(resumen['base_cobrada'])} € "
            f"sin IVA × {_num(inv.iva_cobro)} % = **{_eur(resumen['repercutido'])} €**"
        )
        if resumen["servicios_sin_cobro"]:
            st.caption(f"⚠️ {resumen['servicios_sin_cobro']} servicio(s) completado(s) sin precio de cobro: no cuentan.")
        m1, m2, m3 = st.columns(3)
        m1.metric("IVA cobrado", f"{_eur(resumen['repercutido'])} €")
        m2.metric("IVA pagado", f"{_eur(resumen['soportado'])} €")
        etiqueta = "A ingresar (aprox.)" if resumen["resultado"] >= 0 else "A compensar (aprox.)"
        m3.metric(etiqueta, f"{_eur(abs(resumen['resultado']))} €")
        st.caption("Solo cuenta lo registrado aquí: no incluye compras, gastos o ventas que no estén en el programa.")
    else:
        st.info("El negocio no recupera el IVA de sus compras (Ajustes): este IVA forma parte de lo que te cuestan. "
                "Se muestra solo como información.")
    st.warning(AVISO_FISCAL)


def pagina_ajustes() -> None:
    st.header("⚙️ Ajustes")
    inv = st.session_state.inventario
    st.subheader("IVA de las compras")
    st.write("En todo el programa ves **lo que has pagado de verdad** (con IVA), y el IVA queda apuntado aparte. "
             "Este ajuste solo decide cómo se calcula la **rentabilidad** de los servicios:")
    opciones = ("Recupero el IVA de mis compras", "No recupero el IVA de mis compras")
    elegido = st.radio("¿Tu negocio recupera el IVA de sus compras?", opciones,
                       index=0 if inv.iva_recuperable else 1, key="ajuste_iva")
    c1, c2 = st.columns(2)
    with c1.container(border=True):
        st.markdown("**✅ Recupero el IVA de mis compras**")
        st.markdown(
            "Para autónomos y empresas en **régimen general** que presentan cada trimestre la declaración de IVA "
            "(modelo 303) y se deducen el IVA de sus compras.\n\n"
            "- El IVA que pagas al comprar lo recuperas: se resta del IVA que cobras a tus clientes.\n"
            "- Por eso, en la **rentabilidad** de cada servicio lo comprado cuenta **sin IVA**, y el IVA aparece aparte "
            "como \"IVA recuperable\".\n"
            "- En **Métricas > 🧾 IVA** verás una estimación del IVA del trimestre (cobrado − pagado).\n\n"
            "*Ejemplo:* compras tomate por 20,80 € (20 € + 0,80 € de IVA). Ves 20,80 €, pero al margen del servicio "
            "le cuestan 20 €, porque los 0,80 € los recuperas."
        )
    with c2.container(border=True):
        st.markdown("**❌ No recupero el IVA de mis compras**")
        st.markdown(
            "Para negocios que **no se deducen el IVA**: por ejemplo, en **recargo de equivalencia** o si no "
            "presentas el modelo 303.\n\n"
            "- El IVA que pagas al comprar es un gasto más: no vuelve.\n"
            "- En la **rentabilidad** de cada servicio lo comprado cuenta **con IVA**, igual que lo que ves.\n"
            "- En Métricas el IVA pagado se muestra solo como información.\n\n"
            "*Ejemplo:* el mismo tomate de 20,80 € le cuesta al servicio 20,80 €."
        )
    st.caption("Qué NO cambia con este ajuste: los precios que ves (siempre lo pagado), el tipo de IVA de cada producto "
               "y lo que ya está registrado. Conviene elegirlo una vez, al empezar, según cómo tribute el negocio.")
    if st.button("Guardar ajuste de IVA", type="primary", key="ajuste_iva_guardar"):
        inv.iva_recuperable = elegido == opciones[0]
        avisar("success", f"Ajuste guardado: {elegido.lower()}.")
        st.rerun()
    st.caption(f"Ahora mismo: **{'recupero' if inv.iva_recuperable else 'no recupero'} el IVA** de mis compras.")

    if inv.iva_recuperable:
        st.markdown("**IVA que cobras a tus clientes**")
        iva_cobro = st.number_input(
            "IVA de tus servicios (%)", min_value=0.0, max_value=100.0, step=1.0, value=float(inv.iva_cobro),
            key="ajuste_iva_cobro", help="El de catering suele ser el 10 %. Sirve para estimar el IVA del trimestre: "
                                         "el precio de cobro de los servicios se apunta sin IVA.",
        )
        if st.button("Guardar IVA de cobro", key="ajuste_iva_cobro_guardar"):
            inv.iva_cobro = iva_cobro
            avisar("success", f"IVA de cobro guardado: {_num(iva_cobro)} %.")
            st.rerun()
    st.warning(AVISO_FISCAL)

    st.divider()
    st.subheader("⚠️ Empezar de cero")
    st.write("Borra **todos** los datos (productos, recetas, menús, servicios, gastos, material, historial...) y deja "
             "la app vacía, por ejemplo después de probarla con los datos de ejemplo. Los ajustes del IVA se conservan.")
    st.caption("Antes de borrar se hace una copia de seguridad de todo en la carpeta de datos (Exportar › Dónde se "
               "guardan tus datos), en «copias», con un nombre que empieza por «antes_de_empezar_de_cero». Esa copia "
               "no se borra sola.")
    texto = st.text_input("Para confirmarlo, escribe BORRAR", key="cero_confirmar")
    if st.button("🗑️ Borrar todos los datos", disabled=texto.strip() != "BORRAR", key="cero_boton"):
        try:
            copia = copia_antes_de_empezar_de_cero(_datos_sesion(), RUTA_SESION)
        except OSError as error:
            st.error(f"No se ha borrado nada: no se ha podido hacer la copia de seguridad ({error}).")
            return
        _empezar_de_cero()
        avisar("success", f"Todos los datos se han borrado. La copia de lo que había está en: {copia}")
        st.rerun()


def _empezar_de_cero() -> None:
    """Deja la app vacía (conservando los Ajustes del IVA). La copia de seguridad la hace quien llama."""
    Servicio._siguiente_id = 1
    Gasto._siguiente_id = 1
    _poner_sesion(sesion_vacia(st.session_state.inventario))


def _poner_sesion(nueva: Sesion) -> None:
    """Sustituye TODOS los datos de la app por los de `nueva` (y olvida lo elegido en las pantallas)."""
    ss = st.session_state
    for clave in list(ss.keys()):
        if isinstance(clave, str) and not clave.startswith("_") and clave != "avisos":
            del ss[clave]
    ss.inventario = nueva.inventario
    ss.registro_servicios = nueva.registro_servicios
    ss.recetario = nueva.recetario
    ss.gestor_compras = nueva.gestor_compras
    ss.archivo_informes = nueva.archivo_informes
    ss.registro_gastos = nueva.registro_gastos
    ss.registro_material = nueva.registro_material
    ss.ultima_exportacion = None
    ss.receta_ingredientes = {}


def pagina_metricas() -> None:
    st.header("📊 Métricas")
    inv = st.session_state.inventario
    metricas = Metricas(inv)

    c1, c2 = st.columns(2)
    periodo = c1.selectbox("Periodo", PERIODOS_VALIDOS, index=1, key="periodo_metricas")
    tipo = VISTAS_PRODUCTOS[c2.radio("Productos", list(VISTAS_PRODUCTOS), horizontal=True, key="metricas_tipo")]
    desde, hasta = rango_desde_periodo(periodo)
    st.caption(f"Del {desde.strftime('%d/%m/%Y')} al {hasta.strftime('%d/%m/%Y')}")
    nombres_tipo = [p.nombre for p in inv.productos_de(tipo)]

    if not inv.historial:
        st.info(
            "Todavía no hay movimientos de stock registrados. Usa 'Actualizar stock' "
            "en Inventario (entradas y salidas) para empezar a generar datos."
        )
        return

    tab_consumo, tab_desperdicio, tab_ranking, tab_gasto, tab_merma, tab_iva = st.tabs(
        ["Consumo por producto", "Desperdicio por producto", "🏆 Más consumidos", "💰 Gasto por categoría", "🦴 Merma",
         "🧾 IVA"]
    )
    with tab_iva:
        _pestana_iva(metricas, inv)

    with tab_merma:
        # La merma va aparte del desperdicio: el hueso es inevitable, lo que
        # caduca en la cámara no.
        resumen = metricas.resumen_limpiezas(desde, hasta)
        if tipo != "alimento":
            st.info("Solo los alimentos tienen merma.")
        elif not resumen:
            st.info("No hay limpiezas registradas en este periodo.")
        else:
            st.metric("Merma total del periodo", f"{_num(metricas.merma_total_kg(desde, hasta))} kg")
            st.dataframe([{
                "Producto": nombre,
                "Limpiezas": fila["limpiezas"],
                "Bruto (kg)": _num(fila["bruto_kg"]),
                "Limpio (kg)": _num(fila["limpio_kg"]),
                "Derivados (kg)": _num(fila["derivados_kg"]),
                "Merma (kg)": _num(fila["merma_kg"]),
                "Rendimiento": f"{_pct(fila['rendimiento'])}",
            } for nombre, fila in resumen.items()], width="stretch", hide_index=True)
            df_merma = pd.DataFrame(
                {nombre: [_num(fila["limpio_kg"]), _num(fila["derivados_kg"]), fila["merma_kg"]] for nombre, fila in resumen.items()},
                index=["Limpio", "Derivados", "Merma"],
            ).T
            st.bar_chart(df_merma)

    with tab_consumo:
        if not nombres_tipo:
            st.info("No hay productos en esta lista.")
        else:
            nombre = st.selectbox("Producto", nombres_tipo, key="metricas_consumo_producto")
            cantidad = metricas.cantidad_consumida(nombre, desde, hasta)
            st.metric(f"Consumido de {nombre}", f"{_num(cantidad)} {inv.buscar_producto(nombre).unidad}")

    with tab_desperdicio:
        if nombres_tipo:
            nombre2 = st.selectbox("Producto", nombres_tipo, key="metricas_desperdicio_producto")
            cantidad2 = metricas.cantidad_desperdiciada(nombre2, desde, hasta)
            st.metric(f"Desperdiciado de {nombre2}", f"{cantidad2} {inv.buscar_producto(nombre2).unidad}")
        valor_total = metricas.valor_desperdiciado_total(desde, hasta, tipo)
        st.metric("Valor total desperdiciado (toda esta lista)", f"{_eur(valor_total)} €")

    with tab_ranking:
        ranking = metricas.productos_mas_consumidos(desde, hasta, top=10, tipo=tipo)
        if not ranking:
            st.info("No hay datos de consumo en este periodo.")
        else:
            st.caption("Ordenado por lo que vale lo consumido (€, con IVA): así se pueden comparar productos que se "
                       "miden distinto (huevos por unidades, harina por kg...).")
            st.bar_chart(pd.DataFrame([{"Producto": f["producto"], "Consumido (€)": f["valor"]} for f in ranking])
                         .set_index("Producto"))
            st.dataframe([{"Producto": f["producto"], "Cantidad": f"{_num(f['cantidad'])} {f['unidad']}",
                           "Valor consumido (€)": _eur(f["valor"])} for f in ranking], width="stretch", hide_index=True)

    with tab_gasto:
        gasto = metricas.gasto_por_categoria(desde, hasta, tipo)
        por_tipo = metricas.gasto_por_tipo(desde, hasta)
        st.caption(
            f"Gasto en compras del periodo: alimentos {_eur(por_tipo['alimento'])} € · consumibles {_eur(por_tipo['consumible'])} € · "
            f"limpieza y mantenimiento {_eur(por_tipo['mantenimiento'])} € (lo pagado, con IVA). "
            f"De eso, IVA: {_eur(metricas.iva_soportado(desde, hasta))} € (el detalle, en la pestaña 🧾 IVA)."
        )
        if not gasto:
            st.info("No hay compras registradas en este periodo.")
        else:
            df_gasto = pd.DataFrame(list(gasto.items()), columns=["Categoría", "Gasto (€)"]).set_index("Categoría")
            st.bar_chart(df_gasto)
            st.dataframe(df_gasto.reset_index(), width="stretch", hide_index=True)
            st.metric("Gasto total", f"{_eur(sum(gasto.values()))} €")

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
                    c3.metric(f"Gasto — {elegido1}", f"{_eur(resultado['gasto_total_1'])} €")
                    c4.metric(
                        f"Gasto — {elegido2}", f"{_eur(resultado['gasto_total_2'])} €",
                        delta=f"{_es(format(resultado['diferencia_gasto_total'], '+.2f'))} €", delta_color="inverse",
                    )
                    c5.metric(
                        "Diferencia en desperdicio", f"{_es(format(resultado['diferencia_desperdicio'], '+.2f'))} €",
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
            🍽️ Gestión Catering
        </div>
        <div style="font-size: 0.85rem; color: #A79E8E; margin-top: 0.1rem;">
            Cocina, eventos y almacén
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
pagina = st.sidebar.radio("Navegación", PAGINAS, key="pagina_nav")

st.sidebar.divider()
zona_guardado = st.sidebar.empty()

# Los datos de ejemplo solo se ofrecen con el programa VACÍO: así nunca se
# mezclan con los datos reales de un negocio.
if _app_vacia() and st.sidebar.button("🧪 Cargar datos de ejemplo",
                                      help="Rellena el programa con datos inventados para probarlo. "
                                           "Solo aparece mientras el programa está vacío."):
    cargar_datos_ejemplo()
    avisar("success", "Datos de ejemplo cargados.")
    st.rerun()

if st.sidebar.button("⏻ Cerrar el programa", key="cerrar_programa",
                     help="Guarda y apaga el programa. Después puedes cerrar la pestaña del navegador."):
    autoguardar(zona_guardado)
    if firma(_datos_sesion()) != st.session_state._firma_guardada:
        st.error("No se ha cerrado: los últimos cambios no se han podido guardar (mira el aviso de la barra lateral).")
        st.stop()
    if os.environ.get("GESTION_RESTAURANTE_LANZADOR") == "1":
        st.success("✅ Todo guardado. El programa se ha cerrado: ya puedes cerrar esta pestaña del navegador.")
        # Se apaga un momento después, para que el mensaje llegue al navegador.
        threading.Timer(1.5, os._exit, args=(0,)).start()
    else:
        st.success("✅ Todo guardado. Para terminar, cierra la ventana donde se está ejecutando el programa.")
    st.stop()

# Se guarda SIEMPRE al terminar cada vuelta, también si la página hace
# st.rerun() o si falla al dibujarse (finally se ejecuta en los dos casos).
try:
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
    elif pagina == "Ajustes":
        pagina_ajustes()
finally:
    autoguardar(zona_guardado)
