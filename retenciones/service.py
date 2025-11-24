from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from db import DB
from dte import _load_dte_api_config, _post_dte_with_config, generar_dte_json, resolve_ambiente

import hashlib

from .builder import DEFAULT_RATE, build_cr_payload, serialize_cr, sign_cr as sign_cr_payload
from .catalogos_retencion import CatalogosRetencion
from .validators import validate_ccf, validate_cr

logger = logging.getLogger(__name__)

_ALLOWED_TIPO_DOC_CR = {"1", "2"}


class RetencionCRService:
    """High level helpers to persist, sign and send Comprobantes de Retención."""

    def __init__(self, db: DB, catalogos: CatalogosRetencion | None = None) -> None:
        self.db = db
        self.catalogos = catalogos or CatalogosRetencion()

    def prepare_cr(
        self,
        venta_id: int,
        *,
        factura: Mapping[str, Any] | None = None,
        tasa: Decimal | str | float = DEFAULT_RATE,
        codigo_retencion: str = "22",
        base_sujeta: Decimal | str | float | None = None,
        ambiente: str | None = None,
        tipo_moneda: str = "USD",
        emisor_override: Mapping[str, Any] | None = None,
        receptor_override: Mapping[str, Any] | None = None,
        descripcion: str | None = None,
        fecha_emision: datetime | None = None,
        identificacion_override: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build and persist a CR linked to ``venta_id`` raising on duplicates."""

        if factura is None:
            resolved_env = resolve_ambiente(ambiente)
            factura = generar_dte_json(self.db, venta_id, tipo_dte="03", ambiente=resolved_env)

        tipo_dte = str((factura.get("identificacion") or {}).get("tipoDte") or "").zfill(2)
        self._ensure_documento_origen(tipo_dte)
        if tipo_dte != "03":
            raise ValueError("CR-07 solo para DTE 03")
        if tipo_dte == "03":
            try:
                validate_ccf(factura)
            except Exception as exc:
                raise ValueError(f"DTE origen inválido: {exc}") from exc

        payload = build_cr_payload(
            factura,
            db=self.db,
            catalogos=self.catalogos,
            tasa=tasa,
            codigo_retencion=codigo_retencion,
            base_sujeta_override=base_sujeta,
            ambiente=ambiente,
            tipo_moneda=tipo_moneda,
            emisor_override=emisor_override,
            receptor_override=receptor_override,
            descripcion=descripcion,
            fecha_emision=fecha_emision,
            identificacion_override=identificacion_override,
        )
        _assert_cr_required_fields(payload)
        validate_cr(payload, catalogos=self.catalogos)
        payload_json = serialize_cr(payload, indent=None)

        ident = payload.get("identificacion") or {}
        origin_ident = (factura.get("identificacion") or {}).copy()
        numero_control = _required_upper(ident.get("numeroControl"), "identificacion.numeroControl")
        codigo_generacion = _required_upper(
            ident.get("codigoGeneracion"), "identificacion.codigoGeneracion"
        )
        numero_control_origen = _required_upper(
            origin_ident.get("numeroControl"), "identificacion.numeroControl (origen)"
        )
        codigo_generacion_origen = _required_upper(
            origin_ident.get("codigoGeneracion"), "identificacion.codigoGeneracion (origen)"
        )

        row_id = self.db.insert_retencion_cr(
            venta_id,
            payload_json=payload_json,
            codigo_generacion=codigo_generacion,
            numero_control=numero_control,
            codigo_generacion_origen=codigo_generacion_origen,
            numero_control_origen=numero_control_origen,
        )

        resumen = payload.get("resumen") or {}
        base = _decimal(resumen.get("totalSujetoRetencion"))
        retenido = _decimal(resumen.get("totalIVAretenido"))
        logger.info(
            "CR.STORE venta_id=%s db_id=%s numeroControl=%s codigoGeneracion=%s base=%.2f retenido=%.2f",
            venta_id,
            row_id,
            numero_control,
            codigo_generacion,
            float(base),
            float(retenido),
        )
        return payload

    def sign_cr(
        self,
        venta_id: int,
        payload: Mapping[str, Any] | str | None = None,
        **sign_kwargs: Any,
    ) -> str:
        """Sign the stored CR returning the JWS token."""

        record = self.db.get_retencion_cr(venta_id)
        if not record:
            raise ValueError(f"No existe CR registrado para la venta {venta_id}")
        stored_json = record.get("payload_json")
        if not stored_json:
            raise ValueError("CR sin payload para firmar")

        if payload is not None:
            provided = payload if isinstance(payload, str) else serialize_cr(payload, indent=None)
            if provided != stored_json:
                raise ValueError("El payload entregado no coincide con el CR persistido")

        if record.get("jws"):
            return record["jws"]

        source_str = stored_json
        try:
            payload_obj = json.loads(source_str)
        except Exception as exc:
            raise ValueError("CR payload inválido para firmar") from exc
        _assert_tipo_dte_03(payload_obj)
        stored_hash = hashlib.sha256(source_str.encode("utf-8")).hexdigest()
        logger.info("CR.SIGN payload_sha256=%s", stored_hash)
        ident = payload_obj.get("identificacion") or {}
        token = sign_cr_payload(
            source_str,
            preserve_str=True,
            version=ident.get("version"),
            tipo_dte=ident.get("tipoDte"),
            **sign_kwargs,
        )
        logger.info("CR.SIGNED payload_sha256=%s", stored_hash)
        self.db.update_retencion_cr_signature(venta_id, token)
        return token

    def send_cr(self, venta_id: int) -> dict[str, Any]:
        """Sign (if needed) and transmit the CR to Hacienda."""

        record = self.db.get_retencion_cr(venta_id)
        if not record:
            raise ValueError(f"No existe CR registrado para la venta {venta_id}")
        payload_json = record.get("payload_json")
        if not payload_json:
            raise ValueError("CR sin payload para transmisión")
        _assert_tipo_dte_03(payload_json)
        try:
            payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        except Exception:
            payload_hash = None
        if payload_hash:
            logger.info("CR.SEND payload_sha256=%s", payload_hash)
        payload_dict = json.loads(payload_json)
        ident = payload_dict.get("identificacion") or {}
        resumen = payload_dict.get("resumen") or {}
        base = _decimal(resumen.get("totalSujetoRetencion"))
        retenido = _decimal(resumen.get("totalIVAretenido"))

        jws = record.get("jws") or self.sign_cr(venta_id, payload_json)

        config = _load_dte_api_config()
        url = config.get("url")
        if not url:
            raise RuntimeError("Configuración de recepción DTE no encontrada")

        logger.info(
            "CR.SEND venta_id=%s numeroControl=%s codigoGeneracion=%s ambiente=%s base=%.2f retenido=%.2f",
            venta_id,
            ident.get("numeroControl"),
            ident.get("codigoGeneracion"),
            ident.get("ambiente"),
            float(base),
            float(retenido),
        )
        logger.info(
            "RETENCION.SEND venta_id=%s base=%.2f retenido=%.2f rate=%.4f",
            venta_id,
            float(base),
            float(retenido),
            float(DEFAULT_RATE),
        )

        response = _post_dte_with_config(
            url,
            jws,
            payload_dict,
            config,
            identity_snapshot=ident,
        )
        normalized = _normalize_response(response)
        logger.info(
            "CR.RESP venta_id=%s estado=%s sello=%s detalle=%s",
            venta_id,
            normalized.get("estado"),
            normalized.get("sello"),
            normalized.get("detalle") or normalized.get("descripcionMsg"),
        )

        respuesta_text = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        self.db.update_retencion_cr_response(
            venta_id,
            estado=normalized.get("estado"),
            sello=normalized.get("sello"),
            respuesta=respuesta_text,
        )
        return normalized

    @staticmethod
    def _ensure_documento_origen(tipo: str) -> None:
        tipo_norm = str(tipo or "").strip().zfill(2)
        if tipo_norm != "03":
            raise ValueError("CR-07 solo para DTE 03")


def _required_upper(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Campo requerido faltante: {field}")
    return text.upper()


def _decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _normalize_response(resp: Any) -> dict[str, Any]:
    if not isinstance(resp, Mapping):
        return {"estado": "DESCONOCIDO", "detalle": resp}
    merged: dict[str, Any] = dict(resp)
    body = merged.pop("body", None)
    if isinstance(body, Mapping):
        body_data = dict(body)
        body_data.update(merged)
        merged = body_data

    estado = str(merged.get("estado") or merged.get("Estado") or "").strip()
    normalized: dict[str, Any] = {"estado": estado.upper() or "DESCONOCIDO"}
    for key in (
        "detalle",
        "descripcionMsg",
        "observaciones",
        "fhProcesamiento",
        "codigoGeneracion",
        "codigoMsg",
    ):
        if merged.get(key) is not None:
            normalized[key] = merged.get(key)
    sello = merged.get("selloRecibido") or merged.get("sello")
    if sello:
        normalized["sello"] = str(sello).strip().upper()
    return normalized


def _assert_cr_required_fields(payload: Mapping[str, Any]) -> None:
    receptor = payload.get("receptor") or {}
    for field in ("codActividad", "descActividad", "telefono", "nrc", "tipoDocumento", "numDocumento"):
        if receptor.get(field) in (None, ""):
            raise ValueError(f"CR receptor sin {field}")

    cuerpo = payload.get("cuerpoDocumento") or []
    if not cuerpo:
        raise ValueError("CR sin cuerpoDocumento")
    tipo_doc = (cuerpo[0] or {}).get("tipoDoc")
    if str(tipo_doc) not in _ALLOWED_TIPO_DOC_CR:
        raise ValueError(f"cuerpoDocumento[0].tipoDoc '{tipo_doc}' fuera de catálogo permitido")


def _assert_tipo_dte_03(source: str | Mapping[str, Any]) -> None:
    try:
        data = json.loads(source) if isinstance(source, str) else dict(source)
    except Exception:
        raise ValueError("CR-07 solo para DTE 03") from None
    cuerpo = (data.get("cuerpoDocumento") or [{}])[0]
    tipo_rel = str(cuerpo.get("tipoDte") or "").zfill(2)
    if tipo_rel != "03":
        raise ValueError("CR-07 solo para DTE 03")


__all__ = ["RetencionCRService"]
