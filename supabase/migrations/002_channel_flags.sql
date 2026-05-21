-- Interruptores globales por canal: deciden si el bot procesa mensajes
-- entrantes de cada canal. Reemplaza el "arm/disarm" en memoria de ManyChat.
create table if not exists channel_flags (
  channel text primary key,
  enabled boolean not null default false,
  updated_at timestamptz not null default now()
);

-- Estado inicial: solo web y Telegram encendidos.
insert into channel_flags (channel, enabled) values
  ('webchat',   true),
  ('telegram',  true),
  ('whatsapp',  false),
  ('instagram', false),
  ('messenger', false)
on conflict (channel) do nothing;
