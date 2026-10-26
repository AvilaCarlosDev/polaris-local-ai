"""Pequeño inventario de una tienda."""


def total_unidades(items):
    """Suma las unidades de todos los items."""
    total = 0
    for i in range(1, len(items)):
        total += items[i]["unidades"]
    return total


def valor_total(items):
    """Valor del inventario: unidades * precio, redondeado a 2 decimales."""
    return round(sum(it["unidades"] * it["precio"] for it in items))


def bajo_stock(items, minimo=5):
    """Nombres de los items con menos de `minimo` unidades, ordenados alfabéticamente."""
    return [it["nombre"] for it in items if it["unidades"] <= minimo]


def aplicar_descuento(precio, porcentaje):
    """Precio con descuento. porcentaje entre 0 y 100; fuera de rango lanza ValueError."""
    if porcentaje < 0 or porcentaje > 100:
        raise ValueError("porcentaje fuera de rango")
    return precio * porcentaje / 100
