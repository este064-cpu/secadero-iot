import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client

st.set_page_config(page_title="Secadero IoT", layout="wide")

SUPABASE_URL = "https://esdlelzxxcqavbwfqbti.supabase.co"
SUPABASE_KEY = "TU_API_KEY_PUBLISHABLE_LARGUISIMA"  # Recordá pegar tu clave acá

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
# BARRA LATERAL: CARGA MANUAL
# ==========================================
with st.sidebar:
    st.header("📝 Controles Manuales")
    
    if not df_telemetria.empty:
        lote_activo = df_telemetria['lote'].iloc[-1]
        peso_ref = df_telemetria['peso_inicial'].iloc[-1]
    else:
        lote_activo = "Lote-001"
        peso_ref = 10.0

    st.subheader(f"Lote Activo: {lote_activo}")
    st.info("Para iniciar un lote nuevo, actualizá el nombre y peso inicial en el código del ESP32.")

    with st.form("form_bromatologia"):
        st.write("Registrar Control de pH y Notas")
        ph_val = st.number_input("Valor de pH", min_value=3.0, max_value=8.0, value=5.5, step=0.1)
        notas = st.text_input("Observaciones (Ej: Cambio coloración, hongos)")
        submit_manual = st.form_submit_button("Guardar Registro")
        
        if submit_manual:
            nuevo_registro = {
                "lote": lote_activo,
                "peso_inicial": peso_ref,
                "ph": ph_val,
                "notas": notas
            }
            supabase.table("secado").insert(nuevo_registro).execute()
            st.success("✅ Guardado en Supabase")
            st.cache_data.clear()  # Fuerza a recargar los datos

# ==========================================
# INTERFAZ DEL PANEL CENTRAL
# ==========================================
st.title("🥩 Panel de Control Industrial - Secadero")

if df_telemetria.empty:
    st.warning("⏳ Esperando los primeros datos desde el ESP32...")
else:
    ultimo = df_telemetria.iloc[-1]
    merma_actual = ((ultimo['peso_inicial'] - ultimo['peso_actual']) / ultimo['peso_inicial']) * 100

    # 1. KPIs Generales
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("🌡️ Temp. Sala", f"{ultimo['temp_sala']:.1f} °C")
    c2.metric("💧 Humedad", f"{ultimo['hum_sala']:.1f} %")
    c3.metric("🎯 Núcleo", f"{ultimo['temp_int']:.1f} °C")
    c4.metric("🔦 Superficie (IR)", f"{ultimo['temp_sup']:.1f} °C")
    c5.metric("⚖️ Peso Actual", f"{ultimo['peso_actual']:.2f} Kg", f"-{merma_actual:.1f}% Merma", delta_color="inverse")

    st.markdown("---")
    
    # 2. Semáforos (Mantenemos la lógica de prevención bromatológica)
    st.subheader("🚦 Semáforos Prescriptivos Bromatológicos")
    s1, s2, s3 = st.columns(3)
    
    with s1:
        if ultimo['temp_sala'] > 18.0:
            st.error("**Temperatura:** Alta. Bajar termostato.")
        elif ultimo['temp_sala'] < 12.0:
            st.warning("**Temperatura:** Baja. Subir a 15°C.")
        else:
            st.success("**Temperatura:** Óptima.")
            
    with s2:
        if ultimo['hum_sala'] < 70.0:
            st.error("**Humedad:** Encostramiento. Subir humedad.")
        elif ultimo['hum_sala'] > 85.0:
            st.warning("**Humedad:** Riesgo de hongos. Ventilar.")
        else:
            st.success("**Humedad:** Óptima.")
            
    with s3:
        punto_rocio = ultimo['temp_sala'] - ((100 - ultimo['hum_sala']) / 5)
        if ultimo['temp_sup'] <= punto_rocio:
            st.error(f"**Condensación:** Tripa transpirando. Bajar humedad.")
        else:
            st.success(f"**Superficie:** Segura.")

    st.markdown("---")

    # 3. Gráficos Individuales Detallados
    st.subheader("📈 Análisis de Evolución del Lote")
    
    # Filtramos valores nulos para no romper los gráficos con las inserciones manuales
    df_graficos = df_telemetria.dropna(subset=['temp_sala'])

    tab1, tab2, tab3, tab4 = st.tabs(["Temperaturas", "Humedad", "Merma de Peso", "Evolución de pH"])
    
    with tab1:
        fig_temp = px.line(df_graficos, x='fecha_hora', y=['temp_sala', 'temp_int', 'temp_sup'], 
                           title="Comparativa Térmica (Sala vs Núcleo vs Superficie)")
        st.plotly_chart(fig_temp, use_container_width=True)
        
    with tab2:
        fig_hum = px.line(df_graficos, x='fecha_hora', y='hum_sala', 
                          title="Humedad Relativa de la Sala", color_discrete_sequence=['#00a8ff'])
        st.plotly_chart(fig_hum, use_container_width=True)
        
    with tab3:
        fig_peso = px.line(df_graficos, x='fecha_hora', y='peso_actual', 
                           title="Caída de Peso del Chacinado", color_discrete_sequence=['#e84118'])
        st.plotly_chart(fig_peso, use_container_width=True)
        
    with tab4:
        df_ph = df_telemetria.dropna(subset=['ph'])
        if not df_ph.empty:
            fig_ph = px.line(df_ph, x='fecha_hora', y='ph', markers=True, 
                             title="Curva de Acidificación (Descenso de pH)", color_discrete_sequence=['#9c88ff'])
            st.plotly_chart(fig_ph, use_container_width=True)
        else:
            st.info("Aún no hay registros manuales de pH para graficar.")
