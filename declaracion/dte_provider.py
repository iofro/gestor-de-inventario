"""Proveedor de datos para la generación de anexos DTE."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from declaracion.anexo_contribuyentes import VentaContribuyente
from declaracion.anexo_consumidor_final import VentaCF

logger = logging.getLogger(__name__)

APTOS = {"enviado", "aceptado", "recibido"}
ALIASES = {
    "procesado": "recibido",
    "procesada": "recibido",
    "procesamiento": "recibido",
    "recibido": "recibido",
    "recibida": "recibido",
    "enviado": "enviado",
    "enviada": "enviado",
    "transmitido": "enviado",
    "transmitida": "enviado",
    "aceptado": "aceptado",
    "aceptada": "aceptado",
    "aprobado": "aceptado",
    "aprobada": "aceptado",
    "pendiente": "pendiente",
    "rechazado": "rechazado",
    "rechazada": "rechazado",
    "anulado": "anulado",
    "anulada": "anulado",
    "invalidado": "invalidado",
    "invalidada": "invalidado",
    "cancelado": "anulado",
    "cancelada": "anulado",
}

TIPOS_ANEXO_I = {"03", "05", "06"}
TIPOS_ANEXO_II = {"01", "02", "10", "11"}

CLASE_POR_TIPO = {
    "01": "1",
    "02": "1",
    "03": "4",
    "05": "4",
    "06": "4",
    "10": "1",
    "11": "1",
}

_ACCENT_TRANSLATION = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouaeiou")


def _validate_periodo(periodo_yyyymm: str) -> str:
    texto = str(periodo_yyyymm).strip()
    if len(texto) != 6 or not texto.isdigit():
        raise ValueError("El período debe tener formato YYYYMM.")
    anio = int(texto[:4])
    mes = int(texto[4:])
    if mes < 1 or mes > 12:
        raise ValueError("El período debe tener un mes válido (01-12).")
    if anio < 2000:
        raise ValueError("El período debe tener un año válido.")
    return texto


def _parse_fecha(value: Any) -> datetime | None:
    if not value:
        return None
    texto = str(value).strip()
    if not texto:
        return None
    formatos = ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%Y%m%d"]
    for formato in formatos:
        try:
            return datetime.strptime(texto[:10], formato)
        except ValueError:
            continue
    return None


def _load_json(candidate: Any) -> Any:
    if isinstance(candidate, dict):
        return candidate
    if isinstance(candidate, str) and candidate.strip():
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return None


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    texto = str(value).strip()
    if not texto:
        return Decimal("0")
    texto = texto.replace(",", ".")
    try:
        return Decimal(texto)
    except Exception:
        return Decimal("0")


def _decimal_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


def _extract_cliente(row: dict) -> dict:
    cliente = {
        "nombre": row.get("cliente_nombre"),
        "nit": row.get("cliente_nit"),
        "nrc": row.get("cliente_nrc"),
        "dui": row.get("cliente_dui"),
    }
    extra = row.get("dte_json", {}).get("receptor") or {}
    if extra:
        cliente = {
            "nombre": extra.get("nombre") or cliente.get("nombre"),
            "nit": extra.get("nit") or extra.get("numDocumento") or cliente.get("nit"),
            "nrc": extra.get("nrc") or cliente.get("nrc"),
            "dui": extra.get("dui") or extra.get("numDocumento", cliente.get("dui")),
        }
    return cliente


def _extract_resumen(row: dict) -> dict:
    dte_json = row.get("dte_json") or {}
    resumen = dte_json.get("resumen") or {}
    if not resumen:
        extra = row.get("extra_data") or {}
        resumen = extra.get("resumen") or {}
    return resumen or {}


def _codigo_generacion(row: dict) -> str | None:
    codigo = (row.get("envio") or {}).get("codigo_generacion")
    if not codigo:
        dte_json = row.get("dte_json") or {}
        codigo = dte_json.get("identificacion", {}).get("codigoGeneracion")
    if not codigo:
        extra = row.get("extra_data") or {}
        codigo = extra.get("codigoGeneracion") or extra.get("codigo_generacion")
    if not codigo:
        return None
    codigo = str(codigo).strip()
    return codigo.upper() or None


def _numero_control(row: dict) -> str | None:
    numero = (row.get("envio") or {}).get("numero_control")
    if not numero:
        dte_json = row.get("dte_json") or {}
        numero = dte_json.get("identificacion", {}).get("numeroControl")
    if not numero:
        extra = row.get("extra_data") or {}
        numero = extra.get("numeroControl")
    if not numero:
        return None
    numero = str(numero).strip()
    return numero or None


def _fecha_emision(row: dict) -> tuple[str | None, datetime | None]:
    dte_json = row.get("dte_json") or {}
    identificacion = dte_json.get("identificacion") or {}
    fec = identificacion.get("fecEmi") or row.get("fecEmi")
    if not fec:
        fec = (row.get("fecha_venta") or "")[:10]
    parsed = _parse_fecha(fec)
    return (str(fec).strip() if fec else None, parsed)


def _tipo_dte(row: dict) -> str | None:
    dte_json = row.get("dte_json") or {}
    identificacion = dte_json.get("identificacion") or {}
    tipo = identificacion.get("tipoDte")
    if not tipo:
        extra = row.get("extra_data") or {}
        tipo = extra.get("tipoDte") or extra.get("tipo")
    if not tipo:
        return None
    texto = str(tipo).strip()
    if len(texto) == 1:
        texto = f"0{texto}"
    return texto


def _estado_base(row: dict) -> tuple[str | None, str | None]:
    envio = row.get("envio") or {}
    base = envio.get("estado_ui_tag") or envio.get("estado_ui") or row.get("estado_display")
    manual = None
    if envio.get("estado_ui_manual"):
        manual = (
            envio.get("estado_manual")
            or envio.get("estado_manual_text")
            or envio.get("estado_ui")
            or envio.get("estado_ui_tag")
        )
    return base, manual


def _tipo_operacion(row: dict) -> str:
    identificacion = row.get("dte_json", {}).get("identificacion") or {}
    tipo = identificacion.get("tipoOperacion")
    if tipo is None:
        tipo = row.get("extra_data", {}).get("tipoOperacion")
    return str(tipo).strip() if tipo is not None else "0"


def _tipo_ingreso(row: dict) -> str:
    identificacion = row.get("dte_json", {}).get("identificacion") or {}
    tipo = identificacion.get("tipoModelo")
    if tipo is None:
        tipo = row.get("extra_data", {}).get("tipoModelo")
    return str(tipo).strip() if tipo is not None else "0"


def _sello_recepcion(row: dict) -> str | None:
    envio = row.get("envio") or {}
    respuesta = envio.get("respuesta_json")
    if isinstance(respuesta, dict):
        sello = respuesta.get("selloRecibido") or respuesta.get("sello")
        if sello:
            return str(sello).strip() or None
    extra = row.get("extra_data") or {}
    sello = extra.get("selloRecibido") or extra.get("sello")
    if sello:
        return str(sello).strip() or None
    return None


def _log_summary(context: str, total: int, incluidos: int, stats: dict[str, dict[str, int]], motivos: dict[str, list[str]]) -> None:
    excluidos = total - incluidos
    logger.info(
        "%s - total_leidos=%s incluidos=%s excluidos=%s",
        context,
        total,
        incluidos,
        excluidos,
    )
    if stats:
        for tipo in sorted(stats):
            datos = stats[tipo]
            logger.info(
                "%s - tipo %s -> incluidos=%s excluidos=%s",
                context,
                tipo,
                datos.get("incluidos", 0),
                datos.get("excluidos", 0),
            )
    for motivo, ejemplos in motivos.items():
        logger.info(
            "%s - descartados_%s=%s%s",
            context,
            motivo,
            len(ejemplos),
            f" ejemplos: {' | '.join(ejemplos[:3])}" if ejemplos else "",
        )


def get_facturacion_rows(db, periodo_yyyymm: str) -> list[dict]:
    """Obtiene filas crudas de facturación para el período indicado."""

    periodo = _validate_periodo(periodo_yyyymm)
    db.ensure_column("ventas", "extra", "TEXT")
    query = (
        "SELECT v.id AS venta_id, v.fecha AS fecha_venta, v.total AS total_venta, v.extra, "
        "v.cliente_id, c.nombre AS cliente_nombre, c.nit AS cliente_nit, "
        "c.nrc AS cliente_nrc, c.dui AS cliente_dui "
        "FROM ventas AS v "
        "LEFT JOIN clientes AS c ON c.id = v.cliente_id"
    )
    filas = [dict(row) for row in db.cursor.execute(query)]
    venta_ids = [fila["venta_id"] for fila in filas]

    env_map: dict[int, dict[str, Any]] = {}
    if venta_ids:
        placeholders = ",".join(["?"] * len(venta_ids))
        env_query = (
            "SELECT id, venta_id, codigo_generacion, numero_control, estado_ui, "
            "estado_ui_tag, estado_ui_manual, respuesta "
            "FROM dte_envios WHERE venta_id IN ("
            + placeholders
            + ") ORDER BY id DESC"
        )
        for envio in db.cursor.execute(env_query, venta_ids):
            venta_id = envio["venta_id"]
            if venta_id in env_map:
                continue
            payload = dict(envio)
            respuesta = payload.get("respuesta")
            if respuesta:
                data = _load_json(respuesta) or {}
                if isinstance(data, dict):
                    payload["respuesta_json"] = data
                    payload.setdefault("codigo_generacion", data.get("codigoGeneracion"))
                    payload.setdefault("numero_control", data.get("numeroControl"))
                    if data.get("estado"):
                        payload.setdefault("estado_ui", data.get("estado"))
            env_map[venta_id] = payload

    periodo_rows: list[dict] = []
    descartes = defaultdict(list)

    for fila in filas:
        extra = _load_json(fila.get("extra")) or {}
        dte_json = _load_json(extra.get("dteJson")) or extra.get("dteJson")
        if not isinstance(dte_json, dict):
            dte_json = extra.get("dte_json")
        if not isinstance(dte_json, dict):
            dte_json = extra.get("dte_json_dict")

        row_data = {
            "venta_id": fila["venta_id"],
            "fecha_venta": fila.get("fecha_venta"),
            "extra_data": extra,
            "dte_json": dte_json if isinstance(dte_json, dict) else {},
            "envio": env_map.get(fila["venta_id"], {}),
            "cliente_nombre": fila.get("cliente_nombre"),
            "cliente_nit": fila.get("cliente_nit"),
            "cliente_nrc": fila.get("cliente_nrc"),
            "cliente_dui": fila.get("cliente_dui"),
        }
        json_path = extra.get("dteJsonPath") or extra.get("jsonPath")
        if json_path:
            row_data["json_path"] = json_path

        if isinstance(row_data["envio"].get("respuesta_json"), dict) and "dteJson" in row_data["envio"]["respuesta_json"]:
            row_data["dte_json"] = row_data["envio"]["respuesta_json"].get("dteJson") or row_data["dte_json"]

        fec_texto, fecha_obj = _fecha_emision(row_data)
        if not fecha_obj:
            descartes["sin_fecha"].append(f"venta {fila['venta_id']}")
            continue
        periodo_fila = f"{fecha_obj.year:04d}{fecha_obj.month:02d}"
        if periodo_fila != periodo:
            descartes["fuera_de_periodo"].append(f"venta {fila['venta_id']} {periodo_fila}")
            continue

        row_data["fecEmi"] = fec_texto
        row_data["fecha_obj"] = fecha_obj

        tipo = _tipo_dte(row_data)
        if tipo:
            row_data["tipo"] = tipo

        numero_control = _numero_control(row_data)
        if numero_control:
            row_data["numero_control"] = numero_control

        codigo_generacion = _codigo_generacion(row_data)
        if codigo_generacion:
            row_data["codigo_generacion"] = codigo_generacion

        sello = _sello_recepcion(row_data)
        if sello:
            row_data["sello_recepcion"] = sello

        periodo_rows.append(row_data)

    _log_summary(
        f"Facturación {periodo}",
        len(filas),
        len(periodo_rows),
        {},
        descartes,
    )
    return periodo_rows


def normalize_estado(value: str | None) -> str | None:
    if not value:
        return None
    texto = str(value).strip().lower()
    if not texto:
        return None
    texto = texto.translate(_ACCENT_TRANSLATION)
    texto = " ".join(texto.split())
    return ALIASES.get(texto, texto)


def estado_apto(value: str | None, override_manual: str | None = None) -> bool:
    override = normalize_estado(override_manual)
    if override and override in APTOS:
        return True
    base = normalize_estado(value)
    if base and base in APTOS:
        return True
    return False


def _montos_anexo_i(row: dict) -> dict:
    resumen = _extract_resumen(row)
    exentas = _to_decimal(resumen.get("totalExenta"))
    no_sujetas = _to_decimal(resumen.get("totalNoSuj"))
    gravadas = _to_decimal(resumen.get("totalGravada"))
    debito = _to_decimal(resumen.get("totalIva"))
    if debito == Decimal("0"):
        tributos = resumen.get("tributos") or []
        total_tributos = sum((_to_decimal(item.get("valor")) for item in tributos), Decimal("0"))
        debito = total_tributos
    terceros = _to_decimal(resumen.get("ventasTerceros"))
    debito_terceros = _to_decimal(resumen.get("debitoTerceros"))
    total = _to_decimal(resumen.get("totalPagar") or resumen.get("montoTotalOperacion"))
    subtotal = exentas + no_sujetas + gravadas + terceros + debito_terceros
    if total and subtotal != total:
        gravadas += total - subtotal
        subtotal = exentas + no_sujetas + gravadas + terceros + debito_terceros
    return {
        "ventas_exentas": _decimal_text(exentas),
        "ventas_no_sujetas": _decimal_text(no_sujetas),
        "ventas_gravadas_locales": _decimal_text(gravadas),
        "debito_fiscal": _decimal_text(debito),
        "ventas_terceros_no_domiciliados": _decimal_text(terceros),
        "debito_terceros": _decimal_text(debito_terceros),
        "total_ventas": _decimal_text(total or subtotal),
    }


def _montos_anexo_ii(row: dict) -> dict:
    resumen = _extract_resumen(row)
    exentas = _to_decimal(resumen.get("totalExenta"))
    no_sujetas = _to_decimal(resumen.get("totalNoSuj"))
    gravadas = _to_decimal(resumen.get("totalGravada"))
    total = _to_decimal(resumen.get("totalPagar") or resumen.get("montoTotalOperacion"))
    subtotal = exentas + no_sujetas + gravadas
    if total and subtotal != total:
        gravadas += total - subtotal
        subtotal = exentas + no_sujetas + gravadas
    return {
        "ventas_exentas": _decimal_text(exentas),
        "internas_exentas_ns": "0.00",
        "ventas_no_sujetas": _decimal_text(no_sujetas),
        "ventas_gravadas_locales": _decimal_text(gravadas),
        "exp_ca": "0.00",
        "exp_fuera_ca": "0.00",
        "exp_servicios": "0.00",
        "zonas_francas_dpa": "0.00",
        "terceros_no_domic": "0.00",
        "total_ventas": _decimal_text(total or subtotal),
    }


def _identificacion_anexo_i(row: dict) -> tuple[str | None, str | None, str]:
    cliente = _extract_cliente(row)
    dui = cliente.get("dui")
    if dui:
        dui_texto = str(dui).replace("-", "").strip()
        if dui_texto:
            return None, dui_texto, cliente.get("nombre") or ""
    nit = cliente.get("nit")
    nrc = cliente.get("nrc")
    identificacion = None
    if nit:
        identificacion = str(nit).replace("-", "").strip()
    elif nrc:
        identificacion = str(nrc).replace("-", "").strip()
    return identificacion or None, None, cliente.get("nombre") or ""


def build_anexo_i_records(rows: list[dict], db) -> list[VentaContribuyente]:
    registros: list[VentaContribuyente] = []
    seen: set[str] = set()
    stats = defaultdict(lambda: {"incluidos": 0, "excluidos": 0})
    motivos = defaultdict(list)
    total_considerados = 0

    for row in rows:
        tipo = row.get("tipo")
        if tipo not in TIPOS_ANEXO_I:
            continue
        total_considerados += 1
        stats[tipo]
        codigo = row.get("codigo_generacion") or _codigo_generacion(row)
        if not codigo:
            stats[tipo]["excluidos"] += 1
            motivos["sin_codigo"].append(f"venta {row.get('venta_id')}")
            continue
        if codigo in seen:
            stats[tipo]["excluidos"] += 1
            motivos["duplicado"].append(codigo)
            continue
        base, manual = _estado_base(row)
        apto = estado_apto(base, manual)
        if not apto:
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "desconocido"
            motivos["estado_no_apto"].append(f"{codigo}:{descripcion}")
            continue
        fecha_texto, fecha_obj = _fecha_emision(row)
        if not fecha_obj:
            stats[tipo]["excluidos"] += 1
            motivos["sin_fecha"].append(f"{codigo}")
            continue

        montos = _montos_anexo_i(row)
        identificacion, dui, nombre = _identificacion_anexo_i(row)
        numero_control = row.get("numero_control") or _numero_control(row)
        registro = VentaContribuyente(
            fecha_emision=fecha_obj.strftime("%d/%m/%Y"),
            clase=CLASE_POR_TIPO.get(tipo, "4"),
            tipo=tipo,
            numero_control=numero_control,
            codigo_generacion=codigo,
            sello_recepcion=row.get("sello_recepcion") if apto else None,
            identificacion=identificacion,
            nombre_cliente=nombre,
            dui=dui,
            tipo_operacion=_tipo_operacion(row),
            tipo_ingreso=_tipo_ingreso(row),
            estado=base,
            estado_manual=manual,
            estado_fuente="db" if row.get("envio") else "extra",
            json_path=row.get("json_path"),
        )
        for clave, valor in montos.items():
            setattr(registro, clave, valor)
        registros.append(registro)
        seen.add(codigo)
        stats[tipo]["incluidos"] += 1

    _log_summary("Anexo I", total_considerados, len(registros), stats, motivos)
    return registros


def build_anexo_ii_records(rows: list[dict], db) -> list[VentaCF]:
    registros: list[VentaCF] = []
    seen: set[str] = set()
    stats = defaultdict(lambda: {"incluidos": 0, "excluidos": 0})
    motivos = defaultdict(list)
    total_considerados = 0

    for row in rows:
        tipo = row.get("tipo")
        if tipo not in TIPOS_ANEXO_II:
            continue
        total_considerados += 1
        stats[tipo]
        codigo = row.get("codigo_generacion") or _codigo_generacion(row)
        if not codigo:
            stats[tipo]["excluidos"] += 1
            motivos["sin_codigo"].append(f"venta {row.get('venta_id')}")
            continue
        if codigo in seen:
            stats[tipo]["excluidos"] += 1
            motivos["duplicado"].append(codigo)
            continue
        base, manual = _estado_base(row)
        apto = estado_apto(base, manual)
        if not apto:
            stats[tipo]["excluidos"] += 1
            descripcion = normalize_estado(manual) or normalize_estado(base) or "desconocido"
            motivos["estado_no_apto"].append(f"{codigo}:{descripcion}")
            continue
        fecha_texto, fecha_obj = _fecha_emision(row)
        if not fecha_obj:
            stats[tipo]["excluidos"] += 1
            motivos["sin_fecha"].append(f"{codigo}")
            continue

        montos = _montos_anexo_ii(row)
        numero_control = row.get("numero_control") or _numero_control(row)
        registro = VentaCF(
            fecha=fecha_obj.strftime("%d/%m/%Y"),
            clase=CLASE_POR_TIPO.get(tipo, "1"),
            tipo=tipo,
            ctrl_interno_del=numero_control,
            ctrl_interno_al=numero_control,
            numero_doc_del=numero_control,
            numero_doc_al=numero_control,
            ventas_exentas=montos["ventas_exentas"],
            internas_exentas_ns=montos["internas_exentas_ns"],
            ventas_no_sujetas=montos["ventas_no_sujetas"],
            ventas_gravadas_locales=montos["ventas_gravadas_locales"],
            exp_ca=montos["exp_ca"],
            exp_fuera_ca=montos["exp_fuera_ca"],
            exp_servicios=montos["exp_servicios"],
            zonas_francas_dpa=montos["zonas_francas_dpa"],
            terceros_no_domic=montos["terceros_no_domic"],
            total_ventas=montos["total_ventas"],
            tipo_operacion=_tipo_operacion(row),
            tipo_ingreso=_tipo_ingreso(row),
            codigo_generacion=codigo,
            numero_control=numero_control,
            estado=base,
            estado_manual=manual,
            estado_fuente="db" if row.get("envio") else "extra",
            json_path=row.get("json_path"),
        )
        registros.append(registro)
        seen.add(codigo)
        stats[tipo]["incluidos"] += 1

    _log_summary("Anexo II", total_considerados, len(registros), stats, motivos)
    return registros
