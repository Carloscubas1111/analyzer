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
        ht_home = m["score"].get("halfTime", {}).get("home", None)
        ht_away = m["score"].get("halfTime", {}).get("away", None)
        if home == team_name:
            team_matches.append({
                "rival": away, "gf": hg, "gc": ag,
                "date": m["utcDate"][:10], "local": True,
                "ht_gf": ht_home, "ht_gc": ht_away
            })
        elif away == team_name:
            team_matches.append({
                "rival": home, "gf": ag, "gc": hg,
                "date": m["utcDate"][:10], "local": False,
                "ht_gf": ht_away, "ht_gc": ht_home
            })
    if not team_matches:
        return None
    total = len(team_matches)

    # Calcular stats de primer tiempo
    ht_matches = [m for m in team_matches if m["ht_gf"] is not None]
    ht_total = len(ht_matches)
    ht_over05 = sum(1 for m in ht_matches if (m["ht_gf"] or 0) + (m["ht_gc"] or 0) > 0.5)
    ht_gana = sum(1 for m in ht_matches if (m["ht_gf"] or 0) > (m["ht_gc"] or 0))
    ht_goles_favor = sum((m["ht_gf"] or 0) for m in ht_matches)

    return {
        "equipo": team_name,
        "partidos": total,
        "victorias": sum(1 for m in team_matches if m["gf"] > m["gc"]),
        "empates": sum(1 for m in team_matches if m["gf"] == m["gc"]),
        "derrotas": sum(1 for m in team_matches if m["gf"] < m["gc"]),
        "avg_gf": round(sum(m["gf"] for m in team_matches) / total, 2),
        "avg_gc": round(sum(m["gc"] for m in team_matches) / total, 2),
        "btts": sum(1 for m in team_matches if m["gf"] > 0 and m["gc"] > 0),
        "btts_no": sum(1 for m in team_matches if m["gf"] == 0 or m["gc"] == 0),
        "over15": sum(1 for m in team_matches if m["gf"] + m["gc"] > 1.5),
        "over25": sum(1 for m in team_matches if m["gf"] + m["gc"] > 2.5),
        "over35": sum(1 for m in team_matches if m["gf"] + m["gc"] > 3.5),
        "under15": sum(1 for m in team_matches if m["gf"] + m["gc"] < 1.5),
        "under25": sum(1 for m in team_matches if m["gf"] + m["gc"] < 2.5),
        "gana_local": sum(1 for m in team_matches if m["local"] and m["gf"] > m["gc"]),
        "gana_visita": sum(1 for m in team_matches if not m["local"] and m["gf"] > m["gc"]),
        "partidos_local": sum(1 for m in team_matches if m["local"]),
        "partidos_visita": sum(1 for m in team_matches if not m["local"]),
        "ht_over05_pct": round(ht_over05/ht_total*100, 1) if ht_total > 0 else 0,
        "ht_gana_pct": round(ht_gana/ht_total*100, 1) if ht_total > 0 else 0,
        "ht_avg_gf": round(ht_goles_favor/ht_total, 2) if ht_total > 0 else 0,
        "ultimos5": team_matches[-5:],
        "todos": team_matches
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

    # Calcular head to head
    h2h = []
    for m in s1["todos"]:
        if m["rival"] == equipo2:
            h2h.append(m)
    h2h = h2h[-5:]

    # Stats locales y visitante
    local_win_pct = round(s1["gana_local"]/s1["partidos_local"]*100, 1) if s1["partidos_local"] > 0 else 0
    visit_win_pct = round(s2["gana_visita"]/s2["partidos_visita"]*100, 1) if s2["partidos_visita"] > 0 else 0

    prompt = f"""
Eres un analista profesional de apuestas deportivas con experiencia real.
Tu trabajo es dar picks HONESTOS basados ÚNICAMENTE en los datos estadísticos proporcionados.
NO inventes información. Si los datos apuntan a Under, di Under. Si apuntan a pocos goles, dilo.
Analiza TODOS los mercados disponibles y elige los que tengan respaldo estadístico real.

=== DATOS: {s1['equipo']} (JUEGA DE LOCAL) ===
- Record general: {s1['victorias']}V {s1['empates']}E {s1['derrotas']}D en {s1['partidos']} partidos
- Como LOCAL: {s1['gana_local']}V de {s1['partidos_local']} partidos ({local_win_pct}% victorias en casa)
- Promedio goles anotados: {s1['avg_gf']} | recibidos: {s1['avg_gc']}
- Over 1.5: {s1['over15']}/{s1['partidos']} ({round(s1['over15']/s1['partidos']*100,1)}%)
- Over 2.5: {s1['over25']}/{s1['partidos']} ({round(s1['over25']/s1['partidos']*100,1)}%)
- Over 3.5: {s1['over35']}/{s1['partidos']} ({round(s1['over35']/s1['partidos']*100,1)}%)
- Under 2.5: {s1['under25']}/{s1['partidos']} ({round(s1['under25']/s1['partidos']*100,1)}%)
- BTTS Sí: {s1['btts']}/{s1['partidos']} ({round(s1['btts']/s1['partidos']*100,1)}%)
- BTTS No: {s1['btts_no']}/{s1['partidos']} ({round(s1['btts_no']/s1['partidos']*100,1)}%)
- 1er Tiempo con goles: {s1['ht_over05_pct']}%
- 1er Tiempo ganando: {s1['ht_gana_pct']}%
- Promedio goles 1er Tiempo: {s1['ht_avg_gf']}
- Últimos 5: {[(m['rival'], f"{m['gf']}-{m['gc']}", 'Casa' if m['local'] else 'Fuera') for m in s1['ultimos5']]}

=== DATOS: {s2['equipo']} (JUEGA DE VISITANTE) ===
- Record general: {s2['victorias']}V {s2['empates']}E {s2['derrotas']}D en {s2['partidos']} partidos
- Como VISITANTE: {s2['gana_visita']}V de {s2['partidos_visita']} partidos ({visit_win_pct}% victorias fuera)
- Promedio goles anotados: {s2['avg_gf']} | recibidos: {s2['avg_gc']}
- Over 1.5: {s2['over15']}/{s2['partidos']} ({round(s2['over15']/s2['partidos']*100,1)}%)
- Over 2.5: {s2['over25']}/{s2['partidos']} ({round(s2['over25']/s2['partidos']*100,1)}%)
- Over 3.5: {s2['over35']}/{s2['partidos']} ({round(s2['over35']/s2['partidos']*100,1)}%)
- Under 2.5: {s2['under25']}/{s2['partidos']} ({round(s2['under25']/s2['partidos']*100,1)}%)
- BTTS Sí: {s2['btts']}/{s2['partidos']} ({round(s2['btts']/s2['partidos']*100,1)}%)
- BTTS No: {s2['btts_no']}/{s2['partidos']} ({round(s2['btts_no']/s2['partidos']*100,1)}%)
- 1er Tiempo con goles: {s2['ht_over05_pct']}%
- 1er Tiempo ganando: {s2['ht_gana_pct']}%
- Promedio goles 1er Tiempo: {s2['ht_avg_gf']}
- Últimos 5: {[(m['rival'], f"{m['gf']}-{m['gc']}", 'Casa' if m['local'] else 'Fuera') for m in s2['ultimos5']]}

=== HEAD TO HEAD (últimos enfrentamientos disponibles) ===
{[(m['rival'], f"{m['gf']}-{m['gc']}") for m in h2h] if h2h else "Sin datos H2H disponibles en esta temporada"}

MERCADOS A EVALUAR (solo incluye los que tengan respaldo estadístico real):
- Ganador: {s1['equipo']} gana / Empate / {s2['equipo']} gana
- Doble oportunidad: {s1['equipo']} no pierde (1X) / {s2['equipo']} no pierde (X2)
- Goles totales: Over/Under 1.5 / Over/Under 2.5 / Over/Under 3.5
- BTTS: Ambos anotan Sí / No
- Primer tiempo: Over 0.5 goles 1T / Gana {s1['equipo']} en 1T / Empate en 1T
- Hándicap: si hay diferencia clara de nivel

Responde en español con este formato EXACTO:

## 📊 Análisis de Forma
[Analiza el momento actual de cada equipo basado en sus últimos 5. Menciona si juegan bien en casa/fuera. Máximo 5 líneas.]

## ⚽ Análisis de Goles
[Qué dicen los números sobre cuántos goles se esperan. Compara Over 1.5, 2.5, 3.5 y Under. Menciona el primer tiempo si los datos lo respaldan.]

## 🔄 Head to Head
[Si hay datos H2H úsalos. Si no, menciona que no hay enfrentamientos previos en esta temporada y analiza tendencias generales.]

## 🎯 Picks Recomendados
[Lista entre 3 y 5 picks. Solo incluye picks que los datos respalden claramente. Ordénalos de mayor a menor confianza.]

Pick 1 — [Mercado]: [Pick exacto] | Confianza: Alto | Razón: [1 línea con el dato que lo respalda]
Pick 2 — [Mercado]: [Pick exacto] | Confianza: Alto/Medio | Razón: [1 línea]
Pick 3 — [Mercado]: [Pick exacto] | Confianza: Medio | Razón: [1 línea]
Pick 4 — [Mercado]: [Pick exacto] | Confianza: Medio/Bajo | Razón: [1 línea] (solo si los datos lo respaldan)
Pick 5 — [Mercado]: [Pick exacto] | Confianza: Bajo | Razón: [1 línea] (solo si los datos lo respaldan)

## ⚠️ Factores de Riesgo
[Qué podría cambiar el resultado. Máximo 2 líneas.]

## 📝 Conclusión
[2 líneas resumiendo el análisis y el pick más fuerte.]
"""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000
    )

    analisis = response.choices[0].message.content

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