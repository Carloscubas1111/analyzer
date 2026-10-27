import os
import math
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

_cache_matches = {}

def get_matches(codigo):
    """Trae todos los partidos terminados de la liga (con cache simple)"""
    key = f"{codigo}_{datetime.now().strftime('%Y%m%d%H')}"
    if key in _cache_matches:
        return _cache_matches[key]
    url = f"{FD_BASE}/competitions/{codigo}/matches?status=FINISHED"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code != 200:
        return []
    matches = r.json()["matches"]
    _cache_matches[key] = matches
    return matches

def get_equipos(codigo):
    url = f"{FD_BASE}/competitions/{codigo}/teams"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code == 200:
        return [t["name"] for t in r.json()["teams"]]
    return []

def get_liga_promedios(matches):
    """Calcula los promedios de goles de TODA la liga (base para Poisson)"""
    total_partidos = 0
    goles_local = 0
    goles_visita = 0
    for m in matches:
        hg = m["score"]["fullTime"]["home"]
        ag = m["score"]["fullTime"]["away"]
        if hg is None or ag is None:
            continue
        total_partidos += 1
        goles_local += hg
        goles_visita += ag
    if total_partidos == 0:
        return {"avg_local": 1.5, "avg_visita": 1.2, "partidos": 0}
    return {
        "avg_local": round(goles_local / total_partidos, 3),
        "avg_visita": round(goles_visita / total_partidos, 3),
        "partidos": total_partidos
    }

def get_stats(team_name, matches):
    team_matches = []
    for m in matches:
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        hg = m["score"]["fullTime"]["home"]
        ag = m["score"]["fullTime"]["away"]
        if hg is None or ag is None:
            continue
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

def poisson_pmf(k, lam):
    """Probabilidad de exactamente k goles dado lambda"""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)

def calcular_poisson(s1, s2, liga_avg):
    """
    Modelo de Poisson con fuerzas ofensivas/defensivas ajustadas a la liga.
    s1 = equipo local, s2 = equipo visitante
    """
    liga_local = liga_avg["avg_local"]
    liga_visita = liga_avg["avg_visita"]

    if liga_local <= 0 or liga_visita <= 0:
        return None

    # Fuerza ofensiva del local = (goles que mete en casa) / (promedio de goles de local en la liga)
    ataque_local = s1["avg_gf_local"] / liga_local if liga_local > 0 else 1
    # Fuerza defensiva del local = (goles que recibe en casa) / (promedio de goles de visitante en la liga)
    defensa_local = s1["avg_gc_local"] / liga_visita if liga_visita > 0 else 1
    # Fuerza ofensiva del visitante
    ataque_visita = s2["avg_gf_visita"] / liga_visita if liga_visita > 0 else 1
    # Fuerza defensiva del visitante
    defensa_visita = s2["avg_gc_visita"] / liga_local if liga_local > 0 else 1

    # Goles esperados (lambda)
    lambda_local = ataque_local * defensa_visita * liga_local
    lambda_visita = ataque_visita * defensa_local * liga_visita

    # Cap para evitar valores absurdos con pocos datos
    lambda_local = max(0.2, min(lambda_local, 5.0))
    lambda_visita = max(0.2, min(lambda_visita, 5.0))

    # Matriz de probabilidades hasta 6-6
    max_goles = 7
    matriz = []
    for i in range(max_goles):
        fila = []
        for j in range(max_goles):
            p = poisson_pmf(i, lambda_local) * poisson_pmf(j, lambda_visita)
            fila.append(p)
        matriz.append(fila)

    # Probabilidades de resultado
    p_local = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i > j)
    p_empate = sum(matriz[i][i] for i in range(max_goles))
    p_visita = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i < j)

    # Over / Under
    p_over05 = 1 - matriz[0][0]
    p_over15 = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i + j > 1.5)
    p_over25 = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i + j > 2.5)
    p_over35 = sum(matriz[i][j] for i in range(max_goles) for j in range(max_goles) if i + j > 3.5)

    # BTTS
    p_btts = sum(matriz[i][j] for i in range(1, max_goles) for j in range(1, max_goles))

    # Top 5 marcadores
    marcadores = []
    for i in range(max_goles):
        for j in range(max_goles):
            marcadores.append((f"{i}-{j}", round(matriz[i][j]*100, 2)))
    marcadores.sort(key=lambda x: x[1], reverse=True)
    top_marcadores = marcadores[:5]

    return {
        "lambda_local": round(lambda_local, 2),
        "lambda_visita": round(lambda_visita, 2),
        "goles_esperados_total": round(lambda_local + lambda_visita, 2),
        "p_gana_local": round(p_local*100, 1),
        "p_empate": round(p_empate*100, 1),
        "p_gana_visita": round(p_visita*100, 1),
        "p_1x": round((p_local + p_empate)*100, 1),
        "p_x2": round((p_empate + p_visita)*100, 1),
        "p_12": round((p_local + p_visita)*100, 1),
        "p_over05": round(p_over05*100, 1),
        "p_over15": round(p_over15*100, 1),
        "p_over25": round(p_over25*100, 1),
        "p_over35": round(p_over35*100, 1),
        "p_under15": round((1-p_over15)*100, 1),
        "p_under25": round((1-p_over25)*100, 1),
        "p_under35": round((1-p_over35)*100, 1),
        "p_btts_si": round(p_btts*100, 1),
        "p_btts_no": round((1-p_btts)*100, 1),
        "top_marcadores": top_marcadores,
        "liga_avg_local": liga_local,
        "liga_avg_visita": liga_visita
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

    matches = get_matches(codigo)
    if not matches:
        return jsonify({"error": "No se pudieron cargar los partidos de la liga"})

    liga_avg = get_liga_promedios(matches)
    s1 = get_stats(equipo1, matches)
    s2 = get_stats(equipo2, matches)

    if not s1 or not s2:
        return jsonify({"error": "No se encontraron datos de uno o ambos equipos"})

    poisson = calcular_poisson(s1, s2, liga_avg)
    if not poisson:
        return jsonify({"error": "No se pudo calcular el modelo estadístico"})

    h2h = [m for m in s1["todos"] if m["rival"] == equipo2][-5:]

    prompt = f"""
Eres un sharp bettor profesional. Tu trabajo es INTERPRETAR probabilidades ya calculadas matemáticamente
y convertirlas en picks accionables. NO calcules nada tú mismo, NO inventes datos.
Las probabilidades del modelo de Poisson que te doy abajo son la VERDAD matemática de este partido.

=== MODELO DE POISSON (probabilidades calculadas matemáticamente) ===
Este modelo usa la fuerza ofensiva y defensiva de cada equipo ajustada al promedio de la liga.
Promedio de goles de la liga: {poisson['liga_avg_local']} (local) / {poisson['liga_avg_visita']} (visitante) en {liga_avg['partidos']} partidos

GOLES ESPERADOS:
- {s1['equipo']} (local): {poisson['lambda_local']} goles esperados
- {s2['equipo']} (visitante): {poisson['lambda_visita']} goles esperados
- Total esperado en el partido: {poisson['goles_esperados_total']} goles

PROBABILIDADES DE RESULTADO:
- Gana {s1['equipo']}: {poisson['p_gana_local']}%
- Empate: {poisson['p_empate']}%
- Gana {s2['equipo']}: {poisson['p_gana_visita']}%
- Doble oportunidad 1X ({s1['equipo']} no pierde): {poisson['p_1x']}%
- Doble oportunidad X2 ({s2['equipo']} no pierde): {poisson['p_x2']}%
- Doble oportunidad 12 (no hay empate): {poisson['p_12']}%

PROBABILIDADES DE GOLES:
- Over 0.5: {poisson['p_over05']}% | Under 0.5: {round(100-poisson['p_over05'],1)}%
- Over 1.5: {poisson['p_over15']}% | Under 1.5: {poisson['p_under15']}%
- Over 2.5: {poisson['p_over25']}% | Under 2.5: {poisson['p_under25']}%
- Over 3.5: {poisson['p_over35']}% | Under 3.5: {poisson['p_under35']}%

AMBOS EQUIPOS ANOTAN:
- BTTS Sí: {poisson['p_btts_si']}%
- BTTS No: {poisson['p_btts_no']}%

MARCADORES MÁS PROBABLES:
{chr(10).join([f"- {m[0]}: {m[1]}%" for m in poisson['top_marcadores']])}

=== CONTEXTO DE FORMA: {s1['equipo']} (LOCAL) ===
Como local: {s1['gana_local']}V {s1['empata_local']}E {s1['pierde_local']}D en {s1['partidos_local']} partidos
Goles en casa: {s1['avg_gf_local']} a favor / {s1['avg_gc_local']} en contra
Primer tiempo: con goles {s1['ht_over05_pct']}% | ganando al descanso {s1['ht_gana_pct']}%
Últimos 5: {[(m['rival'], f"{m['gf']}-{m['gc']}", 'Casa' if m['local'] else 'Fuera') for m in s1['ultimos5']]}

=== CONTEXTO DE FORMA: {s2['equipo']} (VISITANTE) ===
Como visitante: {s2['gana_visita']}V {s2['empata_visita']}E {s2['pierde_visita']}D en {s2['partidos_visita']} partidos
Goles fuera: {s2['avg_gf_visita']} a favor / {s2['avg_gc_visita']} en contra
Primer tiempo: con goles {s2['ht_over05_pct']}% | ganando al descanso {s2['ht_gana_pct']}%
Últimos 5: {[(m['rival'], f"{m['gf']}-{m['gc']}", 'Casa' if m['local'] else 'Fuera') for m in s2['ultimos5']]}

=== HEAD TO HEAD ===
{[(m['rival'], f"{m['gf']}-{m['gc']}") for m in h2h] if h2h else "Sin enfrentamientos directos en esta temporada"}

REGLAS ESTRICTAS PARA LOS PICKS:
1. Confianza ALTA solo si la probabilidad de Poisson es >= 65%.
2. Confianza MEDIA si está entre 55% y 64%.
3. Confianza BAJA si está entre 50% y 54%. NUNCA recomiendes un pick por debajo de 50%.
4. CADA pick debe citar el porcentaje exacto de Poisson que lo respalda.
5. Si la forma reciente contradice fuertemente a Poisson, menciónalo en Factores de Riesgo.
6. Solo menciona primer tiempo si ht_over05_pct o ht_gana_pct de algún equipo supera 60%.
7. Ordena los picks de mayor a menor probabilidad.

Responde en español con este formato EXACTO:

## 📊 Lectura del Modelo
[Interpreta qué dicen los goles esperados y las probabilidades principales. Máximo 4 líneas.]

## ⚽ Análisis de Goles
[Compara Over/Under según Poisson. Di cuál es el escenario más probable y por qué. Cita porcentajes.]

## 🔄 Forma y Contexto
[Contrasta la forma reciente con lo que dice el modelo. ¿Se confirman o se contradicen?]

## 🎯 Picks Recomendados
[Entre 3 y 5 picks, solo los que superen 50% según Poisson. Ordenados de mayor a menor probabilidad.]

Pick 1 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Alto/Medio/Bajo] | Razón: [1 línea]
Pick 2 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Alto/Medio/Bajo] | Razón: [1 línea]
Pick 3 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Alto/Medio/Bajo] | Razón: [1 línea]
Pick 4 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Medio/Bajo] | Razón: [1 línea] (si aplica)
Pick 5 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Bajo] | Razón: [1 línea] (si aplica)

## 🎲 Marcador Más Probable
[Menciona el top 3 de marcadores con sus porcentajes]

## ⚠️ Factores de Riesgo
[Qué podría invalidar el modelo. Máximo 2 líneas.]

## 📝 Conclusión
[2 líneas con el pick más sólido y su respaldo matemático.]
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
        "poisson": poisson,
        "archivo": nombre
    })

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')