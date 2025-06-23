import ast
import pytest


def load_generar_texto_function():
    with open('ui_mainwindow.py', 'r', encoding='utf-8') as f:
        source = f.read()
    module = ast.parse(source)
    func_node = None
    for node in ast.walk(module):
        if isinstance(node, ast.FunctionDef) and node.name == '_generar_texto_factura_matricial':
            func_node = node
            break
    if func_node is None:
        pytest.skip('_generar_texto_factura_matricial not found')
    namespace = {}
    exec(ast.unparse(func_node), namespace)
    return namespace['_generar_texto_factura_matricial']


def test_factura_texto_contains_client_and_total():
    generar = load_generar_texto_function()
    venta = {
        'fecha': '2024-01-02',
        'condicion_pago': 'Contado',
        'sumas': 5.00,
        'iva': 0.65,
        'subtotal': 5.65,
        'ventas_exentas': 0.0,
        'ventas_no_sujetas': 0.0,
        'total': 5.65,
        'total_letras': 'CINCO DOLARES CON SESENTA Y CINCO CENTAVOS'
    }
    detalles = [
        {
            'cantidad': 1,
            'descripcion': 'Producto X',
            'precio_unitario': 5.00,
            'ventas_gravadas': 5.00,
            'ventas_exentas': 0.0,
            'ventas_no_sujetas': 0.0,
            'tipo_fiscal': 'gravada',
            'iva': 0.65,
            'iva_tipo': 'desglosado'
        }
    ]
    cliente = {'nombre': 'Juan Perez', 'direccion': 'Calle 1', 'nit': '0614-010101-101-1', 'nrc': '1234-5', 'giro': 'Comercio'}
    distribuidor = {'nombre': 'Distribuidor', 'direccion': 'Direc', 'nit': '0000-0', 'nrc': '0'}

    texto = generar(None, venta, detalles, cliente, distribuidor)

    assert 'Juan Perez' in texto
    assert '5.65' in texto
