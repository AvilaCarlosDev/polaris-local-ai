import pytest
from inventario import total_unidades, valor_total, bajo_stock, aplicar_descuento

ITEMS = [
    {"nombre": "tornillo", "unidades": 10, "precio": 0.15},
    {"nombre": "arandela", "unidades": 3, "precio": 0.05},
    {"nombre": "clavo", "unidades": 5, "precio": 0.10},
]

def test_total_unidades():
    assert total_unidades(ITEMS) == 18

def test_valor_total():
    assert valor_total(ITEMS) == 2.15

def test_bajo_stock():
    assert bajo_stock(ITEMS) == ["arandela"]

def test_descuento():
    assert aplicar_descuento(200, 25) == 150

def test_descuento_fuera_de_rango():
    with pytest.raises(ValueError):
        aplicar_descuento(10, 120)
