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

    ht_matches = [m for m in team_matches if m["ht_gf"] is not None]
    ht_total = len(ht_matches)
    ht_over05 = sum(1 for m in ht_matches if (m["ht_gf"] or 0) + (m["ht_gc"] or 0) > 0.5)
    ht_gana = sum(1 for m in ht_matches if (m["ht_gf"] or 0) > (m["ht_gc"] or 0))
    ht_goles_favor = sum((m["ht_gf"] or 0) for m in ht_matches)

    locales = [m for m in team_matches if m["local"]]
    visitas = [m for m in team_matches if not m["local"]]

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
        "under25": sum(1 for m in team_matches if m["gf"] + m["gc"] < 2.5),
        "partidos_local": len(locales),
        "partidos_visita": len(visitas),
        "gana_local": sum(1 for m in locales if m["gf"] > m["gc"]),
        "empata_local": sum(1 for m in locales if m["gf"] == m["gc"]),
        "pierde_local": sum(1 for m in locales if m["gf"] < m["gc"]),
        "gana_visita": sum(1 for m in visitas if m["gf"] > m["gc"]),
        "empata_visita": sum(1 for m in visitas if m["gf"] == m["gc"]),
        "pierde_visita": sum(1 for m in visitas if m["gf"] < m["gc"]),
        "avg_gf_local": round(sum(m["gf"] for m in locales) / len(locales), 2) if locales else 0,
        "avg_gc_local": round(sum(m["gc"] for m in locales) / len(locales), 2) if locales else 0,
        "avg_gf_visita": round(sum(m["gf"] for m in visitas) / len(visitas), 2) if visitas else 0,
        "avg_gc_visita": round(sum(m["gc"] for m in visitas) / len(visitas), 2) if visitas else 0,
        "btts_local_pct": round(sum(1 for m in locales if m["gf"]>0 and m["gc"]>0)/len(locales)*100,1) if locales else 0,
        "btts_visita_pct": round(sum(1 for m in visitas if m["gf"]>0 and m["gc"]>0)/len(visitas)*100,1) if visitas else 0,
        "over25_local_pct": round(sum(1 for m in locales if m["gf"]+m["gc"]>2.5)/len(locales)*100,1) if locales else 0,
        "over25_visita_pct": round(sum(1 for m in visitas if m["gf"]+m["gc"]>2.5)/len(visitas)*100,1) if visitas else 0,
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

    h2h = [m for m in s1["todos"] if m["rival"] == equipo2][-5:]

    prompt = f"""
Eres un sharp bettor (apostador profesional) implacable y analítico. Tu trabajo es dar picks REALES
basados EXCLUSIVAMENTE en los porcentajes matemáticos provistos abajo. Nunca inventes datos que no estén aquí.

REGLAS ESTRICTAS DE FILTRADO (síguelas al pie de la letra):
1. Solo recomienda "Over 2.5" si el promedio combinado de goles (avg_gf + avg_gc de ambos equipos) es >= 2.7,
   O si el porcentaje individual de over25 de AMBOS equipos supera 55%.
2. Solo recomienda "BTTS Sí" si el BTTS% de ambos equipos supera 55%. Si alguno está por debajo de 40%, recomienda "BTTS No".
3. Para el pick de ganador, usa el rendimiento ESPECÍFICO de local del equipo 1 y ESPECÍFICO de visitante del equipo 2 —
   NO el rendimiento global. Un equipo puede ser fuerte en general pero débil de visitante, eso cambia todo.
4. Si los números son mediocres (ni over ni under claro, ni ganador claro), recomienda mercados más seguros
   como Doble Oportunidad o Under, nunca fuerces un pick arriesgado solo por dar opciones.
5. Para el pick de primer tiempo, solo recomiéndalo si ht_over05_pct o ht_gana_pct supera 60%.
6. Cada pick DEBE citar el número exacto que lo respalda. Si no hay un número que lo respalde con fuerza, no lo incluyas.

=== DATOS: {s1['equipo']} — JUEGA DE LOCAL ===
Rendimiento GLOBAL: {s1['victorias']}V {s1['empates']}E {s1['derrotas']}D en {s1['partidos']} partidos | Goles: {s1['avg_gf']} a favor, {s1['avg_gc']} en contra
Rendimiento COMO LOCAL (el que importa para este partido): {s1['gana_local']}V {s1['empata_local']}E {s1['pierde_local']}D en {s1['partidos_local']} partidos en casa
- Goles como local: {s1['avg_gf_local']} a favor, {s1['avg_gc_local']} en contra
- BTTS como local: {s1['btts_local_pct']}%
- Over 2.5 como local: {s1['over25_local_pct']}%
- Over 1.5 total: {round(s1['over15']/s1['partidos']*100,1)}% | Over 3.5 total: {round(s1['over35']/s1['partidos']*100,1)}% | Under 2.5 total: {round(s1['under25']/s1['partidos']*100,1)}%
- Primer tiempo — con goles: {s1['ht_over05_pct']}% | ganando al descanso: {s1['ht_gana_pct']}% | avg goles 1T: {s1['ht_avg_gf']}
- Últimos 5 (todos): {[(m['rival'], f"{m['gf']}-{m['gc']}", 'Casa' if m['local'] else 'Fuera') for m in s1['ultimos5']]}

=== DATOS: {s2['equipo']} — JUEGA DE VISITANTE ===
Rendimiento GLOBAL: {s2['victorias']}V {s2['empates']}E {s2['derrotas']}D en {s2['partidos']} partidos | Goles: {s2['avg_gf']} a favor, {s2['avg_gc']} en contra
Rendimiento COMO VISITANTE (el que importa para este partido): {s2['gana_visita']}V {s2['empata_visita']}E {s2['pierde_visita']}D en {s2['partidos_visita']} partidos fuera
- Goles como visitante: {s2['avg_gf_visita']} a favor, {s2['avg_gc_visita']} en contra
- BTTS como visitante: {s2['btts_visita_pct']}%
- Over 2.5 como visitante: {s2['over25_visita_pct']}%
- Over 1.5 total: {round(s2['over15']/s2['partidos']*100,1)}% | Over 3.5 total: {round(s2['over35']/s2['partidos']*100,1)}% | Under 2.5 total: {round(s2['under25']/s2['partidos']*100,1)}%
- Primer tiempo — con goles: {s2['ht_over05_pct']}% | ganando al descanso: {s2['ht_gana_pct']}% | avg goles 1T: {s2['ht_avg_gf']}
- Últimos 5 (todos): {[(m['rival'], f"{m['gf']}-{m['gc']}", 'Casa' if m['local'] else 'Fuera') for m in s2['ultimos5']]}

=== HEAD TO HEAD ===
{[(m['rival'], f"{m['gf']}-{m['gc']}") for m in h2h] if h2h else "Sin enfrentamientos directos en los datos disponibles"}

Responde en español con este formato EXACTO:

## 📊 Análisis de Forma
[Compara el rendimiento de local de {s1['equipo']} vs el rendimiento de visitante de {s2['equipo']} específicamente. Máximo 5 líneas.]

## ⚽ Análisis de Goles
[Qué dicen los números de Over/Under. Cita los porcentajes exactos. Menciona primer tiempo solo si aplica la regla 5.]

## 🔄 Head to Head
[Usa los datos H2H si existen. Si no hay, dilo explícitamente.]

## 🎯 Picks Recomendados
[Entre 3 y 5 picks. CADA pick debe aplicar las reglas estrictas de arriba y citar el número exacto.]

Pick 1 — [Mercado]: [Pick exacto] | Confianza: Alto | Razón: [cita el % exacto]
Pick 2 — [Mercado]: [Pick exacto] | Confianza: Alto/Medio | Razón: [cita el % exacto]
Pick 3 — [Mercado]: [Pick exacto] | Confianza: Medio | Razón: [cita el % exacto]
Pick 4 — [Mercado]: [Pick exacto] | Confianza: Medio/Bajo | Razón: [cita el % exacto] (solo si cumple las reglas)
Pick 5 — [Mercado]: [Pick exacto] | Confianza: Bajo | Razón: [cita el % exacto] (solo si cumple las reglas)

## ⚠️ Factores de Riesgo
[Qué podría invalidar estos picks. Máximo 2 líneas.]

## 📝 Conclusión
[2 líneas con el pick más fuerte y por qué.]
"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2500,
        temperature=0.3
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