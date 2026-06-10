import os
import sqlite3
import requests
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Team name normalization: map whatever The Odds API returns to the canonical
# names used in the schedule.
# ---------------------------------------------------------------------------
NAME_MAP = {
    # Group A
    "Mexico": "Mexico",
    "South Africa": "South Africa",
    "Korea Republic": "South Korea",
    "South Korea": "South Korea",
    "Czech Republic": "Czechia",
    "Czechia": "Czechia",

    # Group B
    "Canada": "Canada",
    "Bosnia & Herzegovina": "Bosnia-Herzegovina",
    "Bosnia and Herzegovina": "Bosnia-Herzegovina",
    "Bosnia-Herzegovina": "Bosnia-Herzegovina",
    "Qatar": "Qatar",
    "Switzerland": "Switzerland",

    # Group C
    "Brazil": "Brazil",
    "Morocco": "Morocco",
    "Haiti": "Haiti",
    "Scotland": "Scotland",

    # Group D
    "United States": "United States",
    "USA": "United States",
    "Paraguay": "Paraguay",
    "Australia": "Australia",
    "Turkey": "Turkiye",
    "Turkiye": "Turkiye",
    "Türkiye": "Turkiye",

    # Group E
    "Germany": "Germany",
    "Curacao": "Curacao",
    "Curaçao": "Curacao",
    "Ivory Coast": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Côte d'Ivoire": "Ivory Coast",
    "Ecuador": "Ecuador",

    # Group F
    "Netherlands": "Netherlands",
    "Japan": "Japan",
    "Sweden": "Sweden",
    "Tunisia": "Tunisia",

    # Group G
    "Belgium": "Belgium",
    "Egypt": "Egypt",
    "Iran": "Iran",
    "New Zealand": "New Zealand",

    # Group H
    "Spain": "Spain",
    "Cape Verde": "Cape Verde",
    "Cabo Verde": "Cape Verde",
    "Saudi Arabia": "Saudi Arabia",
    "Uruguay": "Uruguay",

    # Group I
    "France": "France",
    "Senegal": "Senegal",
    "Iraq": "Iraq",
    "Norway": "Norway",

    # Group J
    "Argentina": "Argentina",
    "Algeria": "Algeria",
    "Austria": "Austria",
    "Jordan": "Jordan",

    # Group K
    "Portugal": "Portugal",
    "DR Congo": "DR Congo",
    "Congo DR": "DR Congo",
    "Democratic Republic of the Congo": "DR Congo",
    "Uzbekistan": "Uzbekistan",
    "Colombia": "Colombia",

    # Group L
    "England": "England",
    "Croatia": "Croatia",
    "Ghana": "Ghana",
    "Panama": "Panama",
}


def normalize(name: str) -> str:
    return NAME_MAP.get(name, name)


def american_to_implied(odds: int) -> float:
    """Convert American odds integer to implied probability (0–1)."""
    if odds >= 0:
        return 100 / (odds + 100)
    else:
        return abs(odds) / (abs(odds) + 100)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            team        TEXT    NOT NULL,
            odds_american INTEGER NOT NULL,
            implied_prob  REAL  NOT NULL,
            fetched_at  TEXT    NOT NULL
        )
    """)
    conn.commit()


def fetch_and_store(api_key: str, db_path: str = "odds.db") -> None:
    url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds"
    params = {
        "apiKey": api_key,
        "regions": "us",
        "markets": "outrights",
        "oddsFormat": "american",
    }

    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    remaining = resp.headers.get("x-requests-remaining", "?")
    used = resp.headers.get("x-requests-used", "?")
    print(f"API quota — used: {used}, remaining: {remaining}")

    # The outrights endpoint returns a list of events; for a tournament futures
    # market there is typically one event whose outcomes are the teams.
    team_odds: dict[str, int] = {}
    for event in data:
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "outrights":
                    continue
                for outcome in market.get("outcomes", []):
                    raw_name = outcome.get("name", "")
                    canonical = normalize(raw_name)
                    price = int(outcome["price"])
                    # Keep the best (lowest) odds seen across bookmakers so
                    # implied probs reflect the sharpest available line.
                    if canonical not in team_odds or price < team_odds[canonical]:
                        team_odds[canonical] = price

    if not team_odds:
        print("WARNING: no outright odds found in API response.")
        return

    fetched_at = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(db_path)
    try:
        init_db(conn)
        rows = [
            (team, odds, american_to_implied(odds), fetched_at)
            for team, odds in sorted(team_odds.items())
        ]
        conn.executemany(
            "INSERT INTO odds_snapshots (team, odds_american, implied_prob, fetched_at) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        print(f"Stored {len(rows)} team odds at {fetched_at}")
        for team, odds, prob, _ in sorted(rows, key=lambda r: -r[2]):
            sign = "+" if odds >= 0 else ""
            print(f"  {team:<30} {sign}{odds:>7}   {prob*100:5.2f}%")
    finally:
        conn.close()


if __name__ == "__main__":
    key = os.environ.get("ODDS_API_KEY")
    if not key:
        raise SystemExit("ERROR: ODDS_API_KEY environment variable not set.")
    fetch_and_store(key)
