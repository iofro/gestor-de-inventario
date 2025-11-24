"""Almacenamiento UI-only de borradores CR-07."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .retencion_models import CRDetalle, CRDraft, CRResumen
from .retencion_utils import draft_to_dict


class RetencionStore:
    """Persistencia ligera en disco para retenciones simuladas."""

    def __init__(self) -> None:
        base = Path(__file__).resolve().parent
        self._draft_dir = base / ".drafts"
        self._draft_dir.mkdir(parents=True, exist_ok=True)
        self._path = self._draft_dir / "cr_store.json"
        self._cache = {"drafts": {}, "status": {}}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._cache["drafts"] = data.get("drafts", {})
                self._cache["status"] = data.get("status", {})
        except Exception:
            # Fallback: conserva cache vacío si hay errores.
            self._cache = {"drafts": {}, "status": {}}

    def _write(self) -> None:
        payload = {
            "drafts": self._cache.get("drafts", {}),
            "status": self._cache.get("status", {}),
        }
        with self._path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)

    def _dict_to_draft(self, data: dict) -> CRDraft:
        detalles_data: List[dict] = data.get("detalles", [])
        detalles: List[CRDetalle] = []
        for raw in detalles_data:
            if not isinstance(raw, dict):
                continue
            detalles.append(
                CRDetalle(
                    tipoDte=raw.get("tipoDte", ""),
                    tipoDoc=raw.get("tipoDoc", ""),
                    numDocumento=raw.get("numDocumento"),
                    codGeneracion=raw.get("codGeneracion"),
                    fechaEmision=raw.get("fechaEmision", ""),
                    montoSujetoGrav=float(raw.get("montoSujetoGrav", 0) or 0),
                    codigoRetencionMH=raw.get("codigoRetencionMH", "22"),
                    ivaRetenido=float(raw.get("ivaRetenido", 0) or 0),
                    descripcion=raw.get("descripcion", ""),
                )
            )
        resumen_data = data.get("resumen") or {}
        resumen = CRResumen(
            totalSujetoRetencion=float(resumen_data.get("totalSujetoRetencion", 0) or 0),
            totalIVAretenido=float(resumen_data.get("totalIVAretenido", 0) or 0),
            totalIVAretenidoLetras=resumen_data.get("totalIVAretenidoLetras", ""),
        )
        return CRDraft(detalles=detalles, resumen=resumen, meta=data.get("meta", {}))

    def save_draft(self, key: str, draft: CRDraft) -> None:
        self._cache["drafts"][key] = draft_to_dict(draft)
        self._write()

    def get_draft(self, key: str) -> Optional[CRDraft]:
        raw = self._cache.get("drafts", {}).get(key)
        if not isinstance(raw, dict):
            return None
        return self._dict_to_draft(raw)

    def has_draft(self, key: str) -> bool:
        return key in self._cache.get("drafts", {})

    def mark_emitted(self, key: str, payload: Optional[dict] = None) -> None:
        status: Dict[str, dict] = self._cache.setdefault("status", {})
        status[key] = {
            "emitted": True,
            "payload_preview": payload or {},
        }
        self._write()

    def is_emitted(self, key: str) -> bool:
        entry = self._cache.get("status", {}).get(key)
        return bool(entry and entry.get("emitted"))

    def all_status(self) -> Dict[str, dict]:
        return dict(self._cache.get("status", {}))


_STORE: Optional[RetencionStore] = None


def get_retencion_store() -> RetencionStore:
    global _STORE
    if _STORE is None:
        _STORE = RetencionStore()
    return _STORE

