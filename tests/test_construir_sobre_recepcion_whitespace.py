import dte


def test_construir_sobre_recepcion_rejects_whitespace():
    cases = [
        "a. b.c",
        "a.b.c\n",
        "a.b.c\r",
        "a.b.\tc",
    ]
    for token in cases:
        assert dte.construir_sobre_recepcion(token) == {
            "estado": "Error",
            "detalle": "documento con espacios",
        }

