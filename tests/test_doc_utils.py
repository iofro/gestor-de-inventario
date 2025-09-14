import os
from utils import docs
from dte import DEFAULT_ADDRESS


def test_generate_document_name():
    name = docs.generate_document_name('2024-07-03', 'Cliente #1', 5, 'CreditoFiscal')
    assert name.startswith('20240703_Cliente_1_5_CreditoFiscal')


def test_get_document_paths_and_list(tmp_path):
    pdf, js = docs.get_document_paths('2024-07-03', 'Acme', 1, 'Ticket', root=tmp_path)
    assert os.path.dirname(pdf) == os.path.join(tmp_path, 'tickets')
    # create files
    with open(pdf, 'w') as f:
        f.write('pdf')
    with open(js, 'w') as f:
        f.write('{}')
    res = docs.list_documents(root=tmp_path)
    assert {'tipo': 'Ticket', 'pdf': pdf, 'json': js} in res


def test_build_invoice_json_preserves_address():
    cliente = {
        'nombre': 'Ariel',
        'direccion': '6a calle oriente',
        'nrc': '123456-7',
        'telefono': '2222-3333',
        'correo': 'ariel@example.com',
    }
    data = docs.build_invoice_json({'fecha': '2024-01-01'}, cliente, [])
    rec = data.get('receptor', {})
    assert rec.get('direccion', {}).get('complemento') == '6a calle oriente'
    assert rec.get('nrc') == '123456-7'
    assert rec.get('telefono') == '2222-3333'
    assert rec.get('correo') == 'ariel@example.com'


def test_build_invoice_json_uses_default_address():
    cliente = {'nombre': 'Ariel', 'direccion': 'abc'}
    data = docs.build_invoice_json({'fecha': '2024-01-01'}, cliente, [])
    assert data.get('receptor', {}).get('direccion') == DEFAULT_ADDRESS
