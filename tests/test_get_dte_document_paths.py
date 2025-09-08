from utils.docs import get_dte_document_paths

def test_get_dte_document_paths_pads_number(tmp_path):
    _, json_path = get_dte_document_paths(
        "2024-01-02",
        "Mi Empresa",
        "DTE-05-ABC-123",
        "NotaCredito",
        root=tmp_path,
    )
    assert json_path.name == "20240102_Mi_Empresa_DTE-05-ABC-000000000000123_NotaCredito.json"
