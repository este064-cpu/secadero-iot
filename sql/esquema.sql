-- =====================================================================
--  Secadero IoT — Nostro Chacinados
--  Esquema de la base. Se corre UNA vez en el editor SQL de Supabase.
--
--  Proyecto: esdlelzxxcqavbwfqbti  (OJO: es un proyecto DISTINTO del que
--  usan Flujo de Fondos, Produccion y Secadero Nostro.)
--
--  Este archivo BORRA Y REHACE las tablas viejas (lotes, secado, galeria).
--  Se decidio arrancar limpio: los datos del 25/09 eran de prueba.
-- =====================================================================

drop table if exists galeria        cascade;  -- se va con el bot de Telegram
drop table if exists secado         cascade;  -- se parte en lecturas + mediciones
drop table if exists alertas        cascade;
drop table if exists mediciones     cascade;
drop table if exists lecturas       cascade;
drop table if exists etapas         cascade;
drop table if exists dispositivos   cascade;
drop table if exists config         cascade;
drop table if exists lotes          cascade;

create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------
--  1. lotes — cada tanda que entra al secadero
--
--  Hay DOS pesos y no son lo mismo:
--
--    tira_peso_inicial_g  es la tira testigo colgada de la celda de carga.
--                         De aca sale la merma REAL, medida.
--    kg_embutidos         es lo que entro al secadero en total.
--                         Nunca se pesa de nuevo: sirve para estimar
--                         cuanto producto queda aplicandole la merma de
--                         la tira. Es una cuenta aproximada, no un dato.
-- ---------------------------------------------------------------------
create table lotes (
  id                  bigint generated always as identity primary key,
  nombre              text not null unique,
  fecha_inicio        timestamptz not null default now(),
  fecha_fin           timestamptz,
  estado              text not null default 'Activo'
                        check (estado in ('Activo', 'Finalizado')),

  -- La tira testigo que cuelga de la celda. En gramos, porque la celda
  -- mide gramos y pasarlo a kilos solo esconde decimales.
  tira_peso_inicial_g numeric(8, 1) check (tira_peso_inicial_g > 0),

  -- Lo que se embutio en total, para la estimacion de producto restante.
  kg_embutidos        numeric(10, 2) check (kg_embutidos > 0),

  nota                text,
  creado_en           timestamptz not null default now(),

  check (fecha_fin is null or fecha_fin >= fecha_inicio)
);

-- Un solo lote activo a la vez. Lo garantiza la base, no la app: antes
-- esto se hacia con un update "a todos los demas" que podia fallar a medias.
create unique index lotes_uno_activo on lotes (estado) where estado = 'Activo';
create index lotes_inicio_idx on lotes (fecha_inicio desc);

-- ---------------------------------------------------------------------
--  2. etapas — los rangos esperados, en orden, de un lote.
--
--  Cada etapa tiene una DURACION, no un dia fijo de calendario. La
--  primera arranca cuando arranca el lote y cada una empieza donde
--  termino la anterior.
--
--  Es asi porque en la camara las etapas no pasan cuando dice el
--  almanaque: el estufado se programa en 48 horas, pero si el pH baja a
--  las 31 se saca igual. Con duraciones, cortar una etapa corre a todas
--  las siguientes sin tocar ningun otro numero; con dias fijos habia que
--  reescribir el lote entero a mano.
--
--  "horas_reales" queda en null mientras la etapa dure lo previsto, y se
--  llena cuando se la corta a mano desde el panel.
--
--  "tolerancia_min" es lo que pidio Esteban: cuantos minutos seguidos
--  tiene que estar fuera de rango antes de que salga el mail. Una puerta
--  abierta dos minutos no es una alarma; media hora si.
-- ---------------------------------------------------------------------
create table etapas (
  id             bigint generated always as identity primary key,
  lote_id        bigint not null references lotes (id) on delete cascade,
  orden          smallint not null,
  nombre         text not null,

  horas          integer not null default 24 check (horas > 0),
  horas_reales   numeric(8, 2) check (horas_reales is null or horas_reales > 0),

  temp_min       numeric(4, 1),
  temp_max       numeric(4, 1),
  hum_min        numeric(4, 1),
  hum_max        numeric(4, 1),

  tolerancia_min smallint not null default 30 check (tolerancia_min >= 0),

  unique (lote_id, orden),
  check (temp_min is null or temp_max is null or temp_min <= temp_max),
  check (hum_min  is null or hum_max  is null or hum_min  <= hum_max)
);

-- ---------------------------------------------------------------------
--  3. lecturas — lo que manda el ESP32. Una fila por medicion.
--
--  Dos relojes a proposito:
--    medido_en   lo pone el ESP32 (hora del sensor).
--    recibido_en lo pone la base cuando entra el dato.
--  Si el ESP32 pierde la hora despues de un corte de luz, "recibido_en"
--  sigue siendo confiable y se nota la diferencia de una.
--
--  Todo lo medido es opcional: un sensor roto manda null, no un cero.
--  Un cero se dibuja en el grafico y dispara alarmas falsas; null no.
-- ---------------------------------------------------------------------
create table lecturas (
  id          bigint generated always as identity primary key,
  lote_id     bigint references lotes (id) on delete set null,
  medido_en   timestamptz not null,
  recibido_en timestamptz not null default now(),

  temp_sala   numeric(4, 1) check (temp_sala   between -20 and 80),
  hum_sala    numeric(4, 1) check (hum_sala    between 0 and 100),
  temp_nucleo numeric(4, 1) check (temp_nucleo between -20 and 80),
  temp_sup    numeric(4, 1) check (temp_sup    between -20 and 80),
  peso_tira_g numeric(8, 1) check (peso_tira_g >= 0),

  -- Si el ESP32 reenvia lo que guardo durante un corte de wifi, el mismo
  -- instante no se duplica.
  unique (lote_id, medido_en)
);

create index lecturas_lote_idx on lecturas (lote_id, medido_en desc);
create index lecturas_recibido_idx on lecturas (recibido_en desc);

-- ---------------------------------------------------------------------
--  4. mediciones — lo que se carga a mano (pH, aw, observaciones).
--
--  Va aparte de "lecturas" a proposito. Antes el pH entraba como una fila
--  de telemetria con todos los sensores en null, y despues habia que
--  filtrarla en cada grafico.
-- ---------------------------------------------------------------------
create table mediciones (
  id         bigint generated always as identity primary key,
  lote_id    bigint not null references lotes (id) on delete cascade,
  medido_en  timestamptz not null,
  ph         numeric(3, 2) check (ph between 3 and 9),
  aw         numeric(4, 3) check (aw between 0.3 and 1),
  notas      text check (char_length(notas) <= 500),
  creado_por uuid references auth.users (id),
  creado_en  timestamptz not null default now()
);

create index mediciones_lote_idx on mediciones (lote_id, medido_en desc);

-- ---------------------------------------------------------------------
--  5. dispositivos — el ESP32 (o los que vengan).
--
--  El equipo NO escribe con la clave de la base: manda su propio token,
--  que se guarda hasheado. Si algun dia se filtra, se cambia este token
--  solo y no hay que tocar nada mas.
-- ---------------------------------------------------------------------
create table dispositivos (
  id             smallint generated always as identity primary key,
  nombre         text not null unique,
  token_hash     text not null,
  activo         boolean not null default true,
  ultima_lectura timestamptz,
  creado_en      timestamptz not null default now()
);

-- ---------------------------------------------------------------------
--  6. config — una sola fila con lo que no depende del lote.
-- ---------------------------------------------------------------------
create table config (
  id                   boolean primary key default true check (id),

  -- A quienes les llega el mail.
  destinatarios        text[] not null default '{}',

  -- Cuantos minutos sin recibir nada para avisar que el equipo esta mudo.
  minutos_sin_lecturas smallint not null default 60
                         check (minutos_sin_lecturas > 0),

  -- Riesgo de condensacion: mas corto, porque moja la tripa rapido.
  tolerancia_rocio_min smallint not null default 15
                         check (tolerancia_rocio_min >= 0),

  -- Cada cuanto se repite el mail mientras el problema siga abierto,
  -- para no recibir 300 mails iguales en una noche.
  reenvio_min          smallint not null default 120
                         check (reenvio_min > 0)
);

insert into config (id) values (true);

-- ---------------------------------------------------------------------
--  7. alertas — el registro de lo que se aviso.
--
--  Existe para no repetir: mientras una alerta sigue "abierta" no se
--  manda otra hasta que pasen los minutos de reenvio. Ademas queda el
--  historial de que paso y cuanto duro.
-- ---------------------------------------------------------------------
create table alertas (
  id           bigint generated always as identity primary key,
  lote_id      bigint references lotes (id) on delete set null,
  tipo         text not null
                 check (tipo in ('temperatura', 'humedad', 'rocio', 'sin_datos')),
  detalle      text not null,
  abierta      boolean not null default true,
  inicio       timestamptz not null default now(),
  ultimo_aviso timestamptz,
  cerrada_en   timestamptz
);

-- Una sola alerta abierta por tipo y por lote.
create unique index alertas_abierta_idx on alertas (lote_id, tipo) where abierta;
create index alertas_inicio_idx on alertas (inicio desc);

-- ---------------------------------------------------------------------
--  8. La puerta del ESP32.
--
--  El equipo hace UN post a /rest/v1/rpc/registrar_lectura con su token.
--  La funcion valida el token, busca sola el lote activo y guarda. No
--  necesita saber nada mas, ni manejar sesiones, ni refrescar nada.
-- ---------------------------------------------------------------------
create or replace function registrar_lectura(
  p_token       text,
  p_medido_en   timestamptz default null,
  p_temp_sala   numeric default null,
  p_hum_sala    numeric default null,
  p_temp_nucleo numeric default null,
  p_temp_sup    numeric default null,
  p_peso_tira_g numeric default null
) returns bigint
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_dispositivo smallint;
  v_lote        bigint;
  v_id          bigint;
begin
  select id into v_dispositivo
    from dispositivos
   where activo
     and token_hash = encode(digest(p_token, 'sha256'), 'hex');

  if v_dispositivo is null then
    raise exception 'Token invalido';
  end if;

  select id into v_lote from lotes where estado = 'Activo';

  -- Sin hora del equipo se usa la de la base. Es mejor que perder el dato.
  insert into lecturas (
    lote_id, medido_en, temp_sala, hum_sala, temp_nucleo, temp_sup, peso_tira_g
  ) values (
    v_lote, coalesce(p_medido_en, now()),
    p_temp_sala, p_hum_sala, p_temp_nucleo, p_temp_sup, p_peso_tira_g
  )
  on conflict (lote_id, medido_en) do nothing
  returning id into v_id;

  update dispositivos set ultima_lectura = now() where id = v_dispositivo;

  return v_id;
end;
$$;

revoke all on function registrar_lectura from public;
grant execute on function registrar_lectura to anon, authenticated;

-- Para dar de alta el equipo (cambiar el token por uno largo e inventado):
--
--   insert into dispositivos (nombre, token_hash)
--   values ('ESP32 Sala 1',
--           encode(digest('PEGAR-ACA-UN-TOKEN-LARGO', 'sha256'), 'hex'));
--
-- Ese token va en el firmware. En la base no queda guardado en claro.

-- ---------------------------------------------------------------------
--  9. Vista por hora — para los graficos largos.
--
--  Un lote de 30 dias midiendo cada minuto son 43.000 filas. Nadie mira
--  43.000 puntos: para ventanas largas el panel lee esta vista.
-- ---------------------------------------------------------------------
-- "security_invoker" es importante: sin eso la vista se saltea el control
-- de acceso de la tabla y cualquiera podria leerla sin estar logueado.
create or replace view lecturas_por_hora with (security_invoker = on) as
select
  lote_id,
  date_trunc('hour', medido_en) as hora,
  round(avg(temp_sala),   2) as temp_sala,
  round(avg(hum_sala),    2) as hum_sala,
  round(avg(temp_nucleo), 2) as temp_nucleo,
  round(avg(temp_sup),    2) as temp_sup,
  round(avg(peso_tira_g), 1) as peso_tira_g,
  count(*)                   as lecturas
from lecturas
group by lote_id, date_trunc('hour', medido_en);

-- ---------------------------------------------------------------------
--  10. Quien puede hacer que.
--
--  Sin login no se lee ni se escribe NADA. Antes la app entraba con la
--  clave publica y cualquiera con el link podia borrar la telemetria.
--  El ESP32 no pasa por aca: entra por registrar_lectura con su token.
-- ---------------------------------------------------------------------
alter table lotes        enable row level security;
alter table etapas       enable row level security;
alter table lecturas     enable row level security;
alter table mediciones   enable row level security;
alter table dispositivos enable row level security;
alter table config       enable row level security;
alter table alertas      enable row level security;

create policy "usuarios" on lotes        for all to authenticated using (true) with check (true);
create policy "usuarios" on etapas       for all to authenticated using (true) with check (true);
create policy "usuarios" on lecturas     for all to authenticated using (true) with check (true);
create policy "usuarios" on mediciones   for all to authenticated using (true) with check (true);
create policy "usuarios" on config       for all to authenticated using (true) with check (true);
create policy "usuarios" on alertas      for all to authenticated using (true) with check (true);

-- Los tokens no los lee ni el panel.
create policy "solo lectura" on dispositivos for select to authenticated using (true);
