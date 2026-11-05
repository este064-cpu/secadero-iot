"""
Las cuentas y los umbrales que comparten el panel, los mails y el PDF.

Esto existe por una razon concreta: el medio grado de margen de rocio y
la formula del punto de rocio estaban copiados en dashboard.py y en
alertas.py, y el dia que uno de los dos cambiara, el cartel de la
pantalla y el mail iban a decir cosas distintas del mismo momento. Aca
hay un solo lugar donde tocarlos.

Lo unico que sigue aparte, y no se puede evitar, es el firmware: vive en
otro lenguaje y en otra maquina. Su MARGEN_ROCIO_AVISO tiene que seguir
el mismo numero que MARGEN_ROCIO de aca.
"""

import math
from datetime import timedelta, timezone

ZONA = timezone(timedelta(hours=-3))  # Argentina

# Cuanto puede acercarse la superficie de la tripa al punto de rocio antes
# de que valga la pena avisar. Con 0 el aviso sale cuando la tripa ya esta
# mojada, que es tarde: para cuando uno llega, la pelicula ya esta.
MARGEN_ROCIO = 0.5

# Una tira no engorda. Si la merma da mas negativa que esto, lo que esta
# mal no es el secadero: es el peso inicial cargado en el lote.
MERMA_MINIMA_CREIBLE = -10.0

# Lo que devuelve Supabase por pedido, aunque no avise.
TOPE_SUPABASE = 1000


def punto_de_rocio(temp, humedad):
    """Temperatura a la que el aire empieza a largar agua.

    Formula de Magnus-Tetens. La cuenta de bolsillo (T - (100-HR)/5) erra
    hasta un grado justo en el margen que decide si hay condensacion, que
    es lo unico que importa aca.
    """
    if temp is None or humedad is None:
        return None
    humedad = float(humedad)
    if humedad <= 0:
        return None
    if humedad > 100:
        humedad = 100.0  # el BME a veces devuelve 100,1

    a, b = 17.625, 243.04
    alfa = math.log(humedad / 100.0) + (a * float(temp)) / (b + float(temp))
    return (b * alfa) / (a - alfa)


def margen_de_rocio(temp_sala, hum_sala, temp_sup):
    """Cuantos grados le faltan a la superficie para empezar a transpirar.

    Positivo es que esta seca; cero o negativo es que esta mojandose.
    None cuando falta alguno de los tres datos.
    """
    rocio = punto_de_rocio(temp_sala, hum_sala)
    if rocio is None or temp_sup is None:
        return None
    return float(temp_sup) - rocio


def merma_de(peso_inicial, peso_ahora):
    """Cuanto bajo la tira respecto de su propio peso inicial, en %."""
    if peso_inicial in (None, 0) or peso_ahora is None:
        return None
    inicial = float(peso_inicial)
    if inicial <= 0:
        return None
    return (inicial - float(peso_ahora)) / inicial * 100.0
