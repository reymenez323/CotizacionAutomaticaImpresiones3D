-- PrototiposRD initial material catalog seed.
-- This file is data seed for the database, not frontend logic.

INSERT OR IGNORE INTO material_catalog (
    material_key, name, description, price_per_gram, density_g_cm3, density_factor, is_active, is_out_of_stock
)
VALUES
    ('PLA', 'PLA', 'Económico, fácil de imprimir y bueno para prototipos o piezas estéticas.', 2.0, 1.24, 1.0, 1, 0),
    ('PETG', 'PETG', 'Más resistente que PLA, buena opción para piezas funcionales generales.', 2.0, 1.27, 1.08, 1, 0),
    ('ABS', 'ABS', 'Resistente a temperatura moderada, útil para piezas técnicas.', 2.0, 1.04, 0.95, 1, 0),
    ('TPU', 'TPU', 'Flexible, recomendado para piezas elásticas o protectores.', 3.0, 1.21, 1.15, 1, 0),
    ('NYLON', 'Nylon', 'Alta resistencia mecánica, ideal para piezas exigentes.', 2.0, 1.14, 1.12, 1, 0);

INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Blanco', 1, 0 FROM material_catalog WHERE material_key = 'PLA';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Negro', 1, 0 FROM material_catalog WHERE material_key = 'PLA';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Gris', 1, 0 FROM material_catalog WHERE material_key = 'PLA';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Rojo', 1, 0 FROM material_catalog WHERE material_key = 'PLA';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Azul', 1, 0 FROM material_catalog WHERE material_key = 'PLA';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Verde', 1, 0 FROM material_catalog WHERE material_key = 'PLA';

INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Transparente', 1, 0 FROM material_catalog WHERE material_key = 'PETG';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Negro', 1, 0 FROM material_catalog WHERE material_key = 'PETG';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Blanco', 1, 0 FROM material_catalog WHERE material_key = 'PETG';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Azul', 1, 0 FROM material_catalog WHERE material_key = 'PETG';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Rojo', 1, 0 FROM material_catalog WHERE material_key = 'PETG';

INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Negro', 1, 0 FROM material_catalog WHERE material_key = 'ABS';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Blanco', 1, 0 FROM material_catalog WHERE material_key = 'ABS';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Gris', 1, 0 FROM material_catalog WHERE material_key = 'ABS';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Rojo', 1, 0 FROM material_catalog WHERE material_key = 'ABS';

INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Negro', 1, 0 FROM material_catalog WHERE material_key = 'TPU';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Transparente', 1, 0 FROM material_catalog WHERE material_key = 'TPU';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Rojo', 1, 0 FROM material_catalog WHERE material_key = 'TPU';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Azul', 1, 0 FROM material_catalog WHERE material_key = 'TPU';

INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Natural', 1, 0 FROM material_catalog WHERE material_key = 'NYLON';
INSERT OR IGNORE INTO material_colors (material_id, color_name, is_active, is_out_of_stock)
SELECT id, 'Negro', 1, 0 FROM material_catalog WHERE material_key = 'NYLON';
