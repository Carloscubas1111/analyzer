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

DECAY = 0.90
VENTANA_RECIENTE = 6
PESO_RECIENTE = 0.55

_cache = {}


def get_matches(codigo):
    key = f"{codigo}_{datetime.now().strftime('%Y%m%d%H')}"
    if key in _cache:
        return _cache[key]
    url = f"{FD_BASE}/competitions/{codigo}/matches?status=FINISHED"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code != 200:
        return []
    matches = r.json()["matches"]
    _cache[key] = matches
    return matches


def get_equipos(codigo):
    url = f"{FD_BASE}/competitions/{codigo}/teams"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code == 200:
        return [t["name"] for t in r.json()["teams"]]
    return []


def get_proximos(codigo):
    url = f"{FD_BASE}/competitions/{codigo}/matches?status=SCHEDULED"
    r = requests.get(url, headers=FD_HEADERS)
    if r.status_code == 200:
        matches = r.json()["matches"][:10]
        return [{"home": m["homeTeam"]["name"], "away": m["awayTeam"]["name"], "date": m["utcDate"][:10]} for m in matches]
    return []


def build_team_matches(matches):
    teams = {}
    for m in matches:
        hg = m["score"]["fullTime"]["home"]
        ag = m["score"]["fullTime"]["away"]
        if hg is None or ag is None:
            continue
        home = m["homeTeam"]["name"]
        away = m["awayTeam"]["name"]
        date = m["utcDate"][:10]
        ht_h = m["score"].get("halfTime", {}).get("home")
        ht_a = m["score"].get("halfTime", {}).get("away")
        teams.setdefault(home, []).append({
            "rival": away, "gf": hg, "gc": ag, "date": date,
            "local": True, "ht_gf": ht_h, "ht_gc": ht_a
        })
        teams.setdefault(away, []).append({
            "rival": home, "gf": ag, "gc": hg, "date": date,
            "local": False, "ht_gf": ht_a, "ht_gc": ht_h
        })
    for t in teams:
        teams[t].sort(key=lambda x: x["date"])
    return teams


def get_liga_promedios(matches):
    total = 0
    gl = 0
    gv = 0
    for m in matches:
        hg = m["score"]["fullTime"]["home"]
        ag = m["score"]["fullTime"]["away"]
        if hg is None or ag is None:
            continue
        total += 1
        gl += hg
        gv += ag
    if total == 0:
        return {"avg_local": 1.50, "avg_visita": 1.20, "gpg": 1.35, "partidos": 0}
    avg_local = gl / total
    avg_visita = gv / total
    return {
        "avg_local": round(avg_local, 3),
        "avg_visita": round(avg_visita, 3),
        "gpg": round((avg_local + avg_visita) / 2, 3),
        "partidos": total
    }


def _crudo(ms, strength, gpg, usar_decay):
    """
    Goles a favor y en contra ajustados por la calidad del rival.
    Devuelve valores en goles por partido (misma escala que gpg).
    """
    if not ms:
        return gpg, gpg
    n = len(ms)
    gf = 0.0
    gc = 0.0
    peso = 0.0
    for i, m in enumerate(ms):
        w = (DECAY ** (n - 1 - i)) if usar_decay else 1.0
        opp = strength.get(m["rival"], {"ataque": 1.0, "defensa": 1.0})
        # dividir por el rating del rival: meterle a una defensa floja vale menos
        gf += (m["gf"] / max(opp["defensa"], 0.5)) * w
        gc += (m["gc"] / max(opp["ataque"], 0.5)) * w
        peso += w
    if peso == 0:
        return gpg, gpg
    return gf / peso, gc / peso


def _normalizar(valores, objetivo=1.0):
    """Escala un dict para que su media sea exactamente 'objetivo'."""
    if not valores:
        return {}
    media = sum(valores.values()) / len(valores)
    if media <= 0:
        return {k: objetivo for k in valores}
    factor = objetivo / media
    return {k: v * factor for k, v in valores.items()}


def calc_strength_table(team_map, liga_avg, iteraciones=5):
    """
    Ratings de ataque/defensa normalizados a media 1.0 de la liga.
    Aplica regresion a la media: con pocos partidos el rating tiende a 1.0.
    """
    gpg = liga_avg["gpg"]
    strength = {t: {"ataque": 1.0, "defensa": 1.0} for t in team_map}

    # Con K partidos de "lastre", un equipo con 7 jugados pesa 7/(7+K)
    K = 5.0

    for _ in range(iteraciones):
        at_temp, df_temp, at_rec, df_rec = {}, {}, {}, {}

        for team, ms in team_map.items():
            a_s, d_s = _crudo(ms, strength, gpg, usar_decay=False)
            a_r, d_r = _crudo(ms[-VENTANA_RECIENTE:], strength, gpg, usar_decay=True)
            at_temp[team] = a_s
            df_temp[team] = d_s
            at_rec[team] = a_r
            df_rec[team] = d_r

        at_temp = _normalizar(at_temp)
        df_temp = _normalizar(df_temp)
        at_rec = _normalizar(at_rec)
        df_rec = _normalizar(df_rec)

        mezcla_at, mezcla_df = {}, {}
        for team, ms in team_map.items():
            n = len(ms)
            # peso de la evidencia: mas partidos = el rating se aleja mas de 1.0
            shrink = n / (n + K)

            a = (1 - PESO_RECIENTE) * at_temp[team] + PESO_RECIENTE * at_rec[team]
            d = (1 - PESO_RECIENTE) * df_temp[team] + PESO_RECIENTE * df_rec[team]

            # regresion a la media
            mezcla_at[team] = 1.0 + shrink * (a - 1.0)
            mezcla_df[team] = 1.0 + shrink * (d - 1.0)

        mezcla_at = _normalizar(mezcla_at)
        mezcla_df = _normalizar(mezcla_df)

        nuevo = {}
        for team in team_map:
            nuevo[team] = {
                "ataque": round(max(0.45, min(mezcla_at[team], 2.0)), 3),
                "defensa": round(max(0.45, min(mezcla_df[team], 2.0)), 3),
                "ataque_temporada": round(at_temp[team], 3),
                "defensa_temporada": round(df_temp[team], 3),
                "ataque_reciente": round(at_rec[team], 3),
                "defensa_reciente": round(df_rec[team], 3),
                "partidos": len(team_map[team])
            }
        strength = nuevo

    return strength

def clasificar_momento(s):
    if s.get("partidos", 0) < 4:
        return {"estado": "Muestra corta", "delta": 0.0,
                "nota": "Pocos partidos, el rating es poco fiable"}
    nivel_temp = s["ataque_temporada"] - s["defensa_temporada"]
    nivel_rec = s["ataque_reciente"] - s["defensa_reciente"]
    delta = round(nivel_rec - nivel_temp, 2)
    if delta <= -0.45:
        return {"estado": "En crisis", "delta": delta, "nota": "Rinde muy por debajo de su nivel de temporada"}
    if delta <= -0.18:
        return {"estado": "A la baja", "delta": delta, "nota": "Viene cayendo respecto a su nivel habitual"}
    if delta >= 0.45:
        return {"estado": "En racha", "delta": delta, "nota": "Rinde muy por encima de su nivel de temporada"}
    if delta >= 0.18:
        return {"estado": "En alza", "delta": delta, "nota": "Mejorando respecto a su nivel habitual"}
    return {"estado": "Estable", "delta": delta, "nota": "Rinde en línea con su nivel de temporada"}


def etiqueta_nivel(s):
    nivel = s["ataque"] - s["defensa"]
    if nivel >= 0.55:
        return "Élite"
    if nivel >= 0.22:
        return "Fuerte"
    if nivel >= -0.05:
        return "Medio-alto"
    if nivel >= -0.30:
        return "Medio-bajo"
    return "Débil"


def calidad_calendario(ms, strength):
    if not ms:
        return 1.0
    n = len(ms)
    total = 0.0
    peso = 0.0
    for i, m in enumerate(ms):
        w = DECAY ** (n - 1 - i)
        opp = strength.get(m["rival"], {"ataque": 1.0, "defensa": 1.0})
        total += (opp["ataque"] / max(opp["defensa"], 0.4)) * w
        peso += w
    return round(total / peso, 2) if peso > 0 else 1.0


def get_stats(team_name, team_map, strength):
    ms = team_map.get(team_name)
    if not ms:
        return None
    total = len(ms)

    ht = [m for m in ms if m["ht_gf"] is not None]
    ht_total = len(ht)
    ht_over05 = sum(1 for m in ht if (m["ht_gf"] or 0) + (m["ht_gc"] or 0) > 0.5)
    ht_gana = sum(1 for m in ht if (m["ht_gf"] or 0) > (m["ht_gc"] or 0))
    ht_gf = sum((m["ht_gf"] or 0) for m in ht)

    locales = [m for m in ms if m["local"]]
    visitas = [m for m in ms if not m["local"]]
    s = strength.get(team_name, {"ataque": 1.0, "defensa": 1.0})

    return {
        "equipo": team_name,
        "partidos": total,
        "victorias": sum(1 for m in ms if m["gf"] > m["gc"]),
        "empates": sum(1 for m in ms if m["gf"] == m["gc"]),
        "derrotas": sum(1 for m in ms if m["gf"] < m["gc"]),
        "avg_gf": round(sum(m["gf"] for m in ms) / total, 2),
        "avg_gc": round(sum(m["gc"] for m in ms) / total, 2),
        "btts": sum(1 for m in ms if m["gf"] > 0 and m["gc"] > 0),
        "btts_no": sum(1 for m in ms if m["gf"] == 0 or m["gc"] == 0),
        "over15": sum(1 for m in ms if m["gf"] + m["gc"] > 1.5),
        "over25": sum(1 for m in ms if m["gf"] + m["gc"] > 2.5),
        "over35": sum(1 for m in ms if m["gf"] + m["gc"] > 3.5),
        "under25": sum(1 for m in ms if m["gf"] + m["gc"] < 2.5),
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
        "btts_local_pct": round(sum(1 for m in locales if m["gf"] > 0 and m["gc"] > 0) / len(locales) * 100, 1) if locales else 0,
        "btts_visita_pct": round(sum(1 for m in visitas if m["gf"] > 0 and m["gc"] > 0) / len(visitas) * 100, 1) if visitas else 0,
        "over25_local_pct": round(sum(1 for m in locales if m["gf"] + m["gc"] > 2.5) / len(locales) * 100, 1) if locales else 0,
        "over25_visita_pct": round(sum(1 for m in visitas if m["gf"] + m["gc"] > 2.5) / len(visitas) * 100, 1) if visitas else 0,
        "ht_over05_pct": round(ht_over05 / ht_total * 100, 1) if ht_total else 0,
        "ht_gana_pct": round(ht_gana / ht_total * 100, 1) if ht_total else 0,
        "ht_avg_gf": round(ht_gf / ht_total, 2) if ht_total else 0,
        "rating_ataque": s["ataque"],
        "rating_defensa": s["defensa"],
        "rating_ataque_temporada": s.get("ataque_temporada", s["ataque"]),
        "rating_defensa_temporada": s.get("defensa_temporada", s["defensa"]),
        "rating_ataque_reciente": s.get("ataque_reciente", s["ataque"]),
        "rating_defensa_reciente": s.get("defensa_reciente", s["defensa"]),
        "nivel": etiqueta_nivel(s),
        "momento": clasificar_momento(s),
        "calendario": calidad_calendario(ms, strength),
        "ultimos5": ms[-5:],
        "todos": ms
    }


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def calcular_poisson(s1, s2, liga_avg):
    base_local = liga_avg["avg_local"]
    base_visita = liga_avg["avg_visita"]
    if base_local <= 0 or base_visita <= 0:
        return None

    gpg = liga_avg["gpg"]
    mod_local = 1.0
    mod_visita = 1.0
    if s1["partidos_local"] >= 3 and gpg > 0:
        mod_local = 1 + 0.30 * ((s1["avg_gf_local"] / gpg) - 1)
    if s2["partidos_visita"] >= 3 and gpg > 0:
        mod_visita = 1 + 0.30 * ((s2["avg_gf_visita"] / gpg) - 1)
    mod_local = max(0.7, min(mod_local, 1.5))
    mod_visita = max(0.7, min(mod_visita, 1.5))

    lambda_local = s1["rating_ataque"] * s2["rating_defensa"] * base_local * mod_local
    lambda_visita = s2["rating_ataque"] * s1["rating_defensa"] * base_visita * mod_visita

    lambda_local = max(0.25, min(lambda_local, 5.0))
    lambda_visita = max(0.25, min(lambda_visita, 5.0))

    N = 8
    matriz = [[poisson_pmf(i, lambda_local) * poisson_pmf(j, lambda_visita) for j in range(N)] for i in range(N)]

    p_local = sum(matriz[i][j] for i in range(N) for j in range(N) if i > j)
    p_empate = sum(matriz[i][i] for i in range(N))
    p_visita = sum(matriz[i][j] for i in range(N) for j in range(N) if i < j)
    p_over05 = 1 - matriz[0][0]
    p_over15 = sum(matriz[i][j] for i in range(N) for j in range(N) if i + j > 1.5)
    p_over25 = sum(matriz[i][j] for i in range(N) for j in range(N) if i + j > 2.5)
    p_over35 = sum(matriz[i][j] for i in range(N) for j in range(N) if i + j > 3.5)
    p_btts = sum(matriz[i][j] for i in range(1, N) for j in range(1, N))

    marcadores = sorted(
        [(f"{i}-{j}", round(matriz[i][j] * 100, 2)) for i in range(N) for j in range(N)],
        key=lambda x: x[1], reverse=True
    )[:5]

    return {
        "lambda_local": round(lambda_local, 2),
        "lambda_visita": round(lambda_visita, 2),
        "goles_esperados_total": round(lambda_local + lambda_visita, 2),
        "p_gana_local": round(p_local * 100, 1),
        "p_empate": round(p_empate * 100, 1),
        "p_gana_visita": round(p_visita * 100, 1),
        "p_1x": round((p_local + p_empate) * 100, 1),
        "p_x2": round((p_empate + p_visita) * 100, 1),
        "p_12": round((p_local + p_visita) * 100, 1),
        "p_over05": round(p_over05 * 100, 1),
        "p_over15": round(p_over15 * 100, 1),
        "p_over25": round(p_over25 * 100, 1),
        "p_over35": round(p_over35 * 100, 1),
        "p_under15": round((1 - p_over15) * 100, 1),
        "p_under25": round((1 - p_over25) * 100, 1),
        "p_under35": round((1 - p_over35) * 100, 1),
        "p_btts_si": round(p_btts * 100, 1),
        "p_btts_no": round((1 - p_btts) * 100, 1),
        "top_marcadores": marcadores,
        "liga_avg_local": base_local,
        "liga_avg_visita": base_visita
    }


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
    team_map = build_team_matches(matches)
    strength = calc_strength_table(team_map, liga_avg)

    s1 = get_stats(equipo1, team_map, strength)
    s2 = get_stats(equipo2, team_map, strength)
    if not s1 or not s2:
        return jsonify({"error": "No se encontraron datos de uno o ambos equipos"})

    poisson = calcular_poisson(s1, s2, liga_avg)
    if not poisson:
        return jsonify({"error": "No se pudo calcular el modelo estadístico"})

    h2h = [m for m in s1["todos"] if m["rival"] == equipo2][-5:]

    def rivales_recientes(s):
        out = []
        for m in s["ultimos5"]:
            rs = strength.get(m["rival"], {"ataque": 1.0, "defensa": 1.0})
            out.append(f"{m['rival']} [{etiqueta_nivel(rs)}] {m['gf']}-{m['gc']} ({'Casa' if m['local'] else 'Fuera'})")
        return out

    prompt = f"""
Eres un sharp bettor profesional. INTERPRETAS probabilidades ya calculadas matemáticamente.
No calcules nada tú mismo. No inventes datos. No uses conocimiento previo sobre la reputación
histórica de los equipos: lo único válido es lo que dicen los números de abajo.

SOBRE LOS RATINGS:
Están normalizados a la media de la liga (1.00 = media exacta) y ajustados por la calidad REAL ACTUAL
de los rivales enfrentados, dando más peso a los últimos {VENTANA_RECIENTE} partidos.
Ataque > 1.00 = mete más que la media. Defensa > 1.00 = recibe más que la media (peor defensa).
El campo "Momento" compara la forma reciente contra el nivel de temporada del propio equipo.
Un club de nombre grande en estado "En crisis" NO es fuerte ahora: trátalo por sus números actuales.

=== MODELO DE POISSON (verdad matemática del partido) ===
Media de la liga: {poisson['liga_avg_local']} goles del local / {poisson['liga_avg_visita']} del visitante, en {liga_avg['partidos']} partidos

GOLES ESPERADOS:
- {s1['equipo']} (local): {poisson['lambda_local']}
- {s2['equipo']} (visitante): {poisson['lambda_visita']}
- Total: {poisson['goles_esperados_total']}

RESULTADO:
- Gana {s1['equipo']}: {poisson['p_gana_local']}%
- Empate: {poisson['p_empate']}%
- Gana {s2['equipo']}: {poisson['p_gana_visita']}%
- 1X ({s1['equipo']} no pierde): {poisson['p_1x']}%
- X2 ({s2['equipo']} no pierde): {poisson['p_x2']}%
- 12 (no hay empate): {poisson['p_12']}%

GOLES:
- Over 0.5: {poisson['p_over05']}%
- Over 1.5: {poisson['p_over15']}% | Under 1.5: {poisson['p_under15']}%
- Over 2.5: {poisson['p_over25']}% | Under 2.5: {poisson['p_under25']}%
- Over 3.5: {poisson['p_over35']}% | Under 3.5: {poisson['p_under35']}%

AMBOS ANOTAN:
- BTTS Sí: {poisson['p_btts_si']}% | BTTS No: {poisson['p_btts_no']}%

MARCADORES MÁS PROBABLES:
{chr(10).join([f"- {m[0]}: {m[1]}%" for m in poisson['top_marcadores']])}

=== {s1['equipo']} — LOCAL ===
Nivel actual: {s1['nivel']} | Momento: {s1['momento']['estado']} ({s1['momento']['nota']})
Rating ataque: {s1['rating_ataque']} (temporada {s1['rating_ataque_temporada']} → reciente {s1['rating_ataque_reciente']})
Rating defensa: {s1['rating_defensa']} (temporada {s1['rating_defensa_temporada']} → reciente {s1['rating_defensa_reciente']})
Dureza del calendario reciente: {s1['calendario']} (1.00 = media de la liga)
Como local: {s1['gana_local']}V {s1['empata_local']}E {s1['pierde_local']}D en {s1['partidos_local']} partidos
Goles en casa: {s1['avg_gf_local']} a favor / {s1['avg_gc_local']} en contra
Goles totales temporada: {s1['avg_gf']} a favor / {s1['avg_gc']} en contra
Primer tiempo: con goles {s1['ht_over05_pct']}% | ganando al descanso {s1['ht_gana_pct']}%
Últimos 5 (con el nivel real de cada rival):
{chr(10).join(['- ' + x for x in rivales_recientes(s1)])}

=== {s2['equipo']} — VISITANTE ===
Nivel actual: {s2['nivel']} | Momento: {s2['momento']['estado']} ({s2['momento']['nota']})
Rating ataque: {s2['rating_ataque']} (temporada {s2['rating_ataque_temporada']} → reciente {s2['rating_ataque_reciente']})
Rating defensa: {s2['rating_defensa']} (temporada {s2['rating_defensa_temporada']} → reciente {s2['rating_defensa_reciente']})
Dureza del calendario reciente: {s2['calendario']} (1.00 = media de la liga)
Como visitante: {s2['gana_visita']}V {s2['empata_visita']}E {s2['pierde_visita']}D en {s2['partidos_visita']} partidos
Goles fuera: {s2['avg_gf_visita']} a favor / {s2['avg_gc_visita']} en contra
Goles totales temporada: {s2['avg_gf']} a favor / {s2['avg_gc']} en contra
Primer tiempo: con goles {s2['ht_over05_pct']}% | ganando al descanso {s2['ht_gana_pct']}%
Últimos 5 (con el nivel real de cada rival):
{chr(10).join(['- ' + x for x in rivales_recientes(s2)])}

=== HEAD TO HEAD ===
{[(m['rival'], f"{m['gf']}-{m['gc']}") for m in h2h] if h2h else "Sin enfrentamientos directos en esta temporada"}

REGLAS PARA LOS PICKS:
REGLAS PARA LOS PICKS:
1. NUNCA incluyas picks por encima del 85%. Son casi certezas, las casas los pagan a cuota ridicula
   y no aportan valor. Over 0.5 goles queda PROHIBIDO salvo que baje de 85%.
2. NUNCA des dos picks que se contradicen entre si. Prohibido en el mismo analisis:
   - 1X junto con X2 (uno dice que el local no pierde, el otro que el visitante no pierde)
   - 1X junto con "gana el visitante", ni X2 junto con "gana el local"
   - 12 junto con cualquier doble oportunidad que incluya el empate
   - Over y Under de la misma linea
   - BTTS Si junto con BTTS No
   Si dos picks se pisan, deja solo el que tenga mayor probabilidad.
3. Prefiere picks INDEPENDIENTES entre si. Over 1.5, Over 2.5 y BTTS Si suelen caer juntos:
   si incluyes mas de uno de ese grupo, advierte que estan correlacionados y no son apuestas separadas.
4. Confianza Alta solo entre 65% y 85%. Media entre 55% y 64%. Baja entre 50% y 54%.
5. Nunca recomiendes un pick por debajo del 50%.
6. Da ENTRE 2 Y 5 PICKS. Si solo hay 2 o 3 que cumplan todas las reglas, da 2 o 3 y ya.
   Es mejor dar 2 picks solidos que rellenar hasta 5 con basura. No inventes picks para llenar el formato.
7. Cada pick cita el porcentaje exacto de Poisson que lo respalda.
8. Si un equipo esta "En crisis" o "A la baja", dilo y considera que es mas debil de lo que sugiere su nombre.
9. Si un equipo enfrento un calendario muy blando (calendario < 0.85), advierte que sus numeros estan inflados.
10. Menciona primer tiempo solo si algun equipo supera 60% en ht_over05_pct o ht_gana_pct.
11. Ordena los picks de mayor a menor probabilidad.
12. Si los goles esperados de Poisson contradicen los promedios de temporada de algun equipo, dilo en Factores de Riesgo.

Responde en español con este formato EXACTO:

## 📊 Lectura del Modelo
[Qué dicen los goles esperados y las probabilidades principales. Máximo 4 líneas.]

## 🔥 Estado Real de los Equipos
[Usa el campo Momento y la dureza de calendario. Señala si algún equipo está sobrevalorado o infravalorado por su nombre. Máximo 4 líneas.]

## ⚽ Análisis de Goles
[Compara Over/Under citando porcentajes. Di cuál es el escenario más probable.]

## 🔄 Forma y Contexto
[Contrasta la forma reciente con el modelo. ¿Se confirman o se contradicen?]

## 🎯 Picks Recomendados
[Entre 2 y 5 picks. Solo los que cumplan TODAS las reglas. No rellenes para llegar a 5.]

Pick 1 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Alto/Medio/Bajo] | Razón: [1 línea]
Pick 2 — [Mercado]: [Pick exacto] | Probabilidad: [X%] | Confianza: [Alto/Medio/Bajo] | Razón: [1 línea]
[Agrega Pick 3, 4 y 5 SOLO si hay material real que cumpla las reglas]

Si dos o más picks están correlacionados (caen juntos), añade esta línea al final:
⚠️ Nota: los picks [X] y [Y] están correlacionados, no cuentan como apuestas independientes.
## 🎲 Marcador Más Probable
[Top 3 de marcadores con sus porcentajes]

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