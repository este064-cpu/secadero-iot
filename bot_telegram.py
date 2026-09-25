import telebot
from supabase import create_client
import datetime

# ==========================================
# CONFIGURACIÓN Y CREDENCIALES
# ==========================================
TELEGRAM_TOKEN = "8696470121:AAHJEke-zNHGpBR-DSMdPXYUZzWQlAoLohI"
SUPABASE_URL = "https://esdlelzxxcqavbwfqbti.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVzZGxlbHp4eGNxYXZid2ZxYnRpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAzNDUyMTEsImV4cCI6MjEwNTkyMTIxMX0.RWKWFl344RC8_aayTUF32-6JMaCw3YeMwfszpfx4I5Q"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

def obtener_lote_activo():
    res = supabase.table("lotes").select("nombre").eq("estado", "Activo").execute()
    if res.data:
        return res.data[0]['nombre']
    return "Sin-Lote-Activo"

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    lote = obtener_lote_activo()
    bot.reply_to(message, f"🥩 **Bot de Monitoreo de Secadero**\n\nEnvía una foto de los chacinados para asociarla automáticamente al **{lote}**.")

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    try:
        lote_actual = obtener_lote_activo()
        
        # Obtener el archivo de imagen enviado
        file_id = message.photo[-1].file_id
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_info.file_path}"

        # Insertar registro en la tabla galeria de Supabase
        nuevo_registro = {
            "lote": lote_actual,
            "ruta_foto": file_url
        }
        
        supabase.table("galeria").insert(nuevo_registro).execute()
        
        bot.reply_to(message, f"📸 **¡Foto guardada exitosamente!**\n\nQuedó registrada en el historial del **{lote_actual}**.")
    
    except Exception as e:
        bot.reply_to(message, f"❌ Error al guardar la foto: {str(e)}")

print("🤖 Bot de Telegram escuchando mensajes...")
bot.infinity_polling()
