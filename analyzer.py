import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"
headers = {"X-Auth-Token": API_KEY}

def get_all_matches(competition="PL"):
    """Trae todos los partidos terminados de la temporada"""
    url = f"{BASE_URL}/competitions/{competition}/matches?status=FINISHED"
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()["matches"]
    else:
        print(f"Error: {response.status_code}")
        return []

def analyze_team(team_name, matches):
    """Analiza estadísticas de un equipo específico"""
    team_matches = []
    
    for match in matches:
        home = match["homeTeam"]["name"]
        away = match["awayTeam"]["name"]
        home_goals = match["score"]["fullTime"]["home"]
        away_goals = match["score"]["fullTime"]["away"]
        date = match["utcDate"][:10]

        if home == team_name:
            team_matches.append({
                "date": date,
                "rival": away,
                "goles_favor": home_goals,
                "goles_contra": away_goals,
                "local": True
            })
        elif away == team_name:
            team_matches.append({
                "date": date,
                "rival": home,
                "goles_favor": away_goals,
                "goles_contra": home_goals,
                "local": False
            })

    if not team_matches:
        print(f"No se encontró el equipo: {team_name}")
        return

    total = len(team_matches)
    goles_favor = sum(m["goles_favor"] for m in team_matches)
    goles_contra = sum(m["goles_contra"] for m in team_matches)
    btts = sum(1 for m in team_matches if m["goles_favor"] > 0 and m["goles_contra"] > 0)
    over25 = sum(1 for m in team_matches if m["goles_favor"] + m["goles_contra"] > 2.5)
    wins = sum(1 for m in team_matches if m["goles_favor"] > m["goles_contra"])
    draws = sum(1 for m in team_matches if m["goles_favor"] == m["goles_contra"])
    losses = sum(1 for m in team_matches if m["goles_favor"] < m["goles_contra"])

    print(f"\n{'='*50}")
    print(f"  ANÁLISIS: {team_name}")
    print(f"{'='*50}")
    print(f"  Partidos jugados  : {total}")
    print(f"  Victorias         : {wins} ({wins/total*100:.1f}%)")
    print(f"  Empates           : {draws} ({draws/total*100:.1f}%)")
    print(f"  Derrotas          : {losses} ({losses/total*100:.1f}%)")
    print(f"  Goles a favor     : {goles_favor} (avg: {goles_favor/total:.2f})")
    print(f"  Goles en contra   : {goles_contra} (avg: {goles_contra/total:.2f})")
    print(f"  BTTS (ambos anotan): {btts}/{total} ({btts/total*100:.1f}%)")
    print(f"  Over 2.5 goles    : {over25}/{total} ({over25/total*100:.1f}%)")

    # Últimos 5 partidos (forma reciente)
    print(f"\n  --- Últimos 5 partidos ---")
    for m in team_matches[-5:]:
        loc = "L" if m["local"] else "V"
        gf = m["goles_favor"]
        gc = m["goles_contra"]
        resultado = "W" if gf > gc else ("D" if gf == gc else "L")
        print(f"  {m['date']} [{loc}] vs {m['rival'][:25]:<25} {gf}-{gc}  {resultado}")

# ---- EJECUTAR ANÁLISIS ----
matches = get_all_matches("PL")
analyze_team("Arsenal FC", matches)
analyze_team("Manchester City FC", matches)