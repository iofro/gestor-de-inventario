from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from utils import resource_path

logger = logging.getLogger(__name__)

DEFAULT_CATALOG_PATH = resource_path("docs", "catalogos_retencion.xlsx")

_NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    label: str


class CatalogosRetencion:
    """Lightweight XLSX reader for the MH catalog subset required by CR."""

    def __init__(self, xlsx_path: str | Path | None = None) -> None:
        self.xlsx_path = Path(xlsx_path or DEFAULT_CATALOG_PATH)
        self._tables: dict[str, dict[str, str]] = {}
        self._sheet_files: dict[str, str] | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def allowed_values(self, catalog_code: str) -> dict[str, str]:
        code = catalog_code.upper()
        if code not in self._tables:
            self._tables[code] = self._load_catalog(code)
        return self._tables[code]

    def ensure(self, catalog_code: str, value: str | None, *, field: str) -> str:
        """Validate ``value`` against ``catalog_code`` returning the canonical value."""

        table = self.allowed_values(catalog_code)
        if value is None:
            raise ValueError(f"{field} requerido por catálogo {catalog_code}")
        text = str(value).strip()
        if not text:
            raise ValueError(f"{field} vacío; catálogo {catalog_code}")
        if text not in table:
            raise ValueError(
                f"{field}='{text}' fuera de catálogo {catalog_code}; valores permitidos: {sorted(table)}"
            )
        return text

    def entries(self, catalog_code: str) -> List[CatalogEntry]:
        """Return catalog entries preserving insertion order."""

        table = self.allowed_values(catalog_code)
        return [CatalogEntry(code, label) for code, label in table.items()]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _load_catalog(self, catalog_code: str) -> dict[str, str]:
        sheets = self._sheet_map()
        target = sheets.get(catalog_code)
        if not target:
            raise KeyError(f"No existe la hoja {catalog_code} en {self.xlsx_path}")
        with ZipFile(self.xlsx_path, "r") as archive:
            xml_bytes = archive.read(target)
        rows = list(self._iter_rows(xml_bytes))
        table: Dict[str, str] = {}
        for row in rows[1:]:  # omitir encabezado
            if not row:
                continue
            code = str(row[0]).strip()
            if not code:
                continue
            label = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ""
            table[code] = label
        if not table:
            raise ValueError(f"Catálogo {catalog_code} vacío en {self.xlsx_path}")
        return table

    def _sheet_map(self) -> dict[str, str]:
        if self._sheet_files is not None:
            return self._sheet_files
        if not self.xlsx_path.exists():
            raise FileNotFoundError(
                f"Catálogo XLSX no encontrado: {self.xlsx_path}. Genera docs/catalogos_retencion.xlsx"
            )
        with ZipFile(self.xlsx_path, "r") as archive:
            wb_tree = ET.fromstring(archive.read("xl/workbook.xml"))
            sheets: dict[str, str] = {}
            for sheet in wb_tree.findall(f"{{{_NS_MAIN}}}sheets/{{{_NS_MAIN}}}sheet"):
                name = sheet.attrib.get("name")
                rid = sheet.attrib.get(f"{{{_NS_REL}}}id")
                if name and rid:
                    sheets[name.strip()] = rid

            rel_tree = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            rels: dict[str, str] = {}
            for rel in rel_tree.findall(f"{{{_NS_PKG_REL}}}Relationship"):
                rel_id = rel.attrib.get("Id")
                target = rel.attrib.get("Target")
                if rel_id and target and target.endswith(".xml"):
                    rels[rel_id] = target

        resolved: dict[str, str] = {}
        for name, rid in sheets.items():
            rel_target = rels.get(rid)
            if not rel_target:
                logger.debug("Hoja %s sin target en rels (rid=%s)", name, rid)
                continue
            path = rel_target
            if not path.startswith("xl/"):
                path = f"xl/{path}"
            resolved[name] = path

        self._sheet_files = resolved
        return resolved

    def _iter_rows(self, xml_bytes: bytes) -> Iterable[list[str]]:
        root = ET.fromstring(xml_bytes)
        sheet_data = root.find(f"{{{_NS_MAIN}}}sheetData")
        if sheet_data is None:
            return
        for row in sheet_data.findall(f"{{{_NS_MAIN}}}row"):
            values: list[str] = []
            for cell in row.findall(f"{{{_NS_MAIN}}}c"):
                ref = cell.attrib.get("r")
                idx = self._col_index(ref) if ref else len(values)
                text = self._cell_text(cell)
                while len(values) < idx + 1:
                    values.append("")
                values[idx] = text
            yield values

    @staticmethod
    def _col_index(ref: str | None) -> int:
        if not ref:
            return 0
        letters = "".join(ch for ch in ref if ch.isalpha())
        result = 0
        for ch in letters:
            result = result * 26 + (ord(ch.upper()) - 64)
        return max(result - 1, 0)

    @staticmethod
    def _cell_text(cell: ET.Element) -> str:
        t = cell.attrib.get("t")
        if t == "inlineStr":
            node = cell.find(f"{{{_NS_MAIN}}}is/{{{_NS_MAIN}}}t")
            return node.text if node is not None and node.text is not None else ""
        value = cell.find(f"{{{_NS_MAIN}}}v")
        return value.text if value is not None and value.text is not None else ""


__all__ = ["CatalogosRetencion", "CatalogEntry", "DEFAULT_CATALOG_PATH"]
