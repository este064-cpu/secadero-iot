"""
Estilo visual del panel — Nostro Chacinados.

La paleta y las formas salen de la app de Flujo de Fondos, para que las
dos aplicaciones de la casa se vean como una sola cosa. La guia es
"Diseño y estilo.md" de ese proyecto; los valores concretos estan
copiados de su dashboard de referencia.

Las tarjetas y los avisos son HTML propio y no componentes de Streamlit
teñidos con CSS. Streamlit renombra sus clases internas en cada version,
asi que pintarle los st.success y los st.metric encima se rompe solo con
cualquier actualizacion. Esto no: el HTML lo escribimos nosotros.
"""

import html

import streamlit as st

# ---------------------------------------------------------------------
#  Paleta
# ---------------------------------------------------------------------
VERDE_MARCA = "#2e6f1f"   # titulos y botones principales
VERDE       = "#2e7d32"   # todo bien / positivo
ROJO        = "#c62828"   # riesgo / negativo
AMBAR       = "#b45309"   # al borde

TEXTO       = "#1f2937"
TEXTO_SUAVE = "#6b7280"
TEXTO_TENUE = "#9ca3af"
TITULO_CARD = "#374151"

FONDO         = "#ffffff"
BORDE         = "#e5e7eb"
TARJETA       = "#f7faf6"
BORDE_TARJETA = "#e3eddf"

# Los fondos de los avisos son los mismos tonos suaves del flujo de
# fondos: rojo clarito para lo urgente y nada de colores saturados.
TONOS = {
    "ok":   ("#f6faf5", "#d9e9d4", "#1e5c22"),
    "ojo":  ("#fffbeb", "#fde68a", "#92400e"),
    "mal":  ("#fef2f2", "#fecaca", "#991b1b"),
    "info": ("#f8fafc", "#e2e8f0", "#475569"),
}

# Para los graficos: mismos colores, mismo orden siempre, asi la "temp
# sala" es del mismo color en todas las pantallas y en el PDF.
COLORES_SERIES = {
    "Temp sala":       "#2e6f1f",
    "Temp núcleo":     "#b45309",
    "Temp superficie": "#1d4ed8",
    "Humedad":         "#0e7490",
    "Peso tira (g)":   "#6d28d9",
    "Merma (%)":       "#2e7d32",
}

TIPOGRAFIA = '-apple-system, system-ui, "Segoe UI", Roboto, sans-serif'


def aplicar():
    """Mete el CSS. Se llama una sola vez, apenas arranca la app."""
    st.markdown(
        f"""
        <style>
          :root {{ color-scheme: light; }}

          .stApp {{
            background: {FONDO};
            color: {TEXTO};
            font-family: {TIPOGRAFIA};
          }}

          /* Menos aire arriba: la pantalla entra sin scrollear de entrada. */
          .block-container {{ padding-top: 2.2rem; max-width: 1200px; }}

          /* Los !important no son por capricho: Streamlit trae sus propios
             estilos de encabezado con mas especificidad que esto, y sin
             eso los titulos salen en gris en vez del verde de la casa. */
          .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5 {{
            font-family: {TIPOGRAFIA} !important;
            color: {VERDE_MARCA} !important;
          }}
          .stApp h1 {{ font-size: 26px !important; font-weight: 700 !important; }}
          .stApp h2 {{ font-size: 17px !important; font-weight: 600 !important;
                       margin-top: 6px !important; }}
          .stApp h3 {{ font-size: 15px !important; }}
          .stApp h4, .stApp h5 {{
            font-size: 12.5px !important; font-weight: 600 !important;
            color: {TEXTO_SUAVE} !important;
            text-transform: uppercase; letter-spacing: .04em;
            margin-bottom: 2px !important;
          }}

          /* ---------- KPIs ---------- */
          .kpis {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 4px 0 18px;
          }}
          .kpi {{
            background: {TARJETA};
            border: 1px solid {BORDE_TARJETA};
            border-radius: 10px;
            padding: 12px 14px;
          }}
          .kpi .lbl {{
            font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
            color: {TEXTO_SUAVE};
          }}
          .kpi .val {{
            font-size: 22px; font-weight: 700; margin-top: 4px; color: {TEXTO};
            line-height: 1.2;
          }}
          .kpi .val.pos {{ color: {VERDE}; }}
          .kpi .val.neg {{ color: {ROJO}; }}
          .kpi .val.sin {{ color: {TEXTO_TENUE}; font-weight: 500; font-size: 18px; }}
          .kpi .pie {{ font-size: 11px; color: {TEXTO_TENUE}; margin-top: 2px; }}

          /* ---------- Avisos ---------- */
          .aviso {{
            border-radius: 10px; padding: 11px 13px; margin-bottom: 10px;
            font-size: 13.5px; line-height: 1.45;
          }}
          .aviso .tit {{ font-weight: 700; display: block; margin-bottom: 2px; }}
          .aviso .acc {{ display: block; margin-top: 5px; }}

          /* ---------- Cinta de estado ---------- */
          .cinta {{
            display: flex; align-items: center; gap: 8px;
            font-size: 13px; padding: 8px 12px; border-radius: 10px;
            margin-bottom: 10px; border: 1px solid {BORDE};
            background: #fcfdfc; color: {TEXTO_SUAVE};
          }}
          .cinta b {{ color: {TEXTO}; font-weight: 600; }}
          .punto {{
            width: 8px; height: 8px; border-radius: 50%; flex: 0 0 8px;
          }}

          /* ---------- Botones ---------- */
          .stButton > button, .stDownloadButton > button,
          .stFormSubmitButton > button {{
            border: 1px solid #cdd7c8; background: #fff; color: {TITULO_CARD};
            border-radius: 8px; font-size: 13px; font-weight: 500;
            transition: none;
          }}
          .stButton > button:hover, .stDownloadButton > button:hover,
          .stFormSubmitButton > button:hover {{
            border-color: {VERDE_MARCA}; color: {VERDE_MARCA};
            background: {TARJETA};
          }}
          .stButton > button[kind="primary"],
          .stFormSubmitButton > button[kind="primary"] {{
            background: {VERDE_MARCA}; border-color: {VERDE_MARCA}; color: #fff;
          }}
          .stButton > button[kind="primary"]:hover,
          .stFormSubmitButton > button[kind="primary"]:hover {{
            background: {VERDE}; border-color: {VERDE}; color: #fff;
          }}

          /* ---------- Varios ---------- */
          [data-testid="stSidebar"] {{
            background: #fbfcfb; border-right: 1px solid {BORDE};
          }}
          [data-testid="stSidebar"] h2 {{ font-size: 15px !important; }}
          .stTabs [data-baseweb="tab"] {{ font-size: 13.5px; }}
          hr {{ margin: 14px 0 !important; border-color: {BORDE} !important; }}
          [data-testid="stCaptionContainer"] p {{ color: {TEXTO_SUAVE}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------
#  Piezas
# ---------------------------------------------------------------------
def _limpio(texto):
    """Escapa lo que venga de la base. Un lote llamado <b>x</b> no rompe
    la pagina ni se dibuja en negrita."""
    return html.escape(str(texto))


def kpis(items):
    """Fila de numeros grandes.

    Cada item es (etiqueta, valor, tono, pie). El tono es "" normal,
    "pos" verde, "neg" rojo o "sin" para cuando no hay dato. El pie es
    una linea chica abajo, opcional.
    """
    celdas = []
    for etiqueta, valor, tono, pie in items:
        pie_html = f'<div class="pie">{_limpio(pie)}</div>' if pie else ""
        celdas.append(
            f'<div class="kpi">'
            f'<div class="lbl">{_limpio(etiqueta)}</div>'
            f'<div class="val {tono}">{_limpio(valor)}</div>'
            f"{pie_html}</div>"
        )
    st.markdown(f'<div class="kpis">{"".join(celdas)}</div>',
                unsafe_allow_html=True)


def aviso(tono, titulo, texto, accion=None):
    """Un recuadro de color con que pasa y, si corresponde, que hacer.

    El "que hacer" va aparte y en renglon propio a proposito: de noche,
    con el telefono en la mano, lo unico que importa es esa linea.
    """
    fondo, borde, color = TONOS.get(tono, TONOS["info"])
    partes = [f'<span class="tit">{_limpio(titulo)}</span>{_limpio(texto)}']
    if accion:
        partes.append(f'<span class="acc"><b>Qué hacer:</b> {_limpio(accion)}</span>')
    st.markdown(
        f'<div class="aviso" style="background:{fondo};border:1px solid {borde};'
        f'color:{color}">{"".join(partes)}</div>',
        unsafe_allow_html=True,
    )


def cinta(color, texto_html):
    """La linea de arriba de todo: un punto de color y una frase."""
    st.markdown(
        f'<div class="cinta"><span class="punto" style="background:{color}">'
        f"</span><span>{texto_html}</span></div>",
        unsafe_allow_html=True,
    )


def grafico(fig):
    """Deja todos los graficos iguales: fondo blanco, sin grilla pesada."""
    fig.update_layout(
        font=dict(family=TIPOGRAFIA, size=12, color=TEXTO),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=30, b=10),
        height=320,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="left", x=0, title_text=""),
    )
    fig.update_xaxes(showgrid=False, linecolor=BORDE, ticks="outside",
                     tickcolor=BORDE)
    fig.update_yaxes(gridcolor="#f1f3f1", zeroline=False, linecolor=BORDE)
    st.plotly_chart(fig, use_container_width=True)
