"""EspiaFerramentas: proxy que GRAVA (tool, args) e delega para a Ferramentas real.

Dá observabilidade às evals (que tool o modelo pediu, com que args) SEM tocar no
código de produção. O orquestrador faz `getattr(ferramentas, nome)(**args)`; aqui o
__getattr__ intercepta os métodos-ferramenta, registra a chamada e repassa ao alvo.
Atributos não-callable (ex.: cliente_id) são delegados sem registro.
"""

from __future__ import annotations

from app.agent.tools import Ferramentas


class EspiaFerramentas:
    def __init__(self, alvo: Ferramentas) -> None:
        self._alvo = alvo
        self.chamadas: list[tuple[str, dict]] = []

    def __getattr__(self, nome: str):
        attr = getattr(self._alvo, nome)
        if not callable(attr):
            return attr

        def _wrap(**kwargs):
            self.chamadas.append((nome, kwargs))
            return attr(**kwargs)

        return _wrap

    def nomes(self) -> list[str]:
        return [nome for nome, _ in self.chamadas]
