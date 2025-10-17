from utils.dte_estado import estado_apto_para_anexo, evaluar_estado, normalizar_estado


def test_estado_apto_prioriza_manual_aceptado():
    assert estado_apto_para_anexo("rechazado", "Aceptado") is True
    assert estado_apto_para_anexo("rechazado", "   enviado   ") is True


def test_estado_apto_manual_rechazado_excluye():
    assert estado_apto_para_anexo("aceptado", "Rechazado") is False
    assert estado_apto_para_anexo("procesado", "Anulado") is False


def test_estado_apto_automatico():
    assert estado_apto_para_anexo("Procesado", None) is True
    assert estado_apto_para_anexo("Recibido MH", None) is True
    assert estado_apto_para_anexo("Pendiente", None) is False


def test_estado_normalizacion():
    assert normalizar_estado("  Aceptado Manual  ") == "aceptadomanual"
    assert evaluar_estado("Envíado") is True
    assert evaluar_estado(" Pendiente ") is False


def test_estado_automatico_desconocido_rechaza():
    assert estado_apto_para_anexo("en revisión", None) is False
