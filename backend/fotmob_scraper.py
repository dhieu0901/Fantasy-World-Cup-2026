"""
FotMob Scraper  Fetch xG, xA, defensive stats for WC2026 Fantasy players.
============================================================================

FotMob has no official API. This module uses their internal JSON endpoints
with proper session management and rate limiting.

Key endpoints (unofficial, reverse-engineered):
  Player:  GET https://www.fotmob.com/api/playerData?id={fotmob_id}
  Match:   GET https://www.fotmob.com/api/matchDetails?matchId={id}
  League:  GET https://www.fotmob.com/api/leagues?id={league_id}
  Search:  GET https://www.fotmob.com/api/searchapi/?term={name}

Strategy:
  1. Use search API to map FIFA Fantasy player names  FotMob player IDs
  2. Fetch player data for current club season stats (xG, xA, tackles, etc.)
  3. Store in player_xstats table
  
Rate limiting: 1 request per 2 seconds to be respectful.
Cache responses to avoid re-fetching.

Usage:
  python fotmob_scraper.py                    # Scrape top 100 players by price
  python fotmob_scraper.py --all              # Scrape all 1410 players (slow, ~45 min)
  python fotmob_scraper.py --injuries-only    # Scrape only injury status from FotMob
  python fotmob_scraper.py --schedule-smart   # Run background smart schedule
  python fotmob_scraper.py --player "Mbapp"  # Scrape a single player
"""

import httpx
import asyncio
import sqlite3
import json
import sys
import time
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher

from database import get_connection, init_db

# ----------------------------------------------
# CONFIG
# ----------------------------------------------
# FotMob uses Cloudflare, so standard requests might get blocked sometimes.
# We will use headers to mimic a browser.
FOTMOB_BASE = "https://www.fotmob.com/api"
FOTMOB_SEARCH_API = "https://apigw.fotmob.com/searchapi/suggest"
FOTMOB_BASE_URL = "https://www.fotmob.com"
RATE_LIMIT_SECONDS = 2.0   # Minimum delay between requests
CACHE_DIR = Path(__file__).parent / "cache" / "fotmob"


# ----------------------------------------------
# HTTP CLIENT  Session + rate limiting + cache
# ----------------------------------------------
class FotMobClient:
    """Async client for FotMob API with rate limiting and retries."""
    
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
        }
        self.client = httpx.AsyncClient(headers=self.headers, timeout=15.0)
        self.build_id = None
        self._last_request_time = 0.0

    async def __aenter__(self):
        await self.init_build_id()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()
        
    async def init_build_id(self):
        try:
            r = await self.client.get(FOTMOB_BASE_URL)
            if r.status_code == 200:
                match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', r.text)
                if match:
                    data = json.loads(match.group(1))
                    self.build_id = data.get('buildId')
        except Exception as e:
            print(f"Failed to fetch build ID: {e}")

    def _cache_key(self, url: str) -> Path:
        """Generate cache file path from URL."""
        safe_name = re.sub(r'[^\w]', '_', url.split('fotmob.com/')[-1]) + ".json"
        return CACHE_DIR / safe_name

    def _get_cached(self, url: str, max_age_hours: float = 0) -> dict | None:
        """Load cached response if fresh enough."""
        # Cache disabled (max_age_hours=0) to ensure we always get fresh injury data
        path = self._cache_key(url)
        if path.exists():
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if max_age_hours > 0 and age_hours < max_age_hours:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data
                except Exception:
                    pass
        return None

    def _save_cache(self, url: str, data: dict):
        """Save response to disk cache."""
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = self._cache_key(url)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    async def get(self, url: str, cache_hours: float = 24) -> dict | None:
        """GET request with rate limiting and caching."""
        cached = self._get_cached(url, cache_hours)
        if cached is not None:
            return cached

        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_SECONDS:
            await asyncio.sleep(RATE_LIMIT_SECONDS - elapsed)

        try:
            resp = await self.client.get(url)
            self._last_request_time = time.time()
            if resp.status_code == 200:
                data = resp.json()
                self._save_cache(url, data)
                return data
        except Exception as e:
            print(f"    Error: {e}")
        return None

    async def get_search(self, term: str) -> dict:
        url = f"{FOTMOB_SEARCH_API}?term={httpx.QueryParams({'term': term}).__str__().replace('term=', '')}"
        return await self.get(url, cache_hours=24)
        
    async def get_player_data(self, player_id: int) -> dict:
        if not self.build_id:
            await self.init_build_id()
        url = f"{FOTMOB_BASE_URL}/_next/data/{self.build_id}/en/players/{player_id}/xyz.json"
        return await self.get(url, cache_hours=4)


# ----------------------------------------------
# 1. Search & Resolve ID
# ----------------------------------------------
def _name_similarity(a: str, b: str) -> float:
    """Fuzzy name matching score (0-1)."""
    a = a.lower().strip()
    b = b.lower().strip()
    return SequenceMatcher(None, a, b).ratio()


async def search_player(client: FotMobClient, search_name: str) -> dict | None:
    """
    Find a player on FotMob and return their ID.
    Returns: {"fotmob_id": int, "name": str, "team": str, "score": float} or None
    """
    data = await client.get_search(search_name)
    if not data:
        return None

    # APIGW search format has squadMemberSuggest -> options
    for suggest in data.get('squadMemberSuggest', []):
        options = suggest.get('options', [])
        if options:
            first_match = options[0]['payload']
            text = options[0].get('text', '')
            name = text.split('|')[0] if '|' in text else search_name
            return {
                "fotmob_id": int(first_match['id']),
                "name": name,
                "team": first_match.get('teamName', ''),
                "score": 1.0,
            }
            
    return None


# ----------------------------------------------
# PLAYER DATA  Fetch detailed stats
# ----------------------------------------------
async def fetch_player_stats(client: FotMobClient, fotmob_id: int) -> dict | None:
    """
    Fetch detailed player stats from FotMob.
    Returns normalized stats dict or None.
    """
    raw_data = await client.get_player_data(fotmob_id)

    if not raw_data:
        return None

    try:
        data = raw_data['pageProps']['fallback'][f'player:{fotmob_id}']
        if not data:
            return None
    except KeyError:
        return None

    # Parse the complex FotMob player data structure
    result = {
        "fotmob_id": fotmob_id,
        "name": data.get("name"),
        "team": None,
        "position": None,
        "season": None,
        "competition": None,
    }

    # Get current team
    primary_team = data.get("primaryTeam") or {}
    result["team"] = primary_team.get("teamName")

    # Get position
    pos_desc = data.get("positionDescription", {})
    result["position"] = pos_desc.get("primaryPosition", {}).get("label")

    injury = data.get("injuryInformation")
    if injury:
        injury_text_lower = str(injury).lower()
        if "suspend" in injury_text_lower or "red card" in injury_text_lower:
            result["injury_status"] = "SUSPENDED"
        elif any(word in injury_text_lower for word in ["knock", "doubt", "ill", "minor", "virus", "sick", "flu", "late"]):
            result["injury_status"] = "DOUBTFUL"
        else:
            result["injury_status"] = "INJURED"
        result["injury_text"] = str(injury)
    else:
        result["injury_status"] = "OK"
        result["injury_text"] = None

    # Find season stats
    # FotMob structure: statSeasons  each season has stats per competition
    stat_seasons = data.get("statSeasons", [])

    if not stat_seasons:
        return result

    # Get the latest/current season
    latest_season = stat_seasons[0] if stat_seasons else {}
    result["season"] = latest_season.get("seasonName")

    # Get primary competition stats (usually the league the player is in)
    tournaments = latest_season.get("tournaments", [])
    if not tournaments:
        # Try alternative structures
        stats_section = data.get("mainLeague", {})
        if stats_section:
            tournaments = [stats_section]

    if not tournaments:
        return result

    # Usually first tournament is the main league
    main_tournament = tournaments[0]
    result["competition"] = main_tournament.get("name", main_tournament.get("tournamentName"))

    # Parse stats  FotMob uses a nested structure:
    # stats > [{title: "Goals", items: [{title: "Goals", stat: {value: 5}}]}]
    stats = main_tournament.get("stats") or data.get("stats") or []

    flat_stats = {}
    for category in stats:
        if isinstance(category, dict):
            items = category.get("items") or category.get("stats") or []
            for item in items:
                if isinstance(item, dict):
                    title = item.get("title", item.get("key", "")).lower().replace(" ", "_")
                    stat_obj = item.get("stat", item.get("value", {}))
                    if isinstance(stat_obj, dict):
                        value = stat_obj.get("value", 0)
                    else:
                        value = stat_obj
                    if value is not None:
                        flat_stats[title] = value

    # Map FotMob stat names to our schema
    stat_mapping = {
        "matches_played": ["matches", "apps", "appearances", "matches_played", "games"],
        "minutes_played": ["minutes_played", "minutes", "mins"],
        "goals": ["goals", "goal", "goals_scored"],
        "assists": ["assists", "assist", "goal_assists"],
        "xG": ["expected_goals_(xg)", "xg", "expected_goals", "xg_total"],
        "xA": ["expected_assists_(xa)", "xa", "expected_assists"],
        "xG_per90": ["xg_per_90", "xg/90"],
        "xA_per90": ["xa_per_90", "xa/90"],
        "shots": ["total_shots", "shots", "shots_total"],
        "shots_on_target": ["shots_on_target", "on_target"],
        "tackles": ["tackles_won", "tackles", "tackles_total"],
        "interceptions": ["interceptions", "interception"],
        "clearances": ["clearances", "clearance"],
        "chances_created": ["chances_created", "key_passes", "big_chances_created"],
        "passes_completed": ["accurate_passes", "passes_completed"],
        "pass_accuracy": ["pass_accuracy", "accurate_passes_%"],
        "saves": ["saves", "save"],
        "clean_sheets": ["clean_sheets", "clean_sheet"],
        "goals_conceded": ["goals_conceded", "goals_against"],
        "yellow_cards": ["yellow_cards", "yellows"],
        "red_cards": ["red_cards", "reds"],
        "rating": ["fotmob_rating", "rating", "avg_rating", "average_rating"],
    }

    for our_key, fotmob_keys in stat_mapping.items():
        for fk in fotmob_keys:
            if fk in flat_stats:
                result[our_key] = flat_stats[fk]
                break

    # Calculate per-90 stats if we have minutes
    try:
        minutes = float(result.get("minutes_played", 0) or 0)
    except ValueError:
        minutes = 0.0

    if minutes > 0:
        nineties = minutes / 90.0
        if nineties > 0:
            for key in ["goals", "assists", "xG", "xA", "shots", "tackles",
                        "interceptions", "chances_created", "saves"]:
                try:
                    val = float(result.get(key, 0) or 0)
                except ValueError:
                    val = 0.0
                if val > 0:
                    result[f"{key}_per90"] = round(val / nineties, 2)

            # Yellow card rate
            try:
                yellows = float(result.get("yellow_cards", 0) or 0)
            except ValueError:
                yellows = 0.0
            if yellows > 0:
                result["yellow_per90"] = round(yellows / nineties, 3)

    return result


# ----------------------------------------------
# UPSERT  Save stats to player_xstats table
# ----------------------------------------------
def save_player_xstats(conn: sqlite3.Connection, player_id: int, stats: dict):
    now = datetime.now(timezone.utc).isoformat()
    if "injury_status" in stats:
        conn.execute("UPDATE players SET injury_status = ?, injury_text = ?, updated_at = ? WHERE id = ?", (stats["injury_status"], stats.get("injury_text"), now, player_id))
    """Save fetched stats to the player_xstats table."""

    conn.execute("""
        INSERT INTO player_xstats (
            player_id, source, season, competition,
            matches_played, minutes_played, goals, assists,
            xG, xA, xG_per90, xA_per90,
            shots, shots_on_target, shots_per90,
            tackles, tackles_per90, interceptions, clearances,
            chances_created, chances_created_per90,
            passes_completed, pass_accuracy,
            saves, saves_per90, clean_sheets, goals_conceded, xGC,
            yellow_cards, red_cards, yellow_per90,
            rating, fotmob_id, sofascore_id,
            updated_at
        ) VALUES (
            ?, 'fotmob', ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?,
            ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?, ?,
            ?
        )
        ON CONFLICT(player_id, source, competition) DO UPDATE SET
            season = excluded.season,
            matches_played = excluded.matches_played,
            minutes_played = excluded.minutes_played,
            goals = excluded.goals,
            assists = excluded.assists,
            xG = excluded.xG,
            xA = excluded.xA,
            xG_per90 = excluded.xG_per90,
            xA_per90 = excluded.xA_per90,
            shots = excluded.shots,
            shots_on_target = excluded.shots_on_target,
            shots_per90 = excluded.shots_per90,
            tackles = excluded.tackles,
            tackles_per90 = excluded.tackles_per90,
            interceptions = excluded.interceptions,
            clearances = excluded.clearances,
            chances_created = excluded.chances_created,
            chances_created_per90 = excluded.chances_created_per90,
            passes_completed = excluded.passes_completed,
            pass_accuracy = excluded.pass_accuracy,
            saves = excluded.saves,
            saves_per90 = excluded.saves_per90,
            clean_sheets = excluded.clean_sheets,
            goals_conceded = excluded.goals_conceded,
            xGC = excluded.xGC,
            yellow_cards = excluded.yellow_cards,
            red_cards = excluded.red_cards,
            yellow_per90 = excluded.yellow_per90,
            rating = excluded.rating,
            fotmob_id = excluded.fotmob_id,
            updated_at = excluded.updated_at
    """, (
        player_id,
        stats.get("season"), stats.get("competition"),
        stats.get("matches_played", 0), stats.get("minutes_played", 0),
        stats.get("goals", 0), stats.get("assists", 0),
        stats.get("xG", 0), stats.get("xA", 0),
        stats.get("xG_per90", 0), stats.get("xA_per90", 0),
        stats.get("shots", 0), stats.get("shots_on_target", 0), stats.get("shots_per90", 0),
        stats.get("tackles", 0), stats.get("tackles_per90", 0),
        stats.get("interceptions", 0), stats.get("clearances", 0),
        stats.get("chances_created", 0), stats.get("chances_created_per90", 0),
        stats.get("passes_completed", 0), stats.get("pass_accuracy", 0),
        stats.get("saves", 0), stats.get("saves_per90", 0),
        stats.get("clean_sheets", 0), stats.get("goals_conceded", 0), stats.get("xGC", 0),
        stats.get("yellow_cards", 0), stats.get("red_cards", 0), stats.get("yellow_per90", 0),
        stats.get("rating", 0), stats.get("fotmob_id"),
        None,  # sofascore_id
        now,
    ))
    conn.commit()


# ----------------------------------------------
# MAIN  Orchestrate scraping
# ----------------------------------------------
async def scrape_fotmob(limit: int = 100, player_name: str = None, injuries_only: bool = False):
    """
    Main scraping pipeline.
    
    Args:
        limit: Number of top players (by price) to scrape. -1 for all.
        player_name: If set, scrape only this player.
    """
    conn = get_connection()
    init_db(conn)

    # Get players to scrape
    if player_name:
        rows = conn.execute(
            "SELECT id, COALESCE(known_name, first_name || ' ' || last_name) as name, "
            "position, price FROM players WHERE is_active = 1 "
            "AND (known_name LIKE ? OR first_name || ' ' || last_name LIKE ?) "
            "ORDER BY price DESC LIMIT 5",
            (f"%{player_name}%", f"%{player_name}%")
        ).fetchall()
    else:
        limit_clause = f"LIMIT {limit}" if limit > 0 else ""
        rows = conn.execute(
            f"SELECT p.id, COALESCE(p.known_name, p.first_name || ' ' || p.last_name) as name, "
            f"p.position, p.price "
            f"FROM players p "
            f"LEFT JOIN squads s ON p.squad_id = s.id "
            f"WHERE p.is_active = 1 "
            f"ORDER BY "
            f"  CASE "
            f"    WHEN s.abbr IN ('FRA', 'BRA', 'ARG', 'ENG', 'GER') THEN 1 "
            f"    WHEN s.abbr IN ('NED', 'BEL', 'URU', 'COL', 'JPN', 'ESP', 'POR') THEN 2 "
            f"    ELSE 3 "
            f"  END ASC, "
            f"  p.percent_selected DESC, "
            f"  p.price DESC "
            f"{limit_clause}"
        ).fetchall()

    players = [dict(r) for r in rows]
    total = len(players)

    if total == 0:
        print("No players found. Run pipeline.py first.")
        conn.close()
        return

    print(f"\n{'=' * 56}")
    print(f"  FotMob Scraper  {total} players to process")
    print(f"  Est. time: ~{total * RATE_LIMIT_SECONDS / 60:.0f} min (with rate limiting)")
    print(f"{'=' * 56}\n")

    success = 0
    failed = 0
    skipped = 0

    async with FotMobClient() as client:
        for i, player in enumerate(players, 1):
            name = player["name"]
            pid = player["id"]
            pos = player["position"]
            price = player["price"]

            print(f"  [{i}/{total}] {name} ({pos}, ${price}m)...", end=" ", flush=True)

            # Check if we already have recent stats
            existing = conn.execute(
                "SELECT updated_at FROM player_xstats WHERE player_id = ? AND source = 'fotmob'",
                (pid,)
            ).fetchone()

            # Removed DB cache check to ensure we always fetch fresh injury data


            # Step 1: Search for player on FotMob
            search_result = await search_player(client, name)
            if not search_result:
                print("not found on FotMob")
                failed += 1
                continue

            fotmob_id = search_result["fotmob_id"]
            match_score = search_result["score"]

            # Step 2: Fetch player stats
            stats = await fetch_player_stats(client, fotmob_id)
            if not stats:
                print(f"no stats (FotMob ID: {fotmob_id})")
                failed += 1
                continue

            # Step 3: Save to database
            stats["fotmob_id"] = fotmob_id
            save_player_xstats(conn, pid, stats)

            xg = stats.get("xG", 0) or 0
            xa = stats.get("xA", 0) or 0
            rating = stats.get("rating", 0) or 0
            comp = stats.get("competition", "?")

            print(f"xG={xg:.1f} xA={xa:.1f} rating={rating:.1f} ({comp}) "
                  f"[match:{match_score:.0%}]")
            success += 1

    # Summary
    print(f"\n{'=' * 56}")
    print(f"  Done: {success} scraped | {failed} failed | {skipped} cached")
    print(f"{'=' * 56}\n")

    # Show top players by xG
    top_xg = conn.execute("""
        SELECT p.id, COALESCE(p.known_name, p.first_name || ' ' || p.last_name) as name,
               s.name as team, p.position, p.price, x.xG, x.xA, x.rating, x.competition
        FROM player_xstats x
        JOIN players p ON x.player_id = p.id
        LEFT JOIN squads s ON p.squad_id = s.id
        WHERE x.source = 'fotmob' AND x.xG > 0
        ORDER BY x.xG DESC LIMIT 15
    """).fetchall()

    if top_xg:
        print("  Top 15 by xG (current club season):")
        print(f"  {'Name':25s} {'Team':15s} {'Pos':4s} {'Price':6s} {'xG':6s} {'xA':6s} {'Rating':6s}")
        print(f"  {'-' * 75}")
        for r in top_xg:
            print(f"  {r[1]:25s} {r[2] or '?':15s} {r[3]:4s} ${r[4]:<5.1f} {r[5]:6.1f} {r[6]:6.1f} {r[7]:6.1f}")

    conn.close()


# ----------------------------------------------
# CLI
# ----------------------------------------------

async def run_smart_schedule():
    print(" Starting smart FotMob scraper schedule (Midnight + Pre-match).")
    while True:
        now = datetime.now(timezone.utc)
        next_runs = []
        target_midnight = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if target_midnight < now:
            target_midnight += timedelta(days=1)
        next_runs.append(target_midnight)
        
        try:
            conn = get_connection()
            fixtures = conn.execute("SELECT match_date FROM fixtures WHERE status != 'completed'").fetchall()
            conn.close()
            
            daily_first_matches = {}
            for (match_date_str,) in fixtures:
                if not match_date_str: continue
                match_dt = datetime.fromisoformat(match_date_str).astimezone(timezone.utc)
                day_str = match_dt.strftime('%Y-%m-%d')
                if day_str not in daily_first_matches or match_dt < daily_first_matches[day_str]:
                    daily_first_matches[day_str] = match_dt
                    
            for day_str, first_match_dt in daily_first_matches.items():
                run_dt = first_match_dt - datetime.timedelta(hours=2)
                if run_dt > now:
                    next_runs.append(run_dt)
        except Exception as e:
            print(f"Failed to fetch schedule from DB: {e}")
            
        next_runs.sort()
        target = next_runs[0]
        
        sleep_seconds = (target - now).total_seconds()
        print(f"\n Next run at {target.strftime('%Y-%m-%d %H:%M:%S %Z')} (sleeping for {sleep_seconds/3600:.2f} hours)...")
        await asyncio.sleep(sleep_seconds)
        
        try:
            print(f"\n--- Running scheduled FotMob scrape at {datetime.now(timezone.utc)} ---")
            await scrape_fotmob(limit=-1)
        except Exception as e:
            print(f"Scheduled run failed: {e}")

if __name__ == "__main__":
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print("""
Usage: python fotmob_scraper.py [OPTIONS]

Options:
  (no args)           Scrape top 100 players by price
  --all               Scrape all players (slow, ~45 min)
  --top N             Scrape top N players by price
  --player "Name"     Scrape a specific player
  --help, -h          Show this help
        """)
        sys.exit(0)

    if "--player" in args:
        idx = args.index("--player")
        name = args[idx + 1] if idx + 1 < len(args) else ""
        asyncio.run(scrape_fotmob(player_name=name))
    elif "--all" in args:
        asyncio.run(scrape_fotmob(limit=-1))
    elif "--injuries-only" in args:
        asyncio.run(scrape_fotmob(limit=-1, injuries_only=True))
    elif "--schedule-smart" in args:
        asyncio.run(run_smart_schedule())
    elif "--top" in args:
        idx = args.index("--top")
        n = int(args[idx + 1]) if idx + 1 < len(args) else 100
        asyncio.run(scrape_fotmob(limit=n))
    else:
        asyncio.run(scrape_fotmob(limit=100))
