"""
Panel de control del secadero — Nostro Chacinados.

Lee la telemetria que manda el ESP32 y la muestra para Esteban y Rafael.
Nada de esto se puede ver sin estar logueado.
"""

import html
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from supabase import create_client

import estilo
from cuentas import (MARGEN_ROCIO, MERMA_MINIMA_CREIBLE, TOPE_SUPABASE, ZONA,
                     merma_de, punto_de_rocio)
from informe import informe_de_lote

st.set_page_config(page_title="Secadero IoT", layout="wide")
estilo.aplicar()


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
    st.title("Secadero Nostro")
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


def merma_de_la_tira(lote, lectura):
    """La merma medida: la tira testigo contra su propio peso inicial.

    Es la unica merma que se mide de verdad. Antes se comparaba el peso de
    la tira contra los kilos del lote entero y daba cualquier cosa.
    """
    if not lote or not lectura:
        return None
    return merma_de(lote.get("tira_peso_inicial_g"), lectura.get("peso_tira_g"))


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
    with st.expander("Peso de la tira testigo"):
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
        st.caption(st.session_state.usuario)
        if st.button("Salir"):
            sb.auth.sign_out()
            st.session_state.clear()
            st.rerun()

        st.markdown("---")
        st.header("Lote")

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
                else "Falta el peso de la tira"
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

        with st.expander("Iniciar lote nuevo"):
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
            st.header("Rangos por etapa")
            st.caption(
                "Los rangos y los minutos de tolerancia se guardan en la base: "
                "los ven igual los dos y de acá salen los mails."
            )
            editor_etapas(sb, lote, lista_etapas)

            st.markdown("---")
            st.header("Carga manual")
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
        with st.expander("Avisos por mail"):
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
    st.title("Panel de control — Secadero")

    if not lectura:
        estilo.aviso(
            "mal", "No llegó ninguna lectura todavía.",
            "El panel está vacío porque el ESP32 nunca mandó nada.",
            "Si el equipo está encendido, revisar el wifi y el token del "
            "firmware.",
        )
        return

    medido = pd.to_datetime(lectura["medido_en"], utc=True).to_pydatetime()
    minutos = (ahora() - medido).total_seconds() / 60
    cuando = medido.astimezone(ZONA).strftime("%d/%m/%Y %H:%M")

    # Lo mas importante de la pantalla: si el dato es viejo, los numeros de
    # abajo son una foto vieja y hay que decirlo fuerte.
    if minutos > config["minutos_sin_lecturas"]:
        estilo.aviso(
            "mal", f"El equipo no manda datos {texto_antiguedad(medido)}.",
            f"La última lectura es del {cuando}. Todo lo que se ve abajo es "
            "esa foto vieja, no el secadero de ahora.",
            "Puede ser el wifi, la corriente o el equipo colgado.",
        )
    else:
        color = estilo.VERDE if minutos <= 15 else estilo.AMBAR
        estilo.cinta(
            color,
            f"Última lectura <b>{texto_antiguedad(medido)}</b> &nbsp;·&nbsp; "
            f"{cuando}",
        )

    if not lote:
        estilo.aviso(
            "info", "No hay ningún lote abierto.",
            "Abajo está lo que el equipo mide ahora mismo, que sirve igual "
            "para calibrar la balanza o para mirar la cámara vacía. Pero sin "
            "lote no sale ningún mail: los rangos de temperatura y humedad "
            "viven en las etapas del lote, así que no hay contra qué comparar.",
        )
        return

    nombre_etapa = etapa["nombre"] if etapa else "sin etapa"
    rangos = (
        f" &nbsp;·&nbsp; T {etapa['temp_min']}-{etapa['temp_max']}°C "
        f"&nbsp;·&nbsp; H {etapa['hum_min']}-{etapa['hum_max']}%"
        if etapa else ""
    )
    inicio = pd.to_datetime(lote["fecha_inicio"], utc=True)
    st.markdown(
        f'<div class="cinta"><span>Lote <b>{html.escape(lote["nombre"])}</b>'
        f" &nbsp;·&nbsp; día <b>{(ahora() - inicio.to_pydatetime()).days}</b>"
        f" &nbsp;·&nbsp; {html.escape(nombre_etapa)}{rangos}</span></div>",
        unsafe_allow_html=True,
    )

    if not del_lote:
        estilo.aviso(
            "info", "Esta lectura es anterior al lote.",
            f"El equipo viene midiendo, pero todavía no entró ninguna lectura "
            f"adentro de «{lote['nombre']}». La primera llega en los próximos "
            "minutos, y hasta entonces tampoco salen mails.",
        )


def _tono(texto):
    """Gris apagado cuando no hay dato, para que no compita con los numeros
    de verdad."""
    return "sin" if texto.startswith("—") else ""


def indicadores(lote, lectura):
    ambiente = [
        ("Temp. sala",   valor(lectura, "temp_sala", "°C"),   "", None),
        ("Humedad",      valor(lectura, "hum_sala", "%"),     "", None),
        ("Temp. núcleo", valor(lectura, "temp_nucleo", "°C"), "", None),
        ("Superficie",   valor(lectura, "temp_sup", "°C"),    "", None),
    ]
    estilo.kpis([(e, v, _tono(v) or t, p) for e, v, t, p in ambiente])

    merma = merma_de_la_tira(lote, lectura)
    peso = valor(lectura, "peso_tira_g", "g", 0)

    # Sin lote no hay merma posible: la merma se mide contra el peso inicial
    # de la tira, y ese numero se carga al abrir el lote. Lo que si hay es el
    # peso crudo de la celda, que es justo lo que uno mira al calibrar.
    if not lote:
        estilo.kpis([("Balanza", peso, _tono(peso),
                      "lo que cuelga de la celda ahora")])
        return None

    estimado = producto_estimado(lote, merma)
    dudosa = merma is not None and merma < MERMA_MINIMA_CREIBLE
    inicial = lote.get("tira_peso_inicial_g")

    if dudosa:
        texto_merma, tono_merma = "revisar", "neg"
        texto_prod, tono_prod = "revisar", "neg"
    else:
        texto_merma = "— sin dato" if merma is None else f"{merma:.1f} %"
        tono_merma = "sin" if merma is None else "pos"
        texto_prod = "— sin dato" if estimado is None else f"{estimado:.0f} kg"
        tono_prod = _tono(texto_prod)

    estilo.kpis([
        ("Tira testigo", peso, _tono(peso),
         f"arrancó en {float(inicial):g} g" if inicial else "falta el peso inicial"),
        ("Merma medida", texto_merma, tono_merma,
         "la tira contra su propio peso inicial"),
        ("Producto estimado", texto_prod, tono_prod,
         "estimación, no una pesada"),
    ])
    return merma


# ---------------------------------------------------------------------
#  Los juicios
#
#  Cada uno devuelve (tono, titulo, texto, accion) y no dibuja nada. Asi
#  el panel y el PDF del lote dicen exactamente lo mismo del mismo dato,
#  en vez de tener dos redacciones que con el tiempo se separan.
# ---------------------------------------------------------------------
def juicio_temperatura(lectura, etapa):
    temp = lectura.get("temp_sala")
    if temp is None:
        return ("info", "Sin dato", "El sensor de sala no está contestando.", None)
    temp = float(temp)
    if not etapa:
        return ("info", f"{temp:.1f} °C",
                "Sin lote abierto no hay rango contra qué compararla.", None)
    if etapa["temp_max"] is not None and temp > float(etapa["temp_max"]):
        return ("mal", f"{temp:.1f} °C — demasiado alta",
                f"Pasa los {etapa['temp_max']} °C de la etapa. Se funde la "
                "grasa de la superficie y la acidez se descontrola.",
                "Bajar el termostato.")
    if etapa["temp_min"] is not None and temp < float(etapa["temp_min"]):
        return ("ojo", f"{temp:.1f} °C — demasiado baja",
                f"Está por debajo de los {etapa['temp_min']} °C de la etapa. "
                "La maduración se frena.",
                "Subir la calefacción.")
    return ("ok", f"{temp:.1f} °C — en rango",
            f"La etapa pide entre {etapa['temp_min']} y {etapa['temp_max']} °C.",
            None)


def juicio_humedad(lectura, etapa):
    hum = lectura.get("hum_sala")
    if hum is None:
        return ("info", "Sin dato", "El sensor de humedad no está contestando.", None)
    hum = float(hum)
    if not etapa:
        return ("info", f"{hum:.1f} %",
                "Sin lote abierto no hay rango contra qué compararla.", None)
    if etapa["hum_min"] is not None and hum < float(etapa["hum_min"]):
        return ("mal", f"{hum:.1f} % — demasiado seca",
                f"Está por debajo del {etapa['hum_min']} % de la etapa. La "
                "tripa se encostra y el anillo de secado tapa la salida de "
                "humedad de adentro.",
                "Apagar forzadores y subir la humedad.")
    if etapa["hum_max"] is not None and hum > float(etapa["hum_max"]):
        return ("ojo", f"{hum:.1f} % — demasiado húmeda",
                f"Pasa el {etapa['hum_max']} % de la etapa. La merma se frena "
                "y aparece flora que no queremos.",
                "Renovar aire.")
    return ("ok", f"{hum:.1f} % — en rango",
            f"La etapa pide entre {etapa['hum_min']} y {etapa['hum_max']} %.",
            None)


def juicio_merma(lote, lectura, merma):
    if not lote:
        return ("info", "Sin lote",
                "La merma se mide contra el peso inicial de la tira testigo, "
                "que se carga al abrir el lote.", None)
    if merma is None:
        return ("info", "Sin merma",
                "Falta el peso inicial de la tira o la celda no está mandando "
                "dato.", None)
    if merma < MERMA_MINIMA_CREIBLE:
        return ("mal", "El peso inicial de la tira está mal cargado",
                f"En el lote figura {float(lote['tira_peso_inicial_g']):g} g y "
                f"la celda marca {float(lectura['peso_tira_g']):.0f} g, así que "
                f"la merma daría {merma:.0f} %.",
                "Corregirlo en «Peso de la tira testigo», en la barra lateral. "
                "No hace falta cerrar el lote.")
    return ("ok", f"{merma:.1f} % perdido",
            "Es lo que bajó la tira testigo respecto de su propio peso "
            "inicial.", None)


def juicio_condensacion(lectura):
    rocio = punto_de_rocio(lectura.get("temp_sala"), lectura.get("hum_sala"))
    sup = lectura.get("temp_sup")
    if rocio is None or sup is None:
        return ("info", "Sin dato",
                "Falta temperatura, humedad o el infrarrojo para calcular el "
                "punto de rocío.", None)
    sup = float(sup)
    margen = sup - rocio
    if margen <= 0:
        return ("mal", "La tripa está transpirando",
                f"La superficie está a {sup:.1f} °C y el rocío es "
                f"{rocio:.1f} °C: el agua ya se le está condensando encima.",
                "Bajar la humedad y ventilar para secar la película.")
    if margen <= MARGEN_ROCIO:
        return ("ojo", f"Al borde — le quedan {margen:.1f} °C",
                f"La superficie está a {sup:.1f} °C contra un rocío de "
                f"{rocio:.1f} °C. Todavía está seca, pero por poco.",
                "Bajar la humedad ahora, antes de que moje.")
    return ("ok", f"Sin riesgo — {margen:.1f} °C de margen",
            f"La superficie está a {sup:.1f} °C y el rocío es {rocio:.1f} °C.",
            None)


def diagnostico(lectura, etapa, merma, lote):
    """Que significa cada numero y que hay que hacer.

    El riesgo de condensacion se muestra SIEMPRE, con lote o sin lote: el
    punto de rocio sale de la temperatura y la humedad del aire contra la
    superficie de la tripa, y no necesita saber nada del lote. La
    temperatura y la humedad, en cambio, se juzgan contra los rangos de la
    etapa, y esos si vienen del lote.
    """
    st.subheader("Diagnóstico")

    bloques = [
        ("Temperatura",  juicio_temperatura(lectura, etapa)),
        ("Humedad",      juicio_humedad(lectura, etapa)),
        ("Merma",        juicio_merma(lote, lectura, merma)),
        ("Condensación", juicio_condensacion(lectura)),
    ]

    for fila in (bloques[:2], bloques[2:]):
        for columna, (encabezado_bloque, juicio) in zip(st.columns(2), fila):
            with columna:
                st.markdown(f"##### {encabezado_bloque}")
                estilo.aviso(*juicio)


def graficos(sb, lote):
    st.subheader("Evolución")

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
            estilo.grafico(px.line(
                df, x="momento", y=columnas,
                color_discrete_map=estilo.COLORES_SERIES,
                labels={"value": "°C", "variable": "", "momento": ""},
            ))
        else:
            st.info("Sin datos de temperatura en esta ventana.")

    with t2:
        if "Humedad" in df and df["Humedad"].notna().any():
            estilo.grafico(px.line(
                df, x="momento", y="Humedad",
                color_discrete_sequence=[estilo.COLORES_SERIES["Humedad"]],
                labels={"Humedad": "%", "momento": ""},
            ))
        else:
            st.info("Sin datos de humedad en esta ventana.")

    with t3:
        # El peso crudo, sin convertir a merma. Es el grafico que hace falta
        # para ver si la celda esta quieta: con un peso fijo colgado la linea
        # tiene que ser plana, y cualquier deriva se ve de una.
        if "Peso tira (g)" in df and df["Peso tira (g)"].notna().any():
            estilo.grafico(px.line(
                df, x="momento", y="Peso tira (g)",
                color_discrete_sequence=[estilo.COLORES_SERIES["Peso tira (g)"]],
                labels={"momento": ""},
            ))
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
            estilo.grafico(px.line(
                df, x="momento", y="Merma (%)",
                color_discrete_sequence=[estilo.COLORES_SERIES["Merma (%)"]],
                labels={"momento": ""},
            ))
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
            estilo.grafico(px.line(
                dfp, x="momento", y="ph", markers=True,
                color_discrete_sequence=[estilo.VERDE_MARCA],
                labels={"ph": "pH", "momento": ""},
            ))
        else:
            st.info("No hay mediciones de pH cargadas para este lote.")


def datos_del_lote(sb, lote_id):
    """Todo lo que necesita el informe de un lote, de una sola vez.

    Las lecturas vienen de la vista por hora y no crudas: un lote de un
    mes son 8.600 filas, y para un PDF que se lee en una pagina el
    promedio horario cuenta la misma historia con 720 puntos.
    """
    filas = _paginar(
        lambda: sb.table("lecturas_por_hora").select("*")
        .eq("lote_id", lote_id).order("hora")
    )
    df = pd.DataFrame(filas)
    if not df.empty:
        df["momento"] = pd.to_datetime(df["hora"], utc=True).dt.tz_convert(ZONA)

    return {
        "df": df,
        "etapas": etapas(sb, lote_id),
        "mediciones": (
            sb.table("mediciones").select("*").eq("lote_id", lote_id)
            .order("medido_en").execute().data or []
        ),
        "alertas": (
            sb.table("alertas").select("*").eq("lote_id", lote_id)
            .order("inicio").execute().data or []
        ),
    }


def _nombre_de_archivo(lote):
    limpio = "".join(
        c if c.isalnum() or c in " -_" else "-" for c in lote["nombre"]
    ).strip().replace(" ", "-")
    inicio = pd.to_datetime(lote["fecha_inicio"], utc=True).tz_convert(ZONA)
    return f"{inicio.strftime('%Y-%m-%d')}-{limpio or 'lote'}.pdf"


def descarga_de_informe(sb, lotes):
    """Elegir un lote y bajarlo en PDF.

    Son dos pasos y no uno a proposito. st.download_button necesita el
    archivo ya armado para poder dibujarse, asi que un boton directo
    significaria generar el PDF de TODOS los lotes en cada recarga de la
    pagina, y la pagina se recarga sola cada minuto.
    """
    st.markdown("##### Descargar un informe")
    st.caption(
        "Un PDF con los datos del lote, los gráficos y las alertas que "
        "saltaron, para analizarlo o mostrarlo fuera del panel."
    )

    por_nombre = {
        f"{l['nombre']} · "
        f"{pd.to_datetime(l['fecha_inicio'], utc=True).tz_convert(ZONA):%d/%m/%Y}": l
        for l in lotes
    }
    elegido = st.selectbox("Lote", list(por_nombre), label_visibility="collapsed")
    lote = por_nombre[elegido]

    if st.button("Preparar el informe", type="primary"):
        with st.spinner("Juntando los datos y dibujando los gráficos…"):
            datos = datos_del_lote(sb, lote["id"])
            st.session_state.informe = {
                "archivo": _nombre_de_archivo(lote),
                "pdf": informe_de_lote(
                    lote, datos["df"], datos["etapas"],
                    datos["mediciones"], datos["alertas"],
                ),
            }

    listo = st.session_state.get("informe")
    if listo:
        st.download_button(
            f"Descargar {listo['archivo']}",
            data=listo["pdf"],
            file_name=listo["archivo"],
            mime="application/pdf",
        )


def historial(sb):
    with st.expander("Lotes anteriores"):
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

        st.markdown("---")
        descarga_de_informe(sb, filas)


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
