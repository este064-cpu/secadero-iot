# Secadero IoT — Nostro

Panel de telemetría del secadero. Un ESP32 adentro de la cámara mide y
manda; esta app muestra y avisa.

## Cómo está armado

```
ESP32  ──►  Supabase (base de datos)  ──►  dashboard.py   (el panel que mirás)
                      │
                      └──────────────────►  alertas.py    (mira cada 5 min y manda mail)
```

`alertas.py` corre en GitHub Actions, **no** en el ESP32 ni en una PC de
casa: si lo que falla es el equipo o se corta la luz en la planta, el
aviso tiene que poder salir igual.

## Puesta en marcha

### 1. La base

En el editor SQL de Supabase, pegar y correr `sql/esquema.sql`
entero. **Ojo: borra las tablas viejas** (`lotes`, `secado`, `galeria`).

> La carpeta se llama `sql/` y no `supabase/` a propósito: una carpeta
> llamada igual que la librería la tapa al importarla y el panel no
> arranca.

Después, dar de alta el equipo con un token inventado largo:

```sql
insert into dispositivos (nombre, token_hash)
values ('ESP32 Sala 1', encode(digest('UN-TOKEN-LARGO-INVENTADO', 'sha256'), 'hex'));
```

Ese token va en el firmware. En la base queda hasheado: si algún día se
filtra, se cambia este renglón y listo.

### 2. Los usuarios

En Supabase → Authentication → Users, crear un usuario para Esteban y
otro para Rafael. Sin eso no se entra al panel, y sin entrar no se lee
ni se escribe nada.

### 3. El panel

Las claves van en `.streamlit/secrets.toml` (copiar de
`secrets.toml.ejemplo`). En Streamlit Cloud: Settings → Secrets.

Para correrlo local:

```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

### 4. Los mails

En GitHub → Settings → Secrets and variables → Actions, cargar:

| Secret | Qué es |
|---|---|
| `SUPABASE_URL` | `https://esdlelzxxcqavbwfqbti.supabase.co` |
| `SUPABASE_SERVICE_KEY` | la clave `service_role` de Supabase |
| `MAIL_USUARIO` | la casilla de Gmail que manda |
| `MAIL_CLAVE` | una **contraseña de aplicación** de Gmail, no la del mail |

La contraseña de aplicación se saca en la cuenta de Google → Seguridad →
Verificación en dos pasos → Contraseñas de aplicaciones.

A quién le llega cada mail se configura **desde el panel**, en la barra
lateral, no acá.

Para probar sin esperar: GitHub → Actions → "Vigilar el secadero" → Run
workflow.

> GitHub desactiva solo los workflows programados si el repo pasa 60 días
> sin un commit. Si dejamos de tocarlo mucho tiempo, hay que volver a
> activarlo desde la pestaña Actions.

### 5. El firmware

El sketch del ESP32 todavía no está en ningún repositorio. Va en la
carpeta `firmware/` de al lado.

El equipo manda cada lectura con un POST a:

```
POST https://esdlelzxxcqavbwfqbti.supabase.co/rest/v1/rpc/registrar_lectura
apikey: <clave anon>
Content-Type: application/json

{
  "p_token": "UN-TOKEN-LARGO-INVENTADO",
  "p_medido_en": "2026-11-03T14:30:00Z",
  "p_temp_sala": 14.2,
  "p_hum_sala": 78.5,
  "p_temp_nucleo": 13.8,
  "p_temp_sup": 13.9,
  "p_peso_tira_g": 712.4
}
```

Todos los valores son opcionales: un sensor que falla manda `null`, no un
cero. Un cero se dibuja en el gráfico y dispara alarmas falsas.

`p_medido_en` también es opcional; si no va, la base pone la hora de
llegada. El equipo puede guardar lo que midió mientras no había wifi y
mandarlo después: el mismo instante no se duplica.

## Decisiones que conviene no olvidar

**Hay dos pesos y no son lo mismo.** La celda pesa **una tira testigo** y
de ahí sale la merma real, medida. Los kilos embutidos del lote no se
vuelven a pesar nunca: sirven para *estimar* cuánto producto queda
aplicándole esa merma. El panel los muestra separados a propósito.

**El panel nunca muestra un dato viejo como si fuera de ahora.** Arriba
de todo dice hace cuánto llegó la última lectura, y se pone en rojo
cuando pasa el tiempo configurado.

**Cuando falta un dato dice "sin dato".** No inventa un cero ni dispara
una alarma. Un sensor mudo no es lo mismo que una temperatura mala.

**Supabase corta en 1000 filas y no avisa.** El panel pide de a tandas y
usa la vista `lecturas_por_hora` para las ventanas largas. Un lote de 30
días midiendo cada minuto son 43.000 filas.
