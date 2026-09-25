import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client

# ==========================================
# CONFIGURACIÓN Y CONEXIÓN
# ==========================================
st.set_page_config(page_title="Secadero IoT", layout="wide")

SUPABASE_URL = "https://esdlelzxxcqavbwfqbti.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzZGxlbHp4eGNxYXZid2ZxYnRpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAzNDUyMTEsImV4cCI6MjEwNTkyMTIxMX0.RWKWFl344RC8_aayTUF32-6JMaCw3YeMwfszpfx4I5Q"  # Pegá tu clave acá

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

# ==========================================
# INTERFAZ DEL PANEL
# ==========================================
st.title("🥩 Panel de Control Industrial - Secadero")

df_telemetria = cargar_datos()

if df_telemetria.empty:
    st.warning("⏳ Esperando los primeros datos desde el ESP32 a través de Supabase...")
else:
    # Obtener el último registro para los semáforos
    ultimo = df_telemetria.iloc[-1]
    merma_actual = ((ultimo['peso_inicial'] - ultimo['peso_actual']) / ultimo['peso_inicial']) * 100

   # 1. KPIs Generales (Ahora con 5 columnas)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🌡️ Temp. Sala", f"{ultimo['temp_sala']:.1f} °C")
    c2.metric("💧 Humedad", f"{ultimo['hum_sala']:.1f} %")
    c3.metric("🎯 Núcleo", f"{ultimo['temp_int']:.1f} °C")
    c4.metric("🔦 Superficie (IR)", f"{ultimo['temp_sup']:.1f} °C")
    
    # Peso actual como métrica principal, merma como indicador secundario (delta)
    c5.metric("⚖️ Peso Actual", f"{ultimo['peso_actual']:.2f} Kg", f"-{merma_actual:.1f}% Merma", delta_color="inverse")

    st.markdown("---")
    st.subheader("🚦 Semáforos Prescriptivos Bromatológicos")
    s1, s2 = st.columns(2)

    # SEMÁFORO 1: TEMPERATURA
    with s1:
        st.markdown("#### 1. Temperatura")
        if ultimo['temp_sala'] > 18.0:
            st.error("**Riesgo:** Fusión de grasas y acidez descontrolada.\n\n**Acción:** Bajar termostato.")
        elif ultimo['temp_sala'] < 12.0:
            st.warning("**Riesgo:** Inactivación del cultivo iniciador.\n\n**Acción:** Subir temperatura a 15°C.")
        else:
            st.success("✅ Temperatura en rango óptimo.")

    # SEMÁFORO 2: HUMEDAD
    with s2:
        st.markdown("#### 2. Humedad")
        if ultimo['hum_sala'] < 70.0:
            st.error("**Riesgo:** Encostramiento severo en superficie.\n\n**Acción:** Detener forzadores y encender humidificador.")
        elif ultimo['hum_sala'] > 85.0:
            st.warning("**Riesgo:** Bloqueo de merma y proliferación de hongos indeseables.\n\n**Acción:** Encender extractores.")
        else:
            st.success("✅ Humedad en rango óptimo.")

    s3, s4 = st.columns(2)

    # SEMÁFORO 3: MERMA Y PH
    with s3:
        st.markdown("#### 3. Merma de Peso")
        if merma_actual > 35.0:
            st.error("**Riesgo:** Sobre-secado.\n\n**Acción:** Finalizar ciclo o subir humedad general.")
        elif merma_actual < 5.0:
            st.info("**Fase Inicial:** Priorizar la caída del pH en estufa antes que la pérdida de agua.")
        else:
            st.success("✅ Evolución de merma correcta.")

    # SEMÁFORO 4: PSICROMETRÍA (PUNTO DE ROCÍO)
    with s4:
        st.markdown("#### 4. Psicrometría (Condensación)")
        # Cálculo matemático aproximado del punto de rocío
        punto_rocio = ultimo['temp_sala'] - ((100 - ultimo['hum_sala']) / 5)
        
        if ultimo['temp_sup'] <= punto_rocio:
            st.error(f"**Riesgo Crítico:** Transpiración en tripa detectada. (Superficie: {ultimo['temp_sup']:.1f}°C <= Rocío: {punto_rocio:.1f}°C)\n\n**Acción Urgente:** Bajar humedad 10% y encender ventiladores.")
        else:
            st.success(f"✅ Superficie segura sin condensación. (Superficie: {ultimo['temp_sup']:.1f}°C > Rocío: {punto_rocio:.1f}°C)")

    st.markdown("---")
    st.subheader("📈 Gráfica de Evolución")
    
    # Gráfico interactivo con Plotly
    fig = px.line(df_telemetria, x='fecha_hora', y=['temp_sala', 'hum_sala', 'temp_int', 'temp_sup'], 
                  labels={'value': 'Valores', 'fecha_hora': 'Tiempo', 'variable': 'Sensores'},
                  title="Historial de Variables del Lote")
    st.plotly_chart(fig, use_container_width=True)
