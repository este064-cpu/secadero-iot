-- =====================================================================
--  Las etapas pasan de dias fijos a duraciones
--
--  Correr UNA vez en el editor SQL de Supabase. No borra nada: convierte
--  las etapas que ya existen.
--
--  Por que
--  -------
--  Antes cada etapa decia "del dia 0 al dia 2". En la camara eso no pasa:
--  el estufado se programa en 48 horas, pero si el pH baja a las 31 se
--  saca igual, y todo lo que viene atras se corre 17 horas. Con dias
--  fijos habia que reescribir a mano todos los numeros del lote cada vez.
--
--  Ahora cada etapa tiene una DURACION en horas y un lugar en la fila. La
--  primera arranca cuando arranca el lote y cada una empieza donde
--  termino la anterior, asi que cortar una corre a todas las siguientes
--  sin tocar ningun otro numero.
--
--  "horas_reales" se llena sola cuando se corta una etapa a mano desde el
--  panel. Mientras este en null, la etapa dura lo previsto.
-- =====================================================================

alter table etapas add column if not exists orden        smallint;
alter table etapas add column if not exists horas        integer;
alter table etapas add column if not exists horas_reales numeric(8, 2);

-- Convertir lo que ya estaba. Los dias son inclusivos de los dos lados,
-- asi que "del 0 al 2" son tres dias: 72 horas.
update etapas
   set orden = sub.fila,
       horas = (dia_hasta - dia_desde + 1) * 24
  from (
    select id, row_number() over (partition by lote_id order by dia_desde) as fila
      from etapas
  ) as sub
 where etapas.id = sub.id
   and etapas.orden is null;

alter table etapas alter column orden set not null;
alter table etapas alter column horas set not null;
alter table etapas alter column horas set default 24;

-- Los "drop if exists" antes de cada "add" son para que esto se pueda
-- correr dos veces sin romperse: si la primera corrida se corta por la
-- mitad, la segunda tiene que poder terminar el trabajo.
alter table etapas drop constraint if exists etapas_horas_positivas;
alter table etapas add  constraint etapas_horas_positivas check (horas > 0);

alter table etapas drop constraint if exists etapas_horas_reales_positivas;
alter table etapas add  constraint etapas_horas_reales_positivas
  check (horas_reales is null or horas_reales > 0);

-- El orden reemplaza al dia de arranque como identidad de la etapa.
alter table etapas drop constraint if exists etapas_lote_id_dia_desde_key;
alter table etapas drop constraint if exists etapas_lote_orden_unico;
alter table etapas add  constraint etapas_lote_orden_unico unique (lote_id, orden);

-- Los dias ya no se usan. Se van al final, por si hay que mirar atras
-- mientras se prueba lo nuevo.
alter table etapas drop column if exists dia_desde;
alter table etapas drop column if exists dia_hasta;
