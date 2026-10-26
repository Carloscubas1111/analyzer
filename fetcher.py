import requests
import os
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("FOOTBALL_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

headers = {"X-Auth-Token": API_KEY}

def get_matches(competition="PL", limit=10):
    """Trae los últimos partidos de una liga"""
    url = f"{BASE_URL}/competitions/{competition}/matches?status=FINISHED"
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        matches = data["matches"][-limit:]
        print(f"\n=== Últimos {limit} partidos de {competition} ===\n")
        for match in matches:
            home = match["homeTeam"]["name"]
            away = match["awayTeam"]["name"]
            score = match["score"]["fullTime"]
            date = match["utcDate"][:10]
            print(f"{date} | {home} {score['home']} - {score['away']} {away}")
    else:
        print(f"Error: {response.status_code} - {response.text}")

get_matches()