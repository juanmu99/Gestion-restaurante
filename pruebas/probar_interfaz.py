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


@prueba("Todas las páginas se muestran")
def prueba_paginas(at: AppTest) -> None:
    for pagina in ["Dashboard", "Inventario", "Servicios", "Recetario", "Compras", "Métricas", "Exportar / Backup"]:
        ir_a(at, pagina)
        comprobar(sin_excepciones(at, pagina) and not at.error, f"Página '{pagina}' sin errores")


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
    at.checkbox(key="edit_merma_Tomate").check()
    at.button(key="edit_boton_Tomate").click().run()
    comprobar(inv.buscar_producto("Tomate").tiene_merma, "Editar: activar la merma de un producto")

    # Cambiar de producto en el desplegable rellena sus propios datos
    at.selectbox(key="editar_select").select("Aceite de oliva").run()
    comprobar(at.text_input(key="edit_nombre_Aceite de oliva").value == "Aceite de oliva",
              "Al cambiar de producto se cargan sus datos")


@prueba("Lotes: corregir y desechar")
def prueba_lotes(at: AppTest) -> None:
    ir_a(at, "Inventario")
    inv = at.session_state["inventario"]
    secreto = inv.buscar_producto("Secreto ibérico")

    # Corregir la caducidad del lote 1 a ayer: pasa a estar caducado
    at.selectbox(key="lotes_select").select("Secreto ibérico").run()
    lote_sb = at.selectbox(key="lotes_lote_Secreto ibérico")
    lote_sb.select(opcion(lote_sb, "Lote 1 ·")).run()
    at.date_input(key="lotes_fecha_Secreto ibérico_1").set_value(date.today() - timedelta(days=1))
    at.button(key="lotes_guardar_Secreto ibérico_1").click().run()
    comprobar(sin_excepciones(at, "corregir lote") and secreto.buscar_lote(1).esta_caducado(),
              "Corregir la caducidad de un lote")
    comprobar(any("Caducado" in t and "Secreto ibérico" in t for t in textos(at.error)),
              "El lote caducado se avisa en rojo arriba")

    # Desecharlo con el botón del aviso: sale todo como desperdicio
    at.button(key="desechar_Secreto ibérico_1").click().run()
    ultimo = inv.historial[-1]
    comprobar(secreto.buscar_lote(1) is None and ultimo.motivo == "desperdicio" and ultimo.lote_id == 1
              and ultimo.cantidad == 1, "'Desechar lote' lo tira entero y lo apunta como desperdicio")
    comprobar([l.id for l in secreto.lotes] == [2, 3], "Quedan los lotes 2 y 3")


@prueba("Completar servicio")
def prueba_completar(at: AppTest) -> None:
    ir_a(at, "Servicios")
    serv = at.session_state["registro_servicios"]
    pendiente = next(s for s in serv.servicios if s.estado == "pendiente")
    at.selectbox(key="completar_select").select(
        f"#{pendiente.id} - {pendiente.fecha.strftime('%d/%m/%Y')} - {pendiente.menu}"
    ).run()
    boton(at.button, "Completar servicio").click().run()
    comprobar(sin_excepciones(at, "completar servicio") and pendiente.estado == "completado",
              "Servicio completado desde la interfaz")


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
    boton(at.button, "Completar servicio").click().run()
    comprobar(sin_excepciones(at, "completar con lotes") and servicio.estado == "completado"
              and secreto.buscar_lote(3) is None and abs(secreto.buscar_lote(2).cantidad - 0.2) < 1e-9,
              "Completa: 0,5 kg del lote 3 y los 0,3 que faltan del lote 2")


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
        boton(at.button, "Marcar como comprado y reponer inventario").click().run()
        comprobar(inv.buscar_producto("Pata de cerdo").stock == stock_antes + pedidas,
                  "Marcar como comprado repone las patas en el inventario")


@prueba("Métricas y guardado")
def prueba_metricas_y_guardado(at: AppTest) -> None:
    ir_a(at, "Métricas")
    comprobar(sin_excepciones(at, "Métricas") and not at.error, "Página de métricas (con la pestaña de merma) sin errores")
    ir_a(at, "Dashboard")
    comprobar(sin_excepciones(at, "Dashboard") and not at.error, "Dashboard con todos los datos sin errores")

    boton(at.sidebar.button, "💾 Guardar sesión").click().run()
    ruta = RAIZ / "datos" / "sesion.json"
    comprobar(ruta.exists(), "Guardar sesión crea datos/sesion.json")

    # Una app NUEVA (como al volver a abrir el programa) carga la sesión guardada
    at2 = nueva_app()
    inv2 = at2.session_state["inventario"]
    comprobar(sin_excepciones(at2, "la carga de la sesión") and len(inv2.limpiezas) == 1
              and "Carne de cerdo limpia" in inv2.productos,
              "Al reabrir, se carga la sesión con la limpieza y el producto limpio")


# ---------------------------------------------------------------- ejecución

def main() -> int:
    # Empezamos siempre desde cero, sin sesiones de ejecuciones anteriores.
    shutil.rmtree(RAIZ / "datos", ignore_errors=True)
    registrar(f"Streamlit {streamlit.__version__} | Python {sys.version.split()[0]} | {date.today().isoformat()}")

    at = nueva_app()
    prueba_arranque(at)
    prueba_paginas(at)
    prueba_anadir(at)
    prueba_stock(at)
    prueba_limpiar(at)
    prueba_editar(at)
    prueba_lotes(at)
    prueba_completar(at)
    prueba_completar_lotes(at)
    prueba_compras(at)
    prueba_metricas_y_guardado(at)

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
