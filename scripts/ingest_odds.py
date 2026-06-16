import os
import sys
import json
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv
from supabase import create_client, Client


load_dotenv()


SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

ODDS_SPORT_KEY = os.getenv("ODDS_SPORT_KEY", "soccer_fifa_world_cup")
ODDS_REGIONS = os.getenv("ODDS_REGIONS", "eu")
ODDS_MARKETS = os.getenv("ODDS_MARKETS", "h2h")
ODDS_ODDS_FORMAT = os.getenv("ODDS_ODDS_FORMAT", "decimal")

SOURCE_NAME = "the_odds_api"


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def require_env():
    missing = []

    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")

    if not SUPABASE_SERVICE_ROLE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")

    if not ODDS_API_KEY:
        missing.append("ODDS_API_KEY")

    if missing:
        raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")


def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def create_log(supabase: Client):
    data = {
        "source": SOURCE_NAME,
        "job_type": "ingest_worldcup_odds",
        "status": "running",
        "records_inserted": 0,
        "started_at": now_iso(),
    }

    result = supabase.table("ingestion_logs").insert(data).execute()
    return result.data[0]["id"]


def finish_log(supabase: Client, log_id: str, status: str, records_inserted: int = 0, error_message: str = None):
    data = {
        "status": status,
        "records_inserted": records_inserted,
        "finished_at": now_iso(),
    }

    if error_message:
        data["error_message"] = error_message[:2000]

    supabase.table("ingestion_logs").update(data).eq("id", log_id).execute()


def fetch_odds():
    url = f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT_KEY}/odds"

    params = {
        "apiKey": ODDS_API_KEY,
        "regions": ODDS_REGIONS,
        "markets": ODDS_MARKETS,
        "oddsFormat": ODDS_ODDS_FORMAT,
        "dateFormat": "iso",
    }

    response = requests.get(url, params=params, timeout=30)

    if response.status_code != 200:
        raise RuntimeError(
            f"Error API odds: {response.status_code} - {response.text}"
        )

    remaining = response.headers.get("x-requests-remaining")
    used = response.headers.get("x-requests-used")

    print(f"API requests used: {used}")
    print(f"API requests remaining: {remaining}")

    return response.json()


def upsert_event(supabase: Client, game: dict):
    external_id = game["id"]

    event_data = {
        "external_id": external_id,
        "sport": "football",
        "competition": "world_cup_2026",
        "home_team_name": game.get("home_team") or game.get("home_team_name") or "Unknown Home",
        "away_team_name": game.get("away_team") or game.get("away_team_name") or "Unknown Away",
        "start_time": game["commence_time"],
        "status": "scheduled",
        "raw_data": game,
        "updated_at": now_iso(),
    }

    existing = (
        supabase
        .table("events")
        .select("id")
        .eq("external_id", external_id)
        .limit(1)
        .execute()
    )

    if existing.data:
        event_id = existing.data[0]["id"]
        supabase.table("events").update(event_data).eq("id", event_id).execute()
        return event_id

    inserted = supabase.table("events").insert(event_data).execute()
    return inserted.data[0]["id"]


def upsert_bookmaker(supabase: Client, bookmaker: dict):
    bookmaker_slug = bookmaker["key"]

    bookmaker_data = {
        "name": bookmaker.get("title", bookmaker_slug),
        "slug": bookmaker_slug,
    }

    existing = (
        supabase
        .table("bookmakers")
        .select("id")
        .eq("slug", bookmaker_slug)
        .limit(1)
        .execute()
    )

    if existing.data:
        return existing.data[0]["id"]

    inserted = supabase.table("bookmakers").insert(bookmaker_data).execute()
    return inserted.data[0]["id"]


def get_market_id(supabase: Client, market_key: str):
    existing = (
        supabase
        .table("markets")
        .select("id")
        .eq("slug", market_key)
        .limit(1)
        .execute()
    )

    if existing.data:
        return existing.data[0]["id"]

    title_by_market = {
        "h2h": "Match Winner",
        "totals": "Totals",
        "spreads": "Spreads",
    }

    market_data = {
        "name": title_by_market.get(market_key, market_key),
        "slug": market_key,
        "description": f"Market {market_key}",
    }

    inserted = supabase.table("markets").insert(market_data).execute()
    return inserted.data[0]["id"]


def insert_odds_snapshots(supabase: Client, event_id: str, game: dict):
    inserted_count = 0
    snapshot_time = now_iso()

    bookmakers = game.get("bookmakers", [])

    for bookmaker in bookmakers:
        bookmaker_id = upsert_bookmaker(supabase, bookmaker)

        for market in bookmaker.get("markets", []):
            market_key = market["key"]
            market_id = get_market_id(supabase, market_key)

            for outcome in market.get("outcomes", []):
                selection = outcome.get("name")
                odds = outcome.get("price")

                if not selection or not odds:
                    continue

                snapshot = {
                    "event_id": event_id,
                    "bookmaker_id": bookmaker_id,
                    "market_id": market_id,
                    "selection": selection,
                    "odds": odds,
                    "snapshot_time": snapshot_time,
                    "source": SOURCE_NAME,
                    "raw_data": {
                        "bookmaker": bookmaker,
                        "market": market,
                        "outcome": outcome,
                    },
                }

                supabase.table("odds_snapshots").insert(snapshot).execute()
                inserted_count += 1

    return inserted_count


def main():
    require_env()

    supabase = get_supabase()
    log_id = create_log(supabase)

    total_inserted = 0

    try:
        games = fetch_odds()

        print(f"Eventos recibidos: {len(games)}")

        for game in games:
            event_id = upsert_event(supabase, game)
            inserted = insert_odds_snapshots(supabase, event_id, game)
            total_inserted += inserted

        finish_log(
            supabase=supabase,
            log_id=log_id,
            status="success",
            records_inserted=total_inserted,
        )

        print(f"Ingesta completada. Odds insertadas: {total_inserted}")

    except Exception as e:
        error_message = str(e)
        finish_log(
            supabase=supabase,
            log_id=log_id,
            status="error",
            records_inserted=total_inserted,
            error_message=error_message,
        )

        print(f"Error: {error_message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
