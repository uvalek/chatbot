"""Grafo principal con LangGraph.

Nodos:
    load_buffer → resolve_media → load_memory → router →
        agent_dispatch (M1|M2|M3|M4) → split → send → save_memory
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.agents import m1_faq, m2_agendamiento, m3_catalogo, m4_seguimiento, router
from app.channels import manychat as manychat_chan
from app.channels import telegram as telegram_chan
from app import memory
from app.media import describe_image, transcribe_audio
from app.splitter import split_response
from app.tools.cal import _normalize_phone

log = structlog.get_logger(__name__)


class ChatState(TypedDict, total=False):
    chat_id: str
    channel: Literal["telegram", "manychat"]
    raw_messages: list[dict[str, Any]]
    user_text: str
    user_phone: str
    history: list[dict[str, str]]
    route: Literal["M1", "M2", "M3", "M4"]
    agent_response: str
    chunks: list[str]


async def _resolve_media(state: ChatState) -> dict[str, Any]:
    pieces: list[str] = []
    for row in state["raw_messages"]:
        if row.get("text"):
            pieces.append(row["text"])
            continue
        media_type = row.get("media_type")
        url = row.get("media_url")
        if not (media_type and url):
            continue
        try:
            if media_type == "audio":
                pieces.append(await transcribe_audio(url))
            elif media_type == "image":
                desc = await describe_image(url)
                pieces.append(f"[Imagen recibida] {desc}")
        except Exception as e:  # noqa: BLE001
            log.warning("media_resolve_failed", media_type=media_type, error=str(e))
    return {"user_text": "\n".join(p for p in pieces if p).strip()}


async def _load_memory(state: ChatState) -> dict[str, Any]:
    history = await memory.load_history(state["chat_id"])
    return {"history": history}


async def _route(state: ChatState) -> dict[str, Any]:
    code = await router.classify(state.get("user_text", ""), state.get("history"))
    return {"route": code}


def _route_branch(state: ChatState) -> str:
    return state.get("route") or "M3"


async def _m1(state: ChatState) -> dict[str, Any]:
    text = await m1_faq.respond(state["user_text"], state.get("history", []))
    return {"agent_response": text}


async def _m2(state: ChatState) -> dict[str, Any]:
    text = await m2_agendamiento.respond(
        state["user_text"], state.get("history", []), user_phone=state.get("user_phone", "")
    )
    return {"agent_response": text}


async def _m3(state: ChatState) -> dict[str, Any]:
    text = await m3_catalogo.respond(state["user_text"], state.get("history", []))
    return {"agent_response": text}


async def _m4(state: ChatState) -> dict[str, Any]:
    text = await m4_seguimiento.respond(state["user_text"], state.get("history", []))
    return {"agent_response": text}


async def _split(state: ChatState) -> dict[str, Any]:
    return {"chunks": split_response(state.get("agent_response") or "")}


async def _send(state: ChatState) -> dict[str, Any]:
    chunks = state.get("chunks") or []
    if state["channel"] == "telegram":
        await telegram_chan.send_messages(state["chat_id"], chunks)
    else:
        await manychat_chan.send_messages(state["chat_id"], chunks)
    return {}


async def _save_memory(state: ChatState) -> dict[str, Any]:
    if state.get("user_text"):
        await memory.append(state["chat_id"], "user", state["user_text"])
    if state.get("agent_response"):
        await memory.append(state["chat_id"], "assistant", state["agent_response"])
    return {}


def build_graph():
    g: StateGraph = StateGraph(ChatState)
    g.add_node("resolve_media", _resolve_media)
    g.add_node("load_memory", _load_memory)
    g.add_node("router", _route)
    g.add_node("M1", _m1)
    g.add_node("M2", _m2)
    g.add_node("M3", _m3)
    g.add_node("M4", _m4)
    g.add_node("split", _split)
    g.add_node("send", _send)
    g.add_node("save_memory", _save_memory)

    g.set_entry_point("resolve_media")
    g.add_edge("resolve_media", "load_memory")
    g.add_edge("load_memory", "router")
    g.add_conditional_edges(
        "router",
        _route_branch,
        {"M1": "M1", "M2": "M2", "M3": "M3", "M4": "M4"},
    )
    for n in ("M1", "M2", "M3", "M4"):
        g.add_edge(n, "split")
    g.add_edge("split", "send")
    g.add_edge("send", "save_memory")
    g.add_edge("save_memory", END)
    return g.compile()


_GRAPH = None


def graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


async def dispatch(chat_id: str, channel: str, messages: list[dict[str, Any]]) -> None:
    """Punto de entrada que usa el buffer cuando expira la ventana."""
    user_phone = ""
    for row in messages:
        payload = row.get("payload") or {}
        if channel == "telegram":
            ph = payload.get("contact", {}).get("phone_number") if isinstance(payload, dict) else None
        else:
            ph = (payload.get("phone") or payload.get("whatsapp_phone")) if isinstance(payload, dict) else None
        if ph:
            user_phone = ph
            break

    # Sanea valores basura tipo "{{phone}}" (placeholder no resuelto de ManyChat)
    # o numeros mal formateados. Si no es E.164 valido -> "" y no se guarda nada.
    user_phone = _normalize_phone(user_phone) or ""

    # WhatsApp/ManyChat: si el placeholder no se resolvio, pedimos el numero
    # real a la API de ManyChat usando el subscriber_id (chat_id). En Telegram
    # / Instagram / Messenger el chatbot le pide el telefono al usuario.
    if not user_phone and channel == "manychat":
        api_phone = await manychat_chan.fetch_subscriber_phone(chat_id)
        user_phone = _normalize_phone(api_phone) or ""

    state: ChatState = {
        "chat_id": chat_id,
        "channel": channel,  # type: ignore[typeddict-item]
        "raw_messages": messages,
        "user_phone": user_phone,
    }
    await graph().ainvoke(state)
