# Guía de Pruebas

Este proyecto utiliza **pytest** para ejecutar pruebas unitarias y de integración. A continuación se describen los comandos básicos, las fixtures disponibles y las pautas para crear mocks.

## Comandos básicos

- Ejecutar toda la suite:
  ```bash
  pytest
  ```
  El archivo `pytest.ini` habilita la medición de cobertura (`--cov`) y muestra los módulos faltantes.
- Ejecutar un archivo o prueba específica:
  ```bash
  pytest tests/test_modulo.py::test_funcion
  ```
- Omitir la recopilación de cobertura cuando no sea necesaria:
  ```bash
  pytest --no-cov
  ```

## Fixtures

### `db_conn`
Fixture definida en `tests/conftest.py` que crea una base de datos temporal de SQLite. Activa las restricciones de clave foránea y elimina el archivo al finalizar la prueba, permitiendo un entorno limpio y aislado para cada caso.

### Fábricas
Las pruebas pueden definir **fábricas** como fixtures que retornan funciones para crear datos o modelos de forma rápida. Estas fábricas suelen residir en los módulos de prueba que las consumen y pueden apoyarse en `db_conn` para persistir la información. Se recomienda mantenerlas simples y reutilizables para facilitar la creación de escenarios.

## Lineamientos para mocks

- Utiliza la fixture `monkeypatch` de pytest o `unittest.mock.patch` para reemplazar funciones y atributos externos.
- Limita el alcance del mock al bloque o prueba que lo necesita y restaura el estado original al finalizar.
- Evita mocks innecesarios; prioriza el uso de fixtures reales cuando sea posible.
- Al usar `patch`, considera `autospec=True` para respetar la interfaz original y detectar llamadas inválidas.
- Documenta en la propia prueba el propósito del mock para facilitar el mantenimiento.

