"""
FotMob Scraper — Fetch xG, xA, defensive stats for WC2026 Fantasy players.
============================================================================

FotMob has no official API. This module uses their internal JSON endpoints
with proper session management and rate limiting.

Key endpoints (unofficial, reverse-engineered):
  Player:  GET https://www.fotmob.com/api/playerData?id={fotmob_id}
  Match:   GET https://www.fotmob.com/api/matchDetails?matchId={id}
  League:  GET https://www.fotmob.com/api/leagues?id={league_id}
  Search:  GET https://www.fotmob.com/api/searchapi/?term={name}

Strategy:
  1. Use search API to map FIFA Fantasy player names → FotMob player IDs
  2. Fetch player data for current club season stats (xG, xA, tackles, etc.)
  3. Store in player_xstats table
  
Rate limiting: 1 request per 2 seconds to be respectful.
Cache responses to avoid re-fetching.

Usage:
  python fotmob_scraper.py                    # Scrape top 100 players by price
  python fotmob_scraper.py --all              # Scrape all 1410 players (slow, ~45 min)
  python fotmob_scraper.py --player "Mbappé"  # Scrape a single player
"""

import httpx
import asyncio
import sqlite3
import json
import sys
import time
import re
from pathlib import Path
from datetime import datetime, timezone
from difflib import SequenceMatcher

from database import get_connection, init_db

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
FOTMOB_BASE = "https://www.fotmob.com/api"
RATE_LIMIT_SECONDS = 2.0   # Minimum delay between requests
CACHE_DIR = Path(__file__).parent / "cache" / "fotmob"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.fotmob.com/",
    "Origin": "https://www.fotmob.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}


# ──────────────────────────────────────────────
# HTTP CLIENT — Session + rate limiting + cache
# ──────────────────────────────────────────────
class FotMobClient:
    """HTTP client with session, rate limiting, and disk cache."""

    def __init__(self):
        self._last_request_time = 0.0
        self._client: httpx.AsyncClient | None = None
        self._request_count = 0
        self._cache_hits = 0
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            headers=HEADERS,
            timeout=30,
            follow_redirects=True,
        )
        # Warm up session by visiting homepage first
        try:
            await self._client.get("https://www.fotmob.com/", timeout=10)
        except Exception:
            pass
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    def _cache_key(self, url: str) -> Path:
        """Generate cache file path from URL."""
        # Simple hash of URL for filename
        safe_name = re.sub(r'[^\w]', '_', url.split('/api/')[-1]) + ".json"
        return CACHE_DIR / safe_name

    def _get_cached(self, url: str, max_age_hours: float = 24) -> dict | None:
        """Load cached response if fresh enough."""
        path = self._cache_key(url)
        if path.exists():
            age_hours = (time.time() - path.stat().st_mtime) / 3600
            if age_hours < max_age_hours:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    self._cache_hits += 1
                    return data
                except Exception:
                    pass
        return None

    def _save_cache(self, url: str, data: dict):
        """Save response to disk cache."""
        path = self._cache_key(url)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    async def get(self, url: str, cache_hours: float = 24) -> dict | None:
        """
        GET request with rate limiting and caching.
        Returns parsed JSON dict or None on failure.
        """
        # Check cache first
        cached = self._get_cached(url, cache_hours)
        if cached is not None:
            return cached

        # Rate limit
        elapsed = time.time() - self._last_request_time
        if elapsed < RATE_LIMIT_SECONDS:
            await asyncio.sleep(RATE_LIMIT_SECONDS - elapsed)

        # Make request
        for attempt in range(3):
            try:
                resp = await self._client.get(url)
                self._last_request_time = time.time()
                self._request_count += 1

                if resp.status_code == 200:
                    data = resp.json()
                    self._save_cache(url, data)
                    return data
                elif resp.status_code == 403:
                    print(f"    [403] Blocked by Cloudflare — waiting 10s...")
                    await asyncio.sleep(10)
                elif resp.status_code == 429:
                    print(f"    [429] Rate limited — waiting 30s...")
                    await asyncio.sleep(30)
                else:
                    print(f"    [{resp.status_code}] {url}")
                    return None
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(3)
                else:
                    print(f"    Error: {e}")
                    return None

        return None


# ──────────────────────────────────────────────
# SEARCH — Map player names to FotMob IDs
# ──────────────────────────────────────────────
def _name_similarity(a: str, b: str) -> float:
    """Fuzzy name matching score (0-1)."""
    a = a.lower().strip()
    b = b.lower().strip()
    return SequenceMatcher(None, a, b).ratio()


async def search_player(client: FotMobClient, name: str) -> dict | None:
    """
    Search FotMob for a player by name.
    Returns dict with fotmob_id, name, team, etc.
    """
    url = f"{FOTMOB_BASE}/searchapi/?term={name}"
    data = await client.get(url, cache_hours=168)  # Cache search for 7 days

    if not data:
        return None

    # Search results structure: data = [{suggestion groups}]
    # We want squad/player suggestions
    players = []
    if isinstance(data, list):
        for group in data:
            if isinstance(group, dict) and group.get("type") == "player":
                for item in group.get("suggestions", []):
                    players.append(item)
            elif isinstance(group, dict):
                # Some formats nest differently
                suggestions = group.get("suggestions", [])
                for s in suggestions:
                    if s.get("type") == "player":
                        players.append(s)
    elif isinstance(data, dict):
        # Alternative format
        for key in ("players", "squad", "player"):
            items = data.get(key, [])
            if isinstance(items, list):
                players.extend(items)

    if not players:
        return None

    # Find best match by name similarity
    best = None
    best_score = 0.0
    for p in players:
        p_name = p.get("name", p.get("text", ""))
        score = _name_similarity(name, p_name)
        if score > best_score:
            best_score = score
            best = p

    if best and best_score >= 0.5:  # At least 50% name match
        return {
            "fotmob_id": best.get("id"),
            "name": best.get("name", best.get("text")),
            "team": best.get("teamName", best.get("team")),
            "score": best_score,
        }

    return None


# ──────────────────────────────────────────────
# PLAYER DATA — Fetch detailed stats
# ──────────────────────────────────────────────
async def fetch_player_stats(client: FotMobClient, fotmob_id: int) -> dict | None:
    """
    Fetch detailed player stats from FotMob.
    Returns normalized stats dict or None.
    """
    url = f"{FOTMOB_BASE}/playerData?id={fotmob_id}"
    data = await client.get(url, cache_hours=12)  # Refresh every 12 hours

    if not data:
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
    primary_team = data.get("primaryTeam", {})
    result["team"] = primary_team.get("teamName")

    # Get position
    pos_desc = data.get("positionDescription", {})
    result["position"] = pos_desc.get("primaryPosition", {}).get("label")

    # Find season stats
    # FotMob structure: statSeasons → each season has stats per competition
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

    # Parse stats — FotMob uses a nested structure:
    # stats > [{title: "Goals", items: [{title: "Goals", stat: {value: 5}}]}]
    stats = main_tournament.get("stats", [])
    if not stats:
        # Try alternative path
        stats = data.get("stats", [])

    flat_stats = {}
    for category in stats:
        if isinstance(category, dict):
            items = category.get("items", category.get("stats", []))
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
    minutes = result.get("minutes_played", 0) or 0
    if minutes > 0:
        nineties = minutes / 90
        if nineties > 0:
            for key in ["goals", "assists", "xG", "xA", "shots", "tackles",
                        "interceptions", "chances_created", "saves"]:
                val = result.get(key, 0) or 0
                if val > 0:
                    result[f"{key}_per90"] = round(val / nineties, 2)

            # Yellow card rate
            yellows = result.get("yellow_cards", 0) or 0
            if yellows > 0:
                result["yellow_per90"] = round(yellows / nineties, 3)

    return result


# ──────────────────────────────────────────────
# UPSERT — Save stats to player_xstats table
# ──────────────────────────────────────────────
def save_player_xstats(conn: sqlite3.Connection, player_id: int, stats: dict):
    """Save fetched stats to the player_xstats table."""
    now = datetime.now(timezone.utc).isoformat()

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


# ──────────────────────────────────────────────
# MAIN — Orchestrate scraping
# ──────────────────────────────────────────────
async def scrape_fotmob(limit: int = 100, player_name: str = None):
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
            f"SELECT id, COALESCE(known_name, first_name || ' ' || last_name) as name, "
            f"position, price FROM players WHERE is_active = 1 "
            f"ORDER BY price DESC {limit_clause}"
        ).fetchall()

    players = [dict(r) for r in rows]
    total = len(players)

    if total == 0:
        print("No players found. Run pipeline.py first.")
        conn.close()
        return

    print(f"\n{'=' * 56}")
    print(f"  FotMob Scraper — {total} players to process")
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

            if existing:
                updated = existing[0]
                if updated:
                    age_hours = (time.time() - datetime.fromisoformat(updated).timestamp()) / 3600
                    if age_hours < 12:
                        print(f"cached ({age_hours:.0f}h old)")
                        skipped += 1
                        continue

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
    print(f"  Cache hits: {client._cache_hits if 'client' in dir() else 'N/A'}")
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
        print(f"  {'─' * 75}")
        for r in top_xg:
            print(f"  {r[1]:25s} {r[2] or '?':15s} {r[3]:4s} ${r[4]:<5.1f} {r[5]:6.1f} {r[6]:6.1f} {r[7]:6.1f}")

    conn.close()


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
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
    elif "--top" in args:
        idx = args.index("--top")
        n = int(args[idx + 1]) if idx + 1 < len(args) else 100
        asyncio.run(scrape_fotmob(limit=n))
    else:
        asyncio.run(scrape_fotmob(limit=100))
