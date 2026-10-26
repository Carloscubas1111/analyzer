import os
import requests
from groq import Groq
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

FOOTBALL_DATA_KEY = os.getenv("FOOTBALL_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY)

FD_HEADERS = {"X-Auth-Token": FOOTBALL_DATA_KEY}
FD_BASE = "https://api.football-data.org/v4"
ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer"

LIGAS = {
    "1":  {"nombre": "Premier League",   "codigo": "PL",    "api": "fd"},
    "2":  {"nombre": "La Liga",          "codigo": "PD",    "api": "fd"},
    "3":  {"nombre": "Bundesliga",       "codigo": "BL1",   "api": "fd"},
    "4":  {"nombre": "Serie A",          "codigo": "SA",    "api": "fd"},
    "5":  {"nombre": "Ligue 1",          "codigo": "FL1",   "api": "fd"},
    "6":  {"nombre": "Champions League", "codigo": "CL",    "api": "fd"},
    "7":  {"nombre": "Brasileirao",      "codigo": "bra.1", "api": "espn"},
    "8":  {"nombre": "Liga Argentina",   "codigo": "arg.1", "api": "espn"},
    "9":  {"nombre": "Liga MX",          "codigo": "mex.1", "api": "espn"},
    "10": {"nombre": "Liga Colombiana",  "codigo": "col.1", "api": "espn"},
    "11": {"nombre": "Liga Chilena",     "codigo": "chi.1", "api": "espn"},
}

def mostrar_ligas():
    print("\n=== LIGAS DISPONIBLES ===")
    print("  -- Europeas --")
    for k, v in LIGAS.items():
        if v["api"] == "fd":
            print(f"  {k}. {v['nombre']}")
    print("  -- Latinoamérica --")
    for k, v in LIGAS.items():
        if v["api"] == "espn":
            print(f"  {k}. {v['nombre']}")

def get_equipos_fd(codigo):
    url = f"{FD_BASE}/competitions/{codigo}/teams"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code == 200:
        return [t["name"] for t in r.json()["teams"]]
    return []

def get_equipos_espn(codigo):
    url = f"{ESPN_BASE}/{codigo}/teams"
    r = requests.get(url)
    if r.status_code == 200:
        teams = r.json().get("sports", [{}])[0].get("leagues", [{}])[0].get("teams", [])
        return [t["team"]["displayName"] for t in teams]
    return []

def get_stats_fd(team_name, codigo):
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
            team_matches.append({"rival": away, "gf": hg, "gc": ag, "date": m["utcDate"][:10]})
        elif away == team_name:
            team_matches.append({"rival": home, "gf": ag, "gc": hg, "date": m["utcDate"][:10]})
    return calcular_stats(team_name, team_matches)

def get_stats_espn(team_name, codigo):
    url = f"{ESPN_BASE}/{codigo}/scoreboard?limit=100"
    r = requests.get(url)
    if r.status_code != 200:
        return None
    events = r.json().get("events", [])
    team_matches = []
    for event in events:
        comp = event["competitions"][0]
        if comp["status"]["type"]["completed"] is False:
            continue
        home_team = comp["competitors"][0]
        away_team = comp["competitors"][1]
        home = home_team["team"]["displayName"]
        away = away_team["team"]["displayName"]
        hg = int(home_team.get("score", 0))
        ag = int(away_team.get("score", 0))
        date = event["date"][:10]
        if home == team_name:
            team_matches.append({"rival": away, "gf": hg, "gc": ag, "date": date})
        elif away == team_name:
            team_matches.append({"rival": home, "gf": ag, "gc": hg, "date": date})
    return calcular_stats(team_name, team_matches)

def calcular_stats(team_name, team_matches):
    if not team_matches:
        return None
    total = len(team_matches)
    return {
        "equipo": team_name,
        "partidos": total,
        "victorias": sum(1 for m in team_matches if m["gf"] > m["gc"]),
        "empates":   sum(1 for m in team_matches if m["gf"] == m["gc"]),
        "derrotas":  sum(1 for m in team_matches if m["gf"] < m["gc"]),
        "avg_gf":  round(sum(m["gf"] for m in team_matches) / total, 2),
        "avg_gc":  round(sum(m["gc"] for m in team_matches) / total, 2),
        "btts":    sum(1 for m in team_matches if m["gf"] > 0 and m["gc"] > 0),
        "over25":  sum(1 for m in team_matches if m["gf"] + m["gc"] > 2.5),
        "ultimos5": team_matches[-5:]
    }

def guardar_analisis(texto, equipo1, equipo2):
    os.makedirs("analisis", exist_ok=True)
    fecha = datetime.now().strftime("%Y%m%d_%H%M%S")
    nombre = f"analisis/{equipo1.replace(' ','_')}_vs_{equipo2.replace(' ','_')}_{fecha}.txt"
    with open(nombre, "w", encoding="utf-8") as f:
        f.write(texto)
    print(f"\n✅ Análisis guardado en: {nombre}")

def generar_prediccion(equipo1, equipo2, liga):
    print(f"\n⏳ Analizando {equipo1} vs {equipo2}...")
    if liga["api"] == "fd":
        s1 = get_stats_fd(equipo1, liga["codigo"])
        s2 = get_stats_fd(equipo2, liga["codigo"])
    else:
        s1 = get_stats_espn(equipo1, liga["codigo"])
        s2 = get_stats_espn(equipo2, liga["codigo"])

    if not s1 or not s2:
        print("❌ No se encontraron datos. Verifica los nombres.")
        return

    prompt = f"""
Eres un analista experto en apuestas deportivas de fútbol.
Analiza los siguientes datos y genera picks recomendados.

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

Responde en español con:
1. Forma reciente de cada equipo
2. Tendencia Over/Under
3. Probabilidad BTTS
4. Pick principal (confianza: Alto/Medio/Bajo)
5. Pick alternativo
6. Resumen en 2 líneas
"""

    response = client.chat.completions.create(
        model="qwen/qwen3.8-27b",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1000
    )

    analisis = response.choices[0].message.content
    resultado = f"\n{'='*60}\n  PREDICCIÓN: {equipo1} vs {equipo2}\n  Liga: {liga['nombre']} | {datetime.now().strftime('%d/%m/%Y %H:%M')}\n{'='*60}\n{analisis}"
    print(resultado)
    guardar_analisis(resultado, equipo1, equipo2)

def menu():
    print("\n" + "="*60)
    print("   ⚽ FOOTBALL ANALYZER - PREDICTOR CON IA ⚽")
    print("="*60)

    while True:
        mostrar_ligas()
        op = input("\nSelecciona liga (1-11) o 'q' para salir: ").strip()
        if op.lower() == 'q':
            print("\n¡Hasta luego! 👋")
            break
        if op not in LIGAS:
            print("❌ Opción inválida.")
            continue

        liga = LIGAS[op]
        print(f"\n✅ {liga['nombre']}")
        print("⏳ Cargando equipos...")

        if liga["api"] == "fd":
            equipos = get_equipos_fd(liga["codigo"])
        else:
            equipos = get_equipos_espn(liga["codigo"])

        if not equipos:
            print("❌ No se pudieron cargar los equipos.")
            continue

        print("\n=== EQUIPOS ===")
        for i, e in enumerate(equipos, 1):
            print(f"  {i:2}. {e}")

        print("\nEscribe el nombre EXACTO (copia de la lista)")
        e1 = input("Equipo local: ").strip()
        e2 = input("Equipo visitante: ").strip()

        if e1 not in equipos or e2 not in equipos:
            print("❌ Equipo no encontrado. Copia el nombre exacto de la lista.")
            continue

        generar_prediccion(e1, e2, liga)

        if input("\n¿Analizar otro? (s/n): ").strip().lower() != 's':
            print("\n¡Hasta luego! 👋")
            break

menu()