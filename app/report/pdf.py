"""HTML -> PDF (WeasyPrint) para o relatório visual no WhatsApp.

A Cloud API REJEITA `text/html` como documento (400). O relatório vai como `application/pdf`
(tipo aceito), reusando os templates HTML da S16 (`gerar_html_*`): a string HTML já pronta é
renderizada para PDF aqui. Sem rede/banco — recebe o HTML, devolve os bytes do PDF.

WeasyPrint depende de libs de sistema (Pango/Cairo/GDK-PixBuf) — ver Dockerfile. O import é
LAZY (dentro da função) para o módulo continuar IMPORTÁVEL onde as libs nativas faltam (ex.:
dev Windows): só falha ao efetivamente renderizar. A política best-effort mora no chamador
(router._enviar_*_html): se a renderização levantar, o texto já saiu e a conversa não cai.
"""

from __future__ import annotations


def html_para_pdf(html: str) -> bytes:
    """Renderiza um HTML autocontido (saída de `gerar_html_*`) em bytes de PDF.

    O HTML é self-contained (sem CSS/imagens externos), então não precisa de `base_url`.
    Levanta em erro de renderização — o chamador degrada (best-effort); não engole aqui para
    não mascarar uma falha real de configuração das libs."""
    from weasyprint import HTML

    return HTML(string=html).write_pdf()
