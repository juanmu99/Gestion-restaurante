"""
main.py
--------
Punto de entrada de la aplicación de gestión del restaurante. Menú de
texto por consola que conecta los 5 módulos (inventario, servicios,
recetario, compras, dashboard) + exportación a Excel + backup a
Google Drive.

⚠️ NOTA SOBRE PERSISTENCIA:
Los datos viven SOLO en memoria mientras el programa está abierto. Si
lo cierras sin exportar, se pierden. La exportación a Excel (opción 6)
es, de momento, la única forma de guardar un "estado" fuera de la
sesión. Cargar datos DESDE un Excel de vuelta a la app es un paso
futuro que aún no hemos construido (sería un buen Módulo 6).
"""

import sys
from pathlib import Path
from datetime import date, time
from typing import Optional

# Añadimos la carpeta modulos/ al path para poder importar sus archivos
# con imports "planos" (from inventario import ...), igual que hemos
# venido haciendo en cada módulo por separado hasta ahora.
sys.path.append(str(Path(__file__).parent / "modulos"))

from inventario import Inventario, Producto, MovimientoStock, FACTORES_CONVERSION
from servicios import RegistroServicios, Servicio
from recetario import Recetario, Receta, Menu
from compras import GestorCompras, ItemCompra
from dashboard import Dashboard
from exportador import exportar_todo
from persistencia import guardar_sesion, cargar_sesion
from metricas import Metricas, ArchivoInformes, rango_desde_periodo, PERIODOS_VALIDOS, NOMBRES_MESES

def _carpeta_base() -> Path:
    """
    Dónde deben vivir los datos que tienen que SOBREVIVIR entre
    arranques (la sesión guardada, los excels exportados...).

    - Ejecución normal (python main.py): la carpeta donde vive este
      script, como hasta ahora.
    - Ejecución empaquetada con PyInstaller (sys.frozen es True): la
      carpeta donde vive el propio .exe -- NUNCA la carpeta temporal
      donde PyInstaller descomprime el programa en cada arranque, que
      es distinta cada vez y se borra sola.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


RUTA_SESION = str(_carpeta_base() / "datos" / "sesion.json")


# --- Estado global de la aplicación (vive mientras el programa esté abierto) ---
inventario = Inventario()
registro_servicios = RegistroServicios()
recetario = Recetario()
gestor_compras = GestorCompras()
dashboard = Dashboard(inventario, registro_servicios, gestor_compras)
archivo_informes = ArchivoInformes()

ultima_exportacion: str | None = None  # ruta del último Excel generado


# ---------- Helpers de entrada por consola ----------

def pedir_texto(mensaje: str) -> str:
    return input(mensaje).strip()


def pedir_texto_no_numerico(mensaje: str) -> str:
    """
    Como pedir_texto(), pero además rechaza entradas vacías o que sean
    PURAMENTE numéricas (ej: "123" o "45.6"). Útil para campos como
    categoría o proveedor, que deben ser texto descriptivo con sentido,
    no un número suelto.
    """
    while True:
        valor = input(mensaje).strip()
        if valor == "":
            print("⚠️  Este campo no puede quedar vacío.")
            continue
        try:
            float(valor)
        except ValueError:
            return valor  # no se pudo convertir a número -> es texto de verdad, válido
        else:
            print("⚠️  Este campo debe contener texto, no solo un número.")


def pedir_si_no(mensaje: str) -> bool:
    """
    Pide una respuesta s/n, repitiendo hasta obtener una válida (en vez
    de aceptar cualquier cosa y tratarla silenciosamente como "no").
    Devuelve True para "s"/"sí", False para "n"/"no".
    """
    while True:
        valor = input(f"{mensaje} (s/n): ").strip().lower()
        if valor in ("s", "si", "sí"):
            return True
        if valor in ("n", "no"):
            return False
        print("⚠️  Responde 's' o 'n'.")


def pedir_opcion(mensaje: str, opciones: tuple) -> str:
    """
    Pide texto que debe ser EXACTAMENTE una de las `opciones` dadas
    (comparando en minúsculas, para no ser tan estricto con mayúsculas).
    Repite hasta obtener una opción válida. Devuelve la opción tal cual
    está escrita en `opciones` (no lo que tecleó el usuario).
    """
    normalizadas = {o.lower(): o for o in opciones}
    while True:
        valor = input(f"{mensaje} ({'/'.join(opciones)}): ").strip().lower()
        if valor in normalizadas:
            return normalizadas[valor]
        print(f"⚠️  Opción no válida. Elige una de: {', '.join(opciones)}")


def pedir_cantidad_ingrediente(producto) -> float:
    """
    Pide la cantidad de un ingrediente "por comensal", dejando elegir en
    qué unidad quieres escribirla (kg o g / litros o ml — lo que tenga
    sentido según cómo esté configurado el producto), y la convierte
    automáticamente a la unidad en la que ese producto vive en el
    inventario. Así la receta y el inventario siempre "hablan en la misma
    unidad" sin que tengas que convertir de cabeza, y sin arriesgarte a
    mezclar gramos con kilos sin darte cuenta al generar la lista de compra.
    """
    unidad_producto = producto.unidad

    if unidad_producto in ("kg", "g"):
        unidad_elegida = pedir_opcion(
            f"  ¿En qué unidad quieres escribir la cantidad de '{producto.nombre}'?", ("kg", "g")
        )
    elif unidad_producto in ("litros", "ml"):
        unidad_elegida = pedir_opcion(
            f"  ¿En qué unidad quieres escribir la cantidad de '{producto.nombre}'?", ("litros", "ml")
        )
    else:  # "unidades" -> no existe una unidad alternativa, solo se lo recordamos
        unidad_elegida = unidad_producto
        print(f"  ('{producto.nombre}' está configurado en '{unidad_producto}', sin conversión posible)")

    cantidad = pedir_numero(f"  Cantidad de '{producto.nombre}' por comensal, en {unidad_elegida}: ")

    if unidad_elegida != unidad_producto:
        factor = FACTORES_CONVERSION[(unidad_elegida, unidad_producto)]
        cantidad = round(cantidad * factor, 6)
        print(f"  🔄 Convertido a las unidades del inventario: {cantidad} {unidad_producto}")

    return cantidad


def pedir_numero(mensaje: str) -> float:
    while True:
        valor = input(mensaje).strip()
        try:
            return float(valor)
        except ValueError:
            print("⚠️  Introduce un número válido.")


def pedir_numero_opcional(mensaje: str) -> Optional[float]:
    """
    Como pedir_numero(), pero para formularios de EDICIÓN: si se deja
    vacío, devuelve None (interpretado como "no modificar este campo")
    en vez de exigir un número obligatoriamente.
    """
    while True:
        valor = input(mensaje).strip()
        if valor == "":
            return None
        try:
            return float(valor)
        except ValueError:
            print("⚠️  Introduce un número válido, o déjalo vacío para no modificarlo.")


def pedir_texto_no_numerico_opcional(mensaje: str) -> Optional[str]:
    """Como pedir_texto_no_numerico(), pero vacío = "no modificar este campo"."""
    while True:
        valor = input(mensaje).strip()
        if valor == "":
            return None
        try:
            float(valor)
        except ValueError:
            return valor
        else:
            print("⚠️  Debe ser texto, no solo un número (o déjalo vacío para no modificarlo).")


def pedir_entero(mensaje: str) -> int:
    return int(pedir_numero(mensaje))


def pedir_fecha(mensaje: str) -> date:
    while True:
        valor = input(f"{mensaje} (dd/mm/aaaa): ").strip()
        try:
            dia, mes, anio = (int(x) for x in valor.split("/"))
            return date(anio, mes, dia)
        except (ValueError, IndexError):
            print("⚠️  Formato no válido, usa dd/mm/aaaa (ej: 25/12/2026).")


def pedir_hora(mensaje: str) -> time:
    while True:
        valor = input(f"{mensaje} (HH:MM): ").strip()
        try:
            h, m = (int(x) for x in valor.split(":"))
            return time(h, m)
        except (ValueError, IndexError):
            print("⚠️  Formato no válido, usa HH:MM (ej: 21:30).")


def pausa() -> None:
    input("\nPulsa Enter para continuar...")


# ---------- Menú: Inventario ----------

def menu_inventario():
    while True:
        print("\n--- INVENTARIO ---")
        print("1. Listar productos")
        print("2. Añadir producto")
        print("3. Actualizar stock")
        print("4. Ver productos bajo mínimo")
        print("5. Ver próximos a caducar")
        print("6. Editar producto")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            inventario.listar_todos()
        elif opcion == "2":
            nombre = pedir_texto("Nombre: ")
            categoria = pedir_texto_no_numerico("Categoría: ")
            stock = pedir_numero("Stock inicial: ")
            unidad = pedir_opcion("Unidad", Producto.UNIDADES_VALIDAS)
            precio = pedir_numero("Precio unitario (€): ")
            proveedor = pedir_texto_no_numerico("Proveedor: ")
            stock_minimo = pedir_numero("Stock mínimo: ")
            tiene_caducidad = pedir_si_no("¿Tiene fecha de caducidad?")
            fecha_caducidad = pedir_fecha("Fecha de caducidad") if tiene_caducidad else None
            try:
                inventario.agregar_producto(Producto(
                    nombre, categoria, stock, unidad, precio, proveedor, stock_minimo, fecha_caducidad
                ))
            except ValueError as e:
                print(f"❌ {e}")
        elif opcion == "3":
            nombre = pedir_texto("Nombre del producto: ")
            producto = inventario.buscar_producto(nombre)
            if producto is None:
                print(f"❌ No existe el producto '{nombre}'.")
            else:
                cantidad = pedir_numero("Cantidad: ")
                es_entrada = pedir_si_no("¿Es una entrada de mercancía (sumar stock)?")
                nueva_fecha = None
                motivo = None
                if es_entrada:
                    renovar = pedir_si_no("¿Quieres renovar la fecha de caducidad con este lote nuevo?")
                    if renovar:
                        nueva_fecha = pedir_fecha("Nueva fecha de caducidad")
                else:
                    motivo = pedir_opcion("Motivo de la salida", MovimientoStock.MOTIVOS_SALIDA)
                inventario.actualizar_stock(
                    nombre, cantidad, sumar=es_entrada, nueva_fecha_caducidad=nueva_fecha, motivo_salida=motivo
                )
        elif opcion == "4":
            productos = inventario.productos_bajo_minimo()
            print("✅ Ningún producto bajo mínimo." if not productos else "")
            for p in productos:
                print(p)
        elif opcion == "5":
            productos = inventario.productos_proximos_a_caducar()
            if not productos:
                print("✅ Ningún producto próximo a caducar.")
            for p in productos:
                fecha_str = p.fecha_caducidad.strftime("%d/%m/%Y")
                print(f"{p} | Caduca: {fecha_str} (en {p.dias_para_caducar()} día(s))")
        elif opcion == "6":
            nombre = pedir_texto("Nombre del producto a editar: ")
            producto = inventario.buscar_producto(nombre)
            if producto is None:
                print(f"❌ No existe el producto '{nombre}'.")
            else:
                print(f"Editando: {producto}")
                print("Deja cualquier campo vacío para NO modificarlo.")

                texto_nombre = pedir_texto(f"Nuevo nombre [{producto.nombre}]: ")
                nuevo_nombre = texto_nombre if texto_nombre else None

                # Si se va a renombrar, identificamos YA qué recetas usan
                # el nombre ACTUAL como ingrediente -- las actualizaremos
                # de verdad más abajo, pero solo si el renombrado en el
                # inventario tiene éxito (podría abortarse, por ejemplo,
                # si el nombre nuevo ya lo usa otro producto).
                recetas_afectadas = []
                if nuevo_nombre and nuevo_nombre != producto.nombre:
                    recetas_afectadas = [
                        r for r in recetario.recetas.values()
                        if producto.nombre in r.ingredientes_por_comensal
                    ]

                categoria = pedir_texto_no_numerico_opcional(f"Nueva categoría [{producto.categoria}]: ")
                stock = pedir_numero_opcional(f"Nuevo stock [{producto.stock}]: ")
                precio = pedir_numero_opcional(f"Nuevo precio unitario [{producto.precio_unitario}]: ")
                proveedor = pedir_texto_no_numerico_opcional(f"Nuevo proveedor [{producto.proveedor}]: ")
                stock_minimo = pedir_numero_opcional(f"Nuevo stock mínimo [{producto.stock_minimo}]: ")

                fecha_actual_str = (
                    producto.fecha_caducidad.strftime("%d/%m/%Y") if producto.fecha_caducidad else "sin fecha"
                )
                print(f"Fecha de caducidad actual: {fecha_actual_str}")
                accion_fecha = pedir_opcion(
                    "¿Qué quieres hacer con la fecha de caducidad?", ("mantener", "cambiar", "borrar")
                )
                nueva_fecha_caducidad = None
                borrar_fecha = False
                if accion_fecha == "cambiar":
                    nueva_fecha_caducidad = pedir_fecha("Nueva fecha de caducidad")
                elif accion_fecha == "borrar":
                    borrar_fecha = True

                nombre_original = producto.nombre
                try:
                    exito = inventario.editar_producto(
                        nombre,
                        nuevo_nombre=nuevo_nombre,
                        categoria=categoria,
                        stock=stock,
                        precio_unitario=precio,
                        proveedor=proveedor,
                        stock_minimo=stock_minimo,
                        fecha_caducidad=nueva_fecha_caducidad,
                        borrar_fecha_caducidad=borrar_fecha,
                    )
                except ValueError as e:
                    print(f"❌ {e}")
                    exito = False

                if exito and recetas_afectadas:
                    # Renombramos la CLAVE del ingrediente en cada receta
                    # afectada, conservando su cantidad. Los Menu que usan
                    # estas recetas NO necesitan tocarse: solo guardan una
                    # REFERENCIA al objeto Receta, no una copia, así que
                    # ven el cambio automáticamente.
                    for receta in recetas_afectadas:
                        cantidad = receta.ingredientes_por_comensal.pop(nombre_original)
                        receta.ingredientes_por_comensal[nuevo_nombre] = cantidad
                    nombres = ", ".join(r.nombre for r in recetas_afectadas)
                    print(f"🔄 Recetas actualizadas automáticamente: {nombres}")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


# ---------- Menú: Servicios ----------

def menu_servicios():
    while True:
        print("\n--- SERVICIOS ---")
        print("1. Listar servicios")
        print("2. Añadir servicio")
        print("3. Cancelar servicio")
        print("4. Ver próximos servicios (7 días)")
        print("5. Completar servicio (descuenta stock automáticamente)")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            registro_servicios.listar_todos()
        elif opcion == "2":
            fecha = pedir_fecha("Fecha del servicio")
            hora = pedir_hora("Hora del servicio")
            comensales = pedir_entero("Número de comensales: ")
            menu_nombre = pedir_texto("Nombre del menú: ")
            notas = pedir_texto("Notas (opcional): ")
            try:
                registro_servicios.agregar_servicio(
                    Servicio(fecha, hora, comensales, menu_nombre, notas)
                )
            except ValueError as e:
                print(f"❌ {e}")
        elif opcion == "3":
            id_servicio = pedir_entero("ID del servicio a cancelar: ")
            registro_servicios.cancelar_servicio(id_servicio)
        elif opcion == "4":
            servicios = registro_servicios.servicios_proximos()
            print("✅ No hay servicios próximos." if not servicios else "")
            for s in servicios:
                print(s)
        elif opcion == "5":
            id_servicio = pedir_entero("ID del servicio a completar: ")
            servicio = registro_servicios.buscar_por_id(id_servicio)
            if servicio is None:
                print(f"❌ No existe un servicio con id {id_servicio}")
            else:
                menu = recetario.buscar_menu(servicio.menu)
                if menu is None:
                    print(f"⚠️  No se encontró el menú '{servicio.menu}' en el recetario.")
                    confirmar = pedir_si_no("¿Marcar como completado igualmente (sin tocar el inventario)?")
                    if confirmar:
                        servicio.completar()
                        print(f"✅ Servicio #{id_servicio} completado (sin descuento de stock).")
                else:
                    necesarios = menu.calcular_ingredientes_totales(servicio.comensales)
                    print(f"Descontando ingredientes para {servicio.comensales} comensales de '{menu.nombre}':")
                    fallidos = []
                    for ingrediente, cantidad in necesarios.items():
                        if inventario.buscar_producto(ingrediente) is None:
                            print(f"⚠️  '{ingrediente}' no existe en el inventario, se omite.")
                            fallidos.append(ingrediente)
                            continue
                        exito = inventario.actualizar_stock(
                            ingrediente, cantidad, sumar=False, motivo_salida="consumo"
                        )
                        if not exito:
                            fallidos.append(ingrediente)
                    servicio.completar()
                    if fallidos:
                        print(f"⚠️  Servicio #{id_servicio} completado, pero no se pudo descontar: {', '.join(fallidos)}")
                    else:
                        print(f"✅ Servicio #{id_servicio} completado, stock descontado correctamente.")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


# ---------- Menú: Recetario ----------

def menu_recetario():
    while True:
        print("\n--- RECETARIO ---")
        print("1. Listar recetas")
        print("2. Listar menús")
        print("3. Crear receta")
        print("4. Crear menú (combinando recetas existentes)")
        print("5. Cargar recetas y menú de ejemplo")
        print("6. Recomendar menú (según caducidad)")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            if not recetario.recetas:
                print("No hay recetas todavía.")
            for r in recetario.recetas.values():
                print(f"{r} | Coste/comensal: {r.costo_por_comensal(inventario)}€")
        elif opcion == "2":
            if not recetario.menus:
                print("No hay menús todavía.")
            for m in recetario.menus.values():
                print(f"{m} | Coste/comensal: {m.costo_por_comensal(inventario)}€")
        elif opcion == "3":
            nombre = pedir_texto("Nombre de la receta: ")
            categoria = pedir_texto("Categoría: ")
            ingredientes = {}
            if not inventario.productos:
                print("⚠️  El inventario está vacío. Añade productos primero (menú Inventario).")
            print("Añade ingredientes uno a uno (nombre vacío para terminar).")
            print("Deben ser productos que YA existan en el inventario (nombre exacto).")
            while True:
                ing = pedir_texto("  Ingrediente: ")
                if ing == "":
                    break
                producto = inventario.buscar_producto(ing)
                if producto is None:
                    print(f"⚠️  '{ing}' no existe en el inventario. Revisa el nombre exacto o añádelo primero.")
                    continue
                ingredientes[producto.nombre] = pedir_cantidad_ingrediente(producto)
            recetario.agregar_receta(Receta(nombre, categoria, ingredientes))
        elif opcion == "4":
            if not recetario.recetas:
                print("⚠️  Primero crea al menos una receta.")
            else:
                print(f"Recetas disponibles: {', '.join(recetario.recetas.keys())}")
                nombre_menu = pedir_texto("Nombre del menú: ")
                nombres = pedir_texto("Recetas a incluir (separadas por comas): ")
                recetas_menu = []
                for nombre_receta in (n.strip() for n in nombres.split(",")):
                    receta = recetario.recetas.get(nombre_receta)
                    if receta is None:
                        print(f"⚠️  No existe la receta '{nombre_receta}', se omite.")
                    else:
                        recetas_menu.append(receta)
                if recetas_menu:
                    recetario.agregar_menu(Menu(nombre_menu, recetas_menu))
        elif opcion == "5":
            pan_casero = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
            ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})
            recetario.agregar_receta(pan_casero)
            recetario.agregar_receta(ensalada)
            recetario.agregar_menu(Menu("Menú del día", [pan_casero, ensalada]))
        elif opcion == "6":
            if not recetario.menus:
                print("No hay menús registrados todavía.")
            else:
                dias = pedir_entero("¿Ventana de caducidad a considerar, en días?: ")
                comensales = pedir_entero("¿Para cuántos comensales comprobamos disponibilidad?: ")
                recomendaciones = recetario.recomendar_menus(inventario, dias)

                print(f"\n--- Menús ordenados por urgencia total (próximos {dias} días) ---")
                for menu, puntuacion in recomendaciones:
                    puede = menu.se_puede_preparar(inventario, comensales)
                    disponibilidad = "✅ se puede preparar ya" if puede else "🛒 faltaría comprar algo"

                    if puntuacion > 0:
                        print(f"🔥 {menu.nombre} | urgencia total {puntuacion:.1f} | {disponibilidad}")

                        riesgo = menu.ingredientes_en_riesgo(inventario, dias)
                        if riesgo:
                            detalle = ", ".join(f"{p.nombre} (caduca en {p.dias_para_caducar()}d)" for p in riesgo)
                            print(f"   ⏳ Por caducidad: {detalle}")

                        exceso = menu.ingredientes_en_exceso(inventario)
                        if exceso:
                            detalle = ", ".join(f"{p.nombre} ({p.stock} sobre mínimo {p.stock_minimo})" for p in exceso)
                            print(f"   📦 Por exceso de stock: {detalle}")
                    else:
                        print(f"   {menu.nombre} | sin urgencia | {disponibilidad}")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


# ---------- Menú: Compras ----------

def menu_compras():
    while True:
        print("\n--- COMPRAS ---")
        print("1. Generar lista de compra (desde servicios próximos)")
        print("2. Ver lista de compra por proveedor")
        print("3. Marcar producto como comprado")
        print("4. Ver coste total pendiente")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            dias = pedir_entero("¿Servicios de cuántos días hacia adelante? ")
            servicios = registro_servicios.servicios_proximos(dias)
            if not servicios:
                print("No hay servicios próximos en ese rango.")
            else:
                gestor_compras.generar_lista_desde_servicios(servicios, recetario, inventario)
        elif opcion == "2":
            gestor_compras.mostrar_lista_por_proveedor()
        elif opcion == "3":
            nombre = pedir_texto("Ingrediente a marcar como comprado: ")
            item = next((i for i in gestor_compras.items if i.ingrediente == nombre and not i.comprado), None)
            if item is None:
                print(f"❌ '{nombre}' no está pendiente en la lista de compra.")
            else:
                print(f"Cantidad calculada como necesaria: {item.cantidad} {item.unidad}")
                cantidad_real = pedir_numero(f"¿Cuánta cantidad has comprado de verdad (en {item.unidad})?: ")
                unidad = item.unidad
                gestor_compras.marcar_comprado(nombre, cantidad_comprada=cantidad_real)
                # Comprarlo implica que ahora está físicamente en el almacén
                # -- lo reponemos en el inventario en el mismo paso, para no
                # tener que acordarte de hacerlo tú a mano por separado.
                # actualizar_stock() ya registra esto en el historial (y por
                # tanto en las métricas de gasto) automáticamente.
                inventario.actualizar_stock(nombre, cantidad_real, sumar=True)
                print(f"📦 Stock repuesto: +{cantidad_real} {unidad} de {nombre}")
        elif opcion == "4":
            print(f"💰 Coste total pendiente: {gestor_compras.costo_total_pendiente()} €")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


# ---------- Acciones de nivel superior ----------

def accion_exportar_excel():
    global ultima_exportacion
    carpeta_datos = str(_carpeta_base() / "datos")
    ruta = exportar_todo(inventario, registro_servicios, gestor_compras, carpeta_datos)
    ultima_exportacion = ruta
    print(f"✅ Exportado a: {ruta}")


def accion_guardar_sesion():
    guardar_sesion(inventario, registro_servicios, recetario, gestor_compras, archivo_informes, RUTA_SESION)


def accion_cargar_sesion():
    # `global` es necesario aquí porque vamos a REEMPLAZAR estas variables
    # por objetos nuevos (los que salen de cargar_sesion), no solo a leerlas
    # o modificar algo dentro de ellas. Sin `global`, Python entendería que
    # estamos creando variables LOCALES nuevas dentro de esta función, y
    # las de fuera (las que usa el resto del programa) no cambiarían.
    global inventario, registro_servicios, recetario, gestor_compras, dashboard, archivo_informes

    resultado = cargar_sesion(RUTA_SESION)
    if resultado is None:
        return

    inventario, registro_servicios, recetario, gestor_compras, archivo_informes = resultado
    # El Dashboard guarda referencias a los objetos antiguos, así que hay
    # que reconstruirlo con los nuevos o seguiría mostrando datos viejos.
    dashboard = Dashboard(inventario, registro_servicios, gestor_compras)


def accion_backup_drive():
    if ultima_exportacion is None:
        print("⚠️  Primero exporta a Excel (opción 6) antes de hacer backup.")
        return
    try:
        from google_drive_backup import subir_archivo
        subir_archivo(ultima_exportacion)
    except ImportError:
        print("⚠️  Faltan librerías para Google Drive. En TU ordenador (no aquí) ejecuta:")
        print("    pip install google-auth-oauthlib google-api-python-client")
    except FileNotFoundError as e:
        print(f"⚠️  {e}")
    except Exception as e:
        print(f"❌ Error al subir a Google Drive: {e}")


def accion_cargar_datos_ejemplo():
    inventario.agregar_producto(Producto("Harina de trigo", "Panadería", 1, "kg", 1.2, "Harinas del Sur", stock_minimo=2))
    inventario.agregar_producto(Producto("Aceite de oliva", "Aceites", 20, "litros", 4.5, "Oleícola Andaluza", stock_minimo=5))
    inventario.agregar_producto(Producto("Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2, fecha_caducidad=date(2026, 9, 1)))

    registro_servicios.agregar_servicio(Servicio(date(2026, 9, 2), time(21, 0), 8, "Menú del día"))
    registro_servicios.agregar_servicio(Servicio(date(2026, 9, 15), time(21, 0), 12, "Menú de bodas"))

    pan_casero = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})
    recetario.agregar_receta(pan_casero)
    recetario.agregar_receta(ensalada)
    recetario.agregar_menu(Menu("Menú del día", [pan_casero, ensalada]))

    print("✅ Datos de ejemplo cargados en los 4 módulos.")


# ---------- Menú principal ----------

def menu_metricas():
    while True:
        print("\n--- MÉTRICAS ---")
        print("1. Cantidad consumida de un producto")
        print("2. Cantidad desperdiciada de un producto")
        print("3. Productos más consumidos (ranking)")
        print("4. Gasto por categoría")
        print("5. Valor total desperdiciado")
        print("6. Generar informe mensual (y guardarlo)")
        print("7. Ver informes guardados")
        print("8. Comparar dos meses")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion in ("1", "2", "3", "4", "5"):
            periodo = pedir_opcion("Periodo", PERIODOS_VALIDOS)
            desde, hasta = rango_desde_periodo(periodo)
            metricas = Metricas(inventario)

        if opcion == "1":
            nombre = pedir_texto("Producto: ")
            cantidad = metricas.cantidad_consumida(nombre, desde, hasta)
            print(f"📉 Consumido de '{nombre}' ({periodo}): {cantidad}")
        elif opcion == "2":
            nombre = pedir_texto("Producto: ")
            cantidad = metricas.cantidad_desperdiciada(nombre, desde, hasta)
            print(f"🗑️  Desperdiciado de '{nombre}' ({periodo}): {cantidad}")
        elif opcion == "3":
            ranking = metricas.productos_mas_consumidos(desde, hasta)
            if not ranking:
                print("No hay datos de consumo en ese periodo.")
            for i, (nombre, cantidad) in enumerate(ranking, start=1):
                print(f"{i}. {nombre}: {cantidad}")
        elif opcion == "4":
            gasto = metricas.gasto_por_categoria(desde, hasta)
            if not gasto:
                print("No hay compras registradas en ese periodo.")
            for categoria, importe in gasto.items():
                print(f"{categoria}: {importe} €")
        elif opcion == "5":
            valor = metricas.valor_desperdiciado_total(desde, hasta)
            print(f"🗑️  Valor total desperdiciado ({periodo}): {valor} €")
        elif opcion == "6":
            año = pedir_entero("Año (ej: 2026): ")
            mes = pedir_entero("Mes (1-12): ")
            archivo_informes.generar_informe(inventario, año, mes)
        elif opcion == "7":
            informes = archivo_informes.listar_informes()
            if not informes:
                print("No hay informes guardados todavía.")
            for informe in informes:
                print(informe)
        elif opcion == "8":
            print("Primer mes a comparar:")
            año1 = pedir_entero("  Año: ")
            mes1 = pedir_entero("  Mes: ")
            print("Segundo mes a comparar:")
            año2 = pedir_entero("  Año: ")
            mes2 = pedir_entero("  Mes: ")
            resultado = archivo_informes.comparar(año1, mes1, año2, mes2)
            if resultado:
                print(f"\n{resultado['periodo_1']} -> {resultado['periodo_2']}")
                print(
                    f"Gasto total: {resultado['gasto_total_1']}€ -> {resultado['gasto_total_2']}€ "
                    f"(diferencia: {resultado['diferencia_gasto_total']:+}€)"
                )
                print("Diferencia por categoría:")
                for categoria, diferencia in resultado["diferencia_por_categoria"].items():
                    print(f"  {categoria}: {diferencia:+}€")
                print(
                    f"Desperdicio: {resultado['desperdicio_1']}€ -> {resultado['desperdicio_2']}€ "
                    f"(diferencia: {resultado['diferencia_desperdicio']:+}€)"
                )
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


def menu_principal():
    while True:
        print("\n" + "=" * 40)
        print("  GESTIÓN RESTAURANTE")
        print("=" * 40)
        print("1. Inventario")
        print("2. Servicios")
        print("3. Recetario")
        print("4. Compras")
        print("5. Dashboard")
        print("6. Exportar a Excel")
        print("7. Backup a Google Drive")
        print("8. Cargar datos de ejemplo (para probar rápido)")
        print("9. Métricas")
        print("10. Guardar sesión")
        print("11. Cargar sesión")
        print("0. Salir")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            menu_inventario()
        elif opcion == "2":
            menu_servicios()
        elif opcion == "3":
            menu_recetario()
        elif opcion == "4":
            menu_compras()
        elif opcion == "5":
            dashboard.mostrar_resumen()
            pausa()
        elif opcion == "6":
            accion_exportar_excel()
            pausa()
        elif opcion == "7":
            accion_backup_drive()
            pausa()
        elif opcion == "8":
            accion_cargar_datos_ejemplo()
            pausa()
        elif opcion == "9":
            menu_metricas()
        elif opcion == "10":
            accion_guardar_sesion()
            pausa()
        elif opcion == "11":
            accion_cargar_sesion()
            pausa()
        elif opcion == "0":
            respuesta = pedir_texto("¿Guardar sesión antes de salir? (s/n): ").strip().lower()
            if respuesta == "s":
                accion_guardar_sesion()
            print("¡Hasta pronto! 👋")
            return
        else:
            print("⚠️  Opción no válida.")


if __name__ == "__main__":
    if Path(RUTA_SESION).exists():
        respuesta = pedir_texto("Hay una sesión guardada. ¿Cargarla? (s/n): ").strip().lower()
        if respuesta == "s":
            accion_cargar_sesion()
    menu_principal()
