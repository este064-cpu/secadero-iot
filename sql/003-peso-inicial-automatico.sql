-- =====================================================================
--  El peso inicial de la tira se toma solo
--
--  Correr UNA vez en el editor SQL de Supabase. No borra nada.
--
--  Por que
--  -------
--  El peso inicial de la tira es el numero del que sale TODA la merma
--  del lote. Si se olvidan de cargarlo, o ese dia no estan en la
--  fabrica, el lote entero queda sin merma y no hay forma de
--  recuperarlo despues: la tira ya empezo a secarse.
--
--  Asi que lo toma el sistema solo, unas horas despues de arrancar el
--  lote, leyendo la celda. Lo hace alertas.py desde GitHub Actions y no
--  el panel, porque el panel solo corre cuando alguien lo tiene abierto,
--  que es justamente lo que no se puede garantizar.
--
--  Se espera un rato y no se toma al instante porque la celda se acomoda
--  sola bajo una carga nueva: sube varios gramos y despues baja. Un peso
--  tomado recien colgada le mete ese error a la merma de todo el lote.
--
--  Y como una celda puede estar mal tarada o directamente rota, antes de
--  colgar la tira se la pesa en otra balanza y ese numero se carga como
--  referencia. Cuando el sistema toma el suyo, compara: si no se parecen,
--  sale un mail. Una balanza sola no se puede controlar a si misma.
-- =====================================================================

-- ---------------------------------------------------------------------
--  1. El lote guarda el peso de control y de donde salio el suyo
-- ---------------------------------------------------------------------
alter table lotes add column if not exists
  tira_peso_referencia_g numeric(8, 1) check (tira_peso_referencia_g > 0);

alter table lotes add column if not exists
  tira_peso_tomado_en timestamptz;

alter table lotes add column if not exists
  tira_peso_origen text;

alter table lotes drop constraint if exists lotes_peso_origen_valido;
alter table lotes add  constraint lotes_peso_origen_valido
  check (tira_peso_origen is null
         or tira_peso_origen in ('manual', 'automatico'));

comment on column lotes.tira_peso_referencia_g is
  'Lo que peso la tira en otra balanza, antes de colgarla. Sirve para '
  'controlar a la celda: si el peso que toma el sistema no se parece a '
  'este, algo esta mal y sale un mail.';

-- Los lotes que ya tienen peso lo cargaron a mano.
update lotes
   set tira_peso_origen = 'manual'
 where tira_peso_inicial_g is not null
   and tira_peso_origen is null;

-- ---------------------------------------------------------------------
--  2. Cuanto esperar y cuanto se le permite diferir
-- ---------------------------------------------------------------------
alter table config add column if not exists
  horas_peso_automatico numeric(4, 1) not null default 2
    check (horas_peso_automatico > 0);

alter table config add column if not exists
  tolerancia_peso_pct numeric(4, 1) not null default 5
    check (tolerancia_peso_pct > 0);

comment on column config.horas_peso_automatico is
  'Cuantas horas despues de arrancar el lote se lee la celda para fijar '
  'el peso inicial de la tira. Dos horas alcanzan para que la celda se '
  'acomode y son pocas para que la tira haya perdido algo que importe.';

-- ---------------------------------------------------------------------
--  3. Un tipo de alerta nuevo
-- ---------------------------------------------------------------------
alter table alertas drop constraint if exists alertas_tipo_check;
alter table alertas add  constraint alertas_tipo_check
  check (tipo in ('temperatura', 'humedad', 'rocio', 'sin_datos',
                  'peso_inicial'));
