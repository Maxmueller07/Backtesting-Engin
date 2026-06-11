from typing import TypedDict, Any

class AgentenState(TypedDict):
    firma: str
    template: dict
    gefundene_daten: dict
    agent_notizen: list
    bericht: str
    such_versuche: int
    offene_fragen: list
    qualitaets_score: int