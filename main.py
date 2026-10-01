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
from datetime import date, time, timedelta
from typing import Optional

# Añadimos la carpeta modulos/ al path para poder importar sus archivos
# con imports "planos" (from inventario import ...), igual que hemos
# venido haciendo en cada módulo por separado hasta ahora.
# insert(0, ...) y no append(): así Python busca PRIMERO en nuestra carpeta
# modulos/. Si el ordenador tuviera instalada una librería con el mismo
# nombre que uno de nuestros módulos, se usaría la nuestra y no la otra.
sys.path.insert(0, str(Path(__file__).parent / "modulos"))

from inventario import Inventario, Producto, MovimientoStock, FACTORES_CONVERSION, UNIDADES_PESO, convertir
from servicios import RegistroServicios, Servicio
from recetario import Recetario, Receta, Menu
from compras import GestorCompras, ItemCompra
from dashboard import Dashboard
from exportador import exportar_todo
from persistencia import guardar_sesion, cargar_sesion
from gastos import Gasto, RegistroGastos, resumen_servicio
from materiales import Material, RegistroMaterial, lista_de_carga
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
registro_gastos = RegistroGastos()
registro_material = RegistroMaterial()

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


def pedir_peso_kg(mensaje: str) -> float:
    """Pide un peso dejando elegir si se escribe en kg o en g, y lo devuelve siempre en kg."""
    unidad = pedir_opcion(f"{mensaje} -- ¿en qué unidad?", UNIDADES_PESO)
    while True:
        valor = pedir_numero(f"{mensaje} (en {unidad}): ")
        if valor > 0:
            return convertir(valor, unidad, "kg")
        print("⚠️  El peso debe ser mayor que 0.")


def pedir_si_no_opcional(mensaje: str) -> Optional[bool]:
    """Como pedir_si_no(), pero vacío = "no modificar" (devuelve None). Para formularios de edición."""
    while True:
        valor = input(f"{mensaje} (s/n, vacío para no cambiar): ").strip().lower()
        if valor == "":
            return None
        if valor in ("s", "si", "sí"):
            return True
        if valor in ("n", "no"):
            return False
        print("⚠️  Responde 's', 'n' o deja vacío.")


def pedir_peso_lote(producto) -> Optional[float]:
    """
    Si el producto tiene merma y se compra por unidades, pide el peso en
    bruto de cada unidad del lote que entra (en kg). Si no, devuelve None.
    """
    if producto.tiene_merma and producto.unidad == "unidades":
        actual = f" (la última vez: {producto.peso_unitario_referencia} kg)" if producto.peso_unitario_referencia else ""
        print(f"'{producto.nombre}' tiene merma y se compra por unidades{actual}.")
        return pedir_peso_kg("Peso en bruto de cada unidad de este lote")
    return None


def pedir_lote(producto, mensaje: str, lotes: Optional[list] = None, sugerir: bool = True, mostrar: bool = True):
    """
    Muestra los lotes de un producto (primero los que caducan antes) y pide
    el número del lote. Con sugerir=True, Enter elige el primero de la lista.
    Devuelve el Lote elegido, o None si no hay lotes.
    """
    lotes = producto.lotes_ordenados() if lotes is None else lotes
    if not lotes:
        return None
    if mostrar:
        mostrar_lotes(producto, lotes)
    numeros = {str(l.id): l for l in lotes}
    extra = f" [Enter = lote {lotes[0].id}]" if sugerir else ""
    while True:
        valor = input(f"{mensaje}{extra}: ").strip()
        if valor == "" and sugerir:
            return lotes[0]
        if valor in numeros:
            return numeros[valor]
        print(f"⚠️  Escribe uno de estos números de lote: {', '.join(numeros)}")


def listar_inventario() -> None:
    """Lista el inventario en dos bloques separados: alimentos y consumibles."""
    for titulo, productos in (("🍅 ALIMENTOS", inventario.alimentos()), ("🧻 CONSUMIBLES", inventario.consumibles())):
        print(f"\n{titulo}")
        if not productos:
            print("   (ninguno)")
        for producto in productos:
            print(producto)
            mostrar_lotes(producto)


def mostrar_lotes(producto, lotes: Optional[list] = None) -> None:
    for lote in producto.lotes_ordenados() if lotes is None else lotes:
        aviso = "  ⚠️ CADUCADO" if lote.esta_caducado() else ""
        print(f"   {lote.descripcion(producto.unidad)}{aviso}")


def pedir_datos_entrada(producto) -> dict:
    """Pide los datos de un lote NUEVO (compra): precio, proveedor, caducidad y, si hace falta, peso por unidad."""
    precio = pedir_numero_opcional(f"Precio de este lote [{producto.precio_referencia} €]: ")
    proveedor = pedir_texto_no_numerico_opcional(f"Proveedor de este lote [{producto.proveedor}]: ")
    fecha = None
    if not producto.es_consumible() and pedir_si_no("¿Este lote tiene fecha de caducidad?"):
        fecha = pedir_fecha("Fecha de caducidad de este lote")
    return {"precio_unitario": precio, "proveedor": proveedor, "fecha_caducidad": fecha,
            "peso_unitario": pedir_peso_lote(producto)}


def pausa() -> None:
    input("\nPulsa Enter para continuar...")


# ---------- Menú: Inventario ----------

def menu_inventario():
    while True:
        print("\n--- INVENTARIO ---")
        print("1. Listar productos")
        print("2. Añadir producto")
        print("3. Actualizar stock (compra = lote nuevo / salida de un lote)")
        print("4. Ver productos bajo mínimo")
        print("5. Ver lotes caducados y próximos a caducar")
        print("6. Editar producto")
        print("7. Limpiar / despiezar un producto con merma")
        print("8. Historial de limpiezas y rendimiento medio")
        print("9. Ver los lotes de un producto o desechar uno")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            listar_inventario()
        elif opcion == "2":
            tipo = pedir_opcion("¿Qué es?", Producto.TIPOS)
            nombre = pedir_texto("Nombre: ")
            categoria = pedir_texto_no_numerico("Categoría: ")
            stock = pedir_numero("Stock inicial (será su primer lote): ")
            unidad = pedir_opcion("Unidad", Producto.UNIDADES_VALIDAS)
            tiene_merma = False
            peso_unitario = None
            if unidad in UNIDADES_PESO + ("unidades",) and tipo == "alimento":
                tiene_merma = pedir_si_no("¿Es un producto con merma (se limpia o despieza antes de usarse)?")
                if tiene_merma and unidad == "unidades":
                    peso_unitario = pedir_peso_kg("Peso en bruto de cada unidad")
            precio = pedir_numero(f"Precio (€ por {'unidad' if unidad == 'unidades' else unidad}): ")
            proveedor = pedir_texto_no_numerico("Proveedor habitual: ")
            stock_minimo = pedir_numero("Stock mínimo: ")
            fecha_caducidad = None
            if tipo == "alimento" and stock > 0 and pedir_si_no("¿Este primer lote tiene fecha de caducidad?"):
                fecha_caducidad = pedir_fecha("Fecha de caducidad")
            try:
                inventario.agregar_producto(Producto(
                    nombre, categoria, stock, unidad, precio, proveedor, stock_minimo, fecha_caducidad,
                    tiene_merma=tiene_merma, peso_unitario=peso_unitario, tipo=tipo,
                ))
            except ValueError as e:
                print(f"❌ {e}")
        elif opcion == "3":
            nombre = pedir_texto("Nombre del producto: ")
            producto = inventario.buscar_producto(nombre)
            if producto is None:
                print(f"❌ No existe el producto '{nombre}'.")
            elif pedir_si_no("¿Es una entrada de mercancía (compra)?"):
                cantidad = pedir_numero("Cantidad: ")
                inventario.entrada_stock(nombre, cantidad, **pedir_datos_entrada(producto))
            elif not producto.lotes:
                print(f"❌ No queda stock de '{nombre}'.")
            else:
                print(f"Lotes de {nombre}:")
                lote = pedir_lote(producto, "¿De qué lote sale?")
                cantidad = pedir_numero(f"Cantidad (hay {lote.cantidad} {producto.unidad} en el lote {lote.id}): ")
                motivo = pedir_opcion("Motivo de la salida", MovimientoStock.MOTIVOS_SALIDA)
                inventario.salida_stock(nombre, cantidad, motivo, lote.id)
        elif opcion == "4":
            productos = inventario.productos_bajo_minimo()
            print("✅ Ningún producto bajo mínimo." if not productos else "")
            for p in productos:
                print(p)
        elif opcion == "5":
            caducados = inventario.lotes_caducados()
            proximos = inventario.lotes_proximos_a_caducar()
            if not caducados and not proximos:
                print("✅ Ningún lote caducado ni próximo a caducar.")
            for p, l in proximos:
                print(f"⏳ {p.nombre}: {l.descripcion(p.unidad)} -> caduca en {l.dias_para_caducar()} día(s)")
            for p, l in caducados:
                print(f"🗑️  {p.nombre}: {l.descripcion(p.unidad)} -> CADUCADO")
                if pedir_si_no(f"   ¿Desechar este lote entero ({l.cantidad} {p.unidad} a desperdicio)?"):
                    inventario.desechar_lote(p.nombre, l.id)
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
                tipo = pedir_texto(f"Tipo (alimento/consumible) [{producto.tipo}]: ").lower() or None
                if tipo is not None and tipo not in Producto.TIPOS:
                    print("⚠️  Tipo no válido, se mantiene el actual.")
                    tipo = None
                es_consumible = (tipo or producto.tipo) == "consumible"
                categoria = pedir_texto_no_numerico_opcional(f"Nueva categoría [{producto.categoria}]: ")
                proveedor = pedir_texto_no_numerico_opcional(f"Nuevo proveedor habitual [{producto.proveedor}]: ")
                stock_minimo = pedir_numero_opcional(f"Nuevo stock mínimo [{producto.stock_minimo}]: ")

                tiene_merma = None
                peso_unitario = None
                if producto.unidad in UNIDADES_PESO + ("unidades",) and not es_consumible:
                    actual = "sí" if producto.tiene_merma else "no"
                    tiene_merma = pedir_si_no_opcional(f"¿Producto con merma? [actual: {actual}]")
                    merma_final = producto.tiene_merma if tiene_merma is None else tiene_merma
                    if merma_final and producto.unidad == "unidades":
                        if producto.peso_unitario_referencia:
                            peso_unitario = pedir_numero_opcional(
                                f"Peso por unidad de referencia para compras nuevas, en kg [{producto.peso_unitario_referencia}]: "
                            )
                        else:
                            peso_unitario = pedir_peso_kg("Peso en bruto de cada unidad")

                # Datos de la compra (el lote): se piden ahora y se guardan
                # después, junto con los datos generales.
                lote = None
                correccion = None
                if producto.lotes:
                    print("\n--- Datos de la compra ---")
                    if len(producto.lotes) == 1:
                        lote = producto.lotes[0]
                        mostrar_lotes(producto)
                    else:
                        print(f"Este producto tiene {len(producto.lotes)} lotes:")
                        lote = pedir_lote(producto, "¿Cuál corriges?")
                    correccion = pedir_correccion_lote(lote, pedir_caducidad=not es_consumible)

                nombre_original = producto.nombre
                try:
                    exito = inventario.editar_producto(
                        nombre,
                        nuevo_nombre=nuevo_nombre,
                        categoria=categoria,
                        proveedor=proveedor,
                        stock_minimo=stock_minimo,
                        tiene_merma=tiene_merma,
                        peso_unitario=peso_unitario,
                        tipo=tipo,
                    )
                    if exito and lote is not None:
                        inventario.editar_lote(producto.nombre, lote.id, **correccion)
                except ValueError as e:
                    print(f"❌ {e}")
                    exito = False

                if exito and producto.nombre != nombre_original:
                    # El nombre también se usa en recetas (ingredientes) y
                    # menús (consumibles): se actualizan conservando las cantidades.
                    actualizados = recetario.renombrar_producto(nombre_original, producto.nombre)
                    if actualizados:
                        print(f"🔄 Recetas y menús actualizados automáticamente: {', '.join(actualizados)}")
        elif opcion == "7":
            accion_limpiar_producto()
        elif opcion == "8":
            mostrar_historial_limpiezas()
        elif opcion == "9":
            accion_lotes()
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


def pedir_correccion_lote(lote, pedir_caducidad: bool = True) -> dict:
    """Pide las correcciones de un lote (vacío = no cambiar). Devuelve los argumentos para editar_lote()."""
    print("Corregir no es un movimiento de stock (no queda en el historial). Deja vacío lo que no cambie.")
    print("Si algo se ha gastado o tirado, regístralo como salida (opción 3). Cantidad 0 = eliminar el lote.")
    cantidad = pedir_numero_opcional(f"Cantidad [{lote.cantidad}]: ")
    precio = pedir_numero_opcional(f"Precio [{lote.precio_unitario}]: ")
    proveedor = pedir_texto_no_numerico_opcional(f"Proveedor de esta compra [{lote.proveedor}]: ")
    accion_fecha, fecha = "mantener", None
    if pedir_caducidad:
        fecha_actual = lote.fecha_caducidad.strftime("%d/%m/%Y") if lote.fecha_caducidad else "sin fecha"
        accion_fecha = pedir_opcion(f"Caducidad (ahora: {fecha_actual})", ("mantener", "cambiar", "borrar"))
        fecha = pedir_fecha("Nueva fecha de caducidad") if accion_fecha == "cambiar" else None
    return {"cantidad": cantidad, "precio_unitario": precio, "proveedor": proveedor,
            "fecha_caducidad": fecha, "borrar_fecha_caducidad": accion_fecha == "borrar"}


def accion_lotes() -> None:
    """Muestra los lotes de un producto y permite desechar uno entero."""
    nombre = pedir_texto("Producto: ")
    producto = inventario.buscar_producto(nombre)
    if producto is None:
        print(f"❌ No existe el producto '{nombre}'.")
        return
    if not producto.lotes:
        print(f"No queda ningún lote de '{nombre}'.")
        return
    print(f"Lotes de {nombre} (total {producto.stock} {producto.unidad}, valor {producto.valor_total()} €):")
    mostrar_lotes(producto)
    print("(Para corregir los datos de un lote, usa 'Editar producto'.)")
    if pedir_si_no("¿Quieres desechar alguno entero (desperdicio)?"):
        lote = pedir_lote(producto, "Número de lote", sugerir=False, mostrar=False)
        inventario.desechar_lote(nombre, lote.id)


def accion_limpiar_producto() -> None:
    """Limpia o despieza un producto con merma: bruto -> limpio + derivados + merma."""
    con_merma = inventario.productos_con_merma()
    if not con_merma:
        print("No hay productos con merma. Márcalos al añadirlos o en 'Editar producto'.")
        return
    print("Productos con merma: " + ", ".join(f"{p.nombre} ({p.stock} {p.unidad})" for p in con_merma))

    nombre = pedir_texto("Producto a limpiar: ")
    origen = inventario.buscar_producto(nombre)
    if origen is None or not origen.tiene_merma:
        print(f"❌ '{nombre}' no existe o no es un producto con merma.")
        return

    if not origen.lotes:
        print(f"❌ No queda stock de '{nombre}'.")
        return
    print(f"Lotes de {nombre}:")
    lote = pedir_lote(origen, "¿Qué lote vas a limpiar?")
    cantidad = pedir_numero(f"¿Cuánto vas a limpiar? (en {origen.unidad}; hay {lote.cantidad} en el lote {lote.id}): ")
    if cantidad <= 0 or cantidad > lote.cantidad:
        print(f"❌ La cantidad debe ser mayor que 0 y como mucho {lote.cantidad} {origen.unidad}.")
        return
    try:
        peso_bruto = origen.peso_kg(cantidad, lote)
    except ValueError as e:
        print(f"❌ {e}")
        return
    print(f"Peso en bruto: {round(peso_bruto, 3)} kg")
    rendimiento = inventario.rendimiento_medio(nombre)
    if rendimiento:
        print(f"Rendimiento medio hasta ahora: {rendimiento:.0%} (se esperan ~{peso_bruto * rendimiento:.2f} kg limpios)")

    unidad_peso = pedir_opcion("¿En qué unidad vas a pesar el resultado?", UNIDADES_PESO)
    sugerido = inventario.producto_limpio_de(nombre) or f"{nombre} limpio"
    producto_limpio = pedir_texto(f"Producto limpio [{sugerido}]: ") or sugerido
    peso_limpio = pedir_numero(f"Peso de '{producto_limpio}' ({unidad_peso}): ")
    caducidades = {}
    if pedir_si_no(f"¿Poner fecha de caducidad a '{producto_limpio}'?"):
        caducidades[producto_limpio] = pedir_fecha("Fecha de caducidad")

    print("\nDerivados que se aprovechan. Lo que no indiques se registra como merma.")
    derivados: dict[str, float] = {}
    for habitual in inventario.derivados_habituales(nombre):
        peso = pedir_numero_opcional(f"  {habitual} ({unidad_peso}, vacío si esta vez no se aprovecha): ")
        if peso:
            derivados[habitual] = peso
    print("Otros derivados (nombre vacío para terminar):")
    while True:
        derivado = pedir_texto("  Derivado: ")
        if not derivado:
            break
        derivados[derivado] = pedir_numero(f"  Peso de '{derivado}' ({unidad_peso}): ")

    peso_limpio_kg = convertir(peso_limpio, unidad_peso, "kg")
    derivados_kg = convertir(sum(derivados.values()), unidad_peso, "kg")
    merma_kg = peso_bruto - peso_limpio_kg - derivados_kg
    print("\n--- Resumen ---")
    print(f"Bruto: {round(peso_bruto, 3)} kg de {nombre}")
    print(f"Limpio: {round(peso_limpio_kg, 3)} kg de {producto_limpio} (rendimiento {peso_limpio_kg / peso_bruto:.1%})")
    for derivado, peso in derivados.items():
        print(f"Derivado: {peso} {unidad_peso} de {derivado} (coste 0 €)")
    print(f"Merma: {round(merma_kg, 3)} kg")

    if pedir_si_no("¿Confirmar la limpieza?"):
        try:
            inventario.limpiar_producto(
                nombre, cantidad, producto_limpio, peso_limpio, derivados,
                unidad_peso=unidad_peso, caducidades=caducidades, lote_id=lote.id,
            )
            print("✅ Limpieza registrada.")
        except ValueError as e:
            print(f"❌ {e}")


def mostrar_historial_limpiezas() -> None:
    if not inventario.limpiezas:
        print("Todavía no hay limpiezas registradas.")
        return
    print("--- Rendimiento medio por producto ---")
    for nombre in sorted({l.producto_origen for l in inventario.limpiezas}):
        limpiezas = inventario.limpiezas_de(nombre)
        bruto = sum(l.peso_bruto_kg for l in limpiezas)
        merma = sum(l.merma_kg for l in limpiezas)
        print(
            f"{nombre}: rendimiento medio {inventario.rendimiento_medio(nombre):.1%} "
            f"en {len(limpiezas)} limpieza(s) | merma media {merma / bruto:.1%}"
        )
    print("\n--- Historial ---")
    for limpieza in inventario.limpiezas:
        print(limpieza)


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
            precio_cobrado = pedir_precio_cobro(comensales)
            try:
                registro_servicios.agregar_servicio(
                    Servicio(fecha, hora, comensales, menu_nombre, notas, precio_cobrado=precio_cobrado)
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
            elif servicio.estado in ("completado", "cancelado"):
                print(f"❌ El servicio #{id_servicio} ya está {servicio.estado}.")
            else:
                filas = recetario.previsualizar_consumo(servicio, inventario)
                if filas is None:
                    print(f"⚠️  No se encontró el menú '{servicio.menu}' en el recetario.")
                    confirmar = pedir_si_no("¿Marcar como completado igualmente (sin tocar el inventario)?")
                    if confirmar:
                        servicio.completar()
                        print(f"✅ Servicio #{id_servicio} completado (sin descuento de stock).")
                        pedir_costes_adicionales(servicio)
                else:
                    elecciones = pedir_lotes_servicio(servicio, filas)
                    filas = recetario.previsualizar_consumo(servicio, inventario, elecciones)
                    # Primero enseñamos qué va a pasar, y solo después se aplica.
                    print(f"\nSe descontará para {servicio.comensales} comensales de '{servicio.menu}':")
                    for f in filas:
                        if not f["existe"]:
                            print(f"  ⚠️  {f['ingrediente']}: no existe en el inventario, no se descontará")
                        elif f["faltante"] > 0:
                            print(
                                f"  ⚠️  {f['ingrediente']}: necesario {f['necesario']} {f['unidad']}, "
                                f"solo hay {f['en_stock']} -> se descuenta todo (faltaban {f['faltante']})"
                            )
                        else:
                            print(f"  ✅ {f['ingrediente']}: -{round(f['a_descontar'], 3)} {f['unidad']}")
                        for lote_id, cantidad in f["reparto"]:
                            print(f"       · {round(cantidad, 3)} {f['unidad']} del lote {lote_id}")
                    if pedir_si_no("¿Confirmar y completar el servicio?"):
                        try:
                            recetario.completar_servicio(servicio, inventario, elecciones)
                            print(f"✅ Servicio #{id_servicio} completado.")
                            pedir_costes_adicionales(servicio)
                        except ValueError as e:
                            print(f"❌ {e}")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


def pedir_costes_adicionales(servicio: Servicio) -> None:
    """Costes no previstos del servicio (taxi, hielo...): se guardan como gastos de ese servicio."""
    while pedir_si_no("¿Hubo algún coste adicional no previsto?"):
        concepto = pedir_texto("  Concepto: ")
        categoria = pedir_opcion("  Categoría", Gasto.CATEGORIAS)
        importe = pedir_numero("  Importe (€): ")
        try:
            registro_gastos.agregar_gasto(Gasto(
                concepto, categoria, importe, servicio_id=servicio.id,
                notas="Coste no previsto, añadido al completar el servicio",
            ))
        except ValueError as e:
            print(f"❌ {e}")


def pedir_lotes_servicio(servicio: Servicio, filas: list[dict]) -> dict[str, list[int]]:
    """
    Para cada ingrediente con varios lotes, pregunta de qué lote sale. Si
    ese lote no llega, pregunta con qué otro lote se completa lo que falta
    (y así hasta cubrirlo). Devuelve {ingrediente: [lotes en orden]}.
    """
    elecciones: dict[str, list[int]] = {}
    for fila in filas:
        producto = inventario.buscar_producto(fila["ingrediente"])
        if (producto is None or fila["a_descontar"] <= 0 or len(producto.lotes) <= 1
                or fila["necesario"] >= fila["en_stock"] - 1e-9):
            continue
        ingrediente = fila["ingrediente"]
        print(f"\n{ingrediente}: hacen falta {round(fila['necesario'], 3)} {producto.unidad}. Lotes:")
        elegidos = [pedir_lote(producto, "¿De qué lote sale?").id]
        while True:
            _, pendiente = inventario.repartir(ingrediente, fila["necesario"], elegidos)
            restantes = [l for l in producto.lotes_ordenados() if l.id not in elegidos]
            if pendiente <= 1e-9 or not restantes:
                break
            print(f"Ese lote no llega: faltan {round(pendiente, 3)} {producto.unidad}. Lotes que quedan:")
            elegidos.append(pedir_lote(producto, "¿Con qué lote lo completas?", restantes, sugerir=False).id)
        elecciones[ingrediente] = elegidos
    return elecciones


# ---------- Menú: Recetario ----------

def pedir_consumibles_menu(actuales: Optional[dict] = None) -> dict:
    """Pide los consumibles por comensal de un menú (nombre vacío para terminar)."""
    consumibles = dict(actuales or {})
    if not inventario.consumibles():
        return consumibles
    print("Consumibles por comensal (servilletas, vasos desechables...). Nombre vacío para terminar.")
    print(f"Disponibles: {', '.join(p.nombre for p in inventario.consumibles())}")
    while True:
        nombre = pedir_texto("  Consumible: ")
        if not nombre:
            return consumibles
        producto = inventario.buscar_producto(nombre)
        if producto is None or not producto.es_consumible():
            print(f"⚠️  '{nombre}' no es un consumible del inventario.")
            continue
        cantidad = pedir_numero(f"  Cantidad por comensal ({producto.unidad}, 0 para quitarlo): ")
        if cantidad > 0:
            consumibles[producto.nombre] = cantidad
        else:
            consumibles.pop(producto.nombre, None)


def pedir_material_menu(actuales: Optional[dict] = None) -> dict:
    """Pide el material por comensal de un menú (nombre vacío para terminar)."""
    materiales = dict(actuales or {})
    if not registro_material.materiales:
        return materiales
    print("Material por comensal (platos, copas, cubiertos...). Nombre vacío para terminar.")
    print(f"Disponibles: {', '.join(registro_material.materiales)}")
    while True:
        nombre = pedir_texto("  Material: ")
        if not nombre:
            return materiales
        if nombre not in registro_material.materiales:
            print(f"⚠️  '{nombre}' no es un material registrado.")
            continue
        cantidad = pedir_numero("  Unidades por comensal (0 para quitarlo): ")
        if cantidad > 0:
            materiales[nombre] = cantidad
        else:
            materiales.pop(nombre, None)


def mostrar_detalle_menu(nombre_menu: str) -> None:
    menu = recetario.buscar_menu(nombre_menu)
    print(f"\n=== {menu.nombre} ===")
    for receta in menu.recetas:
        print(f"🍽️  {receta.nombre} ({receta.categoria}) - {receta.costo_por_comensal(inventario)}€/comensal")
        for nombre, cantidad in receta.ingredientes_por_comensal.items():
            producto = inventario.buscar_producto(nombre)
            print(f"     · {nombre}: {cantidad} {producto.unidad if producto else ''} por comensal")
    print("🧻 Consumibles:")
    if not menu.consumibles_por_comensal:
        print("     (ninguno)")
    for nombre, cantidad in menu.consumibles_por_comensal.items():
        producto = inventario.buscar_producto(nombre)
        print(f"     · {nombre}: {cantidad} {producto.unidad if producto else ''} por comensal")
    print("🍽️  Material (vuelve después del servicio):")
    if not menu.materiales_por_comensal:
        print("     (ninguno)")
    for nombre, cantidad in menu.materiales_por_comensal.items():
        print(f"     · {nombre}: {cantidad} por comensal")
    comida = menu.costo_por_comensal(inventario)
    consumibles = menu.costo_consumibles_por_comensal(inventario)
    print(f"Coste por comensal: comida {comida}€ + consumibles {consumibles}€ = {round(comida + consumibles, 2)}€")
    if inventario.consumibles() and pedir_si_no("¿Cambiar los consumibles de este menú?"):
        menu.consumibles_por_comensal = pedir_consumibles_menu(menu.consumibles_por_comensal)
    if registro_material.materiales and pedir_si_no("¿Cambiar el material de este menú?"):
        menu.materiales_por_comensal = pedir_material_menu(menu.materiales_por_comensal)


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
                ingredientes = ", ".join(f"{n} {round(c, 3)}" for n, c in m.ingredientes_por_comensal().items())
                print(f"{m.nombre} | Comida: {m.costo_por_comensal(inventario)}€/comensal | Ingredientes por comensal: {ingredientes}")
            if recetario.menus and pedir_si_no("¿Ver el detalle de algún menú?"):
                mostrar_detalle_menu(pedir_opcion("Menú", tuple(recetario.menus)))
        elif opcion == "3":
            nombre = pedir_texto("Nombre de la receta: ")
            categoria = pedir_texto("Categoría: ")
            ingredientes = {}
            if not inventario.alimentos():
                print("⚠️  No hay alimentos en el inventario. Añade productos primero (menú Inventario).")
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
                if producto.es_consumible():
                    print(f"⚠️  '{ing}' es un consumible: los consumibles se añaden al menú, no a la receta.")
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
                    recetario.agregar_menu(Menu(nombre_menu, recetas_menu, pedir_consumibles_menu(), pedir_material_menu()))
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
                producto = inventario.buscar_producto(nombre)
                if producto is None:
                    print(f"❌ '{nombre}' no existe en el inventario: créalo antes.")
                else:
                    # Comprarlo implica que ahora está físicamente en el almacén
                    # -- entra en el inventario en el mismo paso, como un lote
                    # nuevo. entrada_stock() ya lo registra en el historial (y
                    # por tanto en las métricas de gasto) automáticamente.
                    lote = inventario.entrada_stock(nombre, cantidad_real, **pedir_datos_entrada(producto))
                    if lote is not None:
                        gestor_compras.marcar_comprado(nombre, cantidad_comprada=cantidad_real)
                        print(f"📦 Stock repuesto: +{cantidad_real} {unidad} de {nombre} ({lote.etiqueta()})")
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
    ruta = exportar_todo(
        inventario, registro_servicios, gestor_compras, carpeta_datos, registro_gastos, recetario, registro_material,
    )
    ultima_exportacion = ruta
    print(f"✅ Exportado a: {ruta}")


def accion_guardar_sesion():
    guardar_sesion(
        inventario, registro_servicios, recetario, gestor_compras, archivo_informes, RUTA_SESION, registro_gastos,
        registro_material,
    )


def accion_cargar_sesion():
    # `global` es necesario aquí porque vamos a REEMPLAZAR estas variables
    # por objetos nuevos (los que salen de cargar_sesion), no solo a leerlas
    # o modificar algo dentro de ellas. Sin `global`, Python entendería que
    # estamos creando variables LOCALES nuevas dentro de esta función, y
    # las de fuera (las que usa el resto del programa) no cambiarían.
    global inventario, registro_servicios, recetario, gestor_compras, dashboard, archivo_informes, registro_gastos
    global registro_material

    sesion = cargar_sesion(RUTA_SESION)
    if sesion is None:
        return

    inventario, registro_servicios, recetario = sesion.inventario, sesion.registro_servicios, sesion.recetario
    gestor_compras, archivo_informes, registro_gastos = sesion.gestor_compras, sesion.archivo_informes, sesion.registro_gastos
    registro_material = sesion.registro_material
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
    # Fechas relativas a hoy, para que los datos de ejemplo no "caduquen" con el tiempo.
    hoy = date.today()
    inventario.agregar_producto(Producto(
        "Tomate", "Verduras", 0.5, "kg", 2.1, "Huerta Local", stock_minimo=2, fecha_caducidad=hoy + timedelta(days=1)
    ))
    # Producto con merma comprado por unidades: 2 patas de ~7 kg en bruto, a 45 € cada una.
    inventario.agregar_producto(Producto(
        "Pata de cerdo", "Carnes", 2, "unidades", 45, "Carnicería Pepe", tiene_merma=True, peso_unitario=7
    ))
    # Producto con DOS lotes: dos compras con distinta caducidad, proveedor y precio.
    secreto = Producto(
        "Secreto ibérico", "Carnes", 1, "kg", 14, "Carnicería Pepe", stock_minimo=0.5,
        fecha_caducidad=hoy + timedelta(days=3),
    )
    secreto.nuevo_lote(0.8, 15, "Ibéricos Sierra", hoy + timedelta(days=9), procedencia="inicial")
    inventario.agregar_producto(secreto)
    # Consumibles: se gastan pero no se comen (lista aparte, sin caducidad).
    inventario.agregar_producto(Producto(
        "Servilletas de papel", "Desechables", 500, "unidades", 0.02, "Hostelería Total", stock_minimo=200,
        tipo="consumible",
    ))
    inventario.agregar_producto(Producto(
        "Vasos desechables", "Desechables", 150, "unidades", 0.05, "Hostelería Total", stock_minimo=100,
        tipo="consumible",
    ))

    registro_servicios.agregar_servicio(Servicio(hoy + timedelta(days=3), time(21, 0), 8, "Menú del día"))
    registro_servicios.agregar_servicio(Servicio(hoy + timedelta(days=16), time(21, 0), 12, "Menú de bodas"))

    pan_casero = Receta("Pan casero", "Panadería", {"Harina de trigo": 0.15, "Aceite de oliva": 0.01})
    ensalada = Receta("Ensalada de tomate", "Entrantes", {"Tomate": 0.1, "Aceite de oliva": 0.005})
    recetario.agregar_receta(pan_casero)
    recetario.agregar_receta(ensalada)
    # Material reutilizable: sale a los servicios y vuelve.
    for nombre, categoria, unidades, precio in (
        ("Plato llano", "Vajilla", 60, 3.5), ("Copa de vino", "Cristalería", 48, 2.8), ("Tenedor", "Cubertería", 80, 1.2),
    ):
        if nombre not in registro_material.materiales:
            registro_material.agregar_material(Material(nombre, categoria, unidades, precio, "Hostelería Total"))
    recetario.agregar_menu(Menu(
        "Menú del día", [pan_casero, ensalada], {"Servilletas de papel": 2, "Vasos desechables": 1},
        {"Plato llano": 2, "Copa de vino": 1, "Tenedor": 1},
    ))

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
        print("9. Merma y rendimiento de las limpiezas")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion in ("1", "2", "3", "4", "5", "9"):
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
        elif opcion == "9":
            resumen = metricas.resumen_limpiezas(desde, hasta)
            if not resumen:
                print("No hay limpiezas registradas en ese periodo.")
            for nombre, fila in resumen.items():
                print(
                    f"{nombre}: {fila['limpiezas']} limpieza(s) | bruto {fila['bruto_kg']} kg -> "
                    f"limpio {fila['limpio_kg']} kg ({fila['rendimiento']:.1%}) | "
                    f"derivados {fila['derivados_kg']} kg | merma {fila['merma_kg']} kg"
                )
            if resumen:
                print(f"🦴 Merma total ({periodo}): {metricas.merma_total_kg(desde, hasta)} kg")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


def pedir_precio_cobro(comensales: int) -> Optional[float]:
    """Precio de cobro de un servicio: opcional. Devuelve el total del servicio, o None si no se indica."""
    precio = pedir_numero_opcional("Precio de cobro en € (opcional, vacío para no indicarlo): ")
    if not precio:
        return None
    forma = pedir_opcion("¿Ese precio es el total o por comensal?", ("total", "comensal"))
    return round(precio * comensales, 2) if forma == "comensal" else precio


def pedir_servicio_opcional() -> Optional[int]:
    """Número de servicio al que asociar algo, o None para 'general'."""
    for s in sorted(registro_servicios.servicios, key=lambda s: (s.fecha, s.hora)):
        if s.estado != "cancelado":
            print(f"   {s}")
    while True:
        valor = input("Nº de servicio (vacío = gasto general del negocio): ").strip().lstrip("#")
        if valor == "":
            return None
        if valor.isdigit() and registro_servicios.buscar_por_id(int(valor)):
            return int(valor)
        print("⚠️  Escribe el número de uno de los servicios de la lista, o déjalo vacío.")


def texto_euros(valor) -> str:
    return "—" if valor is None else f"{valor:.2f}€"


def menu_gastos():
    while True:
        print("\n--- GASTOS Y RENTABILIDAD ---")
        print("1. Registrar gasto (gasolina, personal, alquiler...)")
        print("2. Ver gastos")
        print("3. Eliminar un gasto")
        print("4. Rentabilidad de los servicios")
        print("5. Poner o cambiar el precio de cobro de un servicio")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")

        if opcion == "1":
            concepto = pedir_texto("Concepto (ej: Gasolina boda García): ")
            categoria = pedir_opcion("Categoría", Gasto.CATEGORIAS)
            importe = pedir_numero("Importe (€): ")
            fecha = pedir_fecha("Fecha") if pedir_si_no("¿Es de otro día (no de hoy)?") else None
            servicio_id = pedir_servicio_opcional()
            notas = pedir_texto("Notas (opcional): ")
            try:
                registro_gastos.agregar_gasto(Gasto(concepto, categoria, importe, fecha, servicio_id, notas))
            except ValueError as e:
                print(f"❌ {e}")
        elif opcion == "2":
            periodo = pedir_opcion("Periodo", PERIODOS_VALIDOS)
            desde, hasta = rango_desde_periodo(periodo)
            lista = registro_gastos.gastos_en_rango(desde, hasta)
            if not lista:
                print("No hay gastos en ese periodo.")
            for g in lista:
                print(g)
            for categoria, total in registro_gastos.total_por_categoria(desde, hasta).items():
                print(f"   {categoria}: {total:.2f}€")
        elif opcion == "3":
            for g in registro_gastos.gastos:
                print(g)
            if registro_gastos.gastos:
                registro_gastos.eliminar_gasto(pedir_entero("Nº del gasto a eliminar: "))
        elif opcion == "4":
            servicios = [s for s in registro_servicios.servicios if s.estado != "cancelado"]
            if not servicios:
                print("No hay servicios.")
            for s in sorted(servicios, key=lambda s: (s.fecha, s.hora)):
                r = resumen_servicio(s, inventario, recetario, registro_gastos, registro_material)
                estimado = " (estimado)" if r["estimado"] else ""
                porcentaje = f" ({r['margen_porcentaje']:.0%})" if r["margen_porcentaje"] is not None else ""
                print(
                    f"#{s.id} {s.fecha.strftime('%d/%m/%Y')} {s.menu}: coste {texto_euros(r['coste_total'])}{estimado} "
                    f"[comida {r['comida']:.2f} + consumibles {r['consumibles']:.2f} + gastos {r['gastos']:.2f} "
                    f"+ material roto/perdido {r['material']:.2f}] | "
                    f"cobro {texto_euros(r['cobrado'])} | margen {texto_euros(r['margen'])}{porcentaje}"
                )
        elif opcion == "5":
            id_servicio = pedir_entero("Nº del servicio: ")
            servicio = registro_servicios.buscar_por_id(id_servicio)
            if servicio is None:
                print(f"❌ No existe el servicio #{id_servicio}")
            else:
                print(f"Precio actual: {texto_euros(servicio.precio_cobrado)}")
                servicio.precio_cobrado = pedir_precio_cobro(servicio.comensales)
                print(f"✅ Precio de cobro: {texto_euros(servicio.precio_cobrado)}")
        elif opcion == "0":
            return
        else:
            print("⚠️  Opción no válida.")
        pausa()


def listar_material() -> None:
    if not registro_material.materiales:
        print("No hay material registrado.")
    for m in registro_material.materiales.values():
        print(
            f"{m.nombre} ({m.categoria}) | total {m.cantidad_total} | en uso {registro_material.en_uso(m.nombre)} | "
            f"disponibles {registro_material.disponibles(m.nombre)} | reposición {m.precio_reposicion}€/ud"
        )
    for salida in registro_material.salidas:
        if not salida.ha_vuelto:
            print(f"🚚 Fuera en el servicio #{salida.servicio_id}: {salida.cantidades}")


def pedir_material_existente() -> Optional[str]:
    nombre = pedir_texto("Material: ")
    if nombre not in registro_material.materiales:
        print(f"❌ No existe el material '{nombre}'.")
        return None
    return nombre


def menu_material():
    while True:
        print("\n--- MATERIAL ---")
        print("1. Ver material (total, en uso y disponible)")
        print("2. Añadir material")
        print("3. Editar material")
        print("4. He comprado más / se ha roto o perdido en el almacén")
        print("5. Salida de material a un servicio (lista de carga)")
        print("6. Vuelta del material de un servicio")
        print("7. Ver roturas y pérdidas")
        print("0. Volver")
        opcion = pedir_texto("Elige una opción: ")
        try:
            if opcion == "1":
                listar_material()
            elif opcion == "2":
                nombre = pedir_texto("Nombre: ")
                categoria = pedir_texto_no_numerico("Categoría (ej: Vajilla): ")
                unidades = pedir_entero("Unidades que tienes: ")
                precio = pedir_numero("Precio de reposición (€ por unidad): ")
                proveedor = pedir_texto("Proveedor (opcional): ")
                registro_material.agregar_material(Material(nombre, categoria, unidades, precio, proveedor))
            elif opcion == "3":
                nombre = pedir_material_existente()
                if nombre:
                    m = registro_material.buscar(nombre)
                    print("Deja vacío lo que no cambie.")
                    nuevo = pedir_texto(f"Nombre [{m.nombre}]: ") or None
                    categoria = pedir_texto_no_numerico_opcional(f"Categoría [{m.categoria}]: ")
                    total = pedir_numero_opcional(f"Unidades totales [{m.cantidad_total}]: ")
                    precio = pedir_numero_opcional(f"Precio de reposición [{m.precio_reposicion}]: ")
                    if registro_material.editar_material(
                        nombre, nuevo, categoria, int(total) if total is not None else None, precio,
                    ) and nuevo and nuevo != nombre:
                        recetario.renombrar_material(nombre, nuevo)
            elif opcion == "4":
                nombre = pedir_material_existente()
                if nombre:
                    accion = pedir_opcion("¿Qué ha pasado?", ("comprado", "rotura", "pérdida"))
                    unidades = pedir_entero("Unidades: ")
                    if accion == "comprado":
                        registro_material.reponer(nombre, unidades)
                    else:
                        registro_material.dar_de_baja(nombre, unidades, accion)
            elif opcion == "5":
                id_servicio = pedir_entero("Nº del servicio: ")
                servicio = registro_servicios.buscar_por_id(id_servicio)
                if servicio is None:
                    print(f"❌ No existe el servicio #{id_servicio}")
                else:
                    menu = recetario.buscar_menu(servicio.menu)
                    sugerida = lista_de_carga(menu.materiales_por_comensal, servicio.comensales) if menu else {}
                    print("Lista de carga (Enter = la cantidad propuesta por el menú):")
                    carga = {}
                    for m in registro_material.materiales.values():
                        propuesta = sugerida.get(m.nombre, 0)
                        valor = pedir_numero_opcional(
                            f"  {m.nombre} [{propuesta}] (disponibles {registro_material.disponibles(m.nombre)}): "
                        )
                        carga[m.nombre] = int(propuesta if valor is None else valor)
                    registro_material.registrar_salida(id_servicio, carga)
            elif opcion == "6":
                id_servicio = pedir_entero("Nº del servicio: ")
                salida = registro_material.salida_de(id_servicio)
                if salida is None:
                    print(f"❌ El servicio #{id_servicio} no tiene material fuera.")
                else:
                    vuelto, rotos = {}, {}
                    for nombre, salio in salida.cantidades.items():
                        valor = pedir_numero_opcional(f"  {nombre}: salieron {salio}. ¿Cuántos han vuelto? [{salio}]: ")
                        vuelto[nombre] = salio if valor is None else int(valor)
                        faltan = salio - vuelto[nombre]
                        if faltan > 0:
                            rotos[nombre] = pedir_entero(f"    Faltan {faltan}. ¿Cuántos se han roto? (el resto, perdidos): ")
                    incidencias = registro_material.registrar_vuelta(id_servicio, vuelto, rotos)
                    if incidencias:
                        print(f"Coste de roturas y pérdidas: {sum(i.coste for i in incidencias):.2f}€")
            elif opcion == "7":
                if not registro_material.incidencias:
                    print("No hay roturas ni pérdidas registradas.")
                for i in registro_material.incidencias:
                    print(i)
            elif opcion == "0":
                return
            else:
                print("⚠️  Opción no válida.")
        except ValueError as e:
            print(f"❌ {e}")
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
        print("12. Gastos y rentabilidad")
        print("13. Material (vajilla, cubertería...)")
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
        elif opcion == "12":
            menu_gastos()
        elif opcion == "13":
            menu_material()
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
