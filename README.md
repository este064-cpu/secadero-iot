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

Está en la carpeta `firmware/` de al lado, fuera de este repositorio:

| Carpeta | Qué es |
|---|---|
| `firmware/CONEXIONES.md` | El mapa de patas. Es **el** mapa: si hay que rehacer la caja, se cablea así. |
| `firmware/secadero/` | El firmware. |
| `firmware/detectar_sensores/` | Un sketch de diagnóstico que dice qué hay conectado y por qué no contesta. |

`firmware/secadero/credenciales.h` tiene el token del equipo y **no va a
ningún repositorio**. Hay un `credenciales.h.ejemplo` al lado para
rearmarlo.

Librerías que hay que tener instaladas (Arduino IDE → Librerías):
Adafruit BME280, Adafruit MLX90614, DallasTemperature y OneWire.

> **Para grabar el ESP32 hay que desconectar los sensores.** Con algo
> colgado de las patas la grabación falla con un mensaje sobre el flash
> chip que despista bastante. Se graba con la placa pelada y después se
> vuelve a conectar todo.

#### Calibrar la balanza

Sin calibrar, el equipo manda `null` en el peso en vez de inventar un
número. Por el monitor serie a 115200 acepta tres órdenes:

| Orden | Qué hace |
|---|---|
| `t` | Tara. Con el gancho vacío, sin la tira. |
| `c500` | Calibra con 500 g colgando (o los gramos que sean). |
| `?` | Dice cómo está: wifi, hora, sensores, peso actual, cola. |

Los dos números quedan guardados en el ESP32 y sobreviven a los cortes de
luz, así que esto se hace una sola vez en la instalación.

**Al empezar un lote, el peso inicial de la tira se lee del panel**, no de
otra balanza. Así cualquier error sistemático se cancela: la merma sale de
dos pesadas hechas con el mismo instrumento.

#### Cada cuánto mide

Cada 5 minutos. Son unas 8.600 lecturas por mes, que entran cómodas en el
plan gratis de Supabase; cada minuto serían 43.000. Para un proceso que
dura semanas, cinco minutos es resolución de sobra.

Si no hay wifi guarda las lecturas y las manda cuando vuelve. La cola
aguanta 20 horas y **sobrevive a un reinicio del equipo**, porque vive en
la memoria RTC. No sobrevive a un corte de luz, y está bien así: si se
corta la luz el equipo tampoco está midiendo, no hay nada que guardar.

A la media hora sin wifi se reinicia solo, que destraba la mayoría de los
cuelgues del módulo. No pierde nada al hacerlo.

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

**El ESP32 no valida el certificado de Supabase.** Fue a propósito. Lo que
autentica al equipo es su token; fijar un certificado significa que el día
que Supabase lo cambie el equipo deja de mandar **en silencio**, adentro de
una cámara, sin que nadie se entere hasta que falte un dato. El riesgo que
se acepta a cambio es que alguien metido en la red del local podría ver el
token y mandar lecturas falsas.

**Supabase corta en 1000 filas y no avisa.** El panel pide de a tandas y
usa la vista `lecturas_por_hora` para las ventanas largas. Un lote de 30
días midiendo cada minuto son 43.000 filas.
