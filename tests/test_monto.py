import ast

def num2words(n, lang='es'):
    mapping = {0: 'cero', 174: 'ciento setenta y cuatro'}
    return mapping.get(n, str(n))

with open('ui_mainwindow.py', 'r', encoding='utf-8') as f:
    source = f.read()

module = ast.parse(source)
func_code = None
for node in module.body:
    if isinstance(node, ast.FunctionDef) and node.name == 'monto_a_texto_sv':
        func_code = ast.unparse(node)
        break

namespace = {'num2words': num2words}
exec(func_code, namespace)

monto_a_texto_sv = namespace['monto_a_texto_sv']


def test_monto_a_texto_sv_basic():
    assert monto_a_texto_sv(174.50) == "CIENTO SETENTA Y CUATRO 50/100 D\u00d3LARES"


def test_monto_a_texto_sv_cents():
    assert monto_a_texto_sv(0.99) == "CERO 99/100 D\u00d3LARES"
