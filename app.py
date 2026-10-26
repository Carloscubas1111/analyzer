import os
import requests
from flask import Flask, render_template, request, jsonify
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

app = Flask(__name__)
client = Groq(api_key=GROQ_API_KEY)

FD_HEADERS = {"X-Auth-Token": FOOTBALL_DATA_KEY}
FD_BASE = "https://api.football-data.org/v4"

LIGAS = {
    "PL":  "Premier League",
    "PD":  "La Liga",
    "BL1": "Bundesliga",
    "SA":  "Serie A",
    "FL1": "Ligue 1",
    "CL":  "Champions League",
}

def get_equipos(codigo):
    url = f"{FD_BASE}/competitions/{codigo}/teams"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code == 200:
        return [t["name"] for t in r.json()["teams"]]
    return []

def get_stats(team_name, codigo):
    url = f"{FD_BASE}/competitions/{codigo}/matches?status=FINISHED"
    r = requests.get(url, headers=FD_HEADERS)
    matches = r.json()["matches"]
    team_matches = []
    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        hg = m["score"]["fullTime"]["home"]
        ag = m["score"]["fullTime"]["away"]
        if home == team_name:
            team_matches.append({"rival": away, "gf": hg, "gc": ag, "date": m["utcDate"][:10], "local": True})
        elif away == team_name:
            team_matches.append({"rival": home, "gf": ag, "gc": hg, "date": m["utcDate"][:10], "local": False})
    if not team_matches:
        return None
    total = len(team_matches)
    return {
        "equipo": team_name,
        "partidos": total,
        "victorias": sum(1 for m in team_matches if m["gf"] > m["gc"]),
        "empates": sum(1 for m in team_matches if m["gf"] == m["gc"]),
        "derrotas": sum(1 for m in team_matches if m["gf"] < m["gc"]),
        "avg_gf": round(sum(m["gf"] for m in team_matches) / total, 2),
        "avg_gc": round(sum(m["gc"] for m in team_matches) / total, 2),
        "btts": sum(1 for m in team_matches if m["gf"] > 0 and m["gc"] > 0),
        "over25": sum(1 for m in team_matches if m["gf"] + m["gc"] > 2.5),
        "ultimos5": team_matches[-5:]
    }

def get_proximos(codigo):
    url = f"{FD_BASE}/competitions/{codigo}/matches?status=SCHEDULED"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code == 200:
        matches = r.json()["matches"][:10]
        return [{"home": m["homeTeam"]["name"], "away": m["awayTeam"]["name"], "date": m["utcDate"][:10]} for m in matches]
    return []

@app.route("/")
def index():
    return render_template("index.html", ligas=LIGAS)

@app.route("/equipos/<codigo>")
def equipos(codigo):
    return jsonify(get_equipos(codigo))

@app.route("/proximos/<codigo>")
def proximos(codigo):
    return jsonify(get_proximos(codigo))

@app.route("/analizar", methods=["POST"])
def analizar():
    data = request.json
    equipo1 = data["equipo1"]
    equipo2 = data["equipo2"]
    codigo = data["liga"]

    s1 = get_stats(equipo1, codigo)
    s2 = get_stats(equipo2, codigo)

    if not s1 or not s2:
        return jsonify({"error": "No se encontraron datos"})

    prompt = f"""
Eres un analista experto en apuestas deportivas de fútbol.
Analiza los datos y genera un análisis MUY DETALLADO.

=== {s1['equipo']} ===
- Record: {s1['victorias']}V {s1['empates']}E {s1['derrotas']}D
- Avg goles a favor: {s1['avg_gf']} | en contra: {s1['avg_gc']}
- BTTS: {s1['btts']}/{s1['partidos']} ({round(s1['btts']/s1['partidos']*100,1)}%)
- Over 2.5: {s1['over25']}/{s1['partidos']} ({round(s1['over25']/s1['partidos']*100,1)}%)
- Últimos 5: {[(m['rival'], f"{m['gf']}-{m['gc']}") for m in s1['ultimos5']]}

=== {s2['equipo']} ===
- Record: {s2['victorias']}V {s2['empates']}E {s2['derrotas']}D
- Avg goles a favor: {s2['avg_gf']} | en contra: {s2['avg_gc']}
- BTTS: {s2['btts']}/{s2['partidos']} ({round(s2['btts']/s2['partidos']*100,1)}%)
- Over 2.5: {s2['over25']}/{s2['partidos']} ({round(s2['over25']/s2['partidos']*100,1)}%)
- Últimos 5: {[(m['rival'], f"{m['gf']}-{m['gc']}") for m in s2['ultimos5']]}

Responde en español con este formato exacto:

## 📊 Análisis de Forma
[análisis detallado de cada equipo]

## ⚽ Tendencia de Goles
[Over/Under analysis]

## 🏥 Jugadores Lesionados
[lista jugadores importantes lesionados de cada equipo y su impacto]

## 🎯 Jugadores Clave
[jugadores más probables en remates, asistencias y goles]

## 🔄 Head to Head
[historial reciente entre estos equipos]

## ✅ Pick Principal
[pick con nivel de confianza Alto/Medio/Bajo]

## 🔀 Pick Alternativo
[pick alternativo]

## 📝 Resumen Final
[2 líneas resumiendo todo]
"""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000
    )

    analisis = response.choices[0].message.content

    # Guardar en archivo
    os.makedirs("analisis", exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"analisis/{equipo1.replace(' ','_')}_vs_{equipo2.replace(' ','_')}_{fecha}.txt"
    with open(nombre, "w", encoding="utf-8") as f:
        f.write(analisis)

    return jsonify({
        "analisis": analisis,
        "stats1": s1,
        "stats2": s2,
        "archivo": nombre
    })

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')