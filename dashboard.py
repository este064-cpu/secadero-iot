import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

# ==========================================
# CONFIGURACIÓN GENERAL Y AUTO-REFRESH
# ==========================================
st.set_page_config(page_title="Secadero IoT", layout="wide")

# Recarga automática cada 60 segundos (60000 ms)
st_autorefresh(interval=60000, key="recarga_automatica")

SUPABASE_URL = "https://esdlelzxxcqavbwfqbti.supabase.co"
SUPABASE_KEY = "TU_API_KEY_PUBLISHABLE_LARGUISIMA"  # Pegá tu clave pública acá

@st.cache_resource
def iniciar_conexion():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = iniciar_conexion()

# ==========================================
# EXTRACCIÓN DE DATOS DE SUPABASE
# ==========================================
def cargar_lotes():
    res = supabase.table("lotes").select("*").order("fecha_inicio", desc=True).execute()
    return pd.DataFrame(res.data) if res.data else pd.DataFrame()

def cargar_telemetria():
    res = supabase.table("secado").select("*").order("fecha_hora", desc=False).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        return df
    return pd.DataFrame()

df_lotes = cargar_lotes()
df_telemetria = cargar_telemetria()

# ==========================================
# BARRA LATERAL: CONTROLES, LOTES Y FASES
# ==========================================
with st.sidebar:
    st.header("📦 Gestión de Lotes")
    
    with st.expander("➕ Iniciar Nuevo Lote"):
        with st.form("form_nuevo_lote"):
            nuevo_nombre = st.text_input("Nombre del Lote (Ej: Lote-Salame-01)")
            nuevo_peso = st.number_input("Peso Inicial Total (Kg)", min_value=0.1, value=10.0, step=0.1)
            if st.form_submit_button("Crear Lote"):
                supabase.table("lotes").update({"estado": "Finalizado"}).neq("estado", "Finalizado").execute()
                supabase.table("lotes").insert({"nombre": nuevo_nombre, "peso_inicial": nuevo_peso, "estado": "Activo"}).execute()
                st.success("¡Lote creado exitosamente!")
                st.cache_data.clear()
                st.rerun()

    # Identificación del lote activo
    if not df_lotes.empty:
        lotes_activos = df_lotes[df_lotes['estado'] == 'Activo']
        if not lotes_activos.empty:
            lote_actual = lotes_activos.iloc[0]
            st.info(f"🟢 **Lote Activo:** {lote_actual['nombre']}\n\n**Peso Base:** {lote_actual['peso_inicial']} Kg")
        else:
            st.warning("No hay lotes en estado Activo.")
            lote_actual = None
    else:
        st.warning("No hay registros en la tabla de lotes.")
        lote_actual = None

    st.markdown("---")
    st.header("📝 Carga Manual (pH)")
    with st.form("form_bromatologia"):
        fecha_ph = st.date_input("Fecha de medición", value=datetime.today())
        hora_ph = st.time_input("Hora de medición", value=datetime.now().time())
        ph_val = st.number_input("Valor de pH", min_value=3.0, max_value=8.0, value=5.4, step=0.05)
        notas = st.text_input("Observaciones organolépticas")
        
        if st.form_submit_button("Guardar pH"):
            if lote_actual is not None:
                fecha_hora_combinada = datetime.combine(fecha_ph, hora_ph).isoformat()
                nuevo_registro = {
                    "lote": lote_actual['nombre'],
                    "peso_inicial": lote_actual['peso_inicial'],
                    "ph": ph_val,
                    "notas": notas,
                    "fecha_hora": fecha_hora_combinada
                }
                supabase.table("secado").insert(nuevo_registro).execute()
                st.success("✅ Medición guardada")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Debe existir un lote activo para registrar datos.")

    st.markdown("---")
    st.header("⚙️ Configuración de Fase")
    fase_actual = st.selectbox("Etapa Activa", ["1. Estufa / Fermentación", "2. Secado / Maduración", "3. Estabilización"])
    
    # Rangos dinámicos precargados según etapa
    t_min_def = 20.0 if "Estufa" in fase_actual else 12.0
    t_max_def = 24.0 if "Estufa" in fase_actual else 16.0
    h_min_def = 85.0 if "Estufa" in fase_actual else 72.0
    h_max_def = 95.0 if "Estufa" in fase_actual else 82.0

    col_t1, col_t2 = st.columns(2)
    with col_t1:
        t_min = st.number_input("Temp Min (°C)", value=t_min_def, step=0.5)
        h_min = st.number_input("Hum Min (%)", value=h_min_def, step=1.0)
    with col_t2:
        t_max = st.number_input("Temp Max (°C)", value=t_max_def, step=0.5)
        h_max = st.number_input("Hum Max (%)", value=h_max_def, step=1.0)

# ==========================================
# PANEL CENTRAL
# ==========================================
st.title("🥩 Panel de Control Industrial - Secadero")

if df_telemetria.empty or lote_actual is None:
    st.warning("⏳ Esperando telemetría del ESP32 o creación de un lote activo...")
else:
    # Filtro estricto por fecha de inicio del lote activo
    df_lote_activo = df_telemetria[df_telemetria['fecha_hora'] >= lote_actual['fecha_inicio']]
    
    if not df_lote_activo.empty:
        ultimo = df_lote_activo.iloc[-1]
        peso_ref = lote_actual['peso_inicial']
        merma_actual = ((peso_ref - ultimo['peso_actual']) / peso_ref) * 100 if peso_ref > 0 else 0.0

        st.caption(f"Lote: **{lote_actual['nombre']}** | Fase: **{fase_actual}** | Rango T: {t_min}-{t_max}°C | Rango H: {h_min}-{h_max}%")

        # 1. Indicadores Principales (KPIs)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🌡️ Temp. Sala", f"{ultimo['temp_sala']:.1f} °C")
        c2.metric("💧 Humedad", f"{ultimo['hum_sala']:.1f} %")
        c3.metric("🎯 Temp. Núcleo", f"{ultimo['temp_int']:.1f} °C")
        c4.metric("🔦 Superficie (IR)", f"{ultimo['temp_sup']:.1f} °C")
        c5.metric("⚖️ Peso Actual", f"{ultimo['peso_actual']:.2f} Kg", f"-{merma_actual:.1f}% Merma", delta_color="inverse")

        st.markdown("---")

        # 2. Semáforos Prescriptivos Bromatológicos
        st.subheader("🚦 Diagnóstico Prescriptivo y Alertas")
        s1, s2 = st.columns(2)

        with s1:
            st.markdown("#### 1. Control de Temperatura")
            if ultimo['temp_sala'] > t_max:
                st.error(f"**Riesgo:** Fusión de grasa superficial y acidez descontrolada (Supera {t_max}°C).\n\n**Acción:** Bajar consigna del termostato.")
            elif ultimo['temp_sala'] < t_min:
                st.warning(f"**Riesgo:** Freno en la maduración o inhibición del fermento (Inferior a {t_min}°C).\n\n**Acción:** Incrementar calefacción a consigna óptima.")
            else:
                st.success(f"✅ Temperatura estabilizada dentro de rango ({t_min}°C - {t_max}°C).")

        with s2:
            st.markdown("#### 2. Control de Humedad")
            if ultimo['hum_sala'] < h_min:
                st.error(f"**Riesgo:** Encostramiento severo en tripa (anillo de secado). Bloquea la salida de humedad.\n\n**Acción:** Apagar forzadores y elevar humedad por encima de {h_min}%.")
            elif ultimo['hum_sala'] > h_max:
                st.warning(f"**Riesgo:** Estancamiento de merma y desarrollo de flora fúngica no deseada (Supera {h_max}%).\n\n**Acción:** Activar renovación de aire o deshumidificación.")
            else:
                st.success(f"✅ Humedad relativa en equilibrio ({h_min}% - {h_max}%).")

        s3, s4 = st.columns(2)

        with s3:
            st.markdown("#### 3. Cinética de Merma")
            if merma_actual >= 35.0:
                st.error(f"**Riesgo:** Sobre-secado crítico ({merma_actual:.1f}%). Endurecimiento excesivo de textura.\n\n**Acción:** Concluir proceso o pasar a cámara de estabilización.")
            elif merma_actual < 5.0 and "Secado" in fase_actual:
                st.info(f"**Etapa Temprana:** Merma en {merma_actual:.1f}%. Controlar acidez y caída de pH antes de acelerar desecación.")
            else:
                st.success(f"✅ Ritmo de pérdida de peso dentro de parámetros ({merma_actual:.1f}%).")

        with s4:
            st.markdown("#### 4. Psicrometría y Condensación")
            punto_rocio = ultimo['temp_sala'] - ((100 - ultimo['hum_sala']) / 5)
            if ultimo['temp_sup'] <= punto_rocio:
                st.error(f"**Riesgo Crítico:** Condensación / Transpiración de tripa (Superficie: {ultimo['temp_sup']:.1f}°C <= Rocío: {punto_rocio:.1f}°C).\n\n**Acción Urgente:** Bajar humedad un 10% y activar ventilación para secar película superficial.")
            else:
                st.success(f"✅ Sin riesgo de condensación (Superficie: {ultimo['temp_sup']:.1f}°C > Rocío: {punto_rocio:.1f}°C).")

        st.markdown("---")

        # 3. Gráficos Individuales e Históricos
        st.subheader("📈 Monitoreo Detallado")
        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
            "Temperaturas", "Humedad", "Merma de Peso", "Evolución de pH", "🗄️ Historial de Lotes", "📸 Inspección Visual"
        ])

        # Renombrado de variables para visualización limpia
        df_graficos = df_lote_activo.dropna(subset=['temp_sala']).copy()
        df_graficos = df_graficos.rename(columns={
            'fecha_hora': 'Fecha y hora',
            'temp_sala': 'Temp sala',
            'temp_int': 'Temp núcleo',
            'temp_sup': 'Temp superficie',
            'hum_sala': 'Humedad',
            'peso_actual': 'Peso actual'
        })

        with tab1:
            st.plotly_chart(px.line(df_graficos, x='Fecha y hora', y=['Temp sala', 'Temp núcleo', 'Temp superficie'],
                                    labels={'value': 'Temperatura (°C)', 'variable': 'Sensor'},
                                    title="Evolución Térmica Tri-Punto"), use_container_width=True)

        with tab2:
            st.plotly_chart(px.line(df_graficos, x='Fecha y hora', y='Humedad',
                                    color_discrete_sequence=['#00a8ff'],
                                    labels={'Humedad': 'Humedad (%)'},
                                    title="Humedad Relativa de Cámara"), use_container_width=True)

        with tab3:
            st.plotly_chart(px.line(df_graficos, x='Fecha y hora', y='Peso actual',
                                    color_discrete_sequence=['#e84118'],
                                    labels={'Peso actual': 'Peso (Kg)'},
                                    title="Curva de Pérdida de Masa"), use_container_width=True)

        with tab4:
            df_ph = df_lote_activo.dropna(subset=['ph']).copy()
            if not df_ph.empty:
                df_ph = df_ph.sort_values(by='fecha_hora')
                df_ph = df_ph.rename(columns={'fecha_hora': 'Fecha y hora', 'ph': 'pH'})
                st.plotly_chart(px.line(df_ph, x='Fecha y hora', y='pH', markers=True,
                                        color_discrete_sequence=['#9c88ff'],
                                        title="Curva de Acidificación Bromatológica"), use_container_width=True)
            else:
                st.info("No se han registrado mediciones manuales de pH para este lote.")

        with tab5:
            st.subheader("Registro Histórico de Lotes")
            df_lotes_mostrar = df_lotes.copy()
            if 'id' in df_lotes_mostrar.columns:
                df_lotes_mostrar = df_lotes_mostrar.drop(columns=['id'])
            df_lotes_mostrar['fecha_inicio'] = pd.to_datetime(df_lotes_mostrar['fecha_inicio']).dt.strftime('%Y-%m-%d %H:%M')
            df_lotes_mostrar = df_lotes_mostrar.rename(columns={
                'nombre': 'Nombre',
                'peso_inicial': 'Peso inicial (Kg)',
                'fecha_inicio': 'Fecha inicio',
                'estado': 'Estado'
            })
            st.dataframe(df_lotes_mostrar, use_container_width=True, hide_index=True)

        with tab6:
            st.subheader(f"Galería Fotográfica: {lote_actual['nombre']}")
            res_fotos = supabase.table("galeria").select("*").eq("lote", lote_actual['nombre']).order("fecha_hora", desc=True).execute()
            if res_fotos.data:
                cols = st.columns(3)
                for idx, foto in enumerate(res_fotos.data):
                    with cols[idx % 3]:
                        st.image(foto['ruta_foto'], caption=f"Captura: {foto['fecha_hora'][:16].replace('T', ' ')}")
            else:
                st.info("No hay fotografías enviadas por Telegram para el lote activo.")
    else:
        st.info("Lote activo configurado. Aguardando los primeros paquetes de datos del microcontrolador...")
