"""Helpers para renderizar fotos/enlaces de propiedades según el canal.

El agente M3 emite las fotos en formato Markdown:
  - Foto principal:  ![Foto principal](https://...)
  - Fotos extra:     [Recámara](https://...)  [Cocina](https://...)

Cada canal lo renderiza distinto:
  - Web: el widget interpreta el Markdown (img + <a> azul).
  - Telegram: `parse_mode=Markdown` ya hace los [texto](url) clicables;
    las ![alt](url) se mandan aparte como sendPhoto.
  - ManyChat (WA/IG/MSG): no soporta hipervínculos, así que las
    ![alt](url) se mandan como mensaje de imagen y los [texto](url) se
    convierten en "texto: <link corto>".
"""

from __future__ import annotations

import re

# ![alt](url)
MD_IMAGE = re.compile(r"!\[([^\]]*)\]\((https?://[^\s)]+)\)")
# [texto](url)  — el (?<!!) evita capturar las imágenes de arriba
MD_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\((https?://[^\s)]+)\)")


def extract_images(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Saca los tokens ![alt](url) del texto.

    Devuelve (texto_sin_imagenes, [(alt, url), ...]).
    """
    images: list[tuple[str, str]] = []

    def _grab(m: re.Match[str]) -> str:
        images.append((m.group(1).strip(), m.group(2).strip()))
        return ""

    cleaned = MD_IMAGE.sub(_grab, text)
    # Colapsa líneas en blanco que quedaron al quitar las imágenes.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned, images


def iter_links(text: str) -> list[tuple[str, str]]:
    """Devuelve [(texto, url), ...] de los enlaces Markdown del texto."""
    return [
        (m.group(1).strip(), m.group(2).strip()) for m in MD_LINK.finditer(text)
    ]
