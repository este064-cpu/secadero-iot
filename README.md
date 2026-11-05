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

Si la base **ya estaba andando**, no se vuelve a correr `esquema.sql`: hay
que aplicar las migraciones que falten, en orden, que no borran nada.

| Archivo | Qué hace |
|---|---|
| `sql/002-etapas-en-horas.sql` | Pasa las etapas de días fijos a duraciones. Convierte solo las que ya existan. |
| `sql/003-peso-inicial-automatico.sql` | Agrega el peso de control de la otra balanza y los tiempos de la toma automática. |

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

**El peso inicial de la tira lo toma el sistema solo**, leyendo la celda
dos horas después de arrancar el lote. Nadie lo carga a mano.

Es el número del que sale **toda** la merma del lote, y si alguien se
olvida de cargarlo —o ese día no hay nadie en la planta— el lote queda sin
merma y no se arregla después: la tira ya empezó a secarse. Por eso no
puede depender de que alguien se acuerde.

Lo toma **`alertas.py`, no el panel**. El panel solo corre cuando alguien
lo tiene abierto, que es justo lo que no se puede garantizar; `alertas.py`
corre en GitHub Actions cada 5 minutos pase lo que pase.

**Por qué dos horas y no al instante.** La celda se acomoda sola bajo una
carga nueva: sube varios gramos los primeros minutos y después baja. Un
peso tomado recién colgada le mete ese error a la merma de todo el lote.
Dos horas alcanzan para que se asiente y son pocas para que la tira haya
perdido algo que importe. Se cambia desde el panel, en **Avisos por mail**.

**Y se controla contra otra balanza.** Antes de colgar la tira se la pesa
aparte y ese número se carga al crear el lote. Cuando el sistema toma el
suyo, compara: si difieren más del 5 %, sale un mail. Una balanza sola no
se puede controlar a sí misma — si la celda quedó mal tarada, el número
que da parece perfectamente razonable y la merma del lote entero sale
corrida sin que nadie lo note.

Si la celda no manda **ningún** peso en esas dos horas, también sale un
mail. Un silencio ahí es un lote sin merma.

El orden de trabajo queda así:

1. Tarar con el gancho vacío (`t` por el monitor serie).
2. Pesar la tira en otra balanza y anotar ese número.
3. Crear el lote en el panel con ese peso en **Peso de la tira en la otra
   balanza**.
4. Colgar la tira. Listo, no hay nada más que hacer.

#### Cada cuánto mide

Cada 5 minutos. Son unas 8.600 lecturas por mes, que entran cómodas en el
plan gratis de Supabase; cada minuto serían 43.000. Para un proceso que
dura semanas, cinco minutos es resolución de sobra.

Si no hay wifi guarda las lecturas y las manda cuando vuelve. La cola
aguanta 20 horas y **sobrevive a un reinicio del equipo**, porque vive en
la memoria RTC. No sobrevive a un corte de luz, y está bien así: si se
corta la luz el equipo tampoco está midiendo, no hay nada que guardar.

**Una lectura que la base rechaza para siempre se tira y la cola sigue.**
Un `400` (dato mal armado) o un `409` (ya está guardada) no mejoran por
reintentarlos: la lectura mala se quedaba adelante de todas y tapaba las
buenas hasta 20 horas, sin que nadie se enterara. Todo lo demás sí se
reintenta, incluso un `401`: si el token está mal no entra ninguna
lectura, y lo correcto ahí es que salga el mail de «el equipo no manda
datos», no tirar la cola en silencio. Cuántas se tiraron se ve en `?`,
en **rechazadas de entrada**: si ese número no es cero, el problema es lo
que se está midiendo, no la red.

**La balanza en negativo manda `null`, no un número negativo.** Un peso
negativo no es un peso: es la tara corrida o que no hay nada colgando. La
base lo rechaza (`peso_tira_g >= 0`) y ese rechazo era justamente el que
trababa la cola. El monitor serie avisa y recuerda tarar con `t`.

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

**El aviso de condensación sale medio grado antes.** Si se esperara a que
la superficie toque el punto de rocío, el mail llegaría cuando la tripa ya
está mojada y la película ya se formó. Con 0,5 °C de margen todavía se
llega a bajar la humedad.

Ese medio grado, la fórmula del punto de rocío y el resto de los umbrales
viven en **`cuentas.py`**, que importan el panel, los mails y el PDF. Antes
estaban copiados en dos archivos y el día que uno cambiara, la pantalla y
el mail iban a decir cosas distintas del mismo momento. El único que sigue
aparte, y no hay forma de evitarlo, es el firmware: está en otro lenguaje y
en otra máquina, así que `MARGEN_ROCIO_AVISO` de `secadero.ino` tiene que
seguir a mano el mismo número que `MARGEN_ROCIO` de `cuentas.py`.

**Las etapas tienen duración, no día de calendario.** La primera arranca
cuando arranca el lote y cada una empieza donde terminó la anterior. Es
así porque en la cámara las cosas no pasan cuando dice el almanaque: el
estufado se programa en 48 h, pero si el pH baja a las 31 se saca igual.

Con duraciones, cortar una etapa **corre a todas las que siguen** y no hay
que tocar ningún otro número. Con días fijos (del día 0 al 2, del 3 al 21)
había que reescribir el lote entero a mano cada vez que eso pasaba, que es
siempre.

El botón **«Terminar y pasar a…»** de la barra lateral guarda en
`horas_reales` lo que la etapa duró de verdad. Mientras ese campo esté en
null, la etapa dura lo previsto. No hay ningún proceso que avance las
etapas de fondo: el plan se calcula cada vez a partir de las duraciones,
así que el panel y los mails no pueden quedar desfasados entre sí.

**Las etapas se agregan y se borran desde la misma tabla.** Tiene filas
dinámicas, y al guardar el `orden` se renumera por la posición: el lugar
en la lista **es** el orden. No hay forma de arrastrar filas en una tabla
editable de Streamlit, así que una fila nueva va al final; para meter una
etapa en el medio se agrega abajo y se corren los nombres, que para una
rampa de días es lo mismo. El botón **«Agregar días al final»** hace el
caso común de un tirón, copiando los rangos de la última etapa.

**Un lote nuevo se crea con el estufado y una etapa por día.** Después del
estufado la cámara baja de a escalones diarios, así que la receta por
defecto interpola entre 18 °C / 88 % el primer día de secado y 12 °C /
72 % el último, con una banda de ±1 °C y ±3 %. Son un punto de partida:
cada fila se edita desde la barra lateral.

**El panel se ve como la app de Flujo de Fondos, a propósito.** La paleta y
las formas salen de su `Diseño y estilo.md`: fondo blanco, tarjetas con
borde fino y esquinas redondeadas, verde `#2e6f1f` de marca, nada de tema
oscuro. Todo eso está en `estilo.py`.

Las tarjetas y los avisos son **HTML propio**, no componentes de Streamlit
pintados con CSS. Streamlit renombra sus clases internas en cada versión:
un `st.success` teñido por fuera se rompe solo con cualquier actualización,
y encima sin avisar. Lo que escribimos nosotros no.

**El PDF usa reportlab y matplotlib, no los gráficos de la pantalla.**
Plotly exporta a imagen solo con kaleido, que necesita un navegador
headless: una pieza más que se puede romper sin aviso en Streamlit Cloud.
Matplotlib dibuja un PNG y listo. Los colores son los mismos, así que la
línea de temperatura del informe es del mismo color que la del panel.

**En el informe, cada lectura se juzga contra el rango que regía en ese
momento.** 22 °C son perfectos en la estufa y un desastre en secado, así
que las horas fuera de rango se cuentan etapa por etapa y nunca contra un
rango único. Los bordes salen del plan de verdad, con las etapas cortadas
a mano ya corridas, y en la tabla van marcadas con un asterisco. Las horas
sin lectura no suman: mientras el equipo estuvo callado no sabemos qué
pasó ahí adentro, y contarlas como "en rango" sería inventarlo.

**El informe muestra la merma de dos maneras y las dos hacen falta.** La
acumulada dice cuánto perdió en total; la de por día dice a qué velocidad.
Una merma que se frenó se ve igual de linda en la curva acumulada, y una
caída muy alta y muy pareja al principio es justamente la que encostra la
tripa. Eso solo se ve en las barras diarias.

**El panel muestra lo que el equipo mide ahora, haya lote o no.** Los
sensores y la celda no saben de lotes: sirven igual para calibrar la
balanza o para mirar la cámara vacía. Antes todo colgaba de la primera
lectura del lote, así que sin lote abierto —o con un lote recién creado—
la pantalla quedaba vacía y parecía que el equipo estaba muerto.

**Los mails, en cambio, sí dependen del lote.** Sin lote abierto
`alertas.py` no revisa nada, y está bien: los rangos de temperatura y
humedad viven en las etapas del lote, así que sin lote no hay contra qué
comparar. El panel lo dice en pantalla para que no se confunda con una
falla.

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
