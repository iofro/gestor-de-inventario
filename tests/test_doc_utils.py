import os
from utils import docs


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
