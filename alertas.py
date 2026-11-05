"""
Vigilancia del secadero. Corre sola cada 5 minutos en GitHub Actions.

Mira la ultima telemetria y manda un mail cuando algo esta mal:

  - temperatura fuera del rango de la etapa, sostenida X minutos
  - humedad idem
  - riesgo de condensacion sostenido
  - el equipo dejo de mandar datos

Lo importante es que esto NO corre en el ESP32 ni en una PC de la casa:
si lo que falla es el equipo o se corta la luz en la planta, el aviso
tiene que salir igual desde afuera.
"""

import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from supabase import create_client

# El margen de rocio y la formula viven en cuentas.py, junto con las del
# panel. Antes estaban copiadas aca y en dashboard.py, y el dia que una de
# las dos cambiara el mail y la pantalla iban a decir cosas distintas del
# mismo momento.
from cuentas import MARGEN_ROCIO, ZONA, etapa_vigente, punto_de_rocio

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]
MAIL_USUARIO = os.environ["MAIL_USUARIO"]
MAIL_CLAVE = os.environ["MAIL_CLAVE"]

sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# =====================================================================
#  Mail
# =====================================================================
def mandar_mail(destinatarios, asunto, cuerpo):
    if not destinatarios:
        print("Sin destinatarios cargados: no se manda nada.")
        return

    mensaje = EmailMessage()
    mensaje["From"] = MAIL_USUARIO
    mensaje["To"] = ", ".join(destinatarios)
    mensaje["Subject"] = asunto
    mensaje.set_content(cuerpo)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context()) as s:
        s.login(MAIL_USUARIO, MAIL_CLAVE)
        s.send_message(mensaje)

    print(f"Mail enviado a {len(destinatarios)}: {asunto}")


# =====================================================================
#  Estado de las alertas (para no mandar 300 mails iguales)
# =====================================================================
def alerta_abierta(lote_id, tipo):
    filas = (
        sb.table("alertas").select("*")
        .eq("lote_id", lote_id).eq("tipo", tipo).eq("abierta", True)
        .limit(1).execute().data
    )
    return filas[0] if filas else None


def abrir_o_repetir(lote, tipo, titulo, detalle, config):
    """Abre la alerta si es nueva, o la repite si ya paso el tiempo de reenvio."""
    abierta = alerta_abierta(lote["id"], tipo)
    ahora = datetime.now(timezone.utc)

    if abierta:
        ultimo = abierta.get("ultimo_aviso")
        if ultimo:
            pasados = (ahora - datetime.fromisoformat(ultimo)).total_seconds() / 60
            if pasados < config["reenvio_min"]:
                print(f"{tipo}: ya avisado hace {pasados:.0f} min, no repito.")
                return
        desde = datetime.fromisoformat(abierta["inicio"]).astimezone(ZONA)
        encabezado = f"Sigue desde las {desde.strftime('%H:%M')} del {desde.strftime('%d/%m')}."
        registro_id = abierta["id"]
    else:
        encabezado = "Empezó recién."
        registro_id = sb.table("alertas").insert({
            "lote_id": lote["id"], "tipo": tipo, "detalle": detalle,
        }).execute().data[0]["id"]

    mandar_mail(
        config["destinatarios"],
        f"🔴 Secadero — {titulo}",
        f"{detalle}\n\n{encabezado}\n\nLote: {lote['nombre']}\n"
        f"Hora: {datetime.now(ZONA).strftime('%d/%m/%Y %H:%M')}\n\n"
        f"Panel: https://telemetrianostro.streamlit.app/\n",
    )

    sb.table("alertas").update(
        {"ultimo_aviso": ahora.isoformat(), "detalle": detalle}
    ).eq("id", registro_id).execute()


def cerrar(lote, tipo, titulo, config):
    """Si habia una alerta abierta y el problema paso, avisar que se normalizo."""
    abierta = alerta_abierta(lote["id"], tipo)
    if not abierta:
        return

    ahora = datetime.now(timezone.utc)
    desde = datetime.fromisoformat(abierta["inicio"])
    duracion = int((ahora - desde).total_seconds() // 60)

    sb.table("alertas").update(
        {"abierta": False, "cerrada_en": ahora.isoformat()}
    ).eq("id", abierta["id"]).execute()

    mandar_mail(
        config["destinatarios"],
        f"🟢 Secadero — {titulo}: normalizado",
        f"Se normalizó después de {duracion} minutos.\n\n"
        f"Lote: {lote['nombre']}\n"
        f"Hora: {datetime.now(ZONA).strftime('%d/%m/%Y %H:%M')}\n",
    )


# =====================================================================
#  Cuentas
# =====================================================================
def minutos_seguidos_mal(lecturas, esta_mal):
    """Hace cuantos minutos que TODAS las lecturas vienen mal.

    Recorre de la mas nueva a la mas vieja y se frena en la primera que
    estuvo bien. Una puerta abierta dos minutos no es una alarma; que
    nunca haya vuelto a entrar en rango en media hora, si.
    """
    ahora = datetime.now(timezone.utc)
    arranque = None
    for fila in lecturas:  # vienen ordenadas de nueva a vieja
        if not esta_mal(fila):
            break
        arranque = datetime.fromisoformat(fila["medido_en"])
    if arranque is None:
        return 0
    return (ahora - arranque).total_seconds() / 60


# =====================================================================
#  Revision
# =====================================================================
def revisar():
    config = sb.table("config").select("*").limit(1).execute().data[0]

    lotes = sb.table("lotes").select("*").eq("estado", "Activo").limit(1).execute().data
    if not lotes:
        print("No hay lote activo: no hay nada que vigilar.")
        return
    lote = lotes[0]

    ultima = (
        sb.table("lecturas").select("*").eq("lote_id", lote["id"])
        .order("medido_en", desc=True).limit(1).execute().data
    )

    # --- El equipo dejo de mandar -------------------------------------
    if not ultima:
        print("El lote todavia no tiene ninguna lectura.")
        return

    medido = datetime.fromisoformat(ultima[0]["medido_en"])
    silencio = (datetime.now(timezone.utc) - medido).total_seconds() / 60

    if silencio > config["minutos_sin_lecturas"]:
        abrir_o_repetir(
            lote, "sin_datos", "el equipo no manda datos",
            f"Hace {int(silencio)} minutos que no llega ninguna lectura. "
            f"La última fue a las {medido.astimezone(ZONA).strftime('%H:%M')} "
            f"del {medido.astimezone(ZONA).strftime('%d/%m')}.\n\n"
            "Puede ser el wifi, la corriente o el equipo colgado. "
            "Mientras tanto el secadero está sin vigilancia.",
            config,
        )
        # Sin datos frescos no se puede decir nada de temperatura ni humedad.
        return

    cerrar(lote, "sin_datos", "El equipo volvió a mandar datos", config)

    # --- Rangos de la etapa -------------------------------------------
    etapas = (
        sb.table("etapas").select("*").eq("lote_id", lote["id"])
        .order("orden").execute().data or []
    )
    etapa = etapa_vigente(datetime.fromisoformat(lote["fecha_inicio"]), etapas)
    if not etapa:
        print("El lote no tiene etapas cargadas: sin rangos que controlar.")
        return

    tolerancia = max(etapa["tolerancia_min"], config["tolerancia_rocio_min"])
    desde = datetime.now(timezone.utc) - timedelta(minutes=tolerancia + 120)
    recientes = (
        sb.table("lecturas").select("*").eq("lote_id", lote["id"])
        .gte("medido_en", desde.isoformat())
        .order("medido_en", desc=True).limit(1000).execute().data or []
    )

    revisar_rango(lote, etapa, config, recientes, "temperatura", "temp_sala",
                  etapa["temp_min"], etapa["temp_max"], "°C", etapa["tolerancia_min"])
    revisar_rango(lote, etapa, config, recientes, "humedad", "hum_sala",
                  etapa["hum_min"], etapa["hum_max"], "%", etapa["tolerancia_min"])
    revisar_rocio(lote, config, recientes)


def revisar_rango(lote, etapa, config, lecturas, tipo, campo, minimo, maximo,
                  unidad, tolerancia):
    if minimo is None and maximo is None:
        return

    def mal(fila):
        v = fila.get(campo)
        if v is None:
            return False  # un sensor mudo no es "fuera de rango"
        v = float(v)
        return (minimo is not None and v < float(minimo)) or \
               (maximo is not None and v > float(maximo))

    minutos = minutos_seguidos_mal(lecturas, mal)

    if minutos >= tolerancia and lecturas and mal(lecturas[0]):
        actual = float(lecturas[0][campo])
        lado = "por encima" if maximo is not None and actual > float(maximo) else "por debajo"
        abrir_o_repetir(
            lote, tipo, f"{tipo} fuera de rango",
            f"La {tipo} está en {actual:.1f}{unidad}, {lado} del rango de la etapa "
            f"«{etapa['nombre']}» ({minimo}-{maximo}{unidad}).\n\n"
            f"Lleva {int(minutos)} minutos seguidos fuera de rango.",
            config,
        )
    else:
        cerrar(lote, tipo, f"La {tipo} volvió al rango", config)


def revisar_rocio(lote, config, lecturas):
    """Avisa ANTES de que la tripa transpire, no cuando ya esta mojada.

    El aviso sale cuando a la superficie le queda menos de MARGEN_ROCIO
    para llegar al punto de rocio. Medio grado de aire es poco tiempo, pero
    alcanza para bajar la humedad y que la pelicula no llegue a formarse.
    """
    def mal(fila):
        rocio = punto_de_rocio(fila.get("temp_sala"), fila.get("hum_sala"))
        sup = fila.get("temp_sup")
        if rocio is None or sup is None:
            return False
        return float(sup) - rocio <= MARGEN_ROCIO

    minutos = minutos_seguidos_mal(lecturas, mal)
    tolerancia = config["tolerancia_rocio_min"]

    if minutos >= tolerancia and lecturas and mal(lecturas[0]):
        fila = lecturas[0]
        rocio = punto_de_rocio(fila["temp_sala"], fila["hum_sala"])
        margen = float(fila["temp_sup"]) - rocio
        como_esta = (
            "ya está transpirando" if margen <= 0
            else f"le quedan {margen:.1f}°C para empezar a transpirar"
        )
        abrir_o_repetir(
            lote, "rocio", "riesgo de condensación",
            f"La superficie de la tripa está a {float(fila['temp_sup']):.1f}°C y el "
            f"punto de rocío es {rocio:.1f}°C: {como_esta}.\n\n"
            f"Lleva {int(minutos)} minutos así.\n\n"
            "Hay que bajar la humedad y ventilar para secar la película.",
            config,
        )
    else:
        cerrar(lote, "rocio", "Pasó el riesgo de condensación", config)


if __name__ == "__main__":
    try:
        revisar()
    except Exception as error:  # que se vea en el registro de GitHub
        print(f"ERROR: {error}", file=sys.stderr)
        raise
