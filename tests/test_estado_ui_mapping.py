import pytest

from dte import _map_estado_hacienda, _merge_estado_tag, _merge_estado_ui


@pytest.mark.parametrize(
    "payload, esperado_ui, esperado_tag",
    [
        (
            {"estado": "Procesado", "descripcionMsg": "RECIBIDO", "observaciones": []},
            "Enviado",
            "",
        ),
        (
            {
                "estado": "Procesado",
                "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
                "observaciones": ["detalle"],
            },
            "Enviado",
            "observado",
        ),
        (
            {
                "estado": "Procesado",
                "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
                "observaciones": ["detalle"],
                "clasificaMsg": "10",
                "codigoMsg": "001",
            },
            "Enviado",
            "observado",
        ),
        (
            {
                "estado": "Procesado",
                "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
                "observaciones": ["detalle"],
                "clasificaMsg": "10",
                "codigoMsg": "002",
            },
            "Enviado",
            "observado",
        ),
        (
            {
                "estado": "Procesado",
                "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
                "observaciones": ["detalle"],
                "clasificaMsg": "10",
                "codigoMsg": "2",
            },
            "Enviado",
            "observado",
        ),
        (
            {
                "estado": "Procesado",
                "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
                "observaciones": ["detalle"],
                "clasificaMsg": "20",
                "codigoMsg": "801",
            },
            "Enviado",
            "",
        ),
        (
            {
                "estado": "Rechazado",
                "codigoMsg": "096",
                "descripcionMsg": "DOCUMENTO NO CUMPLE ESQUEMA JSON",
            },
            "Rechazado",
            "schema",
        ),
        (
            {
                "estado": "Rechazado",
                "codigoMsg": "96",
                "descripcionMsg": "DOCUMENTO NO CUMPLE ESQUEMA JSON",
            },
            "Rechazado",
            "schema",
        ),
        (
            {"estado": "Rechazado", "codigoMsg": "017", "descripcionMsg": "FECHA NO ES CORRECTA"},
            "Rechazado",
            "fecha",
        ),
        (
            {
                "estado": "Rechazado",
                "codigoMsg": "014",
                "descripcionMsg": "NO EXISTE UN REGISTRO CON ESTE DATO",
            },
            "Rechazado",
            "no_registro",
        ),
        (
            {"estado": "Aceptado", "descripcionMsg": "ACEPTADO"},
            "Aceptado",
            "",
        ),
    ],
)
def test_map_estado_hacienda(payload, esperado_ui, esperado_tag):
    mapped = _map_estado_hacienda(payload)
    assert mapped["ui"] == esperado_ui
    assert mapped["tag"] == esperado_tag


def test_merge_estado_ui_tag_sequence():
    secuencia = [
        None,
        {"estado": "Procesado"},
        {
            "estado": "Procesado",
            "descripcionMsg": "RECIBIDO CON OBSERVACIONES",
            "observaciones": ["detalle"],
        },
        {
            "estado": "Rechazado",
            "codigoMsg": "096",
            "descripcionMsg": "DOCUMENTO NO CUMPLE ESQUEMA JSON",
        },
        {"estado": "Aceptado"},
    ]

    prev_ui = None
    prev_tag = None
    for payload in secuencia:
        mapped = _map_estado_hacienda(payload)
        merged_ui = _merge_estado_ui(prev_ui, mapped["ui"])
        merged_tag = _merge_estado_tag(prev_tag, mapped["tag"], merged_ui)
        prev_ui, prev_tag = merged_ui, merged_tag

    assert prev_ui == "Aceptado"
    assert prev_tag == ""


def test_merge_estado_no_degrada_rechazado_con_tag():
    prev_ui = None
    prev_tag = None

    mapped_rechazo = _map_estado_hacienda(
        {
            "estado": "Rechazado",
            "codigoMsg": "014",
            "descripcionMsg": "NO EXISTE UN REGISTRO CON ESTE DATO",
        }
    )
    prev_ui = _merge_estado_ui(prev_ui, mapped_rechazo["ui"])
    prev_tag = _merge_estado_tag(prev_tag, mapped_rechazo["tag"], prev_ui)

    mapped_enviado = _map_estado_hacienda({"estado": "Procesado"})
    prev_ui = _merge_estado_ui(prev_ui, mapped_enviado["ui"])
    prev_tag = _merge_estado_tag(prev_tag, mapped_enviado["tag"], prev_ui)

    assert prev_ui == "Rechazado"
    assert prev_tag == "no_registro"
