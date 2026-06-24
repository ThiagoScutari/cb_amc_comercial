# ADR-0002 — Cópia visual por listas (Caminho A); 2ª via individual adiada

- Status: Aceito
- Data: 2026-06-23
- Fase: S16 (decisão tomada no fechamento da sprint S11–S16)

## Contexto

A sprint S11–S16 adicionou as entidades fiscais (nota fiscal, título, devolução) e o pedido
do comercial incluía "cópia" de documentos no WhatsApp. O HTML existente
(`gerar_html_pedidos`) era específico de pedidos e **desacoplado das tool-calls**: o gatilho
lê só o texto do cliente (substring) e chama `listar_*` por conta própria — nunca o resultado
da ferramenta que o orquestrador rodou. Havia três caminhos para a cópia visual:

- **A (escolhido):** LISTAS visuais por entidade ("minhas notas fiscais" → HTML renderizado),
  com a MESMA mecânica do resumo de pedidos. Aditivo, dentro do padrão já testado, zero
  acoplamento novo.
- **B:** 2ª via por número EXPLÍCITO no texto ("manda a NF 60001"), via parsing do número no
  gatilho — sem acoplar à tool-call, mas não cobre fraseado livre ("aquela nota de quarenta
  mil").
- **C:** 2ª via ACOPLADA à tool-call — o dispatcher renderiza a NF que `consultar_nota_fiscal`
  resolveu, cobrindo qualquer fraseado que o modelo entenda. Mais poderoso, mas introduz um
  acoplamento render↔orquestrador que a arquitetura atual evita de propósito.

## Decisão

1. **Implementar o Caminho A no S16.** Cópia visual como LISTA para pedido/NF/título/
   devolução, via gatilho substring + render best-effort (degradação graciosa, igual ao
   resumo de pedidos). Refactor com base reutilizável (`_SHELL` + corpo genérico), mantendo
   a saída de pedidos byte-idêntica (ver `gerar_html_pedidos`).
2. **Adiar a 2ª via individual (B/C)** para uma fase futura, idealmente o **Caminho C**
   (acoplado à tool-call), por ser o correto para produção, onde o cliente fala livremente.
3. **Motivo do adiamento:** para a DEMO, as listas visuais das 4 entidades já entregam o
   fator visual; o ganho marginal de B/C não justifica introduzir acoplamento novo às
   vésperas da apresentação (YAGNI + preservar a arquitetura desacoplada já testada).

## Consequências

- Cópia visual disponível como LISTA para pedido/NF/título/devolução, aditiva e best-effort
  (se o HTML falhar, a conversa segue — o texto já saiu).
- Quando a 2ª via individual for implementada (Caminho C), exigirá **expor o resultado da
  tool-call ao dispatcher de HTML** — essa é a peça arquitetural a desenhar com cuidado
  então (hoje o HTML não vê o que a ferramenta resolveu).
- Documentar aqui evita que o "eu do futuro" reimplemente sem saber que **B e C foram
  avaliados** e por que **A veio primeiro**. Caminho C é a evolução recomendada.
