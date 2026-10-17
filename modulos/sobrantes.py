"""
Módulo: sobrantes.py
--------------------------
Lo que SOBRA de un servicio y se decide tirar, aunque esté en buen estado,
porque no se va a aprovechar (en un catering con poca demanda es lo normal).

Es distinto de:
- el DESPERDICIO: algo que caducó o se estropeó en el almacén (se "pasó").
  No se carga a ningún servicio.
- la MERMA: lo que se pierde al limpiar (huesos, pieles...).

Un sobrante es una salida de stock normal (motivo "sobrante") ligada a su
servicio: así el inventario nunca se desajusta (entradas - salidas = stock),
y su coste cuenta en la rentabilidad de ese servicio. Las raciones ya
preparadas que sobran salen de su tanda igual (UsoTanda "sobrante").

Este módulo no guarda cifras propias: todos los totales y porcentajes se
calculan cada vez a partir de esas salidas. Si un sobrante se anula (por un
error al apuntarlo), su cantidad vuelve a su mismo lote o tanda y el registro
pasa a la lista de anulados, con la fecha: deja de contar, pero queda constancia.
"""

from datetime import date, timedelta
from typing import Optional, Union

from inventario import Inventario, MovimientoStock, _numero
from elaboraciones import UsoTanda
from servicios import Servicio

TIPOS_CON_SOBRANTE = ("alimento", "consumible")
Registro = Union[MovimientoStock, UsoTanda]


def nombre_preparada(receta: str) -> str:
    return f"{receta} (preparada)"


def _coste(registro: Registro, sin_iva: bool) -> float:
    if isinstance(registro, UsoTanda):
        return registro.coste_sin_iva if sin_iva else registro.coste
    return registro.valor_sin_iva() if sin_iva else registro.valor()


# ---------- Lo que hay registrado ----------

def salidas_sobrante(inventario: Inventario, servicio_id: Optional[int] = None) -> list[MovimientoStock]:
    """Los productos tirados como sobrante (de un servicio, o de todos si no se indica)."""
    return [m for m in inventario.historial if m.tipo == "salida" and m.motivo == "sobrante"
            and (servicio_id is None or m.servicio_id == servicio_id)]


def usos_sobrante(inventario: Inventario, servicio_id: Optional[int] = None) -> list[UsoTanda]:
    """Las raciones preparadas tiradas como sobrante (de un servicio, o de todos)."""
    return [u for u in inventario.elaboraciones.usos if u.motivo == "sobrante"
            and (servicio_id is None or u.servicio_id == servicio_id)]


def registros_servicio(inventario: Inventario, servicio_id: int) -> list[Registro]:
    """Cada sobrante apuntado para un servicio (raciones primero, luego productos)."""
    return [*usos_sobrante(inventario, servicio_id), *salidas_sobrante(inventario, servicio_id)]


def anulados_servicio(inventario: Inventario, servicio_id: int) -> list[Registro]:
    return [r for r in [*inventario.elaboraciones.sobrantes_anulados, *inventario.sobrantes_anulados]
            if r.servicio_id == servicio_id]


def usado_en_servicio(inventario: Inventario, servicio_id: int) -> dict[str, float]:
    """
    Lo que se CONSUMIÓ en el servicio al completarlo, por producto (y las
    raciones preparadas como "<receta> (preparada)"). Es la base del
    porcentaje: tirado / (consumido + tirado).
    """
    usado: dict[str, float] = {}
    for m in inventario.historial:
        if m.servicio_id == servicio_id and m.tipo == "salida" and m.motivo == "consumo" \
                and m.tipo_producto in TIPOS_CON_SOBRANTE:
            usado[m.producto_nombre] = round(usado.get(m.producto_nombre, 0) + m.cantidad, 6)
    for u in inventario.elaboraciones.usos_de_servicio(servicio_id):
        clave = nombre_preparada(u.receta)
        usado[clave] = round(usado.get(clave, 0) + u.raciones, 6)
    return usado


def _coste_consumido(inventario: Inventario, servicio_id: int, sin_iva: bool,
                     tipos: tuple = TIPOS_CON_SOBRANTE) -> float:
    """Coste de lo CONSUMIDO en el servicio (sin los sobrantes): comida y consumibles, o solo los `tipos` indicados."""
    total = sum(m.valor_sin_iva() if sin_iva else m.valor() for m in inventario.historial
                if m.servicio_id == servicio_id and m.tipo == "salida" and m.motivo == "consumo"
                and m.tipo_producto in tipos)
    if "alimento" in tipos:  # las raciones preparadas son comida
        total += inventario.elaboraciones.coste_servicio(servicio_id, sin_iva=sin_iva)
    return round(total, 2)


def _tipo_registro(registro: Registro) -> str:
    """"alimento" o "consumible" (las raciones preparadas son alimento)."""
    return "alimento" if isinstance(registro, UsoTanda) else registro.tipo_producto


def _porcentaje(tirado: float, usado: float) -> Optional[float]:
    """Parte de lo dedicado al servicio que se tiró. None si en el servicio no se consumió nada de eso."""
    if usado <= 1e-9:
        return None
    return tirado / (usado + tirado)


def resumen_servicio(servicio: Servicio, inventario: Inventario) -> dict:
    """
    Los sobrantes de un servicio, listos para mostrar:
    - filas: una por producto o receta preparada: cantidad tirada, unidad,
      coste y porcentaje de lo dedicado al servicio (consumido + tirado).
    - registros: cada sobrante apuntado (para poder anularlo).
    - total: su coste; porcentaje_coste: qué parte del coste de comida y
      consumibles del servicio (consumido + tirado) se tiró.
    - anulados: los que se anularon (solo constancia).
    El coste sigue el criterio de la rentabilidad: sin IVA si se recupera.
    """
    sin_iva = inventario.iva_recuperable
    usado = usado_en_servicio(inventario, servicio.id)
    agrupado: dict[str, dict] = {}
    registros = registros_servicio(inventario, servicio.id)
    for r in registros:
        if isinstance(r, UsoTanda):
            nombre, unidad, cantidad = nombre_preparada(r.receta), "raciones", r.raciones
        else:
            nombre, unidad, cantidad = r.producto_nombre, r.unidad, r.cantidad
        fila = agrupado.setdefault(nombre, {"producto": nombre, "cantidad": 0.0, "unidad": unidad, "coste": 0.0})
        fila["cantidad"] = round(fila["cantidad"] + cantidad, 6)
        fila["coste"] = round(fila["coste"] + _coste(r, sin_iva), 2)
    filas = sorted(agrupado.values(), key=lambda f: f["coste"], reverse=True)
    for fila in filas:
        fila["usado"] = round(usado.get(fila["producto"], 0.0), 6)
        fila["porcentaje"] = _porcentaje(fila["cantidad"], fila["usado"])
    total = round(sum(f["coste"] for f in filas), 2)
    consumido = _coste_consumido(inventario, servicio.id, sin_iva)
    return {
        "filas": filas,
        "registros": registros,
        "total": total,
        "porcentaje_coste": total / (consumido + total) if (consumido + total) > 0 and total > 0 else None,
        "anulados": anulados_servicio(inventario, servicio.id),
        "sin_iva": sin_iva,
    }


def descripcion(registro: Registro) -> str:
    """Una línea legible de un sobrante: '17/10/2026 · 2 kg de Salmón · Lote 1 · cad. ...'."""
    if isinstance(registro, UsoTanda):
        texto = f"{_numero(registro.raciones)} raciones de {nombre_preparada(registro.receta)} · Tanda {registro.tanda_id}"
    else:
        texto = f"{_numero(registro.cantidad)} {registro.unidad} de {registro.producto_nombre} · {registro.lote or 'sin lote'}"
    return f"{registro.fecha.strftime('%d/%m/%Y')} · {texto}"


# ---------- Qué se puede tirar ----------

def _lotes_en_orden(inventario: Inventario, nombre: str, servicio_id: int) -> list[int]:
    """Primero los lotes de los que salió el consumo del servicio; luego el resto, el que caduca antes primero."""
    producto = inventario.productos[nombre]
    usados = []
    for m in inventario.historial:
        if m.servicio_id == servicio_id and m.producto_nombre == nombre and m.tipo == "salida" \
                and m.lote_id is not None and m.lote_id not in usados and producto.buscar_lote(m.lote_id):
            usados.append(m.lote_id)
    return usados + [l.id for l in producto.lotes_para_usar() if l.id not in usados]


def _tandas_en_orden(inventario: Inventario, receta: str, servicio_id: int) -> list[int]:
    reg = inventario.elaboraciones
    usadas = []
    for u in reg.usos_de_servicio(servicio_id):
        if u.receta == receta and u.tanda_id not in usadas and reg.buscar(u.tanda_id):
            usadas.append(u.tanda_id)
    return usadas + [t.id for t in reg.tandas_de(receta) if t.id not in usadas]


def candidatos(servicio: Servicio, inventario: Inventario) -> list[dict]:
    """
    Lo que tiene sentido revisar al volver de un servicio: los productos
    (alimentos y consumibles) que se consumieron en él y las raciones
    preparadas de las recetas de su menú, siempre que quede algo en el
    inventario. Cada uno: {"tipo": "producto"/"preparada", "clave" (nombre
    del producto o de la receta), "nombre", "unidad", "disponible", "usado"
    (consumido en el servicio) y "tirado" (ya apuntado como sobrante)}.
    """
    usado = usado_en_servicio(inventario, servicio.id)
    tirado: dict[str, float] = {}
    for r in registros_servicio(inventario, servicio.id):
        clave = nombre_preparada(r.receta) if isinstance(r, UsoTanda) else r.producto_nombre
        tirado[clave] = round(tirado.get(clave, 0) + (r.raciones if isinstance(r, UsoTanda) else r.cantidad), 6)

    # Productos: los que salieron del inventario para este servicio (si un
    # ingrediente no salió, por ejemplo porque se usaron raciones ya
    # preparadas, lo que queda de él no es sobra del servicio). Raciones: las
    # de las recetas del menú que aún queden en alguna tanda.
    foto = servicio.menu_completado or {}
    recetas = [r["nombre"] for r in foto.get("recetas", [])]
    productos: list[str] = [n for n in usado if not n.endswith(" (preparada)")]
    recetas += [n[: -len(" (preparada)")] for n in usado if n.endswith(" (preparada)")]

    filas = []
    for receta in dict.fromkeys(recetas):
        disponible = inventario.elaboraciones.raciones_disponibles(receta)
        if disponible > 1e-9:
            clave = nombre_preparada(receta)
            filas.append({"tipo": "preparada", "clave": receta, "nombre": clave, "unidad": "raciones",
                          "disponible": disponible, "usado": usado.get(clave, 0.0), "tirado": tirado.get(clave, 0.0)})
    for nombre in dict.fromkeys(productos):
        producto = inventario.productos.get(nombre)
        if producto is None or producto.tipo not in TIPOS_CON_SOBRANTE or producto.stock <= 1e-9:
            continue
        filas.append({"tipo": "producto", "clave": nombre, "nombre": nombre, "unidad": producto.unidad,
                      "disponible": round(producto.stock, 6), "usado": usado.get(nombre, 0.0),
                      "tirado": tirado.get(nombre, 0.0)})
    return filas


def otros_productos(servicio: Servicio, inventario: Inventario) -> list[str]:
    """Productos con stock (alimentos y consumibles) que no salen en candidatos(): por si se llevó algo más."""
    ya = {c["clave"] for c in candidatos(servicio, inventario) if c["tipo"] == "producto"}
    return sorted(n for n, p in inventario.productos.items()
                  if n not in ya and p.tipo in TIPOS_CON_SOBRANTE and p.stock > 1e-9)


# ---------- Previsualizar y registrar ----------

def _necesidades_proximas(registro_servicios, recetario, hoy: date, dias: int = 30) -> list[tuple[Servicio, dict]]:
    if registro_servicios is None or recetario is None:
        return []
    proximos = sorted((s for s in registro_servicios.servicios
                       if hoy <= s.fecha <= hoy + timedelta(days=dias) and s.estado in ("pendiente", "confirmado")),
                      key=lambda s: (s.fecha, s.hora))
    resultado = []
    for s in proximos:
        menu = recetario.buscar_menu(s.menu)
        if menu is not None:
            resultado.append((s, menu))
    return resultado


def previsualizar(
    servicio: Servicio, inventario: Inventario, productos: Optional[dict[str, float]] = None,
    raciones: Optional[dict[str, float]] = None, registro_servicios=None, recetario=None,
) -> dict:
    """
    Comprueba (SIN tocar nada) cómo quedaría tirar como sobrante `productos`
    ({nombre: cantidad}) y `raciones` ({receta: raciones}) de un servicio.
    Devuelve {"filas": [...], "problemas": [...], "avisos": [...]}:
    - cada fila: tipo, nombre, cantidad, unidad, reparto [(lote o tanda, cantidad)],
      antes, despues, coste (criterio de la rentabilidad).
    - problemas: lo que impide registrarlo (si hay alguno, no se registra NADA).
    - avisos: servicios próximos que necesitan ese producto o esa receta.
    """
    productos = {n: c for n, c in (productos or {}).items() if c}
    raciones = {n: c for n, c in (raciones or {}).items() if c}
    sin_iva = inventario.iva_recuperable
    filas, problemas, avisos = [], [], []
    if servicio.estado != "completado":
        problemas.append(f"El servicio #{servicio.id} no está completado: los sobrantes se apuntan al completarlo o después.")

    for receta, cantidad in raciones.items():
        if cantidad < 0:
            problemas.append(f"'{nombre_preparada(receta)}': la cantidad no puede ser negativa.")
            continue
        reg = inventario.elaboraciones
        disponible = reg.raciones_disponibles(receta)
        if cantidad > disponible + 1e-6:
            problemas.append(f"Según el inventario solo quedan {_numero(disponible)} raciones de "
                             f"{nombre_preparada(receta)}, y quieres tirar {_numero(cantidad)}. Si de verdad sobraron "
                             f"más, puede que falte por apuntar alguna tanda preparada.")
            continue
        reparto, _ = reg.repartir(receta, cantidad, _tandas_en_orden(inventario, receta, servicio.id))
        coste = sum(r * (reg.buscar(t).coste_por_racion_sin_iva if sin_iva else reg.buscar(t).coste_por_racion)
                    for t, r in reparto)
        filas.append({"tipo": "preparada", "clave": receta, "nombre": nombre_preparada(receta), "cantidad": cantidad,
                      "unidad": "raciones", "reparto": reparto, "antes": disponible,
                      "despues": round(disponible - cantidad, 6), "coste": round(coste, 2),
                      "texto_reparto": ", ".join(f"{_numero(r)} raciones de la tanda {t}" for t, r in reparto)})

    for nombre, cantidad in productos.items():
        producto = inventario.productos.get(nombre)
        if producto is None:
            problemas.append(f"No existe el producto '{nombre}'.")
            continue
        if producto.tipo not in TIPOS_CON_SOBRANTE:
            problemas.append(f"'{nombre}' es de limpieza o mantenimiento: no se apunta como sobrante.")
            continue
        if cantidad < 0:
            problemas.append(f"'{nombre}': la cantidad no puede ser negativa.")
            continue
        if cantidad > producto.stock + 1e-6:
            problemas.append(f"Según el inventario solo quedan {_numero(producto.stock)} {producto.unidad} de "
                             f"{nombre}, y quieres tirar {_numero(cantidad)}. Si de verdad sobró más, puede que falte "
                             f"alguna compra por registrar.")
            continue
        reparto, falta = inventario.repartir(nombre, cantidad, _lotes_en_orden(inventario, nombre, servicio.id))
        if falta > 1e-6:  # no debería pasar (la cantidad cabe en el stock), pero por si acaso
            problemas.append(f"No se ha podido repartir la cantidad de '{nombre}' entre sus lotes.")
            continue
        error = inventario.problema_salida(nombre, reparto, "sobrante")
        if error:
            problemas.append(error)
            continue
        coste = sum(c * (producto.buscar_lote(l).precio_base if sin_iva else producto.buscar_lote(l).precio_unitario)
                    for l, c in reparto)
        filas.append({"tipo": "producto", "clave": nombre, "nombre": nombre, "cantidad": cantidad,
                      "unidad": producto.unidad, "reparto": reparto, "antes": round(producto.stock, 6),
                      "despues": round(producto.stock - cantidad, 6), "coste": round(coste, 2),
                      "texto_reparto": ", ".join(f"{_numero(c)} {producto.unidad} del lote {l}" for l, c in reparto)})

    if not filas and not problemas:
        problemas.append("No has indicado nada que tirar.")

    # Avisos: si un servicio próximo necesita lo que se va a tirar.
    hoy = date.today()
    for s, menu in _necesidades_proximas(registro_servicios, recetario, hoy):
        necesidades = menu.calcular_necesidades_totales(s.comensales)
        recetas_menu = {r.nombre for r in menu.recetas}
        for f in filas:
            if f["tipo"] == "producto" and necesidades.get(f["clave"], 0) > f["despues"] + 1e-9:
                avisos.append(f"Ojo: el servicio del {s.fecha.strftime('%d/%m/%Y')} ({s.menu}) necesita "
                              f"{_numero(necesidades[f['clave']])} {f['unidad']} de {f['clave']}. Si tiras esto, "
                              f"quedarán {_numero(f['despues'])} y tendrás que comprar más.")
            elif f["tipo"] == "preparada" and f["clave"] in recetas_menu:
                avisos.append(f"Ojo: el servicio del {s.fecha.strftime('%d/%m/%Y')} ({s.menu}) lleva "
                              f"{f['clave']}: quizá se puedan aprovechar esas raciones si aguantan hasta entonces.")
    return {"filas": filas, "problemas": problemas, "avisos": list(dict.fromkeys(avisos))}


def registrar(
    servicio: Servicio, inventario: Inventario, productos: Optional[dict[str, float]] = None,
    raciones: Optional[dict[str, float]] = None,
) -> list[Registro]:
    """
    Tira como sobrante de `servicio` lo indicado (ver previsualizar). TODO O
    NADA: se comprueba todo antes de tocar nada; si algo falla, lanza
    ValueError y no se registra ninguna línea. Devuelve los registros creados.
    """
    plan = previsualizar(servicio, inventario, productos, raciones)
    if plan["problemas"]:
        raise ValueError("No se ha apuntado nada (no se ha tocado el inventario): " + " ".join(plan["problemas"]))
    creados: list[Registro] = []
    reg = inventario.elaboraciones
    for f in plan["filas"]:
        if f["tipo"] == "preparada":
            for tanda_id, cantidad in f["reparto"]:
                creados.append(reg._sacar(reg.buscar(tanda_id), cantidad, "sobrante", servicio.id))
        else:
            antes = len(inventario.historial)
            inventario.salida_repartida(f["clave"], f["reparto"], "sobrante", servicio.id)
            creados += inventario.historial[antes:]
    print(f"🗑️  Sobrante del servicio #{servicio.id} apuntado ({len(creados)} línea(s)).")
    return creados


# ---------- Anular ----------

def _problema_anular(inventario: Inventario, registro: Registro) -> Optional[str]:
    if isinstance(registro, UsoTanda):
        if not any(u is registro for u in inventario.elaboraciones.usos) or registro.motivo != "sobrante":
            return "Ese sobrante ya no está apuntado (¿ya se anuló?)."
        return None
    if not any(m is registro for m in inventario.historial) or registro.motivo != "sobrante":
        return "Ese sobrante ya no está apuntado (¿ya se anuló?)."
    if registro.producto_nombre not in inventario.productos:
        return (f"El producto '{registro.producto_nombre}' ya no existe en el inventario, así que no se le puede "
                f"devolver lo tirado.")
    return None


def anular(inventario: Inventario, registro: Registro, fecha: Optional[date] = None) -> None:
    """
    Anula un sobrante apuntado por error: su cantidad vuelve a su MISMO lote
    (o tanda), con su caducidad y su precio, aunque se hubiera gastado entero.
    El registro sale de los movimientos (deja de contar en todo) y se guarda
    en la lista de anulados con la fecha de anulación.
    """
    error = _problema_anular(inventario, registro)
    if error:
        raise ValueError(error)
    _anular_sin_comprobar(inventario, registro, fecha or date.today())


def _anular_sin_comprobar(inventario: Inventario, registro: Registro, fecha: date) -> None:
    if isinstance(registro, UsoTanda):
        reg = inventario.elaboraciones
        reg._devolver_a_tandas([registro])
        reg.usos = [u for u in reg.usos if u is not registro]
        registro.anulado = fecha
        reg.sobrantes_anulados.append(registro)
        return
    producto = inventario.productos[registro.producto_nombre]
    lote = producto.buscar_lote(registro.lote_id) if registro.lote_id is not None else None
    if lote is None:
        lote = inventario._recrear_lote(producto, registro)
    lote.cantidad = round(lote.cantidad + registro.cantidad, 6)
    inventario.historial = [m for m in inventario.historial if m is not registro]
    registro.anulado = fecha
    inventario.sobrantes_anulados.append(registro)


def anular_servicio(inventario: Inventario, servicio_id: int, fecha: Optional[date] = None) -> int:
    """Anula TODOS los sobrantes de un servicio (al deshacerlo). Todo o nada. Devuelve cuántos."""
    registros = registros_servicio(inventario, servicio_id)
    problemas = [p for p in (_problema_anular(inventario, r) for r in registros) if p]
    if problemas:
        raise ValueError(" ".join(dict.fromkeys(problemas)))
    for r in registros:
        _anular_sin_comprobar(inventario, r, fecha or date.today())
    return len(registros)


# ---------- Para Métricas y para ajustar los próximos eventos ----------

def en_rango(inventario: Inventario, servicios: list[Servicio], desde: date, hasta: date,
             tipo: Optional[str] = None) -> dict:
    """
    Los sobrantes de los servicios cuya FECHA DEL SERVICIO cae entre dos fechas
    (como la rentabilidad y el Historial: si el servicio fue el 31 y las sobras
    se tiraron el día 1, cuentan en el mes del servicio). `tipo` ("alimento" o
    "consumible") deja solo los de ese tipo de producto; None = todos.
    - total: su coste (criterio de la rentabilidad) y "lineas" apuntadas.
    - por_producto: producto, cantidad, unidad, coste y porcentaje medio de lo
      dedicado a esos servicios que se tiró (de más a menos coste).
    - por_menu: menú, servicios, coste tirado y qué parte del coste de comida
      y consumibles de esos servicios se tiró (de más a menos porcentaje).
    """
    sin_iva = inventario.iva_recuperable
    por_id = {s.id: s for s in servicios}
    tipos = TIPOS_CON_SOBRANTE if tipo is None else (tipo,)

    def fecha(r: Registro) -> date:
        s = por_id.get(r.servicio_id)
        return s.fecha if s else r.fecha

    registros = [r for r in [*usos_sobrante(inventario), *salidas_sobrante(inventario)]
                 if desde <= fecha(r) <= hasta and _tipo_registro(r) in tipos]
    ids = sorted({r.servicio_id for r in registros if r.servicio_id is not None})
    usados = {sid: usado_en_servicio(inventario, sid) for sid in ids}

    agrupado: dict[str, dict] = {}
    for r in registros:
        if isinstance(r, UsoTanda):
            nombre, unidad, cantidad = nombre_preparada(r.receta), "raciones", r.raciones
        else:
            nombre, unidad, cantidad = r.producto_nombre, r.unidad, r.cantidad
        fila = agrupado.setdefault(nombre, {"producto": nombre, "cantidad": 0.0, "unidad": unidad, "coste": 0.0,
                                            "_servicios": set()})
        fila["cantidad"] = round(fila["cantidad"] + cantidad, 6)
        fila["coste"] = round(fila["coste"] + _coste(r, sin_iva), 2)
        fila["_servicios"].add(r.servicio_id)
    por_producto = []
    for fila in agrupado.values():
        usado = sum(usados.get(sid, {}).get(fila["producto"], 0) for sid in fila.pop("_servicios"))
        fila["porcentaje"] = _porcentaje(fila["cantidad"], usado)
        por_producto.append(fila)
    por_producto.sort(key=lambda f: f["coste"], reverse=True)

    menus: dict[str, dict] = {}
    for sid in ids:
        s = por_id.get(sid)
        nombre = s.menu if s else f"Servicio #{sid}"
        tirado = round(sum(_coste(r, sin_iva) for r in registros if r.servicio_id == sid), 2)
        fila = menus.setdefault(nombre, {"menu": nombre, "servicios": 0, "coste": 0.0, "_base": 0.0})
        fila["servicios"] += 1
        fila["coste"] = round(fila["coste"] + tirado, 2)
        fila["_base"] += _coste_consumido(inventario, sid, sin_iva, tipos) + tirado
    por_menu = []
    for fila in menus.values():
        base = fila.pop("_base")
        fila["porcentaje"] = fila["coste"] / base if base > 0 else None
        por_menu.append(fila)
    por_menu.sort(key=lambda f: (f["porcentaje"] or 0), reverse=True)
    return {
        "total": round(sum(_coste(r, sin_iva) for r in registros), 2),
        "lineas": len(registros),
        "por_producto": por_producto,
        "por_menu": por_menu,
        "sin_iva": sin_iva,
    }


def aviso_menu(menu: str, servicios: list[Servicio], inventario: Inventario, ultimos: int = 3,
               maximo: int = 3) -> Optional[dict]:
    """
    Para ajustar el siguiente evento: en los últimos `ultimos` servicios
    completados con ese menú, qué parte de cada producto se tiró de media.
    Cuentan todos esos servicios (los que no tuvieron sobrantes, como 0).
    Devuelve None si no hay nada que avisar; si no, {"servicios": n,
    "productos": [{"producto", "unidad", "porcentaje", "por_10" (cantidad
    tirada por cada 10 comensales)}]} con los `maximo` de más coste.
    Es solo informativo: no cambia ninguna cantidad.
    """
    hechos = sorted((s for s in servicios if s.menu == menu and s.estado == "completado"),
                    key=lambda s: (s.fecha, s.hora), reverse=True)[:ultimos]
    if not hechos:
        return None
    sin_iva = inventario.iva_recuperable
    tirado: dict[str, dict] = {}
    usado: dict[str, float] = {}
    comensales = sum(s.comensales for s in hechos)
    for s in hechos:
        for nombre, cantidad in usado_en_servicio(inventario, s.id).items():
            usado[nombre] = usado.get(nombre, 0) + cantidad
        for r in registros_servicio(inventario, s.id):
            if isinstance(r, UsoTanda):
                nombre, unidad, cantidad = nombre_preparada(r.receta), "raciones", r.raciones
            else:
                nombre, unidad, cantidad = r.producto_nombre, r.unidad, r.cantidad
            fila = tirado.setdefault(nombre, {"producto": nombre, "unidad": unidad, "cantidad": 0.0, "coste": 0.0})
            fila["cantidad"] += cantidad
            fila["coste"] += _coste(r, sin_iva)
    productos = []
    for fila in sorted(tirado.values(), key=lambda f: f["coste"], reverse=True):
        porcentaje = _porcentaje(fila["cantidad"], usado.get(fila["producto"], 0))
        if porcentaje is None or porcentaje <= 0:
            continue
        productos.append({"producto": fila["producto"], "unidad": fila["unidad"], "porcentaje": porcentaje,
                          "por_10": round(fila["cantidad"] / comensales * 10, 3) if comensales else None})
    if not productos:
        return None
    return {"servicios": len(hechos), "productos": productos[:maximo]}


def texto_aviso_menu(menu: str, aviso: dict, formato_num=_numero, formato_pct=None) -> str:
    """El aviso de aviso_menu() en una frase."""
    formato_pct = formato_pct or (lambda v: f"{round(v * 100)} %")
    partes = []
    for p in aviso["productos"]:
        unos = "unas" if p["unidad"] in ("raciones", "unidades") else "unos"
        extra = (f" ({unos} {formato_num(p['por_10'])} {p['unidad']} por cada 10 comensales)"
                 if p["por_10"] else "")
        partes.append(f"un {formato_pct(p['porcentaje'])} de {p['producto']}{extra}")
    lista = partes[0] if len(partes) == 1 else ", ".join(partes[:-1]) + " y " + partes[-1]
    n = aviso["servicios"]
    if n == 1:
        inicio = f"En el último servicio con el menú «{menu}» sobró "
    else:
        inicio = f"En los últimos {n} servicios con el menú «{menu}» sobró de media "
    return inicio + lista + ". Es solo orientativo: tú decides si ajustas la receta o compras menos."
