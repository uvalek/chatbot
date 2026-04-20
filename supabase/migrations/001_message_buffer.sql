-- Buffer de mensajes entrantes con ventana de 25 s.
-- Reemplaza el patrón de Redis "Insertar + Wait + Delete" del flujo n8n.

create table if not exists public.message_buffer (
    id          bigserial primary key,
    chat_id     text        not null,
    channel     text        not null check (channel in ('telegram', 'manychat')),
    payload     jsonb       not null,
    text        text,
    media_type  text,
    media_url   text,
    created_at  timestamptz not null default now(),
    processed   boolean     not null default false,
    processed_at timestamptz
);

create index if not exists message_buffer_pending_idx
    on public.message_buffer (chat_id, created_at)
    where processed = false;

create index if not exists message_buffer_created_at_idx
    on public.message_buffer (created_at);
