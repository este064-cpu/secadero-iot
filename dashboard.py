import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client
from datetime import datetime
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Secadero IoT", layout="wide")

# ==========================================
# AUTO-ACTUALIZACIÓN
# ==========================================
# Recarga la página sola cada 60 segundos (60000 milisegundos)
st_autorefresh(interval=60000, key="recarga_automatica")

SUPABASE_URL = "https://esdlelzxxcqavbwfqbti.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzZGxlbHp4eGNxYXZid2ZxYnRpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAzNDUyMTEsImV4cCI6MjEwNTkyMTIxMX0.RWKWFl344RC8_aayTUF32-6JMaCw3YeMwfszpfx4I5Q"  # ¡Pegá tu clave acá!

@st.cache_resource
def iniciar_conexion():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

supabase = iniciar_conexion()

# ==========================================
# FUNCIONES DE BASE DE DATOS
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
# BARRA LATERAL: GESTIÓN Y CONTROLES
# ==========================================
with st.sidebar:
    st.header("📦 Gestión de Lotes")
    
    with st.expander("➕ Iniciar Nuevo Lote"):
        with st.form("form_nuevo_lote"):
            nuevo_nombre = st.text_input("Nombre del Lote (Ej: Tanda-Abril-01)")
            nuevo_peso = st.number_input("Peso Inicial Total (Kg)", min_value=0.1, value=10.0)
            if st.form_submit_button("Crear Lote"):
                supabase.table("lotes").update({"estado": "Finalizado"}).neq("estado", "Finalizado").execute()
                supabase.table("lotes").insert({"nombre": nuevo_nombre, "peso_inicial": nuevo_peso, "estado": "Activo"}).execute()
                st.success("Lote creado!")
                st.cache_data.clear()
                st.rerun()

    if not df_lotes.empty:
        lotes_activos = df_lotes[df_lotes['estado'] == 'Activo']
        if not lotes_activos.empty:
            lote_actual = lotes_activos.iloc[0]
            st.info(f"🟢 **Lote Activo:** {lote_actual['nombre']}\n\n**Peso Base:** {lote_actual['peso_inicial']} Kg")
        else:
            st.warning("No hay ningún lote activo. Creá uno nuevo.")
            lote_actual = None
    else:
        st.warning("No hay lotes registrados.")
        lote_actual = None

    st.markdown("---")
    st.header("📝 Carga Manual (pH)")
    
    with st.form("form_bromatologia"):
        st.write("Registrar medición de pH")
        fecha_ph = st.date_input("Fecha de medición", value=datetime.today())
        hora_ph = st.time_input("Hora de medición", value=datetime.now().time())
        ph_val = st.number_input("Valor de pH", min_value=3.0, max_value=8.0, value=5.5, step=0.1)
        notas = st.text_input("Observaciones")
        
        if st.form_submit_button("Guardar Registro"):
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
                st.success("✅ Guardado correctamente")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error("Creá un lote activo primero.")

    st.markdown("---")
    st.header("⚙️ Ajustes de Fase")
    fase_actual = st.selectbox("Etapa del Proceso", ["1. Estufa", "2. Secado", "3. Estabilización"])
    t_min = st.number_input("Temp Min (°C)", value=20.0 if "Estufa" in fase_actual else 12.0)
    t_max = st.number_input("Temp Max (°C)", value=25.0 if "Estufa" in fase_actual else 16.0)
    h_min = st.number_input("Hum Min (%)", value=85.0 if "Estufa" in fase_actual else 70.0)
    h_max = st.number_input("Hum Max (%)", value=95.0 if "Estufa" in fase_actual else 80.0)

# ==========================================
# INTERFAZ DEL PANEL CENTRAL
# ==========================================
st.title("🥩 Panel de Control Industrial - Secadero")

if df_telemetria.empty or lote_actual is None:
    st.warning("⏳ Esperando telemetría o creación de Lote...")
else:
    df_lote_activo = df_telemetria[df_telemetria['fecha_hora'] >= lote_actual['fecha_inicio']]
    
    if not df_lote_activo.empty:
        ultimo = df_lote_activo.iloc[-1]
        peso_ref = lote_actual['peso_inicial']
        merma_actual = ((peso_ref - ultimo['peso_actual']) / peso_ref) * 100 if peso_ref > 0 else 0

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("🌡️ Temp. Sala", f"{ultimo['temp_sala']:.1f} °C")
        c2.metric("💧 Humedad", f"{ultimo['hum_sala']:.1f} %")
        c3.metric("🎯 Núcleo", f"{ultimo['temp_int']:.1f} °C")
        c4.metric("🔦 Superficie (IR)", f"{ultimo['temp_sup']:.1f} °C")
        c5.metric("⚖️ Peso Actual", f"{ultimo['peso_actual']:.2f} Kg", f"-{merma_actual:.1f}% Merma", delta_color="inverse")

        st.markdown("---")
        
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "Temperaturas", "Humedad", "Merma de Peso", "Evolución de pH", "🗄️ Historial de Lotes"
        ])
        
        # Preparamos los datos para gráficos (limpiando nombres)
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
                                    labels={'value': 'Temperatura (°C)', 'variable': 'Sensor'}), use_container_width=True)
        with tab2:
            st.plotly_chart(px.line(df_graficos, x='Fecha y hora', y='Humedad', color_discrete_sequence=['#00a8ff']), use_container_width=True)
        with tab3:
            st.plotly_chart(px.line(df_graficos, x='Fecha y hora', y='Peso actual', color_discrete_sequence=['#e84118']), use_container_width=True)
        with tab4:
            df_ph = df_lote_activo.dropna(subset=['ph']).copy()
            if not df_ph.empty:
                df_ph = df_ph.sort_values(by='fecha_hora')
                df_ph = df_ph.rename(columns={'fecha_hora': 'Fecha y hora', 'ph': 'pH'})
                st.plotly_chart(px.line(df_ph, x='Fecha y hora', y='pH', markers=True, color_discrete_sequence=['#9c88ff']), use_container_width=True)
            else:
                st.info("Aún no hay registros de pH para este lote.")
        with tab5:
            st.subheader("Historial de Producción")
            # Preparamos la tabla de lotes para que se vea prolija
            df_lotes_mostrar = df_lotes.copy()
            # Ocultamos la columna ID que no suma visualmente
            df_lotes_mostrar = df_lotes_mostrar.drop(columns=['id'])
            # Formateamos la fecha (Año-Mes-Día Hora:Minuto)
            df_lotes_mostrar['fecha_inicio'] = pd.to_datetime(df_lotes_mostrar['fecha_inicio']).dt.strftime('%Y-%m-%d %H:%M')
            # Renombramos las columnas
            df_lotes_mostrar = df_lotes_mostrar.rename(columns={
                'nombre': 'Nombre',
                'peso_inicial': 'Peso inicial (Kg)',
                'fecha_inicio': 'Fecha inicio',
                'estado': 'Estado'
            })
            # Mostramos la tabla (hide_index saca el número de fila de la izquierda)
            st.dataframe(df_lotes_mostrar, use_container_width=True, hide_index=True)
    else:
         st.info("Lote creado correctamente. Esperando los primeros datos del ESP32...")
