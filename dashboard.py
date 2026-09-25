import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client

st.set_page_config(page_title="Secadero IoT", layout="wide")

SUPABASE_URL = "https://esdlelzxxcqavbwfqbti.supabase.co"
SUPABASE_KEY = "TU_API_KEY_PUBLISHABLE_LARGUISIMA"  # Pegá tu clave acá

@st.cache_resource
def iniciar_conexion():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = iniciar_conexion()

@st.cache_data(ttl=60)
def cargar_datos():
    respuesta = supabase.table("secado").select("*").order("fecha_hora", desc=False).execute()
    if respuesta.data:
        df = pd.DataFrame(respuesta.data)
        df['fecha_hora'] = pd.to_datetime(df['fecha_hora'])
        return df
    return pd.DataFrame()

df_telemetria = cargar_datos()

# ==========================================
# BARRA LATERAL: FASES, LOTES Y CONTROLES
# ==========================================
with st.sidebar:
    st.header("⚙️ Configuración de Fase")
    fase_actual = st.selectbox("Etapa del Proceso", [
        "1. Estufa / Fermentación", 
        "2. Secado / Maduración", 
        "3. Estabilización"
    ])
    
    st.subheader("Rangos Objetivo")
    colA, colB = st.columns(2)
    with colA:
        # Valores por defecto dinámicos según la fase elegida
        t_min = st.number_input("Temp Min (°C)", value=20.0 if "Estufa" in fase_actual else 12.0)
        h_min = st.number_input("Hum Min (%)", value=85.0 if "Estufa" in fase_actual else 70.0)
    with colB:
        t_max = st.number_input("Temp Max (°C)", value=25.0 if "Estufa" in fase_actual else 16.0)
        h_max = st.number_input("Hum Max (%)", value=95.0 if "Estufa" in fase_actual else 80.0)
        
    st.markdown("---")
    st.header("📝 Gestión de Lote y pH")
    
    # Simulación de cambio de lote desde UI (Requiere tabla en BD para ser persistente)
    lote_input = st.text_input("Nombre del Lote Activo", value=df_telemetria['lote'].iloc[-1] if not df_telemetria.empty else "Lote-001")
    peso_ref = st.number_input("Peso Inicial (Kg)", value=10.0)

    with st.form("form_bromatologia"):
        st.write("Registrar Control Manual")
        ph_val = st.number_input("Valor de pH", min_value=3.0, max_value=8.0, value=5.5, step=0.1)
        notas = st.text_input("Observaciones (Ej: Cambio coloración)")
        submit_manual = st.form_submit_button("Guardar Registro")
        
        if submit_manual:
            nuevo_registro = {
                "lote": lote_input,
                "peso_inicial": peso_ref,
                "ph": ph_val,
                "notas": notas
            }
            supabase.table("secado").insert(nuevo_registro).execute()
            st.success("✅ Guardado en Supabase")
            st.cache_data.clear()

# ==========================================
# INTERFAZ DEL PANEL CENTRAL
# ==========================================
st.title("🥩 Panel de Control Industrial - Secadero")
st.caption(f"Fase Activa: **{fase_actual}** | Evaluando contra T: {t_min}-{t_max}°C y H: {h_min}-{h_max}%")

if df_telemetria.empty:
    st.warning("⏳ Esperando los primeros datos desde el ESP32...")
else:
    ultimo = df_telemetria.iloc[-1]
    
    # Prevención de división por cero en la merma
    if peso_ref > 0:
        merma_actual = ((peso_ref - ultimo['peso_actual']) / peso_ref) * 100
    else:
        merma_actual = 0.0

    # 1. KPIs Generales
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🌡️ Temp. Sala", f"{ultimo['temp_sala']:.1f} °C")
    c2.metric("💧 Humedad", f"{ultimo['hum_sala']:.1f} %")
    c3.metric("🎯 Núcleo", f"{ultimo['temp_int']:.1f} °C")
    c4.metric("🔦 Superficie (IR)", f"{ultimo['temp_sup']:.1f} °C")
    c5.metric("⚖️ Peso Actual", f"{ultimo['peso_actual']:.2f} Kg", f"-{merma_actual:.1f}% Merma", delta_color="inverse")

    st.markdown("---")
    
    # 2. Semáforos Prescriptivos Detallados (Vinculados a los rangos de la barra lateral)
    st.subheader("🚦 Semáforos Prescriptivos Bromatológicos")
    s1, s2 = st.columns(2)
    
    with s1:
        st.markdown("#### 1. Temperatura")
        if ultimo['temp_sala'] > t_max:
            st.error(f"**Riesgo:** Fusión de grasas y proliferación de bacterias perjudiciales. La temperatura supera el límite de {t_max}°C para esta fase.\n\n**Acción:** Bajar termostato inmediatamente.")
        elif ultimo['temp_sala'] < t_min:
            st.warning(f"**Riesgo:** Ralentización de la maduración o inactivación del cultivo iniciador. Temperatura por debajo de {t_min}°C.\n\n**Acción:** Subir temperatura.")
        else:
            st.success("✅ Temperatura en rango óptimo para la fase actual.")

    with s2:
        st.markdown("#### 2. Humedad")
        if ultimo['hum_sala'] < h_min:
            st.error(f"**Riesgo:** Encostramiento severo en superficie (anillo seco). Bloqueará la salida de humedad interna.\n\n**Acción:** Detener forzadores y encender humidificador para superar el {h_min}%.")
        elif ultimo['hum_sala'] > h_max:
            st.warning(f"**Riesgo:** Proliferación de hongos indeseables y bloqueo de la merma. Supera el {h_max}%.\n\n**Acción:** Encender extractores / renovación de aire.")
        else:
            st.success("✅ Humedad en rango óptimo para la fase actual.")

    s3, s4 = st.columns(2)
    
    with s3:
        st.markdown("#### 3. Merma de Peso")
        if merma_actual > 35.0:
            st.error("**Riesgo:** Sobre-secado. Chacinado excesivamente duro.\n\n**Acción:** Finalizar ciclo o subir humedad general.")
        elif merma_actual < 5.0 and "Secado" in fase_actual:
            st.info("**Fase Inicial:** Priorizar la caída del pH en estufa antes que la pérdida acelerada de agua.")
        else:
            st.success(f"✅ Evolución de merma correcta (Actual: {merma_actual:.1f}%).")

    with s4:
        st.markdown("#### 4. Psicrometría (Condensación)")
        punto_rocio = ultimo['temp_sala'] - ((100 - ultimo['hum_sala']) / 5)
        if ultimo['temp_sup'] <= punto_rocio:
            st.error(f"**Riesgo Crítico:** Transpiración en tripa detectada. (Superficie: {ultimo['temp_sup']:.1f}°C <= Rocío: {punto_rocio:.1f}°C)\n\n**Acción Urgente:** Bajar humedad un 10% y encender ventiladores.")
        else:
            st.success(f"✅ Superficie segura sin condensación. (Superficie: {ultimo['temp_sup']:.1f}°C > Rocío: {punto_rocio:.1f}°C)")

    st.markdown("---")

    # 3. Gráficos
    st.subheader("📈 Análisis de Evolución")
    df_graficos = df_telemetria.dropna(subset=['temp_sala'])

    tab1, tab2, tab3, tab4 = st.tabs(["Temperaturas", "Humedad", "Merma de Peso", "Evolución de pH"])
    with tab1:
        st.plotly_chart(px.line(df_graficos, x='fecha_hora', y=['temp_sala', 'temp_int', 'temp_sup']), use_container_width=True)
    with tab2:
        st.plotly_chart(px.line(df_graficos, x='fecha_hora', y='hum_sala', color_discrete_sequence=['#00a8ff']), use_container_width=True)
    with tab3:
        st.plotly_chart(px.line(df_graficos, x='fecha_hora', y='peso_actual', color_discrete_sequence=['#e84118']), use_container_width=True)
    with tab4:
        df_ph = df_telemetria.dropna(subset=['ph'])
        if not df_ph.empty:
            st.plotly_chart(px.line(df_ph, x='fecha_hora', y='ph', markers=True, color_discrete_sequence=['#9c88ff']), use_container_width=True)
        else:
            st.info("Aún no hay registros manuales de pH para graficar.")
