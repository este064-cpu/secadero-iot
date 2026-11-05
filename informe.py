"""
El PDF de un lote terminado, para analizarlo despues o mostrarlo.

Se arma con los datos que quedaron en la base, no con lo que hay en
pantalla: un lote de hace seis meses tiene que dar el mismo informe hoy
que el año que viene.

Los graficos se dibujan con matplotlib y no con los plotly del panel.
Plotly necesita un navegador headless (kaleido) para exportar a imagen, y
eso en Streamlit Cloud es una pieza mas que se puede romper sin aviso.
Matplotlib dibuja un PNG y listo. Los colores son los mismos, asi que la
linea de temperatura del PDF es del mismo color que la de la pantalla.
"""

import io
from datetime import datetime

import matplotlib
matplotlib.use("Agg")          # sin ventana: corre en un servidor
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph,
                                SimpleDocTemplate, Spacer, Table, TableStyle)

import estilo
from cuentas import MARGEN_ROCIO, ZONA, margen_de_rocio, merma_de

ANCHO_UTIL = A4[0] - 32 * mm


# =====================================================================
#  Estilos de texto
# =====================================================================
def _estilos():
    base = getSampleStyleSheet()
    normal = ParagraphStyle(
        "cuerpo", parent=base["Normal"], fontName="Helvetica", fontSize=9.5,
        leading=13.5, textColor=colors.HexColor(estilo.TEXTO), alignment=TA_LEFT,
    )
    return {
        "titulo": ParagraphStyle(
            "titulo", parent=normal, fontName="Helvetica-Bold", fontSize=18,
            leading=22, textColor=colors.HexColor(estilo.VERDE_MARCA),
            spaceAfter=2,
        ),
        "bajada": ParagraphStyle(
            "bajada", parent=normal, fontSize=9,
            textColor=colors.HexColor(estilo.TEXTO_SUAVE), spaceAfter=14,
        ),
        "seccion": ParagraphStyle(
            "seccion", parent=normal, fontName="Helvetica-Bold", fontSize=11.5,
            leading=15, textColor=colors.HexColor(estilo.VERDE_MARCA),
            spaceBefore=12, spaceAfter=6,
        ),
        "cuerpo": normal,
        "nota": ParagraphStyle(
            "nota", parent=normal, fontSize=8.5, leading=11.5,
            textColor=colors.HexColor(estilo.TEXTO_SUAVE), spaceBefore=3,
        ),
    }


# =====================================================================
#  Piezas
# =====================================================================
def _tabla(filas, anchos, cabecera=True):
    """Una tabla con la misma cara que las del panel: fina, con aire."""
    t = Table(filas, colWidths=anchos, repeatRows=1 if cabecera else 0)
    estilos = [
        ("FONTNAME",   (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8.8),
        ("TEXTCOLOR",  (0, 0), (-1, -1), colors.HexColor(estilo.TEXTO)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 7),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 7),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW",  (0, 0), (-1, -2), 0.4, colors.HexColor(estilo.BORDE)),
        ("BOX",        (0, 0), (-1, -1), 0.6, colors.HexColor(estilo.BORDE)),
    ]
    if cabecera:
        estilos += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(estilo.TARJETA)),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.HexColor(estilo.TITULO_CARD)),
            ("LINEBELOW",  (0, 0), (-1, 0), 0.6,
             colors.HexColor(estilo.BORDE_TARJETA)),
        ]
    t.setStyle(TableStyle(estilos))
    return t


def _fila_de_kpis(items):
    """La misma fila de numeros grandes que arriba del panel."""
    etiquetas = [Paragraph(
        f'<font size="7" color="{estilo.TEXTO_SUAVE}">{e.upper()}</font>',
        getSampleStyleSheet()["Normal"]) for e, _ in items]
    valores = [Paragraph(
        f'<font size="14" color="{estilo.TEXTO}"><b>{v}</b></font>',
        getSampleStyleSheet()["Normal"]) for _, v in items]

    ancho = ANCHO_UTIL / len(items)
    t = Table([etiquetas, valores], colWidths=[ancho] * len(items))
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), colors.HexColor(estilo.TARJETA)),
        ("BOX",           (0, 0), (-1, -1), 0.6,
         colors.HexColor(estilo.BORDE_TARJETA)),
        ("INNERGRID",     (0, 0), (-1, -1), 0.6,
         colors.HexColor(estilo.BORDE_TARJETA)),
        ("TOPPADDING",    (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
        ("TOPPADDING",    (0, 1), (-1, 1), 1),
        ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 9),
    ]))
    return t


def _junto(*piezas):
    """Que el titulo no quede solo al pie de una pagina y el grafico en la
    siguiente."""
    return KeepTogether(list(piezas))


def _grafico(df, columnas, etiqueta_y, bandas=None):
    """Un PNG de una serie de tiempo, con los colores del panel.

    "bandas" son (desde, hasta, minimo, maximo): el rango que pedia la
    etapa, pintado nada mas que sobre los dias en que esa etapa estuvo
    vigente. Pintarlas de lado a lado seria mentir, porque daria a
    entender que los tres rangos valian todo el tiempo.
    """
    presentes = [c for c in columnas if c in df and df[c].notna().any()]
    if not presentes:
        return None

    fig, ax = plt.subplots(figsize=(7.2, 2.6), dpi=170)

    for desde, hasta, minimo, maximo in (bandas or []):
        if minimo is None or maximo is None:
            continue
        ax.fill_between([desde, hasta], float(minimo), float(maximo),
                        color=estilo.VERDE_MARCA, alpha=0.07, linewidth=0,
                        zorder=0)

    # La primera columna se dibuja ARRIBA de las demas: las tres
    # temperaturas se superponen casi siempre, y la de sala es la que
    # importa. El zorder lo decide el orden pedido, no el de dibujo.
    lineas = {}
    for altura, columna in enumerate(presentes):
        lineas[columna], = ax.plot(
            df["momento"], df[columna], linewidth=1.2,
            color=estilo.COLORES_SERIES.get(columna, estilo.VERDE_MARCA),
            label=columna, zorder=10 - altura,
        )

    ax.set_ylabel(etiqueta_y, fontsize=8, color=estilo.TEXTO_SUAVE)
    ax.tick_params(labelsize=7.5, colors=estilo.TEXTO_SUAVE, length=3)
    ax.grid(axis="y", color="#f1f3f1", linewidth=0.8, zorder=1)
    ax.set_axisbelow(True)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(estilo.BORDE)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m", tz=ZONA))
    if len(presentes) > 1:
        ax.legend([lineas[c] for c in presentes], presentes,
                  fontsize=7.5, frameon=False, ncol=len(presentes),
                  loc="upper left", bbox_to_anchor=(0, 1.18))

    fig.tight_layout(pad=0.4)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    return Image(buf, width=ANCHO_UTIL, height=ANCHO_UTIL * 0.355)


# =====================================================================
#  Cuentas del informe
# =====================================================================
def _resumen(serie):
    """Minimo, promedio y maximo de una columna, o None si esta vacia."""
    s = serie.dropna() if serie is not None else None
    if s is None or s.empty:
        return None
    return float(s.min()), float(s.mean()), float(s.max())


def _horas_fuera(serie, minimo, maximo):
    """Horas que esa serie estuvo fuera del rango.

    El df viene por hora, asi que cada fila es una hora. Las lecturas que
    faltan no cuentan, y esta bien: si el equipo estuvo caido no sabemos
    que paso ahi adentro, y contarlo como "en rango" seria inventarlo.
    """
    if serie is None or (minimo is None and maximo is None):
        return None
    s = serie.dropna()
    if s.empty:
        return None
    mal = pd.Series(False, index=s.index)
    if minimo is not None:
        mal |= s < float(minimo)
    if maximo is not None:
        mal |= s > float(maximo)
    return int(mal.sum())


def _horas_al_borde_del_rocio(trozo):
    """Horas en que a la superficie le quedaba medio grado o menos."""
    columnas = ["temp_sala", "hum_sala", "temp_sup"]
    if any(c not in trozo for c in columnas):
        return None
    margenes = [
        margen_de_rocio(f.temp_sala, f.hum_sala, f.temp_sup)
        for f in trozo[columnas].itertuples()
    ]
    validos = [m for m in margenes if m is not None]
    if not validos:
        return None
    return sum(1 for m in validos if m <= MARGEN_ROCIO)


def _tramos_por_etapa(df, etapas, inicio):
    """Parte las lecturas segun que etapa estaba vigente en cada momento.

    Sin esto no se puede decir nada honesto sobre "horas fuera de rango":
    los 22 °C del primer dia son perfectos en la estufa y un desastre en
    secado. Hay que juzgar cada lectura contra el rango que regia ese dia.
    """
    if df.empty or not etapas:
        return []

    dia = (df["momento"] - inicio).dt.days
    tramos = []
    for i, etapa in enumerate(etapas):
        # La ultima etapa se estira hasta el final: un lote que dura mas
        # de lo previsto no se queda sin rangos contra que compararse.
        ultima = i == len(etapas) - 1
        dentro = (dia >= etapa["dia_desde"]) if ultima else (
            (dia >= etapa["dia_desde"]) & (dia <= etapa["dia_hasta"]))
        trozo = df[dentro]
        if not trozo.empty:
            tramos.append((etapa, trozo))
    return tramos


# =====================================================================
#  El informe
# =====================================================================
def informe_de_lote(lote, df, etapas, mediciones, alertas):
    """Devuelve el PDF en bytes.

    "df" son las lecturas por hora del lote, ya con la columna "momento"
    en hora argentina. Lo arma quien llama, que es el que sabe paginar
    Supabase.
    """
    s = _estilos()
    partes = []

    inicio = pd.to_datetime(lote["fecha_inicio"], utc=True).tz_convert(ZONA)
    fin = (pd.to_datetime(lote["fecha_fin"], utc=True).tz_convert(ZONA)
           if lote.get("fecha_fin") else None)
    dias = ((fin or pd.Timestamp.now(tz=ZONA)) - inicio).days

    # ---- Encabezado -------------------------------------------------
    partes.append(Paragraph(lote["nombre"], s["titulo"]))
    partes.append(Paragraph(
        f"Secadero Nostro &nbsp;·&nbsp; informe de lote &nbsp;·&nbsp; "
        f"generado el {datetime.now(ZONA).strftime('%d/%m/%Y a las %H:%M')}",
        s["bajada"]))

    # ---- Los numeros del lote ---------------------------------------
    inicial = lote.get("tira_peso_inicial_g")
    peso_final = None
    if "peso_tira_g" in df and df["peso_tira_g"].notna().any():
        peso_final = float(df["peso_tira_g"].dropna().iloc[-1])
    merma = merma_de(inicial, peso_final)

    partes.append(_fila_de_kpis([
        ("Duración", f"{dias} días"),
        ("Estado", lote.get("estado", "—")),
        ("Tira inicial", f"{float(inicial):g} g" if inicial else "sin dato"),
        ("Tira final", f"{peso_final:.0f} g" if peso_final is not None else "sin dato"),
        ("Merma", f"{merma:.1f} %" if merma is not None else "sin dato"),
    ]))
    partes.append(Spacer(1, 4))

    datos = [["Desde", inicio.strftime("%d/%m/%Y %H:%M")],
             ["Hasta", fin.strftime("%d/%m/%Y %H:%M") if fin else "sigue abierto"],
             ["Lecturas del equipo", f"{len(df)} horas con datos"]]
    if lote.get("kg_embutidos"):
        kilos = float(lote["kg_embutidos"])
        datos.append(["Kilos embutidos", f"{kilos:.0f} kg"])
        if merma is not None:
            datos.append(["Producto estimado al cierre",
                          f"{kilos * (1 - merma / 100):.0f} kg "
                          f"(estimación, no una pesada)"])
    if lote.get("nota"):
        datos.append(["Nota", lote["nota"]])
    partes.append(_tabla(datos, [55 * mm, ANCHO_UTIL - 55 * mm], cabecera=False))

    if df.empty:
        partes.append(Paragraph(
            "Este lote no tiene ninguna lectura del equipo, así que no hay "
            "gráficos ni estadísticas que mostrar.", s["nota"]))
        return _armar(partes)

    # ---- Condiciones ------------------------------------------------
    partes.append(Paragraph("Condiciones en la cámara", s["seccion"]))

    filas = [["", "Mínima", "Promedio", "Máxima"]]
    for etiqueta, columna, unidad in [
        ("Temperatura de sala", "temp_sala", "°C"),
        ("Humedad", "hum_sala", "%"),
        ("Temperatura de núcleo", "temp_nucleo", "°C"),
        ("Temperatura de superficie", "temp_sup", "°C"),
    ]:
        r = _resumen(df.get(columna))
        filas.append([etiqueta] + (
            [f"{v:.1f} {unidad}" for v in r] if r else ["sin dato"] * 3))
    partes.append(_tabla(filas, [62 * mm] + [(ANCHO_UTIL - 62 * mm) / 3] * 3))

    # ---- Cuanto tiempo estuvo fuera de rango, etapa por etapa --------
    tramos = _tramos_por_etapa(df, etapas, inicio)
    if tramos:
        partes.append(Spacer(1, 9))
        filas = [["Etapa", "Días", "Horas\ncon datos",
                  "Temp. fuera\nde rango", "Humedad fuera\nde rango",
                  "Al borde\ndel rocío"]]
        for etapa, trozo in tramos:
            def _h(valor):
                return "—" if valor is None else f"{valor} h"
            filas.append([
                etapa["nombre"],
                f"{etapa['dia_desde']}–{etapa['dia_hasta']}",
                str(len(trozo)),
                _h(_horas_fuera(trozo.get("temp_sala"),
                                etapa["temp_min"], etapa["temp_max"])),
                _h(_horas_fuera(trozo.get("hum_sala"),
                                etapa["hum_min"], etapa["hum_max"])),
                _h(_horas_al_borde_del_rocio(trozo)),
            ])
        resto = ANCHO_UTIL - 48 * mm
        partes.append(_tabla(filas, [48 * mm] + [resto / 5] * 5))
        partes.append(Paragraph(
            "Cada lectura se compara contra el rango que regía ese día, no "
            "contra uno solo: 22 °C son perfectos en la estufa y un desastre "
            "en secado. Las horas sin lectura no suman, porque no sabemos qué "
            "pasó ahí adentro mientras el equipo estuvo callado.", s["nota"]))

    # ---- Graficos ---------------------------------------------------
    # Cada etapa pinta su rango solo sobre los dias en que estuvo vigente.
    bandas = [
        (trozo["momento"].iloc[0], trozo["momento"].iloc[-1],
         etapa["temp_min"], etapa["temp_max"])
        for etapa, trozo in tramos
    ]
    bandas_hum = [
        (trozo["momento"].iloc[0], trozo["momento"].iloc[-1],
         etapa["hum_min"], etapa["hum_max"])
        for etapa, trozo in tramos
    ]

    lindo = df.rename(columns=NOMBRES)
    for titulo, columnas, unidad, franjas in [
        ("Temperaturas", ["temp_sala", "temp_nucleo", "temp_sup"], "°C", bandas),
        ("Humedad", ["hum_sala"], "%", bandas_hum),
        ("Peso de la tira testigo", ["peso_tira_g"], "g", None),
    ]:
        img = _grafico(lindo, [NOMBRES[c] for c in columnas], unidad, franjas)
        if img is not None:
            partes.append(_junto(Paragraph(titulo, s["seccion"]), img))

    if merma is not None and inicial:
        copia = df.copy()
        copia["Merma (%)"] = (float(inicial) - copia["peso_tira_g"]) \
            / float(inicial) * 100
        img = _grafico(copia, ["Merma (%)"], "%")
        if img is not None:
            partes.append(_junto(
                Paragraph("Merma de la tira", s["seccion"]), img))

    # ---- Mediciones a mano ------------------------------------------
    if mediciones:
        partes.append(PageBreak())
        partes.append(Paragraph("Mediciones cargadas a mano", s["seccion"]))
        filas = [["Fecha", "pH", "aw", "Observaciones"]]
        for m in mediciones:
            cuando = pd.to_datetime(m["medido_en"], utc=True).tz_convert(ZONA)
            filas.append([
                cuando.strftime("%d/%m/%Y %H:%M"),
                f"{float(m['ph']):.2f}" if m.get("ph") is not None else "—",
                f"{float(m['aw']):.3f}" if m.get("aw") is not None else "—",
                Paragraph(m.get("notas") or "—", s["cuerpo"]),
            ])
        partes.append(_tabla(
            filas, [34 * mm, 16 * mm, 18 * mm, ANCHO_UTIL - 68 * mm]))

    # ---- Alertas ----------------------------------------------------
    partes.append(Paragraph("Alertas que saltaron", s["seccion"]))
    if not alertas:
        partes.append(Paragraph(
            "Ninguna. El lote pasó entero sin disparar un solo aviso.",
            s["cuerpo"]))
    else:
        filas = [["Tipo", "Empezó", "Duró", "Detalle"]]
        for a in alertas:
            desde = pd.to_datetime(a["inicio"], utc=True).tz_convert(ZONA)
            hasta = (pd.to_datetime(a["cerrada_en"], utc=True).tz_convert(ZONA)
                     if a.get("cerrada_en") else None)
            duro = (f"{(hasta - desde).total_seconds() / 3600:.1f} h"
                    if hasta else "quedó abierta")
            filas.append([
                a["tipo"], desde.strftime("%d/%m %H:%M"), duro,
                Paragraph(a.get("detalle") or "—", s["cuerpo"]),
            ])
        partes.append(_tabla(
            filas, [24 * mm, 24 * mm, 22 * mm, ANCHO_UTIL - 70 * mm]))

    return _armar(partes)


NOMBRES = {
    "temp_sala": "Temp sala",
    "temp_nucleo": "Temp núcleo",
    "temp_sup": "Temp superficie",
    "hum_sala": "Humedad",
    "peso_tira_g": "Peso tira (g)",
}


def _pie(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor(estilo.TEXTO_TENUE))
    canvas.drawString(16 * mm, 12 * mm, "Secadero Nostro")
    canvas.drawRightString(A4[0] - 16 * mm, 12 * mm, f"Página {doc.page}")
    canvas.setStrokeColor(colors.HexColor(estilo.BORDE))
    canvas.setLineWidth(0.5)
    canvas.line(16 * mm, 16 * mm, A4[0] - 16 * mm, 16 * mm)
    canvas.restoreState()


def _armar(partes):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=16 * mm, bottomMargin=22 * mm,
        title="Informe de lote — Secadero Nostro", author="Secadero Nostro",
    )
    doc.build(partes, onFirstPage=_pie, onLaterPages=_pie)
    return buf.getvalue()
