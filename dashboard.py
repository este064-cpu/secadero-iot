"""
Panel de control del secadero — Nostro Chacinados.

Lee la telemetria que manda el ESP32 y la muestra para Esteban y Rafael.
Nada de esto se puede ver sin estar logueado.
"""

import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from supabase import create_client

ZONA = timezone(timedelta(hours=-3))  # Argentina
TOPE_SUPABASE = 1000  # lo que devuelve Supabase por pedido, aunque no avise

# Margen de aviso de condensacion: el mismo medio grado que usan el
# firmware ("AL BORDE" en el monitor serie) y alertas.py. Si el panel
# esperara a que la superficie toque el punto de rocio, el cartel verde
# estaria mintiendo justo el rato en que todavia se podia hacer algo.
MARGEN_ROCIO = 0.5

# Una tira no engorda. Si la merma da muy negativa, lo que esta mal no es el
# secadero: es el peso inicial que quedo cargado en el lote. Un par de puntos
# negativos son ruido de la celda; cien mil son un dato cargado mal.
MERMA_MINIMA_CREIBLE = -10.0

st.set_page_config(page_title="Secadero IoT", layout="wide")


# =====================================================================
#  Conexion y login
# =====================================================================
def conexion():
    """Un cliente por navegador.

    A proposito NO se usa st.cache_resource: eso comparte el mismo cliente
    entre todos los que abren la app, y con el cliente viajaria la sesion
    de quien se logueo primero.
    """
    if "sb" not in st.session_state:
        st.session_state.sb = create_client(
            st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"]
        )
    return st.session_state.sb


def pantalla_login(sb):
    st.title("🥩 Secadero Nostro")
    st.caption("Panel de control del secadero. Hay que ingresar para verlo.")

    with st.form("login"):
        mail = st.text_input("Mail")
        clave = st.text_input("Contraseña", type="password")
        if st.form_submit_button("Ingresar", type="primary"):
            try:
                sb.auth.sign_in_with_password({"email": mail, "password": clave})
                st.session_state.usuario = mail
                st.rerun()
            except Exception:
                st.error("Mail o contraseña incorrectos.")


# =====================================================================
#  Lectura de datos
# =====================================================================
def _paginar(armar_consulta, paso=TOPE_SUPABASE):
    """Trae TODAS las filas, de a tandas.

    Supabase corta en 1000 filas y no avisa: devuelve las primeras 1000 y
    se queda callado. Pidiendo de a tandas hasta que venga una incompleta
    no se pierde nada.
    """
    filas, desde = [], 0
    while True:
        datos = armar_consulta().range(desde, desde + paso - 1).execute().data or []
        filas.extend(datos)
        if len(datos) < paso:
            return filas
        desde += paso


def lote_activo(sb):
    datos = sb.table("lotes").select("*").eq("estado", "Activo").limit(1).execute().data
    return datos[0] if datos else None


def ultima_lectura(sb, lote_id=None):
    """La ultima lectura del lote, o la ultima del equipo si no se pide lote.

    Sin lote_id devuelve lo ultimo que mando el ESP32, venga del lote que
    venga. Los sensores no saben de lotes: la balanza y el termometro
    sirven igual para calibrar o para mirar la camara vacia.
    """
    consulta = sb.table("lecturas").select("*")
    if lote_id is not None:
        consulta = consulta.eq("lote_id", lote_id)
    datos = consulta.order("medido_en", desc=True).limit(1).execute().data
    return datos[0] if datos else None


def lecturas(sb, lote_id, desde, por_hora):
    """La ventana que se esta mirando, no la tabla entera.

    Para ventanas largas se usa la vista por hora: un mes de lote son
    43.000 filas y nadie mira 43.000 puntos en un grafico.

    Con lote_id en None trae todo lo que mando el equipo, sin filtrar.
    """
    def filtrar(consulta):
        return consulta if lote_id is None else consulta.eq("lote_id", lote_id)

    if por_hora:
        filas = _paginar(
            lambda: filtrar(sb.table("lecturas_por_hora").select("*"))
            .gte("hora", desde.isoformat())
            .order("hora")
        )
        columna = "hora"
    else:
        filas = _paginar(
            lambda: filtrar(sb.table("lecturas").select("*"))
            .gte("medido_en", desde.isoformat())
            .order("medido_en")
        )
        columna = "medido_en"

    if not filas:
        return pd.DataFrame()

    df = pd.DataFrame(filas)
    df["momento"] = pd.to_datetime(df[columna], utc=True).dt.tz_convert(ZONA)
    return df


def etapas(sb, lote_id):
    return (
        sb.table("etapas")
        .select("*")
        .eq("lote_id", lote_id)
        .order("dia_desde")
        .execute()
        .data
        or []
    )


def etapa_vigente(lista, fecha_inicio):
    """La etapa que corresponde al dia que va corriendo el lote.

    Despues de la ultima etapa se siguen usando sus rangos: un lote que se
    estira no se queda sin control.
    """
    if not lista:
        return None
    dia = (ahora() - pd.to_datetime(fecha_inicio, utc=True).to_pydatetime()).days
    for etapa in lista:
        if etapa["dia_desde"] <= dia <= etapa["dia_hasta"]:
            return etapa
    return lista[-1] if dia > lista[-1]["dia_hasta"] else lista[0]


# =====================================================================
#  Cuentas
# =====================================================================
def ahora():
    return datetime.now(timezone.utc)


def punto_de_rocio(temp, humedad):
    """Formula de Magnus.

    La cuenta de bolsillo (T - (100-HR)/5) erra hasta un grado justo en el
    margen que decide si hay condensacion, que es lo unico que importa aca.
    """
    if temp is None or humedad is None or humedad <= 0:
        return None
    a, b = 17.625, 243.04
    alfa = math.log(humedad / 100.0) + (a * float(temp)) / (b + float(temp))
    return (b * alfa) / (a - alfa)


def merma_de_la_tira(lote, lectura):
    """La merma medida: la tira testigo contra su propio peso inicial.

    Es la unica merma que se mide de verdad. Antes se comparaba el peso de
    la tira contra los kilos del lote entero y daba cualquier cosa.
    """
    if not lote or not lectura:
        return None
    peso = lectura.get("peso_tira_g")
    inicial = lote.get("tira_peso_inicial_g")
    if peso is None or not inicial:
        return None
    return (float(inicial) - float(peso)) / float(inicial) * 100.0


def producto_estimado(lote, merma):
    """Cuanto producto quedaria en camara, estimado.

    Es la merma de la tira aplicada a los kilos que se embutieron. Es una
    cuenta, no una medicion: sirve para tener una idea, no para facturar.
    """
    if merma is None or not lote or not lote.get("kg_embutidos"):
        return None
    return float(lote["kg_embutidos"]) * (1 - merma / 100.0)


def texto_antiguedad(momento):
    minutos = int((ahora() - momento).total_seconds() // 60)
    if minutos < 1:
        return "recién"
    if minutos < 60:
        return f"hace {minutos} min"
    if minutos < 60 * 48:
        return f"hace {minutos // 60} h"
    return f"hace {minutos // 1440} días"


def valor(lectura, campo, unidad, decimales=1):
    if not lectura or lectura.get(campo) is None:
        return "— sin dato"
    return f"{float(lectura[campo]):.{decimales}f} {unidad}"


# =====================================================================
#  Barra lateral
# =====================================================================
def peso_inicial_de_la_tira(sb, lote, lectura):
    """Cargar o corregir el peso inicial de la tira, con el lote abierto.

    Tiene que poder editarse despues de abrir el lote: la tira se cuelga y
    hay que dejar la celda unas horas quieta antes de que el numero valga
    algo. Si el peso inicial solo se pudiera poner al crear el lote, habria
    que elegir entre anotar un peso que todavia se esta acomodando o cerrar
    el lote y volver a abrirlo.
    """
    with st.expander("⚖️ Peso de la tira testigo"):
        st.caption(
            "Se carga **después** de colgar la tira y de dejar la celda unas "
            "horas quieta. La celda se acomoda sola los primeros minutos, y "
            "un peso tomado recién colgada le mete ese error a toda la merma "
            "del lote."
        )

        marca = lectura.get("peso_tira_g") if lectura else None
        actual = lote.get("tira_peso_inicial_g")

        if marca is not None:
            st.caption(f"La balanza marca ahora **{float(marca):.0f} g**.")
            if st.button("Usar el peso de ahora", use_container_width=True):
                guardar_peso_tira(sb, lote, float(marca))

        with st.form("peso_tira"):
            nuevo = st.number_input(
                "O escribirlo a mano (g)",
                min_value=0.0, step=10.0,
                value=float(actual) if actual else 0.0,
            )
            if st.form_submit_button("Guardar"):
                guardar_peso_tira(sb, lote, nuevo)


def guardar_peso_tira(sb, lote, gramos):
    # La base exige > 0; un cero se guarda como null, que es "todavia no se
    # sabe" y no un peso de cero gramos.
    sb.table("lotes").update(
        {"tira_peso_inicial_g": gramos if gramos > 0 else None}
    ).eq("id", lote["id"]).execute()
    st.success(f"Peso inicial: {gramos:g} g" if gramos > 0 else "Peso borrado.")
    st.rerun()


def barra_lateral(sb, lote, lista_etapas, lectura=None):
    with st.sidebar:
        st.caption(f"👤 {st.session_state.usuario}")
        if st.button("Salir"):
            sb.auth.sign_out()
            st.session_state.clear()
            st.rerun()

        st.markdown("---")
        st.header("📦 Lote")

        if lote:
            st.success(f"**{lote['nombre']}** — activo")
            inicio = pd.to_datetime(lote["fecha_inicio"], utc=True).tz_convert(ZONA)
            st.caption(
                f"Desde el {inicio.strftime('%d/%m/%Y')} · "
                f"día {(ahora() - inicio.to_pydatetime()).days}"
            )
            tira = lote.get("tira_peso_inicial_g")
            # ":g" y no ":.0f": una tira de 0,5 g cargada por error se veria
            # como "0 g" y parece un dato faltante en vez de un dato absurdo.
            st.caption(
                f"Tira testigo: {float(tira):g} g" if tira
                else "⚠️ Falta el peso de la tira"
            )
            if lote.get("kg_embutidos"):
                st.caption(f"Embutido: {float(lote['kg_embutidos']):.0f} kg")

            peso_inicial_de_la_tira(sb, lote, lectura)

            if st.button("Finalizar lote"):
                sb.table("lotes").update(
                    {"estado": "Finalizado", "fecha_fin": ahora().isoformat()}
                ).eq("id", lote["id"]).execute()
                st.rerun()
        else:
            st.warning("No hay ningún lote activo.")

        with st.expander("➕ Iniciar lote nuevo"):
            with st.form("nuevo_lote"):
                nombre = st.text_input("Nombre", placeholder="Salame 2026-11")
                # Arranca en 0 a proposito: lo correcto es colgar la tira,
                # dejar la celda acomodarse unas horas y recien ahi cargar el
                # peso desde "Peso de la tira testigo". Un valor por defecto
                # invita a dejarlo como viene y arruina la merma del lote.
                tira = st.number_input(
                    "Peso inicial de la tira testigo (g)",
                    min_value=0.0, value=0.0, step=10.0,
                    help=(
                        "Se puede dejar en 0 y cargarlo después, cuando la "
                        "tira esté colgada y la celda quieta. De acá sale la "
                        "merma: un peso apurado la arruina para todo el lote."
                    ),
                )
                kilos = st.number_input(
                    "Kilos embutidos en total",
                    min_value=0.0, value=100.0, step=1.0,
                    help="Solo para estimar cuánto producto queda. No se vuelve a pesar.",
                )
                if st.form_submit_button("Crear", type="primary"):
                    crear_lote(sb, nombre, tira, kilos)

        if lote:
            st.markdown("---")
            st.header("🎚️ Rangos por etapa")
            st.caption(
                "Los rangos y los minutos de tolerancia se guardan en la base: "
                "los ven igual los dos y de acá salen los mails."
            )
            editor_etapas(sb, lote, lista_etapas)

            st.markdown("---")
            st.header("📝 Carga manual")
            with st.form("medicion"):
                fecha = st.date_input("Fecha", value=datetime.now(ZONA).date())
                hora = st.time_input("Hora", value=datetime.now(ZONA).time())
                ph = st.number_input("pH", min_value=3.0, max_value=9.0,
                                     value=5.4, step=0.05)
                aw = st.number_input("aw (opcional)", min_value=0.0, max_value=1.0,
                                     value=0.0, step=0.005, format="%.3f")
                notas = st.text_input("Observaciones")
                if st.form_submit_button("Guardar"):
                    sb.table("mediciones").insert({
                        "lote_id": lote["id"],
                        "medido_en": datetime.combine(fecha, hora)
                        .replace(tzinfo=ZONA).isoformat(),
                        "ph": ph,
                        "aw": aw if aw > 0 else None,
                        "notas": notas or None,
                    }).execute()
                    st.success("Guardado")
                    st.rerun()

        st.markdown("---")
        with st.expander("✉️ Avisos por mail"):
            editor_config(sb)


def crear_lote(sb, nombre, tira, kilos):
    if not nombre.strip():
        st.error("Poné un nombre.")
        return

    # Cerrar el anterior primero: la base no deja dos lotes activos.
    sb.table("lotes").update(
        {"estado": "Finalizado", "fecha_fin": ahora().isoformat()}
    ).eq("estado", "Activo").execute()

    nuevo = sb.table("lotes").insert({
        "nombre": nombre.strip(),
        "tira_peso_inicial_g": tira or None,
        "kg_embutidos": kilos or None,
    }).execute().data[0]

    # Etapas por defecto. Se editan despues desde la barra lateral.
    sb.table("etapas").insert([
        {"lote_id": nuevo["id"], "nombre": "Estufa / Fermentación",
         "dia_desde": 0, "dia_hasta": 2,
         "temp_min": 20, "temp_max": 24, "hum_min": 85, "hum_max": 95,
         "tolerancia_min": 30},
        {"lote_id": nuevo["id"], "nombre": "Secado / Maduración",
         "dia_desde": 3, "dia_hasta": 21,
         "temp_min": 12, "temp_max": 16, "hum_min": 72, "hum_max": 82,
         "tolerancia_min": 60},
        {"lote_id": nuevo["id"], "nombre": "Estabilización",
         "dia_desde": 22, "dia_hasta": 180,
         "temp_min": 10, "temp_max": 14, "hum_min": 70, "hum_max": 78,
         "tolerancia_min": 120},
    ]).execute()

    st.success(f"Lote {nombre} creado.")
    st.rerun()


def editor_etapas(sb, lote, lista_etapas):
    if not lista_etapas:
        st.info("Este lote no tiene etapas cargadas.")
        return

    columnas = ["nombre", "dia_desde", "dia_hasta", "temp_min", "temp_max",
                "hum_min", "hum_max", "tolerancia_min"]
    tabla = pd.DataFrame(lista_etapas)[["id"] + columnas]

    editada = st.data_editor(
        tabla, hide_index=True, use_container_width=True,
        disabled=["id"], column_config={
            "id": None,
            "nombre": st.column_config.TextColumn("Etapa"),
            "dia_desde": st.column_config.NumberColumn("Día desde", width="small"),
            "dia_hasta": st.column_config.NumberColumn("Día hasta", width="small"),
            "temp_min": st.column_config.NumberColumn("T mín", format="%.1f"),
            "temp_max": st.column_config.NumberColumn("T máx", format="%.1f"),
            "hum_min": st.column_config.NumberColumn("H mín", format="%.1f"),
            "hum_max": st.column_config.NumberColumn("H máx", format="%.1f"),
            "tolerancia_min": st.column_config.NumberColumn(
                "Avisar tras (min)",
                help="Minutos seguidos fuera de rango antes de mandar el mail.",
            ),
        },
    )

    if st.button("Guardar rangos"):
        for _, fila in editada.iterrows():
            sb.table("etapas").update(
                {c: (None if pd.isna(fila[c]) else fila[c]) for c in columnas}
            ).eq("id", int(fila["id"])).execute()
        st.success("Rangos guardados")
        st.rerun()


def editor_config(sb):
    actual = sb.table("config").select("*").limit(1).execute().data[0]

    with st.form("config"):
        destinos = st.text_input(
            "Mails, separados por coma",
            value=", ".join(actual.get("destinatarios") or []),
        )
        mudo = st.number_input(
            "Avisar si no llega nada hace (min)",
            min_value=5, max_value=1440, value=actual["minutos_sin_lecturas"], step=5,
        )
        rocio = st.number_input(
            "Tolerancia de condensación (min)",
            min_value=0, max_value=240, value=actual["tolerancia_rocio_min"], step=5,
        )
        reenvio = st.number_input(
            "Repetir el aviso cada (min)",
            min_value=15, max_value=1440, value=actual["reenvio_min"], step=15,
        )
        if st.form_submit_button("Guardar"):
            sb.table("config").update({
                "destinatarios": [m.strip() for m in destinos.split(",") if m.strip()],
                "minutos_sin_lecturas": mudo,
                "tolerancia_rocio_min": rocio,
                "reenvio_min": reenvio,
            }).eq("id", True).execute()
            st.success("Guardado")


# =====================================================================
#  Panel
# =====================================================================
def encabezado(lote, etapa, lectura, config, del_lote):
    """Arriba de todo: que tan fresco es el dato y de donde sale.

    "del_lote" dice si la lectura que se esta mostrando cayo adentro del
    lote abierto o es simplemente lo ultimo que mando el equipo. No es lo
    mismo y hay que decirlo: si no, el panel muestra numeros de ayer como
    si fueran del lote de hoy.
    """
    st.title("🥩 Panel de control — Secadero")

    if not lectura:
        st.warning(
            "Todavía no llegó **ninguna** lectura del ESP32. Si el equipo "
            "está encendido, revisá el wifi y el token del firmware."
        )
        return

    medido = pd.to_datetime(lectura["medido_en"], utc=True).to_pydatetime()
    minutos = (ahora() - medido).total_seconds() / 60
    sello = (
        f"Última lectura: **{texto_antiguedad(medido)}** "
        f"({medido.astimezone(ZONA).strftime('%d/%m/%Y %H:%M')})"
    )

    # Lo mas importante de la pantalla: si el dato es viejo, los numeros de
    # abajo son una foto vieja y hay que decirlo fuerte.
    if minutos > config["minutos_sin_lecturas"]:
        st.error(
            f"⚠️ {sello}. El equipo no está mandando datos: "
            "lo que se ve abajo es viejo."
        )
    elif minutos > 15:
        st.warning(f"{sello}")
    else:
        st.caption(f"🟢 {sello}")

    if not lote:
        st.info(
            "**No hay ningún lote abierto.** Lo que se ve abajo es lo que el "
            "equipo está midiendo ahora mismo, que sirve igual para calibrar "
            "la balanza o para mirar la cámara vacía.\n\n"
            "**Sin lote abierto no sale ningún mail de alerta.** Los rangos de "
            "temperatura y humedad viven en las etapas del lote: sin lote no "
            "hay contra qué comparar."
        )
        return

    nombre_etapa = etapa["nombre"] if etapa else "sin etapa"
    rangos = (
        f"T {etapa['temp_min']}-{etapa['temp_max']}°C · "
        f"H {etapa['hum_min']}-{etapa['hum_max']}%"
        if etapa else ""
    )
    st.caption(f"Lote **{lote['nombre']}** · Etapa **{nombre_etapa}** · {rangos}")

    if not del_lote:
        st.info(
            f"Esta lectura es **anterior al lote**: el equipo viene midiendo, "
            f"pero todavía no entró ninguna lectura adentro de "
            f"«{lote['nombre']}». La primera llega en los próximos minutos, y "
            f"hasta entonces tampoco salen mails."
        )


def indicadores(lote, lectura):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🌡️ Temp. sala", valor(lectura, "temp_sala", "°C"))
    c2.metric("💧 Humedad", valor(lectura, "hum_sala", "%"))
    c3.metric("🎯 Temp. núcleo", valor(lectura, "temp_nucleo", "°C"))
    c4.metric("🔦 Superficie", valor(lectura, "temp_sup", "°C"))

    merma = merma_de_la_tira(lote, lectura)

    # Sin lote no hay merma posible: la merma se mide contra el peso inicial
    # de la tira, y ese numero se carga al abrir el lote. Lo que si hay es el
    # peso crudo de la celda, que es justo lo que uno mira al calibrar.
    if not lote:
        st.metric(
            "⚖️ Balanza",
            valor(lectura, "peso_tira_g", "g", 0),
            help="Lo que cuelga de la celda en este momento.",
        )
        return None

    estimado = producto_estimado(lote, merma)

    dudosa = merma is not None and merma < MERMA_MINIMA_CREIBLE

    c5, c6, c7 = st.columns(3)
    c5.metric("⚖️ Tira testigo", valor(lectura, "peso_tira_g", "g", 0))
    c6.metric(
        "📉 Merma medida",
        "⚠️ revisar" if dudosa else
        "— sin dato" if merma is None else f"{merma:.1f} %",
        help="La tira testigo contra su propio peso inicial. Es lo único que se mide.",
    )
    c7.metric(
        "📦 Producto estimado",
        "⚠️ revisar" if dudosa else
        "— sin dato" if estimado is None else f"{estimado:.0f} kg",
        help=(
            "Estimación: la merma de la tira aplicada a los kilos embutidos. "
            "Es una cuenta aproximada, no una pesada."
        ),
    )
    return merma


def diagnostico(lectura, etapa, merma, lote):
    """Que significa cada numero y que hay que hacer.

    El riesgo de condensacion se muestra SIEMPRE, con lote o sin lote: el
    punto de rocio sale de la temperatura y la humedad del aire contra la
    superficie de la tripa, y no necesita saber nada del lote. La
    temperatura y la humedad, en cambio, se juzgan contra los rangos de la
    etapa, y esos si vienen del lote.
    """
    st.subheader("🚦 Diagnóstico")

    c1, c2 = st.columns(2)

    with c1:
        st.markdown("#### Temperatura")
        temp = lectura.get("temp_sala")
        if temp is None:
            st.info("Sin dato del sensor de sala.")
        elif not etapa:
            st.info(
                f"La sala está a **{float(temp):.1f}°C**.\n\n"
                "Sin lote abierto no hay rango contra qué compararla."
            )
        elif etapa["temp_max"] is not None and float(temp) > float(etapa["temp_max"]):
            st.error(
                f"**Riesgo:** fusión de grasa superficial y acidez descontrolada "
                f"(supera {etapa['temp_max']}°C).\n\n**Acción:** bajar el termostato."
            )
        elif etapa["temp_min"] is not None and float(temp) < float(etapa["temp_min"]):
            st.warning(
                f"**Riesgo:** se frena la maduración (por debajo de "
                f"{etapa['temp_min']}°C).\n\n**Acción:** subir la calefacción."
            )
        else:
            st.success("✅ Temperatura en rango.")

    with c2:
        st.markdown("#### Humedad")
        hum = lectura.get("hum_sala")
        if hum is None:
            st.info("Sin dato del sensor de humedad.")
        elif not etapa:
            st.info(
                f"La sala está al **{float(hum):.1f} %**.\n\n"
                "Sin lote abierto no hay rango contra qué compararla."
            )
        elif etapa["hum_min"] is not None and float(hum) < float(etapa["hum_min"]):
            st.error(
                f"**Riesgo:** encostramiento de la tripa, el anillo de secado "
                f"bloquea la salida de humedad (por debajo de {etapa['hum_min']}%)."
                f"\n\n**Acción:** apagar forzadores y subir la humedad."
            )
        elif etapa["hum_max"] is not None and float(hum) > float(etapa["hum_max"]):
            st.warning(
                f"**Riesgo:** se frena la merma y aparece flora no deseada "
                f"(supera {etapa['hum_max']}%).\n\n**Acción:** renovar aire."
            )
        else:
            st.success("✅ Humedad en rango.")

    c3, c4 = st.columns(2)

    with c3:
        st.markdown("#### Merma")
        if not lote:
            st.info(
                "Sin lote abierto no hay merma. Se mide contra el peso "
                "inicial de la tira testigo, que se carga al abrir el lote."
            )
        elif merma is None:
            st.info(
                "Sin merma: falta el peso de la tira testigo o la celda "
                "todavía no manda dato."
            )
        elif merma < MERMA_MINIMA_CREIBLE:
            st.error(
                f"**El peso inicial de la tira está mal cargado.** En el lote "
                f"figura {float(lote['tira_peso_inicial_g']):g} g y la celda "
                f"marca {float(lectura['peso_tira_g']):.0f} g, así que la merma "
                f"daría {merma:.0f} %.\n\n"
                "**Acción:** corregilo en «Peso de la tira testigo», en la "
                "barra lateral. No hace falta cerrar el lote."
            )
        else:
            st.success(f"La tira perdió **{merma:.1f} %** de su peso inicial.")

    with c4:
        st.markdown("#### Condensación")
        rocio = punto_de_rocio(lectura.get("temp_sala"), lectura.get("hum_sala"))
        sup = lectura.get("temp_sup")
        if rocio is None or sup is None:
            st.info("Sin datos para calcular el punto de rocío.")
        elif float(sup) <= rocio:
            st.error(
                f"**Riesgo:** la tripa transpira (superficie {float(sup):.1f}°C ≤ "
                f"rocío {rocio:.1f}°C).\n\n**Acción:** bajar humedad y ventilar."
            )
        elif float(sup) - rocio <= MARGEN_ROCIO:
            st.warning(
                f"**Al borde:** a la superficie le quedan "
                f"{float(sup) - rocio:.1f}°C para transpirar "
                f"({float(sup):.1f}°C contra un rocío de {rocio:.1f}°C).\n\n"
                "**Acción:** bajar la humedad ahora, antes de que moje."
            )
        else:
            st.success(
                f"✅ Sin riesgo (superficie {float(sup):.1f}°C > rocío {rocio:.1f}°C, "
                f"{float(sup) - rocio:.1f}°C de margen)."
            )


def graficos(sb, lote):
    st.subheader("📈 Evolución")

    ventanas = ["Últimas 24 h", "Últimos 7 días"] + (["Todo el lote"] if lote else [])
    ventana = st.radio(
        "Ventana", ventanas, horizontal=True, label_visibility="collapsed",
    )
    if ventana == "Últimas 24 h":
        desde, por_hora = ahora() - timedelta(hours=24), False
    elif ventana == "Últimos 7 días":
        # Sin lote se leen las lecturas crudas: "lecturas_por_hora" agrupa
        # por lote, asi que la misma hora vendria repetida una vez por lote
        # y el grafico dibujaria dos lineas pisadas.
        desde, por_hora = ahora() - timedelta(days=7), lote is not None
    else:
        desde = pd.to_datetime(lote["fecha_inicio"], utc=True).to_pydatetime()
        por_hora = True

    df = lecturas(sb, lote["id"] if lote else None, desde, por_hora)
    if df.empty:
        st.info("No hay lecturas en esta ventana.")
        return

    if not lote:
        st.caption("Todo lo que mandó el equipo, sin filtrar por lote.")
    if por_hora:
        st.caption(f"{len(df)} puntos, promediados por hora.")

    nombres = {
        "temp_sala": "Temp sala",
        "temp_nucleo": "Temp núcleo",
        "temp_sup": "Temp superficie",
        "hum_sala": "Humedad",
        "peso_tira_g": "Peso tira (g)",
    }
    df = df.rename(columns=nombres)

    t1, t2, t3, t4, t5 = st.tabs(
        ["Temperaturas", "Humedad", "Peso", "Merma", "pH"]
    )

    with t1:
        columnas = [c for c in ["Temp sala", "Temp núcleo", "Temp superficie"]
                    if c in df and df[c].notna().any()]
        if columnas:
            st.plotly_chart(
                px.line(df, x="momento", y=columnas,
                        labels={"value": "°C", "variable": "Sensor", "momento": ""}),
                use_container_width=True,
            )
        else:
            st.info("Sin datos de temperatura en esta ventana.")

    with t2:
        if "Humedad" in df and df["Humedad"].notna().any():
            st.plotly_chart(
                px.line(df, x="momento", y="Humedad",
                        labels={"Humedad": "%", "momento": ""}),
                use_container_width=True,
            )
        else:
            st.info("Sin datos de humedad en esta ventana.")

    with t3:
        # El peso crudo, sin convertir a merma. Es el grafico que hace falta
        # para ver si la celda esta quieta: con un peso fijo colgado la linea
        # tiene que ser plana, y cualquier deriva se ve de una.
        if "Peso tira (g)" in df and df["Peso tira (g)"].notna().any():
            st.plotly_chart(
                px.line(df, x="momento", y="Peso tira (g)",
                        labels={"momento": ""}),
                use_container_width=True,
            )
            st.caption(
                "Lo que marca la celda, en crudo. Con un peso fijo colgado "
                "la línea tiene que ser plana: si sube o baja sola, la "
                "balanza está derivando."
            )
        else:
            st.info(
                "La celda no está mandando peso. Si nunca se calibró, el "
                "equipo manda `null` a propósito en vez de inventar un número."
            )

    with t4:
        inicial = lote.get("tira_peso_inicial_g") if lote else None
        if not lote:
            st.info(
                "No hay merma para esta ventana: la merma se calcula contra "
                "el peso inicial de la tira del lote. En la pestaña **Peso** "
                "está lo que marcó la celda."
            )
        elif "Peso tira (g)" in df and df["Peso tira (g)"].notna().any() and inicial:
            df["Merma (%)"] = (
                (float(inicial) - df["Peso tira (g)"]) / float(inicial) * 100
            )
            st.plotly_chart(
                px.line(df, x="momento", y="Merma (%)",
                        labels={"momento": ""}),
                use_container_width=True,
            )
        else:
            st.info(
                "Sin merma todavía: falta el peso inicial de la tira o la celda "
                "no está mandando."
            )

    with t5:
        filas = (
            sb.table("mediciones").select("*").eq("lote_id", lote["id"])
            .not_.is_("ph", "null").order("medido_en").execute().data or []
        ) if lote else []
        if not lote:
            st.info("El pH se carga a mano y va atado a un lote.")
        elif filas:
            dfp = pd.DataFrame(filas)
            dfp["momento"] = pd.to_datetime(dfp["medido_en"], utc=True).dt.tz_convert(ZONA)
            st.plotly_chart(
                px.line(dfp, x="momento", y="ph", markers=True,
                        labels={"ph": "pH", "momento": ""}),
                use_container_width=True,
            )
        else:
            st.info("No hay mediciones de pH cargadas para este lote.")


def historial(sb):
    with st.expander("🗄️ Lotes anteriores"):
        filas = (
            sb.table("lotes").select("*").order("fecha_inicio", desc=True)
            .limit(100).execute().data or []
        )
        if not filas:
            st.info("Todavía no hay lotes.")
            return
        df = pd.DataFrame(filas)
        df["fecha_inicio"] = pd.to_datetime(df["fecha_inicio"], utc=True) \
            .dt.tz_convert(ZONA).dt.strftime("%d/%m/%Y %H:%M")
        st.dataframe(
            df[["nombre", "fecha_inicio", "estado",
                "tira_peso_inicial_g", "kg_embutidos"]]
            .rename(columns={
                "nombre": "Lote", "fecha_inicio": "Inicio", "estado": "Estado",
                "tira_peso_inicial_g": "Tira (g)", "kg_embutidos": "Embutido (kg)",
            }),
            use_container_width=True, hide_index=True,
        )


# =====================================================================
#  Arranque
# =====================================================================
def main():
    sb = conexion()

    if "usuario" not in st.session_state:
        pantalla_login(sb)
        return

    st_autorefresh(interval=60000, key="recarga")

    lote = lote_activo(sb)
    lista_etapas = etapas(sb, lote["id"]) if lote else []
    config = sb.table("config").select("*").limit(1).execute().data[0]
    etapa = etapa_vigente(lista_etapas, lote["fecha_inicio"]) if lote else None

    # El panel muestra lo que el equipo esta midiendo AHORA, haya lote o no.
    # Antes todo colgaba de la primera lectura del lote: sin lote abierto, o
    # con un lote recien creado, la pantalla quedaba vacia y parecia que el
    # equipo estaba muerto cuando en realidad venia mandando cada 5 minutos.
    lectura = ultima_lectura(sb, lote["id"]) if lote else None
    del_lote = lectura is not None
    if lectura is None:
        lectura = ultima_lectura(sb)

    # Despues de la lectura: la barra lateral la usa para ofrecer el peso que
    # marca la balanza en este momento.
    barra_lateral(sb, lote, lista_etapas, lectura)

    encabezado(lote, etapa, lectura, config, del_lote)

    if lectura:
        st.markdown("---")
        merma = indicadores(lote, lectura)
        st.markdown("---")
        diagnostico(lectura, etapa, merma, lote)
        st.markdown("---")
        # Si el lote todavia no recibio nada, los graficos se dibujan con lo
        # del equipo: un grafico vacio no le sirve a nadie.
        graficos(sb, lote if del_lote else None)

    historial(sb)


if __name__ == "__main__":
    main()
