from dotenv import load_dotenv
from langchain.agents import AgentState
from tavily import TavilyClient
from langchain_openai import ChatOpenAI
import os
llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY")
)

load_dotenv()
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

def such_knoten(state):
    alle_ergebnisse = {}

    firma = state["firma"]
    for kategorie, kennzahlen in state["template"].items():

        suchbegriff = f"{firma} Geschäftsbericht {' '.join(kennzahlen)}"
        ergebnis = tavily.search(suchbegriff)
        alle_ergebnisse[kategorie] = ergebnis
    return {"gefundene_daten": alle_ergebnisse}

def check(state,):
    alle_ergebnisse = {}
    firma = state["firma"]
    for kategorie, kennzahlen in state["template"].items():
        daten = state["gefundene_daten"][kategorie]
        Nachricht = f"Extrahiere die Folgengeden kenzahlen: {' '.join(kennzahlen)} aus diesen daten: {daten} für die Firma {firma}"
        ergebnis = llm.invoke(Nachricht)
        alle_ergebnisse[kategorie] = ergebnis.content

    return {"gefundene_daten": alle_ergebnisse}

def Bericht(state):
    firma = state["firma"]
    daten = state["gefundene_daten"]
    Nachricht = f"""
Du bekommst Finanzdaten der Firma {firma}.
Schreibe einen strukturierten Bericht mit diesen Kategorien: {list(state['template'].keys())}
Für jede Kategorie liste die Kennzahlen übersichtlich auf.
Daten: {daten}
"""
    ergebnis = llm.invoke(Nachricht)
    return {"bericht": ergebnis.content}

def offenefragne(state):
    firma = state["firma"]
    daten = state["gefundene_daten"]

    offenKategorien = {}

    for kategorie, kennzahlen in state["template"].items():
        offen = {}

        for kennzahl in kennzahlen:
            if kennzahl not in daten.get(kategorie, {}):
                offen[kennzahl] = kennzahl
        offenKategorien[kategorie] = offen

    return {"offene_fragen": offenKategorien,
            "such_versuche": state["such_versuche"]+1
            }
def Qualtät (state):
    Bericht = state["bericht"]
    insgesamt = sum(len(k) for k in state["template"].values())
    offen = sum(len(k) for k in state["offene_fragen"].values())
    score1 = ( (insgesamt-offen) / insgesamt) * 100
    Nachricht = f"Prüfe den Bericht {Bericht} zur firma {state['firma']} auf die Qualität und Bewerte es mit einer Scala vpn 1 bis 10 "
    antwort = llm.invoke(Nachricht)
    try:
        kizahl = int (antwort.content.strip())
    except:
        kizahl = 5

    score2 = (kizahl/10) * 100

    ergebnis = (score1 + score2 )/2

    return {"qualitaets_score": ergebnis}





