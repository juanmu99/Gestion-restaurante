"""
pruebas/probar_interfaz.py
----------------------------
Prueba automática de la interfaz gráfica con Streamlit REAL.

Se ejecuta sola en GitHub Actions cada vez que se sube un cambio a main
(ver .github/workflows/probar-interfaz.yml), en un ordenador de GitHub.
Usa AppTest, la herramienta oficial de Streamlit para probar apps: ejecuta
app.py sin navegador, rellena campos, pulsa botones y deja comprobar el
resultado (el inventario, los mensajes de error, etc.).

También se puede ejecutar a mano desde la carpeta del proyecto:
    python pruebas/probar_interfaz.py

Es un script normal de Python (sin pytest): cada comprobación imprime
✅ o ❌, y al final sale con código 1 si alguna falló, para que GitHub
marque la ejecución en rojo.
"""

import shutil
import sys
import traceback
from datetime import date, time, timedelta
from pathlib import Path

import streamlit
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")
RESULTADOS = RAIZ / "resultados"
sys.path.insert(0, str(RAIZ / "modulos"))

from servicios import Servicio  # noqa: E402

lineas: list[str] = []
fallos: list[str] = []


def registrar(texto: str) -> None:
    print(texto)
    lineas.append(texto)


def comprobar(condicion: bool, descripcion: str) -> None:
    registrar(("✅ " if condicion else "❌ ") + descripcion)
    if not condicion:
        fallos.append(descripcion)


def sin_excepciones(at: AppTest, contexto: str) -> bool:
    """True si la última ejecución no lanzó ninguna excepción. Si lanzó, la registra entera."""
    if at.exception:
        for exc in at.exception:
            registrar(f"   💥 Excepción en {contexto}: {exc.value}")
            for linea in getattr(exc, "stack_trace", [])[-8:]:
                registrar(f"      {linea}")
        return False
    return True


def textos(elementos) -> list[str]:
    return [str(e.value) for e in elementos]


def boton(lista, etiqueta: str):
    for b in lista:
        if b.label == etiqueta:
            return b
    raise AssertionError(f"No encuentro el botón '{etiqueta}'")


def opcion(selectbox, prefijo: str) -> str:
    """La opción de un desplegable que empieza por `prefijo` (ej: 'Lote 2 ·')."""
    for texto in selectbox.options:
        if texto.startswith(prefijo):
            return texto
    raise AssertionError(f"No encuentro la opción '{prefijo}...' en {selectbox.options}")


def por_clave(lista, prefijo: str):
    """El widget cuya key empieza por `prefijo` (para las keys que llevan una huella al final)."""
    for w in lista:
        if w.key and w.key.startswith(prefijo):
            return w
    raise AssertionError(f"No encuentro ningún campo cuya clave empiece por '{prefijo}'")


def por_etiqueta(lista, etiqueta: str):
    """El widget de una lista cuya etiqueta es `etiqueta` (para los que están dentro de un formulario, sin key)."""
    for w in lista:
        if w.label == etiqueta:
            return w
    raise AssertionError(f"No encuentro el campo '{etiqueta}'")


def ir_a(at: AppTest, pagina: str) -> AppTest:
    at.sidebar.radio[0].set_value(pagina).run()
    return at


def nueva_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


def prueba(nombre):
    """Ejecuta una prueba y, si revienta de forma inesperada, lo registra como fallo sin parar las demás."""
    def decorador(funcion):
        def envoltorio(*args):
            registrar(f"\n--- {nombre} ---")
            try:
                return funcion(*args)
            except Exception as e:  # noqa: BLE001 -- queremos seguir con el resto de pruebas
                comprobar(False, f"{nombre}: error inesperado en la prueba: {e!r}")
                for linea in traceback.format_exc().splitlines()[-6:]:
                    registrar(f"      {linea}")
        return envoltorio
    return decorador


# ---------------------------------------------------------------- pruebas

@prueba("Arranque y datos de ejemplo")
def prueba_arranque(at: AppTest) -> None:
    comprobar(sin_excepciones(at, "el arranque"), "La app arranca sin errores")
    boton(at.sidebar.button, "🧪 Cargar datos de ejemplo").click().run()
    inv = at.session_state["inventario"]
    comprobar("Pata de cerdo" in inv.productos and "Tomate" in inv.productos, "Datos de ejemplo cargados")
    comprobar(not any("ejemplo" in b.label for b in at.sidebar.button),
              "Con datos, el botón de datos de ejemplo desaparece (no se pueden mezclar con los reales)")
    comprobar((RAIZ / "datos" / "sesion.json").exists() and any("se guardan solos" in t for t in textos(at.sidebar.caption)),
              "Los cambios se guardan solos en disco, sin pulsar nada")


@prueba("Todas las páginas se muestran")
def prueba_paginas(at: AppTest) -> None:
    for pagina in ["Dashboard", "Inventario", "Servicios", "Historial", "Recetario", "Compras", "Gastos", "Métricas",
                   "Exportar / Backup", "Ajustes"]:
        ir_a(at, pagina)
        comprobar(sin_excepciones(at, pagina) and not at.error, f"Página '{pagina}' sin errores")


@prueba("Precios: total pagado, historial y avisos")
def prueba_precios(at: AppTest) -> None:
    inv = at.session_state["inventario"]
    ir_a(at, "Dashboard")
    avisos_caro = " ".join(textos(at.warning))
    avisos_barato = " ".join(textos(at.success))
    comprobar("Tomate" in avisos_caro and "más caro" in avisos_caro
              and "Harina de trigo" in avisos_barato and "más barato" in avisos_barato,
              "El Dashboard avisa de los precios fuera de lo habitual (tomate más caro, harina más barata)")

    # Compra indicando el TOTAL pagado: el programa calcula el precio por kg
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🍅 Alimentos").run()
    nombre = "Pimiento rojo"
    at.selectbox(key="stock_select").select(nombre).run()
    at.radio(key=f"stock_tipo_{nombre}").set_value("Entrada (compra)").run()
    at.number_input(key=f"stock_cantidad_{nombre}").set_value(10.0)
    at.radio(key=f"stock_modo_precio_{nombre}").set_value("Total pagado").run()
    at.number_input(key=f"stock_precio_total_{nombre}").set_value(48.0).run()
    comprobar(any("4.8 € por kg" in t for t in textos(at.caption)),
              "Con el total pagado se muestra el precio por kg antes de guardar (48 € / 10 kg = 4,8 €)")
    at.button(key=f"stock_boton_{nombre}").click().run()
    ultima = inv.precios_de(nombre)[-1]
    comprobar(sin_excepciones(at, "compra con total") and ultima.precio_unitario == 4.8 and ultima.cantidad == 10,
              "La compra se guarda a 4,8 €/kg y entra en el historial de precios")

    at.selectbox(key="precios_select").select(nombre).run()
    comprobar(sin_excepciones(at, "historial de precios") and not at.error,
              "La pestaña 'Historial de precios' se muestra (con la gráfica por proveedor)")

    # (B) Corregir el precio de una compra mal apuntada
    def lote_2():
        caja = at.selectbox(key=f"edit_lote_{nombre}")
        caja.select(opcion(caja, "Lote 2 ·")).run()

    at.selectbox(key="editar_select").select(nombre).run()
    lote_2()
    por_clave(at.number_input, f"edit_lote_precio_{nombre}_2_").set_value(4.0).run()
    at.button(key=f"edit_boton_{nombre}").click().run()
    compra_mov = next(m for m in inv.historial if m.producto_nombre == nombre and m.lote_id == 2 and m.es_compra())
    comprobar(sin_excepciones(at, "corregir precio sin salidas") and inv.precios_de(nombre)[-1].precio_unitario == 4.0
              and compra_mov.precio_unitario == 4.0,
              "Corregir el precio de un lote sin usar corrige también su compra y el historial de precios")

    at.radio(key=f"stock_tipo_{nombre}").set_value("Salida").run()
    at.number_input(key=f"stock_cantidad_{nombre}").set_value(1.0)
    caja = at.selectbox(key=f"stock_lote_{nombre}")
    caja.select(opcion(caja, "Lote 2 ·")).run()
    at.button(key=f"stock_boton_{nombre}").click().run()
    lote_2()
    por_clave(at.number_input, f"edit_lote_precio_{nombre}_2_").set_value(3.5).run()
    pregunta = por_clave(at.radio, f"edit_lote_corregir_{nombre}_2_")
    comprobar(any("salida de 1 kg" in t for t in textos(at.info)),
              "Si ya ha salido algo del lote, se avisa de lo registrado y se pregunta qué hacer")
    pregunta.set_value(next(o for o in pregunta.options if o.startswith("Dejarlo"))).run()
    at.button(key=f"edit_boton_{nombre}").click().run()
    salida = next(m for m in inv.historial if m.producto_nombre == nombre and m.lote_id == 2 and m.tipo == "salida")
    comprobar(inv.buscar_producto(nombre).buscar_lote(2).precio_unitario == 3.5 and salida.precio_unitario == 4.0
              and inv.precios_de(nombre)[-1].precio_unitario == 4.0,
              "'Dejarlo como estaba': cambia el lote, pero no lo ya registrado")

    at.selectbox(key="precios_select").select(nombre).run()
    lote_id = inv.precios_de(nombre)[-1].lote_id
    por_clave(at.number_input, f"corregir_compra_precio_{nombre}_{lote_id}_").set_value(3.5).run()
    por_clave(at.button, f"corregir_compra_guardar_{nombre}_{lote_id}_").click().run()
    comprobar(sin_excepciones(at, "corregir compra") and inv.precios_de(nombre)[-1].precio_unitario == 3.5
              and salida.precio_unitario == 3.5,
              "Desde el historial de precios se corrige una compra y lo que ya salió de ella")

    # (D) IVA: producto al 4 % con el precio escrito con IVA incluido (lo del ticket)
    v = at.session_state["add_version"]
    at.text_input(key=f"add_nombre_{v}").input("Huevos camperos")
    at.text_input(key=f"add_categoria_{v}").input("Huevos")
    at.number_input(key=f"add_stock_{v}").set_value(30.0)
    at.selectbox(key=f"add_unidad_{v}").select("unidades")
    at.selectbox(key=f"add_iva_{v}").select("4 % (superreducido)").run()
    comprobar(at.radio(key=f"add_con_iva_{v}").value.startswith("Con IVA"),
              "Por defecto el precio se escribe con IVA incluido (lo que se paga)")
    at.number_input(key=f"add_precio_{v}").set_value(0.26).run()
    comprobar(any("0.25 € sin IVA" in t and "0.01 € de IVA" in t for t in textos(at.caption)),
              "Al escribir el precio se ve el desglose (0,26 € = 0,25 € sin IVA + 0,01 € de IVA)")
    at.text_input(key=f"add_proveedor_{v}").input("Granja Sol")
    at.button(key=f"add_boton_{v}").click().run()
    huevos = inv.buscar_producto("Huevos camperos")
    comprobar(sin_excepciones(at, "producto con IVA") and huevos is not None and huevos.iva == 4
              and abs(huevos.lotes[0].precio_base - 0.25) < 1e-9 and abs(huevos.precio_unitario - 0.26) < 1e-9,
              "Se ve lo pagado (0,26 €) y se guarda aparte el precio sin IVA (0,25 €) y su tipo (4 %)")

    ir_a(at, "Ajustes")
    comprobar(sin_excepciones(at, "ajustes") and any("no sustituye" in t for t in textos(at.warning))
              and any("régimen general" in t for t in textos(at.markdown))
              and any("recargo de equivalencia" in t for t in textos(at.markdown)),
              "Ajustes explica las dos opciones del IVA y avisa de que no sustituye a un gestor")
    at.radio(key="ajuste_iva").set_value("No recupero el IVA de mis compras").run()
    at.button(key="ajuste_iva_guardar").click().run()
    comprobar(not inv.iva_recuperable and abs(huevos.precio_unitario - 0.26) < 1e-9,
              "Se puede elegir 'No recupero el IVA' (los precios se siguen viendo igual)")
    for pagina in ("Dashboard", "Servicios", "Métricas", "Inventario"):
        ir_a(at, pagina)
        comprobar(sin_excepciones(at, f"{pagina} sin recuperar IVA") and not at.error,
                  f"'{pagina}' funciona sin recuperar el IVA")
    ir_a(at, "Ajustes")
    at.radio(key="ajuste_iva").set_value("Recupero el IVA de mis compras").run()
    at.button(key="ajuste_iva_guardar").click().run()
    at.number_input(key="ajuste_iva_cobro").set_value(10.0)
    at.button(key="ajuste_iva_cobro_guardar").click().run()
    comprobar(inv.iva_recuperable and inv.iva_cobro == 10, "...y volver a 'Recupero el IVA', con el IVA de cobro (10 %)")
    ir_a(at, "Métricas")
    comprobar(sin_excepciones(at, "pestaña IVA") and any("no sustituye" in t for t in textos(at.warning))
              and any("IVA cobrado" in m.label for m in at.metric),
              "Métricas > IVA: estimación del trimestre (cobrado y pagado) con el aviso de que no sustituye a un gestor")


@prueba("Añadir productos")
def prueba_anadir(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]

    # Producto con merma comprado por unidades, con el peso en gramos
    v = at.session_state["add_version"]
    at.text_input(key=f"add_nombre_{v}").input("Pollo entero")
    at.text_input(key=f"add_categoria_{v}").input("Carnes")
    at.number_input(key=f"add_stock_{v}").set_value(3.0)
    at.selectbox(key=f"add_unidad_{v}").select("unidades").run()
    at.checkbox(key=f"add_merma_{v}").check().run()
    at.selectbox(key=f"add_peso_{v}_unidad").select("g").run()
    at.number_input(key=f"add_peso_{v}_g").set_value(2200.0)
    at.number_input(key=f"add_precio_{v}").set_value(6.0)
    at.text_input(key=f"add_proveedor_{v}").input("Avícola")
    at.button(key=f"add_boton_{v}").click().run()
    pollo = inv.buscar_producto("Pollo entero")
    comprobar(sin_excepciones(at, "añadir pollo"), "Añadir producto sin excepciones")
    comprobar(pollo is not None and pollo.tiene_merma and pollo.peso_unitario == 2.2,
              "Pollo con merma por unidades: 2200 g/unidad se guardan como 2.2 kg")
    comprobar(any("añadido" in t for t in textos(at.success)), "Mensaje de 'producto añadido' visible")
    comprobar(at.text_input(key=f"add_nombre_{v + 1}").value == "", "El formulario queda vacío tras añadir")

    # Con merma por unidades pero SIN peso: debe dar error y no añadirse
    v = at.session_state["add_version"]
    at.text_input(key=f"add_nombre_{v}").input("Conejo")
    at.text_input(key=f"add_categoria_{v}").input("Carnes")
    at.selectbox(key=f"add_unidad_{v}").select("unidades").run()
    at.checkbox(key=f"add_merma_{v}").check().run()
    at.text_input(key=f"add_proveedor_{v}").input("Granja")
    at.button(key=f"add_boton_{v}").click().run()
    comprobar("Conejo" not in inv.productos and len(at.error) > 0,
              "Sin peso por unidad: error visible y no se añade")

    # La fecha de caducidad elegida se respeta (antes se guardaba la de hoy)
    v = at.session_state["add_version"]
    fecha = date.today() + timedelta(days=20)
    at.text_input(key=f"add_nombre_{v}").input("Nata")
    at.text_input(key=f"add_categoria_{v}").input("Lácteos")
    at.selectbox(key=f"add_unidad_{v}").select("litros")
    at.text_input(key=f"add_proveedor_{v}").input("Lácteos SA")
    at.number_input(key=f"add_stock_{v}").set_value(2.0).run()
    at.checkbox(key=f"add_tiene_caducidad_{v}").check().run()
    at.date_input(key=f"add_fecha_{v}").set_value(fecha)
    at.button(key=f"add_boton_{v}").click().run()
    comprobar("Nata" not in inv.productos and any("precio" in t for t in textos(at.error)),
              "Con stock inicial y sin precio no se añade (antes entraba a 0 €)")
    at.number_input(key=f"add_precio_{v}").set_value(1.5)
    at.button(key=f"add_boton_{v}").click().run()
    nata = inv.buscar_producto("Nata")
    comprobar(nata is not None and nata.fecha_caducidad == fecha and nata.lotes[0].fecha_caducidad == fecha,
              "Se guarda la fecha de caducidad elegida (en su primer lote)")


@prueba("Actualizar stock")
def prueba_stock(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]

    # Salida por desperdicio (antes el motivo quedaba fijo en "consumo")
    at.selectbox(key="stock_select").select("Tomate").run()
    at.number_input(key="stock_cantidad_Tomate").set_value(0.2)
    at.radio(key="stock_tipo_Tomate").set_value("Salida").run()
    at.selectbox(key="stock_motivo_Tomate").select("desperdicio")
    at.button(key="stock_boton_Tomate").click().run()
    ultimo = inv.historial[-1]
    comprobar(ultimo.producto_nombre == "Tomate" and ultimo.motivo == "desperdicio",
              "Salida con motivo 'desperdicio' registrada")

    # Sacar más de lo que hay: error visible y nada cambia
    stock_antes = inv.buscar_producto("Tomate").stock
    at.number_input(key="stock_cantidad_Tomate").set_value(50.0)
    at.radio(key="stock_tipo_Tomate").set_value("Salida").run()
    at.button(key="stock_boton_Tomate").click().run()
    comprobar(inv.buscar_producto("Tomate").stock == stock_antes and len(at.error) > 0,
              "Salida mayor que el stock: error visible y el stock no cambia")

    # Compra de 2 patas de 6 kg (había 2 de 7 kg): media ponderada 6.5 kg
    at.selectbox(key="stock_select").select("Pata de cerdo").run()
    at.number_input(key="stock_cantidad_Pata de cerdo").set_value(2.0)
    at.radio(key="stock_tipo_Pata de cerdo").set_value("Entrada (compra)").run()
    at.selectbox(key="stock_peso_Pata de cerdo_unidad").select("kg").run()
    at.number_input(key="stock_peso_Pata de cerdo_kg").set_value(6.0)
    comprobar(at.number_input(key="stock_precio_Pata de cerdo").value is None,
              "El precio de la compra empieza vacío (no se da por bueno el de la última vez)")
    at.button(key="stock_boton_Pata de cerdo").click().run()
    comprobar(inv.buscar_producto("Pata de cerdo").stock == 2 and any("precio" in t for t in textos(at.error)),
              "Sin precio no se registra la compra")
    at.number_input(key="stock_precio_Pata de cerdo").set_value(42.0)
    at.button(key="stock_boton_Pata de cerdo").click().run()
    pata = inv.buscar_producto("Pata de cerdo")
    comprobar(pata.stock == 4 and pata.peso_unitario == 6.5 and len(pata.lotes) == 2,
              f"Compra con peso por unidad: un lote nuevo, 4 patas de media 6.5 kg (hay {pata.stock}, {pata.peso_unitario} kg)")

    # Salida de un lote ELEGIDO: el que caduca más tarde (no el sugerido)
    secreto = inv.buscar_producto("Secreto ibérico")
    at.selectbox(key="stock_select").select("Secreto ibérico").run()
    at.radio(key="stock_tipo_Secreto ibérico").set_value("Salida").run()
    at.number_input(key="stock_cantidad_Secreto ibérico").set_value(0.3)
    lote_sb = at.selectbox(key="stock_lote_Secreto ibérico")
    lote_sb.select(opcion(lote_sb, "Lote 2 ·"))
    at.selectbox(key="stock_motivo_Secreto ibérico").select("consumo")
    at.button(key="stock_boton_Secreto ibérico").click().run()
    comprobar(sin_excepciones(at, "salida de un lote") and abs(secreto.buscar_lote(2).cantidad - 0.5) < 1e-9
              and secreto.buscar_lote(1).cantidad == 1,
              "Salida del lote elegido (lote 2): solo baja ese lote")
    comprobar(inv.historial[-1].lote_id == 2, "El historial apunta de qué lote salió")
    comprobar(at.number_input(key="stock_cantidad_Secreto ibérico").value == 0,
              "Tras registrar la salida, el formulario queda vacío")

    # Sacar de un lote más de lo que tiene: error y nada cambia
    at.number_input(key="stock_cantidad_Secreto ibérico").set_value(0.9)
    lote_sb = at.selectbox(key="stock_lote_Secreto ibérico")
    lote_sb.select(opcion(lote_sb, "Lote 2 ·"))
    at.button(key="stock_boton_Secreto ibérico").click().run()
    comprobar(abs(secreto.buscar_lote(2).cantidad - 0.5) < 1e-9 and any("solo hay" in t for t in textos(at.error)),
              "Más de lo que tiene el lote: error visible y no cambia nada")

    # Compra: un lote nuevo con su precio, proveedor y caducidad
    fecha = date.today() + timedelta(days=20)
    at.radio(key="stock_tipo_Secreto ibérico").set_value("Entrada (compra)").run()
    at.number_input(key="stock_cantidad_Secreto ibérico").set_value(0.5)
    at.number_input(key="stock_precio_Secreto ibérico").set_value(16.0)
    at.text_input(key="stock_proveedor_Secreto ibérico").input("Ibéricos Sierra")
    at.checkbox(key="stock_tiene_fecha_Secreto ibérico").check().run()
    at.date_input(key="stock_fecha_Secreto ibérico").set_value(fecha)
    at.button(key="stock_boton_Secreto ibérico").click().run()
    nuevo = secreto.buscar_lote(3)
    comprobar(nuevo is not None and nuevo.cantidad == 0.5 and nuevo.precio_unitario == 16
              and nuevo.proveedor == "Ibéricos Sierra" and nuevo.fecha_caducidad == fecha,
              "Compra: lote 3 con su cantidad, precio, proveedor y caducidad")


@prueba("Limpiar producto")
def prueba_limpiar(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]
    at.selectbox(key="limpiar_origen").select("Pata de cerdo").run()

    # Se limpia el lote 2 (las 2 patas de 6 kg), no el que se sugiere
    v = at.session_state["limpiar_version"]
    lote_sb = at.selectbox(key=f"limpiar_lote_Pata de cerdo_{v}")
    lote_sb.select(opcion(lote_sb, "Lote 2 ·")).run()
    k = lambda campo: f"limpiar_{campo}_Pata de cerdo_{v}_2"
    at.number_input(key=k("cantidad")).set_value(2.0)
    at.radio(key=k("unidad")).set_value("kg")
    at.text_input(key=k("limpio")).input("Carne de cerdo limpia")
    at.number_input(key=k("peso_limpio")).set_value(8.0).run()
    comprobar(sin_excepciones(at, "la vista previa de la limpieza"), "Vista previa de la limpieza sin errores")
    at.button(key=k("boton")).click().run()

    comprobar(len(inv.limpiezas) == 1, "Limpieza registrada")
    if inv.limpiezas:
        l = inv.limpiezas[0]
        comprobar(l.peso_bruto_kg == 12 and l.merma_kg == 4 and "Lote 2" in (l.lote_origen or ""),
                  f"Lote 2: 2 patas de 6 kg = 12 kg bruto, 8 kg limpio, 4 kg de merma (bruto {l.peso_bruto_kg}, merma {l.merma_kg})")
    carne = inv.buscar_producto("Carne de cerdo limpia")
    comprobar(carne is not None and carne.stock == 8 and carne.origen == "Pata de cerdo",
              "Se crea 'Carne de cerdo limpia' con 8 kg y su origen")
    pata = inv.buscar_producto("Pata de cerdo")
    comprobar(pata.stock == 2 and pata.buscar_lote(2) is None, "Quedan las 2 patas del lote 1")
    comprobar(any("Limpieza registrada" in t for t in textos(at.success)), "Mensaje de limpieza visible tras recargar")

    # Limpieza imposible: más limpio que bruto
    v = at.session_state["limpiar_version"]
    k = lambda campo: f"limpiar_{campo}_Pata de cerdo_{v}_1"
    comprobar(at.number_input(key=k("cantidad")).value is None and at.number_input(key=k("peso_limpio")).value is None
              and at.selectbox(key=k("limpio_select")).value is None,
              "Al volver a limpiar, el formulario empieza vacío (sin datos de la limpieza anterior)")
    at.selectbox(key=k("limpio_select")).select("Carne de cerdo limpia").run()
    at.number_input(key=k("cantidad")).set_value(1.0)
    at.number_input(key=k("peso_limpio")).set_value(20.0)
    at.button(key=k("boton")).click().run()
    comprobar(len(inv.limpiezas) == 1 and any("pesan más" in t for t in textos(at.error)),
              "Más limpio que bruto: error visible y no se registra nada")


@prueba("Editar producto")
def prueba_editar(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]
    at.selectbox(key="editar_select").select("Tomate").run()
    por_clave(at.checkbox, "edit_merma_Tomate_").check()
    at.button(key="edit_boton_Tomate").click().run()
    comprobar(inv.buscar_producto("Tomate").tiene_merma, "Editar: activar la merma de un producto")

    # Cambiar de producto en el desplegable rellena sus propios datos
    at.selectbox(key="editar_select").select("Aceite de oliva").run()
    comprobar(por_clave(at.text_input, "edit_nombre_Aceite de oliva_").value == "Aceite de oliva",
              "Al cambiar de producto se cargan sus datos")

    # Producto con UN lote: sus datos de compra se corrigen directamente
    kl = lambda lista, campo: por_clave(lista, f"edit_lote_{campo}_Aceite de oliva_1_")
    comprobar(kl(at.number_input, "cantidad").value == 20, "Con un solo lote, sus datos aparecen sin elegir nada")

    # Una salida de stock hecha DESPUÉS de abrir 'Editar producto' no se deshace al guardar (fallo de la revisión)
    at.selectbox(key="stock_select").select("Aceite de oliva").run()
    at.radio(key="stock_tipo_Aceite de oliva").set_value("Salida").run()
    at.number_input(key="stock_cantidad_Aceite de oliva").set_value(5.0)
    at.button(key="stock_boton_Aceite de oliva").click().run()
    comprobar(kl(at.number_input, "cantidad").value == 15,
              "Tras una salida, 'Editar producto' muestra la cantidad actual (15), no la de antes")
    por_clave(at.number_input, "edit_stock_minimo_Aceite de oliva_").set_value(6.0)
    at.button(key="edit_boton_Aceite de oliva").click().run()
    comprobar(inv.buscar_producto("Aceite de oliva").stock == 15 and inv.buscar_producto("Aceite de oliva").stock_minimo == 6,
              "Guardar solo el stock mínimo no deshace la salida (sigue habiendo 15)")

    kl(at.number_input, "cantidad").set_value(18.0)
    kl(at.number_input, "precio").set_value(5.0)
    kl(at.text_input, "proveedor").input("Aceites Jaén")
    kl(at.checkbox, "tiene_fecha").check().run()
    kl(at.date_input, "fecha").set_value(date.today() + timedelta(days=200))
    por_clave(at.text_input, "edit_categoria_Aceite de oliva_").input("Aceites y grasas")
    at.button(key="edit_boton_Aceite de oliva").click().run()
    aceite = inv.buscar_producto("Aceite de oliva")
    lote = aceite.lotes[0]
    comprobar(sin_excepciones(at, "editar con lote") and aceite.categoria == "Aceites y grasas" and aceite.stock == 18
              and lote.precio_unitario == 5 and lote.proveedor == "Aceites Jaén"
              and lote.fecha_caducidad == date.today() + timedelta(days=200),
              "Editar producto corrige a la vez los datos generales y los de la compra (cantidad, precio, proveedor, caducidad)")


@prueba("Lotes: corregir y desechar")
def prueba_lotes(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]
    secreto = inv.buscar_producto("Secreto ibérico")

    # Producto con VARIOS lotes: en 'Editar producto' se elige cuál corregir.
    # Se pone la caducidad del lote 1 a ayer: pasa a estar caducado.
    at.selectbox(key="editar_select").select("Secreto ibérico").run()
    lote_sb = at.selectbox(key="edit_lote_Secreto ibérico")
    lote_sb.select(opcion(lote_sb, "Lote 1 ·")).run()
    por_clave(at.date_input, "edit_lote_fecha_Secreto ibérico_1_").set_value(date.today() - timedelta(days=1))
    at.button(key="edit_boton_Secreto ibérico").click().run()
    comprobar(sin_excepciones(at, "corregir lote") and secreto.buscar_lote(1).esta_caducado()
              and not secreto.buscar_lote(2).esta_caducado(),
              "Editar producto con varios lotes: se corrige solo el lote elegido")
    comprobar(any("Caducado" in t and "Secreto ibérico" in t for t in textos(at.error)),
              "El lote caducado se avisa en rojo arriba")

    # Desecharlo con el botón del aviso: sale todo como desperdicio
    at.button(key="desechar_Secreto ibérico_1").click().run()
    ultimo = inv.historial[-1]
    comprobar(secreto.buscar_lote(1) is None and ultimo.motivo == "desperdicio" and ultimo.lote_id == 1
              and ultimo.cantidad == 1, "'Desechar lote' lo tira entero y lo apunta como desperdicio")
    comprobar([l.id for l in secreto.lotes] == [2, 3], "Quedan los lotes 2 y 3")


@prueba("Consumibles")
def prueba_consumibles(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]
    at.radio(key="inv_tipo").set_value("🧻 Consumibles").run()
    comprobar(sin_excepciones(at, "lista de consumibles"), "La lista de consumibles se muestra sin errores")
    comprobar(at.selectbox(key="editar_select").options == ["Servilletas de papel", "Vasos desechables"],
              "En la lista de consumibles solo aparecen consumibles")

    v = at.session_state["add_version"]
    at.text_input(key=f"add_nombre_{v}").input("Film transparente")
    at.text_input(key=f"add_categoria_{v}").input("Cocina")
    at.number_input(key=f"add_stock_{v}").set_value(2.0)
    at.selectbox(key=f"add_unidad_{v}").select("unidades")
    at.number_input(key=f"add_precio_{v}").set_value(3.5)
    at.text_input(key=f"add_proveedor_{v}").input("Hostelería Total").run()
    claves = {w.key for w in at.checkbox}
    comprobar(f"add_tiene_caducidad_{v}" not in claves and f"add_merma_{v}" not in claves,
              "Al añadir un consumible no se pide caducidad ni merma")
    at.button(key=f"add_boton_{v}").click().run()
    film = inv.buscar_producto("Film transparente")
    comprobar(film is not None and film.es_consumible() and film.stock == 2, "Se añade como consumible")
    at.radio(key="inv_tipo").set_value("🍅 Alimentos").run()
    comprobar("Film transparente" not in at.selectbox(key="editar_select").options,
              "Y no aparece en la lista de alimentos")

    ir_a(at, "Recetario")
    comprobar("Servilletas de papel" not in at.selectbox(key="ing_select").options,
              "Las recetas solo ofrecen alimentos como ingredientes")
    rec = at.session_state["recetario"]
    menu = rec.menus["Menú del día"]
    clave = "menu_Menú del día"
    at.number_input(key=f"{clave}_cons_Servilletas de papel").set_value(3.0)
    at.button(key=f"{clave}_guardar").click().run()
    comprobar(sin_excepciones(at, "editar consumibles del menú") and menu.consumibles_por_comensal.get("Servilletas de papel") == 3,
              "En el detalle del menú se cambian sus consumibles (3 servilletas por comensal)")

    ir_a(at, "Métricas")
    at.radio(key="metricas_tipo").set_value("🧻 Consumibles").run()
    comprobar(sin_excepciones(at, "métricas de consumibles") and not at.error, "Métricas de consumibles sin errores")


@prueba("Elaboraciones")
def prueba_elaboraciones(at: AppTest) -> None:
    inv = at.session_state["inventario"]
    rec = at.session_state["recetario"]
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🥘 Elaboraciones").run()
    comprobar(sin_excepciones(at, "lista de elaboraciones") and len(inv.elaboraciones.tandas) == 1,
              "La lista de elaboraciones se muestra (con la tanda de ejemplo)")

    # Preparar 2 raciones de pan (no tiene vida útil: la caducidad se pide a mano)
    v = at.session_state["elab_version"]
    harina_antes = inv.buscar_producto("Harina de trigo").stock
    at.selectbox(key=f"elab_receta_{v}").select("Pan casero").run()
    at.number_input(key=f"elab_raciones_Pan casero_{v}").set_value(2.0).run()
    clave_cad = f"elab_caducidad_{date.today().isoformat()}_Pan casero_{v}"
    comprobar(at.date_input(key=clave_cad).value is None, "Sin vida útil, la caducidad empieza vacía")
    at.button(key=f"elab_boton_Pan casero_{v}").click().run()
    comprobar(len(inv.elaboraciones.tandas) == 1 and any("caducidad" in t for t in textos(at.error)),
              "Sin caducidad no se prepara")
    at.date_input(key=clave_cad).set_value(date.today() + timedelta(days=5))
    at.button(key=f"elab_boton_Pan casero_{v}").click().run()
    pan = inv.elaboraciones.tandas_de("Pan casero")
    comprobar(sin_excepciones(at, "preparar") and len(pan) == 1 and pan[0].raciones == 2
              and abs(inv.buscar_producto("Harina de trigo").stock - (harina_antes - 0.3)) < 1e-9,
              "Preparar 2 raciones de pan gasta 0,3 kg de harina y crea la tanda")

    # Vida útil: con ella, la caducidad se propone sola
    ir_a(at, "Recetario")
    at.selectbox(key="vida_receta").select("Pan casero").run()
    at.number_input(key="vida_dias_Pan casero").set_value(4)
    at.button(key="vida_guardar_Pan casero").click().run()
    comprobar(rec.recetas["Pan casero"].vida_util_dias == 4, "Se puede poner la vida útil a una receta")
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🥘 Elaboraciones").run()
    v = at.session_state["elab_version"]
    at.selectbox(key=f"elab_receta_{v}").select("Pan casero").run()
    comprobar(at.date_input(key=f"elab_caducidad_{date.today().isoformat()}_Pan casero_{v}").value
              == date.today() + timedelta(days=4), "Con vida útil, la caducidad se propone (hoy + 4 días)")


@prueba("Elaboraciones base")
def prueba_bases(at: AppTest) -> None:
    inv = at.session_state["inventario"]
    sofrito = inv.buscar_producto("Sofrito")
    comprobar(sofrito is not None and sofrito.es_base() and abs(sofrito.stock - 0.9) < 1e-9
              and len(inv.elaboraciones.preparaciones_base) == 1,
              "Los datos de ejemplo traen el sofrito (base) con una preparación: previsto 1 kg, salió 0,9")

    # Crear una base nueva desde el Recetario
    ir_a(at, "Recetario")
    comprobar(sin_excepciones(at, "pestaña de bases") and not at.error, "La pestaña 'Elaboraciones base' se muestra")
    v = at.session_state["base_nueva_version"]
    k = lambda campo: f"base_nueva_{campo}_{v}"
    at.text_input(key=k("nombre")).input("Salsa de tomate")
    at.selectbox(key=k("unidad")).select("litros")
    at.number_input(key=k("cantidad")).set_value(2.0).run()
    at.button(key=k("crear")).click().run()
    comprobar("Salsa de tomate" not in inv.productos and any("ingrediente" in t for t in textos(at.error)),
              "Sin ingredientes no se crea la base")
    at.multiselect(key=f"{k('formula')}_ingredientes").select("Sofrito").select("Aceite de oliva").run()
    at.number_input(key=f"{k('formula')}_cant_Sofrito").set_value(0.5)
    at.number_input(key=f"{k('formula')}_cant_Aceite de oliva").set_value(0.1).run()
    at.button(key=k("crear")).click().run()
    salsa = inv.buscar_producto("Salsa de tomate")
    comprobar(sin_excepciones(at, "crear base") and salsa is not None and salsa.es_base() and salsa.unidad == "litros"
              and salsa.formula == {"cantidad": 2.0, "ingredientes": {"Sofrito": 0.5, "Aceite de oliva": 0.1}},
              "Se crea una base que lleva otra base (salsa con sofrito)")

    # Editar: el sofrito no puede llevar la salsa (que ya lleva sofrito)
    at.radio(key="base_modo").set_value("✏️ Editar una fórmula").run()
    at.selectbox(key="base_editar_select").select("Sofrito").run()
    ve = at.session_state["base_editar_version"]
    clave = f"base_editar_formula_Sofrito_{ve}"
    at.multiselect(key=f"{clave}_ingredientes").select("Salsa de tomate").run()
    at.number_input(key=f"{clave}_cant_Salsa de tomate").set_value(0.2).run()
    at.button(key=f"base_editar_guardar_Sofrito_{ve}").click().run()
    comprobar("Salsa de tomate" not in sofrito.formula["ingredientes"] and any("círculo" in t for t in textos(at.error)),
              "Las fórmulas no pueden ir en círculo")
    at.multiselect(key=f"{clave}_ingredientes").unselect("Salsa de tomate").run()
    at.number_input(key=f"base_editar_vida_Sofrito_{ve}").set_value(5)
    at.button(key=f"base_editar_guardar_Sofrito_{ve}").click().run()
    comprobar(sofrito.vida_util_dias == 5, "Se puede cambiar la vida útil de una base")

    # Preparar sofrito desde Inventario > Elaboraciones
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🥘 Elaboraciones").run()
    at.radio(key="elab_que").set_value("Una elaboración base (kg / litros)").run()
    vb = at.session_state["base_version"]
    at.selectbox(key=f"base_preparar_{vb}").select("Sofrito").run()
    kb = lambda campo: f"base_{campo}_Sofrito_{vb}"
    comprobar(at.date_input(key=kb(f"caducidad_{date.today().isoformat()}")).value == date.today() + timedelta(days=5),
              "La caducidad se propone con la vida útil de la base (hoy + 5)")
    cebolla_antes = inv.buscar_producto("Cebolla dulce").stock
    stock_antes = sofrito.stock
    at.number_input(key=kb("prevista")).set_value(2.0).run()
    at.button(key=kb("boton")).click().run()
    comprobar(sofrito.stock == stock_antes and any("de verdad" in t for t in textos(at.error)),
              "Sin indicar cuánto salió de verdad no se prepara")
    at.number_input(key=kb("obtenida")).set_value(1.7).run()
    at.button(key=kb("boton")).click().run()
    prep = inv.elaboraciones.preparaciones_base[-1]
    comprobar(sin_excepciones(at, "preparar base") and abs(sofrito.stock - (stock_antes + 1.7)) < 1e-9
              and abs(inv.buscar_producto("Cebolla dulce").stock - (cebolla_antes - 3)) < 1e-9
              and prep.prevista == 2 and prep.obtenida == 1.7 and abs(prep.diferencia + 0.3) < 1e-9,
              "Preparar 2 kg gasta 3 kg de cebolla dulce, entra lo obtenido (1,7 kg) y queda apuntada la diferencia")
    comprobar(sin_excepciones(at, "preparaciones de bases") and not at.error,
              "El historial de preparaciones de bases se muestra")


@prueba("Anotaciones")
def prueba_notas(at: AppTest) -> None:
    inv = at.session_state["inventario"]
    rec = at.session_state["recetario"]
    ir_a(at, "Recetario")
    at.text_area(key="nota_receta_Pan casero").input("Amasar 10 minutos.\nReposar 1 hora.")
    at.button(key="nota_guardar_receta_Pan casero").click().run()
    pan = rec.recetas["Pan casero"]
    comprobar(sin_excepciones(at, "nota de receta") and pan.notas == "Amasar 10 minutos.\nReposar 1 hora."
              and pan.notas_fecha == date.today(), "Se escribe la nota de una receta (con varias líneas y su fecha)")
    at.text_area(key="nota_menu_Menú del día").input("Servir el pan caliente.")
    at.button(key="nota_guardar_menu_Menú del día").click().run()
    comprobar(rec.menus["Menú del día"].notas == "Servir el pan caliente.", "Se escribe la nota de un menú")
    at.text_area(key="nota_base_Sofrito").input("")
    at.button(key="nota_guardar_base_Sofrito").click().run()
    comprobar(inv.buscar_producto("Sofrito").notas == "", "Se puede borrar la nota de una base")
    at.text_area(key="nota_base_Sofrito").input("Pochar sin dorar.")
    at.button(key="nota_guardar_base_Sofrito").click().run()
    comprobar(inv.buscar_producto("Sofrito").notas == "Pochar sin dorar.", "...y volver a escribirla")

    # Crear una base con nota
    v = at.session_state["base_nueva_version"]
    k = lambda campo: f"base_nueva_{campo}_{v}"
    at.text_input(key=k("nombre")).input("Fondo blanco")
    at.selectbox(key=k("unidad")).select("litros")
    at.number_input(key=k("cantidad")).set_value(1.0).run()
    at.multiselect(key=f"{k('formula')}_ingredientes").select("Cebolla dulce").run()
    at.number_input(key=f"{k('formula')}_cant_Cebolla dulce").set_value(0.2)
    at.text_area(key=k("notas")).input("Desgrasar en frío.")
    at.button(key=k("crear")).click().run()
    fondo = inv.buscar_producto("Fondo blanco")
    comprobar(fondo is not None and fondo.notas == "Desgrasar en frío.", "Al crear una base se puede escribir su nota")

    # La nota se ve al preparar
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🥘 Elaboraciones").run()
    at.radio(key="elab_que").set_value("Un plato (raciones)").run()
    ve = at.session_state["elab_version"]
    at.selectbox(key=f"elab_receta_{ve}").select("Ensalada de tomate").run()
    comprobar(any("Aliñar justo antes" in t for t in textos(at.info)), "Al preparar un plato se ve su nota")
    at.radio(key="elab_que").set_value("Una elaboración base (kg / litros)").run()
    vb = at.session_state["base_version"]
    at.selectbox(key=f"base_preparar_{vb}").select("Sofrito").run()
    comprobar(any("Pochar sin dorar" in t for t in textos(at.info)), "Al preparar una base se ve su nota")
    at.radio(key="elab_que").set_value("Un plato (raciones)").run()

    # ...y al completar un servicio de ese menú
    ir_a(at, "Servicios")
    caja = at.selectbox(key="completar_select")
    opciones_menu = [o for o in caja.options if o.endswith("Menú del día")]
    if opciones_menu:
        caja.select(opciones_menu[0]).run()
        escrito = " ".join(textos(at.markdown))
        comprobar("Servir el pan caliente." in escrito and "Aliñar justo antes" in escrito,
                  "Al completar un servicio se ven las notas del menú y de sus recetas")
    else:
        comprobar(False, "Hay un servicio pendiente con el 'Menú del día' para ver sus notas")


@prueba("Limpieza y mantenimiento")
def prueba_mantenimiento(at: AppTest) -> None:
    inv = at.session_state["inventario"]
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🧽 Limpieza y mantenimiento").run()
    comprobar(sin_excepciones(at, "lista de mantenimiento") and not at.error
              and any("Bayetas" in t for t in textos(at.warning)),
              "La lista de limpieza y mantenimiento se muestra (y avisa de las bayetas bajo mínimo)")

    # Añadir un producto: sin merma, con caducidad opcional
    v = at.session_state["add_version"]
    at.text_input(key=f"add_nombre_{v}").input("Lavavajillas")
    at.text_input(key=f"add_categoria_{v}").input("Limpieza")
    at.number_input(key=f"add_stock_{v}").set_value(5.0)
    at.selectbox(key=f"add_unidad_{v}").select("litros").run()
    comprobar(not any(c.key == f"add_merma_{v}" for c in at.checkbox)
              and any(c.key == f"add_tiene_caducidad_{v}" for c in at.checkbox),
              "Al añadir no se pregunta por la merma, pero sí (opcional) por la caducidad")
    at.number_input(key=f"add_precio_{v}").set_value(2.0)
    at.number_input(key=f"add_stock_minimo_{v}").set_value(1.0)
    at.text_input(key=f"add_proveedor_{v}").input("Droguería Central")
    at.button(key=f"add_boton_{v}").click().run()
    lavavajillas = inv.buscar_producto("Lavavajillas")
    comprobar(lavavajillas is not None and lavavajillas.es_mantenimiento() and lavavajillas.stock == 5,
              "Se añade a la lista de limpieza y mantenimiento")

    # Gastar lejía para un servicio: cuenta en su rentabilidad
    servicio = next(s for s in at.session_state["registro_servicios"].servicios if s.estado == "pendiente")
    at.selectbox(key="stock_select").select("Lejía").run()
    at.radio(key="stock_tipo_Lejía").set_value("Salida").run()
    at.number_input(key="stock_cantidad_Lejía").set_value(1.0)
    caja = at.selectbox(key="stock_servicio_Lejía")
    caja.select(opcion(caja, f"#{servicio.id} -")).run()
    at.button(key="stock_boton_Lejía").click().run()
    comprobar(sin_excepciones(at, "salida de lejía") and inv.buscar_producto("Lejía").stock == 3
              and inv.historial[-1].servicio_id == servicio.id,
              "Una salida de lejía se puede asociar a un servicio")
    ir_a(at, "Servicios")
    comprobar(sin_excepciones(at, "rentabilidad con mantenimiento") and not at.error,
              "La rentabilidad de los servicios se muestra con la limpieza y el mantenimiento")

    # No aparecen como ingredientes de recetas
    ir_a(at, "Recetario")
    comprobar("Lejía" not in at.selectbox(key="ing_select").options, "No se pueden usar como ingrediente de una receta")

    # La lista de la compra repone las bayetas hasta el mínimo
    ir_a(at, "Compras")
    boton(at.button, "Generar lista de compra").click().run()
    item = at.session_state["gestor_compras"].pendiente_de("Bayetas")
    comprobar(item is not None and item.cantidad == 4, "La lista de la compra repone las bayetas hasta el mínimo (4)")

    ir_a(at, "Métricas")
    at.radio(key="metricas_tipo").set_value("🧽 Limpieza y mantenimiento").run()
    comprobar(sin_excepciones(at, "métricas de mantenimiento") and not at.error, "Métricas de limpieza y mantenimiento sin errores")


@prueba("Completar servicio")
def prueba_completar(at: AppTest) -> None:
    ir_a(at, "Servicios")
    serv = at.session_state["registro_servicios"]
    pendiente = next(s for s in serv.servicios if s.estado == "pendiente")
    at.selectbox(key="completar_select").select(
        f"#{pendiente.id} - {pendiente.fecha.strftime('%d/%m/%Y')} - {pendiente.menu}"
    ).run()
    at.text_area(key=f"valoracion_{pendiente.id}").input("Todo bien; sobró pan")
    boton(at.button, "Completar servicio").click().run()
    servilletas = at.session_state["inventario"].buscar_producto("Servilletas de papel")
    comprobar(sin_excepciones(at, "completar servicio") and pendiente.estado == "completado",
              "Servicio completado desde la interfaz")
    comprobar(servilletas.stock == 500 - 3 * pendiente.comensales,
              f"También descuenta los consumibles del menú (quedan {servilletas.stock} servilletas)")
    usos = at.session_state["inventario"].elaboraciones.usos_de_servicio(pendiente.id)
    comprobar(sorted((u.receta, u.raciones) for u in usos) == [("Ensalada de tomate", 4), ("Pan casero", 2)],
              "Al completar se usan por defecto las raciones ya preparadas (4 de ensalada y 2 de pan)")
    comprobar(pendiente.valoracion == "Todo bien; sobró pan" and pendiente.menu_completado is not None,
              "Al completar se guardan la valoración y la copia del menú")


@prueba("Completar servicio eligiendo lotes")
def prueba_completar_lotes(at: AppTest) -> None:
    from recetario import Receta, Menu

    inv = at.session_state["inventario"]
    rec = at.session_state["recetario"]
    serv = at.session_state["registro_servicios"]
    brasa = Receta("Secreto a la brasa", "Principales", {"Secreto ibérico": 0.2})
    rec.agregar_receta(brasa)
    rec.agregar_menu(Menu("Menú brasa", [brasa]))
    servicio = Servicio(date.today(), time(21, 0), 4, "Menú brasa")  # 0,8 kg; hay 0,5 + 0,5
    serv.agregar_servicio(servicio)

    ir_a(at, "Servicios")
    at.selectbox(key="completar_select").select(
        f"#{servicio.id} - {servicio.fecha.strftime('%d/%m/%Y')} - {servicio.menu}"
    ).run()
    base = f"completar_lote_{servicio.id}_Secreto ibérico"
    primero = at.selectbox(key=f"{base}_0")
    primero.select(opcion(primero, "Lote 3 ·")).run()
    complemento = at.selectbox(key=f"{base}_1")
    comprobar(complemento.value is None and len(complemento.options) == 1 and complemento.options[0].startswith("Lote 2 ·"),
              "Si el lote elegido no llega, pide elegir con qué lote completar (sin elegirlo por ti)")

    boton(at.button, "Completar servicio").click().run()
    secreto = inv.buscar_producto("Secreto ibérico")
    comprobar(servicio.estado != "completado" and secreto.stock == 1 and len(at.error) > 0,
              "Sin elegir el lote de complemento no se completa (error visible, nada cambia)")

    complemento = at.selectbox(key=f"{base}_1")
    complemento.select(opcion(complemento, "Lote 2 ·")).run()

    # Costes adicionales no previstos: se añaden dos y se quita uno
    clave = f"extras_{servicio.id}"
    for concepto, importe in (("Hielo de última hora", 12.0), ("Error", 3.0)):
        v = at.session_state[f"{clave}_version"]
        at.text_input(key=f"{clave}_concepto_{v}").input(concepto)
        at.number_input(key=f"{clave}_importe_{v}").set_value(importe)
        at.button(key=f"{clave}_anadir_{v}").click().run()
    at.button(key=f"{clave}_quitar_1").click().run()

    # Compra no prevista de un producto: 1 kg de tomate por 3 €, se usa 0,4
    v = at.session_state[f"{clave}_version"]
    at.checkbox(key=f"{clave}_es_producto_{v}").check().run()
    at.selectbox(key=f"{clave}_producto_{v}").select("Tomate").run()
    at.number_input(key=f"{clave}_comprada_{v}").set_value(1.0)
    at.number_input(key=f"{clave}_usada_{v}").set_value(0.4)
    at.number_input(key=f"{clave}_importe_{v}").set_value(3.0)
    at.text_input(key=f"{clave}_proveedor_{v}").input("Mercado central")
    at.button(key=f"{clave}_anadir_{v}").click().run()
    tomate = at.session_state["inventario"].buscar_producto("Tomate")
    stock_tomate = tomate.stock

    # Compra no prevista de un producto NUEVO: se da de alta con sus datos
    def producto_nuevo(nombre: str) -> None:
        v = at.session_state[f"{clave}_version"]
        at.checkbox(key=f"{clave}_es_producto_{v}").check().run()
        at.radio(key=f"{clave}_es_nuevo_{v}").set_value("Uno nuevo (darlo de alta)").run()
        at.text_input(key=f"{clave}_nuevo_nombre_{v}").input(nombre)
        at.text_input(key=f"{clave}_nuevo_categoria_{v}").input("Verduras")
        at.selectbox(key=f"{clave}_nuevo_unidad_{v}").select("kg")
        at.number_input(key=f"{clave}_nuevo_stock_minimo_{v}").set_value(1.0)
        at.text_input(key=f"{clave}_nuevo_proveedor_{v}").input("Huerta Local").run()
        at.number_input(key=f"{clave}_comprada_{v}").set_value(2.0)
        at.number_input(key=f"{clave}_usada_{v}").set_value(1.5)
        at.number_input(key=f"{clave}_importe_{v}").set_value(3.0)
        at.button(key=f"{clave}_anadir_{v}").click().run()

    producto_nuevo("Tomate")
    comprobar(any("Ya existe" in t for t in textos(at.error)), "Un producto nuevo no puede llamarse como uno que ya existe")
    producto_nuevo("Cebolla")
    comprobar("Cebolla" not in at.session_state["inventario"].productos,
              "El producto nuevo no se da de alta hasta completar el servicio")
    comprobar([e["concepto"] for e in at.session_state[clave]]
              == ["Hielo de última hora", "Tomate (compra no prevista)", "Cebolla (compra no prevista)"],
              "Se pueden añadir y quitar costes adicionales antes de completar")
    gastos = at.session_state["registro_gastos"]
    comprobar(not gastos.gastos, "...y no se guardan hasta completar el servicio")

    boton(at.button, "Completar servicio").click().run()
    comprobar(sin_excepciones(at, "completar con lotes") and servicio.estado == "completado"
              and secreto.buscar_lote(3) is None and abs(secreto.buscar_lote(2).cantidad - 0.2) < 1e-9,
              "Completa: 0,5 kg del lote 3 y los 0,3 que faltan del lote 2")
    comprobar(len(gastos.gastos) == 1 and gastos.gastos[0].servicio_id == servicio.id
              and gastos.gastos[0].importe == 12 and gastos.gastos[0].categoria == "Otros",
              "Al completar, el coste adicional se guarda como gasto del servicio")
    nuevo_lote = tomate.lotes[-1]
    comprobar(abs(tomate.stock - (stock_tomate + 0.6)) < 1e-9 and nuevo_lote.proveedor == "Mercado central"
              and nuevo_lote.precio_unitario == 3 and abs(nuevo_lote.cantidad - 0.6) < 1e-9,
              "La compra de tomate entra como lote y los 0,6 kg que sobran se quedan en el inventario")
    hist = at.session_state["inventario"].historial
    ultimo = next(m for m in reversed(hist) if m.producto_nombre == "Tomate")
    comprobar(ultimo.motivo == "consumo" and ultimo.servicio_id == servicio.id and abs(ultimo.cantidad - 0.4) < 1e-9,
              "Lo usado sale como consumo de ese servicio")
    cebolla = at.session_state["inventario"].buscar_producto("Cebolla")
    comprobar(cebolla is not None and cebolla.categoria == "Verduras" and cebolla.stock_minimo == 1
              and cebolla.proveedor == "Huerta Local" and abs(cebolla.stock - 0.5) < 1e-9
              and cebolla.lotes[0].precio_unitario == 1.5,
              "Al completar se da de alta 'Cebolla' con sus datos, entra la compra (2 kg a 1,5 €/kg) y sobran 0,5 kg")


@prueba("Precio de cobro, gastos y rentabilidad")
def prueba_gastos(at: AppTest) -> None:
    serv = at.session_state["registro_servicios"]
    gastos = at.session_state["registro_gastos"]
    antes = len(gastos.gastos)  # el coste adicional de la prueba anterior

    # Añadir un servicio con precio POR COMENSAL (25 € x 10 = 250 €)
    ir_a(at, "Servicios")
    por_etiqueta(at.number_input, "Comensales").set_value(10)
    por_etiqueta(at.selectbox, "Menú").select("Menú del día")
    por_etiqueta(at.number_input, "Precio de cobro (€, sin IVA, opcional)").set_value(25.0)
    por_etiqueta(at.radio, "El precio es").set_value("Por comensal")
    por_etiqueta(at.text_input, "Cliente (opcional)").input("Familia García")
    por_etiqueta(at.text_input, "Lugar (opcional)").input("Finca Los Olivos")
    boton(at.button, "Añadir servicio").click().run()
    nuevo = serv.servicios[-1]
    comprobar(sin_excepciones(at, "añadir servicio con precio") and nuevo.comensales == 10 and nuevo.precio_cobrado == 250,
              f"Servicio con precio por comensal: se guarda el total (250 €, hay {nuevo.precio_cobrado})")
    comprobar(nuevo.cliente == "Familia García" and nuevo.lugar == "Finca Los Olivos", "Se guardan el cliente y el lugar")

    # Sin precio: es opcional (en la app el formulario se vacía solo; el
    # simulador de pruebas conserva lo escrito, así que se pone a 0 a mano)
    por_etiqueta(at.number_input, "Precio de cobro (€, sin IVA, opcional)").set_value(0.0)
    por_etiqueta(at.text_input, "Cliente (opcional)").input("")
    por_etiqueta(at.text_input, "Lugar (opcional)").input("")
    por_etiqueta(at.number_input, "Comensales").set_value(4)
    por_etiqueta(at.selectbox, "Menú").select("Menú del día")
    boton(at.button, "Añadir servicio").click().run()
    comprobar(serv.servicios[-1].precio_cobrado is None, "El precio de cobro es opcional")

    # Registrar dos gastos: uno del servicio y uno general
    ir_a(at, "Gastos")
    for concepto, categoria, importe, del_servicio in (
        ("Gasolina", "Transporte", 30.0, True), ("Seguro furgoneta", "Seguros e impuestos", 60.0, False),
    ):
        v = at.session_state["gasto_version"]
        at.text_input(key=f"gasto_concepto_{v}").input(concepto)
        at.selectbox(key=f"gasto_categoria_{v}").select(categoria)
        at.number_input(key=f"gasto_importe_{v}").set_value(importe)
        if del_servicio:
            sb = at.selectbox(key=f"gasto_servicio_{v}")
            sb.select(opcion(sb, f"#{nuevo.id} -"))
        at.button(key=f"gasto_boton_{v}").click().run()
    comprobar(sin_excepciones(at, "registrar gastos") and len(gastos.gastos) == antes + 2
              and gastos.gastos[-2].servicio_id == nuevo.id and gastos.gastos[-1].servicio_id is None,
              "Se registran un gasto del servicio y uno general")

    # Un gasto mal puesto se puede eliminar
    v = at.session_state["gasto_version"]
    at.text_input(key=f"gasto_concepto_{v}").input("Error")
    at.number_input(key=f"gasto_importe_{v}").set_value(5.0)
    at.button(key=f"gasto_boton_{v}").click().run()
    sb = at.selectbox(key="gasto_eliminar_select")
    sb.select(opcion(sb, f"#{gastos.gastos[-1].id} -"))
    at.button(key="gasto_eliminar_boton").click().run()
    comprobar(len(gastos.gastos) == antes + 2 and all(g.concepto != "Error" for g in gastos.gastos), "Eliminar un gasto")

    # Rentabilidad: coste con el gasto del servicio y margen; cambiar el precio
    ir_a(at, "Servicios")
    sb = at.selectbox(key="rentabilidad_select")
    sb.select(opcion(sb, f"#{nuevo.id} -")).run()
    comprobar(sin_excepciones(at, "rentabilidad") and not at.error, "La pestaña de rentabilidad se muestra sin errores")
    at.number_input(key=f"cobro_precio_{nuevo.id}").set_value(300.0)
    at.button(key=f"cobro_guardar_{nuevo.id}").click().run()
    comprobar(nuevo.precio_cobrado == 300, "Se puede cambiar el precio de cobro después")


@prueba("Fase 1: servicios, recetas y guardado")
def prueba_fase1(at: AppTest) -> None:
    import os
    serv = at.session_state["registro_servicios"]
    rec = at.session_state["recetario"]
    inv = at.session_state["inventario"]

    # Cancelar: solo pendientes, y hay que confirmarlo
    from servicios import Servicio as _Servicio
    pendiente = _Servicio(date.today() + timedelta(days=9), time(20, 0), 6, "Menú del día", cliente="Para cancelar")
    serv.agregar_servicio(pendiente)
    ir_a(at, "Servicios")
    caja = at.selectbox(key="cancelar_select")
    completados = [s for s in serv.servicios if s.estado == "completado"]
    comprobar(completados and not any(o.startswith(f"#{s.id} ·") for o in caja.options for s in completados),
              "Los servicios completados no aparecen para cancelar")
    caja.select(opcion(caja, f"#{pendiente.id} ·")).run()
    comprobar(boton(at.button, "Cancelar servicio").disabled and pendiente.estado == "pendiente",
              "Sin marcar la confirmación el botón de cancelar no se puede pulsar")
    at.checkbox(key="cancelar_confirmar").check().run()
    boton(at.button, "Cancelar servicio").click().run()
    comprobar(pendiente.estado == "cancelado", "Marcando la confirmación, se cancela")

    # Un servicio con un menú que no existe: aviso y forma de arreglarlo
    malo = _Servicio(date.today() + timedelta(days=4), time(13, 0), 12, "Menu del dia")
    serv.agregar_servicio(malo)
    ir_a(at, "Servicios")
    comprobar(any("no existe" in t and f"#{malo.id}" in t for t in textos(at.warning)),
              "Se avisa de un servicio con un menú que no existe")
    at.selectbox(key=f"arreglar_menu_{malo.id}").select("Menú del día").run()
    at.button(key=f"arreglar_menu_boton_{malo.id}").click().run()
    comprobar(malo.menu == "Menú del día", "Se le puede elegir el menú correcto")

    # Receta con un nombre que ya existe: error y lo escrito no se borra
    ir_a(at, "Recetario")
    at.session_state["receta_ingredientes"] = {"Tomate": 0.1}
    at.run()
    por_etiqueta(at.text_input, "Nombre de la receta").input("Pan casero")
    boton(at.button, "Guardar receta").click().run()
    comprobar(any("Ya existe" in t for t in textos(at.error)) and len(rec.recetas["Pan casero"].ingredientes_por_comensal) == 2
              and por_etiqueta(at.text_input, "Nombre de la receta").value == "Pan casero",
              "Una receta con un nombre que ya existe no sustituye a la otra, y lo escrito no se borra")
    at.session_state["receta_ingredientes"] = {}

    # La unidad propuesta es la del producto
    from inventario import Producto
    inv.agregar_producto(Producto("Azafrán", "Especias", 50, "g", 3, "Especias SA"))
    at.run()
    at.selectbox(key="ing_select").select("Azafrán").run()
    comprobar(at.radio(key="unidad_ing_Azafrán").value == "g", "Para un ingrediente en gramos se propone 'g' (no 'kg')")

    # Otra ventana del programa guarda: esta deja de guardar y avisa
    ruta = RAIZ / "datos" / "sesion.json"
    os.utime(ruta, (ruta.stat().st_atime, ruta.stat().st_mtime + 100))  # "otra ventana" lo acaba de guardar
    antes = ruta.read_text(encoding="utf-8")
    inv.agregar_producto(Producto("Orégano", "Especias", 1, "kg", 9, "Especias SA"))
    at.run()
    comprobar(ruta.read_text(encoding="utf-8") == antes and any("otra ventana" in t for t in textos(at.sidebar.error)),
              "Si otra ventana guardó, esta no sobrescribe sin preguntar y lo avisa")
    at.button(key="conflicto_guardar").click().run()
    at.run()
    comprobar("Orégano" in ruta.read_text(encoding="utf-8"), "...y se puede elegir guardar lo de esta ventana")


@prueba("Material reutilizable")
def prueba_material(at: AppTest) -> None:
    reg = at.session_state["registro_material"]
    serv = at.session_state["registro_servicios"]

    # Inventario > Material: añadir uno nuevo
    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🍽️ Material").run()
    comprobar(sin_excepciones(at, "lista de material"), "La lista de material se muestra sin errores")
    v = at.session_state["mat_version"]
    at.text_input(key=f"mat_add_nombre_{v}").input("Cuchillo")
    at.text_input(key=f"mat_add_categoria_{v}").input("Cubertería")
    at.number_input(key=f"mat_add_cantidad_{v}").set_value(40)
    at.number_input(key=f"mat_add_precio_{v}").set_value(1.5)
    at.button(key=f"mat_add_boton_{v}").click().run()
    comprobar(reg.buscar("Cuchillo") is not None and reg.buscar("Cuchillo").cantidad_total == 40, "Añadir material")

    # Servicios > Material: salida con la lista de carga que propone el menú
    servicio = next(s for s in serv.servicios if s.precio_cobrado == 300)  # el de 10 comensales (prueba de gastos)
    ir_a(at, "Servicios")
    sb = at.selectbox(key="material_servicio_select")
    sb.select(opcion(sb, f"#{servicio.id} -")).run()
    comprobar(at.number_input(key=f"carga_{servicio.id}_Plato llano").value == 20,
              "La lista de carga propone el material del menú (2 platos x 10 comensales = 20)")
    at.button(key=f"salida_boton_{servicio.id}").click().run()
    comprobar(sin_excepciones(at, "salida de material") and reg.en_uso("Plato llano") == 20
              and reg.disponibles("Plato llano") == 40 and reg.buscar("Plato llano").cantidad_total == 60,
              "Tras la salida, los platos siguen existiendo (60) pero solo 40 están disponibles")

    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🍽️ Material").run()
    comprobar(any("Fuera" in t for t in textos(at.warning)), "El inventario de material avisa de lo que está fuera")

    # Vuelta: 18 platos de 20 (1 roto, 1 perdido); el resto vuelve entero
    ir_a(at, "Servicios")
    sb = at.selectbox(key="material_servicio_select")
    sb.select(opcion(sb, f"#{servicio.id} -")).run()
    at.number_input(key=f"vuelta_{servicio.id}_Plato llano").set_value(18).run()
    at.number_input(key=f"rotos_{servicio.id}_Plato llano_2").set_value(1)
    at.button(key=f"vuelta_boton_{servicio.id}").click().run()
    comprobar(sin_excepciones(at, "vuelta de material") and reg.en_uso("Plato llano") == 0
              and reg.buscar("Plato llano").cantidad_total == 58
              and sorted(i.tipo for i in reg.incidencias) == ["pérdida", "rotura"],
              "Vuelta: todo deja de estar en uso y los 2 platos que faltan se apuntan (1 rotura y 1 pérdida)")
    comprobar(reg.coste_incidencias_servicio(servicio.id) == 7.0, "Las roturas y pérdidas cuestan 2 x 3,5 € = 7 €")

    # Material por comensal del menú, en su detalle
    ir_a(at, "Recetario")
    menu = at.session_state["recetario"].menus["Menú del día"]
    at.number_input(key="menu_Menú del día_mat_Plato llano").set_value(1.0)
    at.button(key="menu_Menú del día_guardar_material").click().run()
    comprobar(sin_excepciones(at, "material del menú") and menu.materiales_por_comensal.get("Plato llano") == 1,
              "En el detalle del menú se cambia su material")


@prueba("Compras")
def prueba_compras(at: AppTest) -> None:
    from recetario import Receta, Menu

    inv = at.session_state["inventario"]
    rec = at.session_state["recetario"]
    cerdo = Receta("Cerdo asado", "Principales", {"Carne de cerdo limpia": 0.3})
    rec.agregar_receta(cerdo)
    rec.agregar_menu(Menu("Menú cerdo", [cerdo]))
    at.session_state["registro_servicios"].agregar_servicio(
        Servicio(date.today() + timedelta(days=2), time(14, 0), 100, "Menú cerdo")
    )

    ir_a(at, "Compras")
    boton(at.button, "Generar lista de compra").click().run()
    comp = at.session_state["gestor_compras"]
    item = next((i for i in comp.items_pendientes() if i.ingrediente == "Pata de cerdo"), None)
    comprobar(item is not None and item.unidad == "unidades" and float(item.cantidad).is_integer(),
              f"La lista pide patas enteras ({item.cantidad if item else '-'} unidades)")
    comprobar(any("salen de limpiar" in t for t in textos(at.info)), "Aviso de la conversión limpio -> bruto visible")

    if item is not None:
        pedidas = item.cantidad
        stock_antes = inv.buscar_producto("Pata de cerdo").stock
        at.selectbox(key="marcar_comprado_select").select("Pata de cerdo").run()
        at.selectbox(key="compra_peso_Pata de cerdo_unidad").select("kg").run()
        at.number_input(key="compra_peso_Pata de cerdo_kg").set_value(7.0)
        at.number_input(key="compra_precio_Pata de cerdo").set_value(45.0)
        boton(at.button, "Marcar como comprado y reponer inventario").click().run()
        comprobar(inv.buscar_producto("Pata de cerdo").stock == stock_antes + pedidas,
                  "Marcar como comprado repone las patas en el inventario")

    # Una compra registrada desde el INVENTARIO de algo pendiente en la lista
    pendiente = next((i for i in comp.items_pendientes() if inv.buscar_producto(i.ingrediente)
                      and inv.buscar_producto(i.ingrediente).unidad == "kg"), None)
    comprobar(pendiente is not None, "Hay algún producto pendiente en la lista para probar")
    if pendiente is not None:
        nombre = pendiente.ingrediente
        ir_a(at, "Inventario")
        at.selectbox(key="stock_select").select(nombre).run()
        at.radio(key=f"stock_tipo_{nombre}").set_value("Entrada (compra)").run()
        comprobar(any("pendiente en la lista" in t for t in textos(at.info))
                  and at.checkbox(key=f"stock_marcar_lista_{nombre}").value is True,
                  "Al comprar desde el inventario, avisa de que está en la lista y propone marcarlo")
        at.number_input(key=f"stock_cantidad_{nombre}").set_value(10.0)
        at.number_input(key=f"stock_precio_{nombre}").set_value(2.0)
        at.button(key=f"stock_boton_{nombre}").click().run()
        comprobar(comp.pendiente_de(nombre) is None and any(i.ingrediente == nombre and i.comprado for i in comp.items),
                  f"'{nombre}' queda marcado como comprado en la lista")


@prueba("Lotes caducados al preparar (Fase 2, bloque 2)")
def prueba_caducados(at: AppTest) -> None:
    from inventario import Producto
    from recetario import Receta

    inv = at.session_state["inventario"]
    rec = at.session_state["recetario"]
    hoy = date.today()
    inv.agregar_producto(Producto("Nata para montar", "Lácteos", 1, "litros", 2, "Granja",
                                  fecha_caducidad=hoy - timedelta(days=2)))
    caducado = inv.buscar_producto("Nata para montar").lotes[0].id
    bueno = inv.entrada_stock("Nata para montar", 2, precio_unitario=2, fecha_caducidad=hoy + timedelta(days=5)).id
    rec.agregar_receta(Receta("Crema montada", "Postres", {"Nata para montar": 0.1}))

    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🥘 Elaboraciones").run()
    at.radio(key="elab_que").set_value("Un plato (raciones)").run()
    v = at.session_state["elab_version"]
    at.selectbox(key=f"elab_receta_{v}").select("Crema montada").run()
    at.number_input(key=f"elab_raciones_Crema montada_{v}").set_value(5.0).run()
    lote = at.selectbox(key=f"elab_lote_Crema montada_{v}_Nata para montar_0")
    comprobar(sin_excepciones(at, "preparar con un lote caducado") and str(lote.value).startswith(f"Lote {bueno} ·")
              and "CADUCADO" in lote.options[-1] and not any("CADUCADO" in t for t in textos(at.error)),
              "Al preparar se propone el lote bueno (no el caducado, que va al final y marcado)")
    lote.select(opcion(lote, f"Lote {caducado} ·")).run()
    comprobar(any("CADUCADO" in t and "Nata para montar" in t for t in textos(at.error)),
              "Si se elige el lote caducado, se avisa en rojo antes de preparar")
    inv.desechar_lote("Nata para montar", caducado)  # para no dejar avisos de caducados en el resto de pruebas


@prueba("Corregir y anular compras (Fase 2, bloque 3)")
def prueba_corregir_compras(at: AppTest) -> None:
    inv = at.session_state["inventario"]
    nombre = "Nata para montar"
    lote = inv.entrada_stock(nombre, 50, precio_unitario=2, fecha_caducidad=date.today() + timedelta(days=5))  # eran 5

    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🍅 Alimentos").run()
    at.selectbox(key="editar_select").select(nombre).run()
    caja = at.selectbox(key=f"edit_lote_{nombre}")
    caja.select(opcion(caja, f"Lote {lote.id} ·")).run()
    por_clave(at.number_input, f"edit_lote_cantidad_{nombre}_{lote.id}_").set_value(5.0).run()
    motivo = por_clave(at.radio, f"edit_lote_motivo_cantidad_{nombre}_{lote.id}_")
    motivo.set_value(next(o for o in motivo.options if o.startswith("Fue un error"))).run()
    comprobar(any("pasará de 50 a 5" in t for t in textos(at.caption)),
              "Al cambiar la cantidad se pregunta si es un recuento o un error en la compra (y se explica qué cambia)")
    at.button(key=f"edit_boton_{nombre}").click().run()
    compra = next(c for c in inv.precios_de(nombre) if c.lote_id == lote.id)
    movimiento = next(m for m in inv.historial if m.producto_nombre == nombre and m.lote_id == lote.id and m.es_compra())
    comprobar(sin_excepciones(at, "corregir cantidad de compra") and lote.cantidad == 5 and compra.cantidad == 5
              and movimiento.cantidad == 5,
              "'Error en la compra': se corrigen el lote, la compra (Métricas e IVA) y el historial de precios")

    at.selectbox(key="precios_select").select(nombre).run()
    caja = at.selectbox(key=f"corregir_compra_{nombre}")
    caja.select(next(o for o in caja.options if o.endswith(f"lote {lote.id}"))).run()
    boton_anular = por_clave(at.button, f"corregir_compra_anular_{nombre}_{lote.id}_")
    comprobar(boton_anular.disabled, "Anular una compra pide confirmarlo antes")
    por_clave(at.checkbox, f"corregir_compra_anular_confirmar_{nombre}_{lote.id}_").check().run()
    por_clave(at.button, f"corregir_compra_anular_{nombre}_{lote.id}_").click().run()
    comprobar(sin_excepciones(at, "anular compra") and inv.buscar_producto(nombre).buscar_lote(lote.id) is None
              and not any(c.lote_id == lote.id for c in inv.precios_de(nombre))
              and not any(m.producto_nombre == nombre and m.lote_id == lote.id for m in inv.historial),
              "Anular una compra quita su lote, su gasto y su línea del historial de precios")


@prueba("Historial de servicios")
def prueba_historial(at: AppTest) -> None:
    serv = at.session_state["registro_servicios"]
    ir_a(at, "Historial")
    comprobar(sin_excepciones(at, "historial") and not at.error, "La página de historial se muestra sin errores")
    completados = [s for s in serv.servicios if s.estado == "completado"]
    filas = at.dataframe[0].value
    comprobar(len(filas) == len(completados), f"Lista los {len(completados)} servicios completados")

    primero = next(s for s in completados if s.menu == "Menú del día")
    sb = at.selectbox(key="hist_ficha")
    sb.select(opcion(sb, f"#{primero.id} -")).run()
    comprobar(sin_excepciones(at, "ficha del servicio"), "La ficha del servicio se muestra sin errores")
    comprobar(any("Todo bien" in str(t.value) for t in at.text_area), "La ficha muestra la valoración")

    at.text_input(key=f"hist_cliente_{primero.id}").input("Bodega Ruiz")
    at.button(key=f"hist_guardar_{primero.id}").click().run()
    comprobar(primero.cliente == "Bodega Ruiz", "Desde la ficha se puede poner o cambiar el cliente")

    at.selectbox(key="hist_cliente").select("Bodega Ruiz").run()
    comprobar(len(at.dataframe[0].value) == 1, "Filtrar el historial por cliente")

    antes = len(serv.servicios)
    sb = at.selectbox(key="hist_ficha")
    sb.select(opcion(sb, f"#{primero.id} -")).run()
    at.date_input(key=f"hist_repetir_fecha_{primero.id}").set_value(date.today() + timedelta(days=40))
    at.button(key=f"hist_repetir_{primero.id}").click().run()
    nuevo = serv.servicios[-1]
    comprobar(len(serv.servicios) == antes + 1 and nuevo.estado == "pendiente" and nuevo.menu == primero.menu
              and nuevo.cliente == "Bodega Ruiz" and nuevo.comensales == primero.comensales,
              "Repetir un servicio crea uno nuevo pendiente con los mismos datos")


@prueba("Métricas y guardado")
def prueba_metricas_y_guardado(at: AppTest) -> None:
    ir_a(at, "Métricas")
    comprobar(sin_excepciones(at, "Métricas") and not at.error, "Página de métricas (con la pestaña de merma) sin errores")
    ir_a(at, "Dashboard")
    comprobar(sin_excepciones(at, "Dashboard") and not at.error, "Dashboard con todos los datos sin errores")

    ruta = RAIZ / "datos" / "sesion.json"
    comprobar(ruta.exists() and "Cuchillo" in ruta.read_text(encoding="utf-8"),
              "Todo lo hecho ya está guardado en datos/sesion.json, sin pulsar ningún botón")

    # Una app NUEVA (como al volver a abrir el programa) carga la sesión guardada
    at2 = nueva_app()
    inv2 = at2.session_state["inventario"]
    comprobar(sin_excepciones(at2, "la carga de la sesión") and len(inv2.limpiezas) == 1
              and "Carne de cerdo limpia" in inv2.productos,
              "Al reabrir, se carga la sesión con la limpieza y el producto limpio")
    comprobar(len(at2.session_state["registro_gastos"].gastos) == 3, "Al reabrir, se cargan también los gastos")
    comprobar(at2.session_state["registro_material"].buscar("Cuchillo") is not None
              and len(at2.session_state["registro_material"].incidencias) == 2,
              "Al reabrir, se carga también el material con sus roturas")


@prueba("Gastos, completar y material (Fase 2, bloque 4)")
def prueba_bloque4(at: AppTest) -> None:
    serv = at.session_state["registro_servicios"]
    gastos = at.session_state["registro_gastos"]
    reg = at.session_state["registro_material"]

    # Gasto con IVA y gasto con fecha futura
    ir_a(at, "Gastos")
    v = at.session_state["gasto_version"]
    at.text_input(key=f"gasto_concepto_{v}").input("Alquiler de carpa")
    at.selectbox(key=f"gasto_categoria_{v}").select("Alquiler de material").run()
    at.number_input(key=f"gasto_importe_{v}").set_value(121.0).run()
    comprobar(any("100.00 € sin IVA" in t and "21.00 € de IVA" in t for t in textos(at.caption)),
              "Al apuntar un gasto se ve su desglose de IVA (121 € = 100 € + 21 €)")
    at.date_input(key=f"gasto_fecha_{v}").set_value(date.today() + timedelta(days=10))
    at.button(key=f"gasto_boton_{v}").click().run()
    gasto = gastos.gastos[-1]
    comprobar(sin_excepciones(at, "gasto con IVA") and gasto.iva == 21 and abs(gasto.cuota_iva - 21) < 1e-9,
              "El gasto se guarda con su IVA (21 %)")
    comprobar(any("📅" in str(f) for f in at.dataframe[0].value["Fecha"]),
              "Un gasto con fecha futura aparece en la lista, marcado como futuro")

    # Completar con un coste adicional escrito pero sin añadir
    servicio = Servicio(date.today(), time(13, 0), 2, "Menú brasa")  # un solo lote: sin elegir lotes
    serv.agregar_servicio(servicio)
    ir_a(at, "Servicios")
    at.selectbox(key="completar_select").select(
        f"#{servicio.id} - {servicio.fecha.strftime('%d/%m/%Y')} - {servicio.menu}"
    ).run()
    v = at.session_state[f"extras_{servicio.id}_version"]
    at.text_input(key=f"extras_{servicio.id}_concepto_{v}").input("Taxi").run()
    boton(at.button, "Completar servicio").click().run()
    comprobar(servicio.estado != "completado" and any("sin añadir" in t for t in textos(at.error)),
              "Con un coste adicional escrito sin añadir, no se completa (y se avisa)")
    at.text_input(key=f"extras_{servicio.id}_concepto_{v}").input("").run()
    boton(at.button, "Completar servicio").click().run()
    comprobar(sin_excepciones(at, "completar sin coste pendiente") and servicio.estado == "completado",
              "Sin nada pendiente, se completa")

    # Material de un servicio cancelado
    cancelado = Servicio(date.today() + timedelta(days=3), time(13, 0), 2, "Menú del día")
    serv.agregar_servicio(cancelado)
    reg.registrar_salida(cancelado.id, {"Cuchillo": 2})
    serv.cancelar_servicio(cancelado.id)
    ir_a(at, "Servicios")
    sb = at.selectbox(key="material_servicio_select")
    sb.select(opcion(sb, f"#{cancelado.id} -")).run()
    comprobar("cancelado" in sb.value, "Un servicio cancelado con material fuera aparece para registrar su vuelta")
    at.button(key=f"vuelta_boton_{cancelado.id}").click().run()
    comprobar(sin_excepciones(at, "vuelta de servicio cancelado") and reg.salida_de(cancelado.id) is None,
              "Se registra la vuelta del material de un servicio cancelado (deja de estar 'en uso')")


@prueba("Editar y borrar servicios, recetas y menús (Fase 3, bloque 1)")
def prueba_fase3_bloque1(at: AppTest) -> None:
    from recetario import Menu

    serv = at.session_state["registro_servicios"]
    rec = at.session_state["recetario"]

    servicio = Servicio(date.today() + timedelta(days=5), time(20, 0), 6, "Menú del día")
    serv.agregar_servicio(servicio)
    ir_a(at, "Servicios")
    sb = at.selectbox(key="editar_servicio_select")
    sb.select(opcion(sb, f"#{servicio.id} ·")).run()
    por_clave(at.number_input, f"editar_servicio_comensales_{servicio.id}_").set_value(9)
    por_clave(at.checkbox, f"editar_servicio_confirmado_{servicio.id}_").check().run()
    por_clave(at.button, f"editar_servicio_guardar_{servicio.id}_").click().run()
    comprobar(sin_excepciones(at, "editar servicio") and servicio.comensales == 9 and servicio.estado == "confirmado",
              "Editar un servicio pendiente: comensales (6 -> 9) y marcarlo como confirmado")

    ir_a(at, "Recetario")
    at.selectbox(key="editar_receta_select").select("Crema montada").run()
    por_clave(at.number_input, "editar_receta_ing_Nata para montar_Crema montada_").set_value(0.2).run()
    por_clave(at.button, "editar_receta_guardar_Crema montada_").click().run()
    comprobar(sin_excepciones(at, "editar receta") and rec.recetas["Crema montada"].ingredientes_por_comensal
              == {"Nata para montar": 0.2}, "Editar la cantidad de un ingrediente de una receta")
    por_clave(at.checkbox, "editar_receta_borrar_confirmar_Crema montada_").check().run()
    por_clave(at.button, "editar_receta_borrar_Crema montada_").click().run()
    comprobar(sin_excepciones(at, "borrar receta") and "Crema montada" not in rec.recetas,
              "Borrar una receta que no está en ningún menú")
    at.selectbox(key="editar_receta_select").select("Pan casero").run()
    comprobar(any("No se puede borrar" in t for t in textos(at.caption)),
              "Una receta que está en un menú no se puede borrar (y dice en cuál)")

    rec.agregar_menu(Menu("Menú prueba", [rec.recetas["Pan casero"]]))
    ir_a(at, "Recetario")
    por_clave(at.multiselect, "menu_Menú prueba_recetas_").set_value(["Pan casero", "Ensalada de tomate"]).run()
    at.button(key="menu_Menú prueba_guardar_recetas").click().run()
    comprobar(sin_excepciones(at, "recetas del menú")
              and [r.nombre for r in rec.menus["Menú prueba"].recetas] == ["Pan casero", "Ensalada de tomate"],
              "Cambiar las recetas de un menú")
    comprobar(any("No se puede borrar" in t and "#" in t for t in textos(at.caption)),
              "Un menú que usa un servicio pendiente no se puede borrar (y dice cuál)")
    at.checkbox(key="menu_Menú prueba_borrar_confirmar").check().run()
    at.button(key="menu_Menú prueba_borrar").click().run()
    comprobar(sin_excepciones(at, "borrar menú") and "Menú prueba" not in rec.menus, "Borrar un menú que no se usa")


@prueba("Borrar productos y material, y empezar de cero (Fase 3, bloque 2)")
def prueba_fase3_bloque2(at: AppTest) -> None:
    import os
    import tempfile
    from materiales import Material

    inv = at.session_state["inventario"]
    reg = at.session_state["registro_material"]

    ir_a(at, "Inventario")
    at.radio(key="inv_tipo").set_value("🍅 Alimentos").run()
    at.selectbox(key="editar_select").select("Harina de trigo").run()
    comprobar(any("No se puede borrar" in t and "Pan casero" in t for t in textos(at.caption)),
              "Un producto que usa una receta no se puede borrar (y dice cuál)")
    at.selectbox(key="editar_select").select("Huevos camperos").run()
    at.checkbox(key="borrar_producto_confirmar_Huevos camperos").check().run()
    at.button(key="borrar_producto_Huevos camperos").click().run()
    comprobar(sin_excepciones(at, "borrar producto") and "Huevos camperos" not in inv.productos,
              "Borrar un producto que no se usa (con confirmación)")

    reg.agregar_material(Material("Bandeja", "Menaje", 5, 3.0, "Bazar"))
    at.radio(key="inv_tipo").set_value("🍽️ Material").run()
    at.selectbox(key="mat_editar_select").select("Bandeja").run()
    por_clave(at.checkbox, "mat_edit_borrar_confirmar_Bandeja_").check().run()
    por_clave(at.button, "mat_edit_borrar_Bandeja_").click().run()
    comprobar(sin_excepciones(at, "borrar material") and reg.buscar("Bandeja") is None, "Borrar un material (con confirmación)")

    # Empezar de cero, en una carpeta de datos aparte (la de las pruebas la usan las capturas)
    with tempfile.TemporaryDirectory() as carpeta:
        shutil.copy2(RAIZ / "datos" / "sesion.json", Path(carpeta) / "sesion.json")
        anterior = os.environ.get("GESTION_RESTAURANTE_DATOS")
        os.environ["GESTION_RESTAURANTE_DATOS"] = carpeta
        try:
            at2 = nueva_app()
            comprobar(bool(at2.session_state["inventario"].productos), "(La copia de los datos se abre con todo)")
            ir_a(at2, "Ajustes")
            comprobar(at2.button(key="cero_boton").disabled, "'Borrar todos los datos' está desactivado hasta escribir BORRAR")
            at2.text_input(key="cero_confirmar").input("BORRAR").run()
            at2.button(key="cero_boton").click().run()
            copias = list((Path(carpeta) / "copias").glob("antes_de_empezar_de_cero_*.json"))
            guardado = (Path(carpeta) / "sesion.json").read_text(encoding="utf-8")
            comprobar(sin_excepciones(at2, "empezar de cero") and not at2.session_state["inventario"].productos
                      and not at2.session_state["recetario"].recetas and not at2.session_state["registro_servicios"].servicios
                      and len(copias) == 1 and "Harina de trigo" in copias[0].read_text(encoding="utf-8")
                      and "Harina de trigo" not in guardado,
                      "Empezar de cero deja la app vacía (también en disco) y antes hace una copia con todo")
        finally:
            if anterior is None:
                os.environ.pop("GESTION_RESTAURANTE_DATOS", None)
            else:
                os.environ["GESTION_RESTAURANTE_DATOS"] = anterior


@prueba("Deshacer un servicio, restaurar una copia y cerrar (Fase 3, bloque 3)")
def prueba_fase3_bloque3(at: AppTest) -> None:
    serv = at.session_state["registro_servicios"]
    inv = at.session_state["inventario"]
    servicio = next(s for s in serv.servicios if s.menu == "Menú brasa" and s.estado == "completado" and s.comensales == 2)
    secreto = inv.buscar_producto("Secreto ibérico")
    antes = secreto.stock

    ir_a(at, "Historial")
    at.selectbox(key="hist_cliente").select("Todos").run()
    sb = at.selectbox(key="hist_ficha")
    sb.select(opcion(sb, f"#{servicio.id} -")).run()
    comprobar(at.button(key=f"deshacer_boton_{servicio.id}").disabled, "Deshacer un servicio pide confirmarlo")
    at.checkbox(key=f"deshacer_confirmar_{servicio.id}").check().run()
    at.button(key=f"deshacer_boton_{servicio.id}").click().run()
    comprobar(sin_excepciones(at, "deshacer servicio") and servicio.estado == "pendiente" and secreto.stock > antes,
              "Deshacer un servicio completado: vuelve a pendiente y lo usado vuelve al inventario")

    ir_a(at, "Exportar / Backup")
    sb = at.selectbox(key="restaurar_select")
    comprobar(any("Copia del día" in o for o in sb.options), "Se listan las copias de seguridad con su fecha y contenido")
    sb.select(next(o for o in sb.options if "Copia del día" in o)).run()
    at.checkbox(key="restaurar_confirmar").check().run()
    at.button(key="restaurar_boton").click().run()
    antes_de_restaurar = list((RAIZ / "datos" / "copias").glob("antes_de_restaurar_*.json"))
    comprobar(sin_excepciones(at, "restaurar copia") and at.session_state["inventario"].productos
              and len(antes_de_restaurar) == 1 and any("restaurada" in t for t in textos(at.success)),
              "Restaurar una copia: se cargan sus datos y antes se guarda una copia de lo que había")

    at.button(key="cerrar_programa").click().run()
    comprobar(any("Todo guardado" in t for t in textos(at.success)),
              "'Cerrar el programa' guarda y avisa (aquí no se apaga: no lo ha abierto el lanzador)")


# ---------------------------------------------------------------- ejecución

def main() -> int:
    # Empezamos siempre desde cero, sin sesiones de ejecuciones anteriores.
    shutil.rmtree(RAIZ / "datos", ignore_errors=True)
    registrar(f"Streamlit {streamlit.__version__} | Python {sys.version.split()[0]} | {date.today().isoformat()}")

    at = nueva_app()
    prueba_arranque(at)
    prueba_paginas(at)
    prueba_precios(at)
    prueba_anadir(at)
    prueba_stock(at)
    prueba_limpiar(at)
    prueba_editar(at)
    prueba_lotes(at)
    prueba_consumibles(at)
    prueba_elaboraciones(at)
    prueba_bases(at)
    prueba_notas(at)
    prueba_mantenimiento(at)
    prueba_completar(at)
    prueba_completar_lotes(at)
    prueba_gastos(at)
    prueba_fase1(at)
    prueba_material(at)
    prueba_compras(at)
    prueba_caducados(at)
    prueba_corregir_compras(at)
    prueba_historial(at)
    prueba_metricas_y_guardado(at)
    prueba_bloque4(at)
    prueba_fase3_bloque1(at)
    prueba_fase3_bloque2(at)
    prueba_fase3_bloque3(at)

    total = sum(1 for linea in lineas if linea.startswith(("✅", "❌")))
    registrar(f"\nRESULTADO: {total - len(fallos)}/{total} comprobaciones correctas")
    if fallos:
        registrar("FALLOS:\n" + "\n".join(f"  - {f}" for f in fallos))

    RESULTADOS.mkdir(exist_ok=True)
    (RESULTADOS / "resultado.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    # La sesión guardada se deja en datos/ a propósito: las capturas de
    # pantalla (pruebas/capturas.py) la cargan para mostrar la app con datos.
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
