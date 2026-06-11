from langgraph.graph import StateGraph
from agent_nodes import such_knoten, check, Bericht, offenefragne, Qualtät
from Agent_State import AgentenState



graph = StateGraph(AgentenState)

# Knoten hinzufügen
graph.add_node("suchen", such_knoten)
graph.add_node("analysieren", check)
graph.add_node("bericht", Bericht)
graph.add_node("offene_fragen", offenefragne())
graph.add_node("qualitaet", Qualtät)

# Reihenfolge
graph.set_entry_point("suchen")
graph.add_edge("suchen", "analysieren")
graph.add_edge("analysieren", "offene_fragen")
graph.add_edge("offene_fragen", "qualitaet")

# Entscheidung — nochmal suchen oder fertig
def entscheidung(state):
    if state["qualitaets_score"] >= 70 or state["such_versuche"] >= 3:
        return "fertig"
    return "nochmal"

graph.add_conditional_edges("qualitaet", entscheidung, {
    "fertig": "bericht",
    "nochmal": "suchen"
})

graph.add_edge("bericht", END)

app = graph.compile()