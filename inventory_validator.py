from __future__ import annotations

from typing import TypedDict, List, Tuple, Any, Set


class Issue(TypedDict):
    path: str
    severity: str
    message: str


def migrate_inventory_json(data: dict) -> tuple[dict, list[str]]:
    """Return migrated copy of *data* and list of applied migrations."""
    migrations: Set[str] = set()
    # Normalize root key for distributors
    if "Distribuidores" in data and "distribuidores" not in data:
        data["distribuidores"] = data.pop("Distribuidores")
        migrations.add("rename Distribuidores -> distribuidores")
    # Rename seller_id -> vendedor_id in ventas and detalles_venta
    for venta in data.get("ventas", []):
        if isinstance(venta, dict) and "seller_id" in venta and "vendedor_id" not in venta:
            venta["vendedor_id"] = venta.pop("seller_id")
            migrations.add("rename ventas[].seller_id -> vendedor_id")
    for det in data.get("detalles_venta", []):
        if isinstance(det, dict) and "seller_id" in det and "vendedor_id" not in det:
            det["vendedor_id"] = det.pop("seller_id")
            migrations.add("rename detalles_venta[].seller_id -> vendedor_id")
    return data, sorted(migrations)


def validate_inventory_json(data: dict) -> List[Issue]:
    issues: List[Issue] = []

    required_sections = [
        "productos",
        "vendedores",
        "distribuidores",
        "clientes",
        "ventas",
        "detalles_venta",
    ]

    for section in required_sections:
        if section not in data:
            issues.append(
                {
                    "path": section,
                    "severity": "error",
                    "message": f"Falta sección {section}[]",
                }
            )
        elif not isinstance(data.get(section), list):
            issues.append(
                {
                    "path": section,
                    "severity": "error",
                    "message": f"{section} debe ser una lista",
                }
            )

    productos = data.get("productos", []) if isinstance(data.get("productos"), list) else []
    vendedores = data.get("vendedores", []) if isinstance(data.get("vendedores"), list) else []
    distribuidores = data.get("distribuidores", []) if isinstance(data.get("distribuidores"), list) else []
    clientes = data.get("clientes", []) if isinstance(data.get("clientes"), list) else []
    ventas = data.get("ventas", []) if isinstance(data.get("ventas"), list) else []
    detalles = data.get("detalles_venta", []) if isinstance(data.get("detalles_venta"), list) else []

    prod_ids: Set[int] = set()
    prod_skus: Set[str] = set()
    for i, p in enumerate(productos):
        if not isinstance(p, dict):
            issues.append({"path": f"productos[{i}]", "severity": "error", "message": "Debe ser objeto"})
            continue
        pid = p.get("id")
        if pid is None:
            issues.append({"path": f"productos[{i}].id", "severity": "error", "message": "Campo requerido"})
        else:
            if pid in prod_ids:
                issues.append({"path": f"productos[{i}].id", "severity": "error", "message": "id duplicado"})
            prod_ids.add(pid)
        sku = p.get("sku")
        if sku is not None:
            if sku in prod_skus:
                issues.append({"path": f"productos[{i}].sku", "severity": "error", "message": "sku duplicado"})
            prod_skus.add(sku)
        if "nombre" not in p:
            issues.append({"path": f"productos[{i}].nombre", "severity": "error", "message": "Campo requerido"})
        if "precio_venta_minorista" not in p:
            issues.append({"path": f"productos[{i}].precio_venta_minorista", "severity": "error", "message": "Campo requerido"})
        stock = p.get("stock")
        if stock is not None:
            try:
                float(stock)
            except (TypeError, ValueError):
                issues.append({
                    "path": f"productos[{i}].stock",
                    "severity": "error",
                    "message": "stock debe ser un número",
                })

    vendedor_ids = {v.get("id") for v in vendedores if isinstance(v, dict)}
    cliente_ids = {c.get("id") for c in clientes if isinstance(c, dict)}
    venta_ids: Set[int] = set()
    for i, v in enumerate(ventas):
        if not isinstance(v, dict):
            issues.append({"path": f"ventas[{i}]", "severity": "error", "message": "Debe ser objeto"})
            continue
        vid = v.get("id")
        if vid is not None:
            venta_ids.add(vid)
        vend_id = v.get("vendedor_id")
        if vend_id is not None and vend_id not in vendedor_ids:
            issues.append({
                "path": f"ventas[{i}].vendedor_id",
                "severity": "error",
                "message": f"vendedor_id {vend_id} no existe",
            })
        cid = v.get("cliente_id")
        if cid is not None and cid not in cliente_ids:
            issues.append({
                "path": f"ventas[{i}].cliente_id",
                "severity": "error",
                "message": f"cliente_id {cid} no existe",
            })

    for i, d in enumerate(detalles):
        if not isinstance(d, dict):
            issues.append({"path": f"detalles_venta[{i}]", "severity": "error", "message": "Debe ser objeto"})
            continue
        pid = d.get("producto_id")
        if pid not in prod_ids:
            issues.append({
                "path": f"detalles_venta[{i}].producto_id",
                "severity": "error",
                "message": f"producto_id {pid} no existe en productos",
            })
        vid = d.get("venta_id")
        if vid not in venta_ids:
            issues.append({
                "path": f"detalles_venta[{i}].venta_id",
                "severity": "error",
                "message": f"venta_id {vid} no existe en ventas",
            })

    return issues
