-- Rebuilds ``dte_envios`` without enforcing ``venta_id`` as a foreign key.
--
-- Older installations created the table with ``FOREIGN KEY (venta_id)
-- REFERENCES ventas(id)``, which prevents storing transmission records for
-- notas and otros documentos que no están registrados en ``ventas``.  The
-- migration recreates the table without that constraint while preserving the
-- existing rows.
BEGIN TRANSACTION;
CREATE TABLE dte_envios_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    venta_id INTEGER,
    modo TEXT,
    estado TEXT,
    sello TEXT,
    fecha_hora TEXT,
    respuesta TEXT,
    codigo_lote TEXT,
    codigo_generacion TEXT,
    numero_control TEXT
);
INSERT INTO dte_envios_new (
    id, venta_id, modo, estado, sello, fecha_hora,
    respuesta, codigo_lote, codigo_generacion, numero_control
)
SELECT
    id, venta_id, modo, estado, sello, fecha_hora,
    respuesta, codigo_lote, codigo_generacion, numero_control
FROM dte_envios;
DROP TABLE dte_envios;
ALTER TABLE dte_envios_new RENAME TO dte_envios;
COMMIT;
