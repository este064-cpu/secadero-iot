-- ---------------------------------------------------------------------
--  004 — "Medir ahora" desde el panel, y el latido del equipo.
--
--  El ESP32 esta adentro de la fabrica, detras del router: el panel no
--  puede golpearle la puerta. Asi que se invierte: el equipo pregunta
--  cada 30 segundos "¿alguien pidio una medicion?" y el panel deja el
--  pedido anotado aca.
--
--  Esa misma pregunta sirve para algo que faltaba y que vale mas que el
--  boton: queda constancia de que el equipo esta vivo aunque no logre
--  guardar ni una lectura. Con eso el panel puede distinguir "se quedo
--  sin wifi" de "esta conectado pero las lecturas no entran", que son
--  dos problemas distintos y hasta ahora se veian iguales.
--
--  Se puede correr mas de una vez sin romper nada.
-- ---------------------------------------------------------------------

alter table dispositivos
  add column if not exists medir_pedido_en timestamptz;

alter table dispositivos
  add column if not exists ultimo_contacto timestamptz;

comment on column dispositivos.medir_pedido_en is
  'Cuando alguien apreto "Medir ahora". El equipo lo consume y lo deja null.';
comment on column dispositivos.ultimo_contacto is
  'Ultima vez que el equipo pregunto algo. Es el latido: dice que esta '
  'vivo y con internet, independientemente de que las lecturas entren.';


-- ---------------------------------------------------------------------
--  La pregunta del equipo.
--
--  Devuelve la hora del pedido pendiente (o null si no hay) y lo borra en
--  el mismo movimiento, para que una medicion pedida no se haga dos veces.
--  El equipo no necesita recordar nada entre reinicios.
-- ---------------------------------------------------------------------
create or replace function tomar_pedido(p_token text)
returns timestamptz
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_dispositivo smallint;
  v_pedido      timestamptz;
begin
  select id, medir_pedido_en
    into v_dispositivo, v_pedido
    from dispositivos
   where activo
     and token_hash = encode(digest(p_token, 'sha256'), 'hex')
     for update;

  if v_dispositivo is null then
    raise exception 'Token invalido';
  end if;

  update dispositivos
     set ultimo_contacto = now(),
         medir_pedido_en = null
   where id = v_dispositivo;

  return v_pedido;
end;
$$;

revoke all on function tomar_pedido from public;
grant execute on function tomar_pedido to anon, authenticated;


-- ---------------------------------------------------------------------
--  El boton del panel.
--
--  No se le da permiso de update sobre dispositivos a nadie: en esa tabla
--  vive el hash del token y conviene que siga siendo de solo lectura.
--  Esta funcion es la unica forma de anotar el pedido, y solo la puede
--  llamar alguien logueado.
-- ---------------------------------------------------------------------
create or replace function pedir_medicion()
returns timestamptz
language plpgsql
security definer
set search_path = public
as $$
declare
  v_ahora timestamptz := now();
begin
  update dispositivos set medir_pedido_en = v_ahora where activo;
  return v_ahora;
end;
$$;

revoke all on function pedir_medicion from public;
grant execute on function pedir_medicion to authenticated;
