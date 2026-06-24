# ADR-0001 — CHECK em enums: fiscais sim, legados não (por ora)

- Status: Aceito
- Data: 2026-06-23
- Fase: S11 (descoberta) → decisão tomada antes de S12

## Contexto

Os documentos-verdade descreviam os enums do schema como "VARCHAR + CHECK". Durante a
Fase S11 descobriu-se que `Enum(..., native_enum=False)` **não** emite constraint CHECK
por padrão: no SQLAlchemy 2.0, `create_constraint` tem default `False`. Logo, os enums
legados (`StatusPedido`, `TipoSolicitacao`, `StatusSolicitacao`) são **VARCHAR sem CHECK**
— os valores são validados apenas na camada ORM (Python), não no banco. A documentação
estava factualmente incorreta.

S11 exigia CHECK real nos enums fiscais novos. Para cumprir, adicionou-se
`create_constraint=True` aos três enums fiscais (`StatusEntrega`, `StatusTitulo`,
`StatusDevolucao`), que passam a ter CHECK de verdade (testado). Isso criou uma assimetria
deliberada: fiscais com CHECK, legados sem.

## Decisão

1. **Corrigir a documentação para a verdade** (Opção B): enums descritos como "VARCHAR via
   `Enum(native_enum=False)`", com nota de que CHECK existe só nos fiscais (S11+) e que
   legados validam na ORM.
2. **Não alterar os enums legados nesta sprint.** Uniformizar é higiene de schema sem
   relação com a demo; misturá-la com o seed (S12) violaria commits atômicos por assunto.
3. **Registrar a uniformização como dívida consciente**, candidata a fase de polimento
   pós-demo (sugestão: `[S17] chore(data): uniformiza CHECK em enums legados`).

## Consequências

- A documentação volta a ser verídica; prompts futuros não herdam a premissa errada.
- Integridade assimétrica no banco: forte (CHECK) nas entidades fiscais, fraca (só ORM)
  nas legadas. Aceitável no estágio de demo/mock, com dados semeados deterministicamente
  e sem escrita arbitrária de status.
- Sem Alembic, uniformizar depois é um one-liner por coluna + `recriar_schema` (que apaga
  e re-semeia — destrói dados, sem custo de migração incremental).
- Primeiro ADR do projeto: estabelece `docs/adr/` como o lugar de decisões arquiteturais
  (antes dispersas em `spec.md §16` e docstrings).
