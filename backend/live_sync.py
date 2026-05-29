import httpx
import asyncio
import sqlite3
import json
from datetime import datetime, timezone
import time

from database import get_connection
from fotmob_scraper import FotMobClient, search_player
from rules import calculate_simple_xpts, SCORING_GK, SCORING_DEF, SCORING_MID, SCORING_FWD, SCORING_ALL

async def fetch_live_matches(client: FotMobClient, date_str: str = None) -> list:
    """Fetch all matches for a given date (YYYYMMDD). Returns list of match IDs for World Cup."""
    if not date_str:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        
    url = f"https://www.fotmob.com/api/matches?date={date_str}"
    data = await client.get(url, cache_hours=0.1)  # Cache for 6 mins
    
    if not data or "leagues" not in data:
        return []
        
    match_ids = []
    for league in data["leagues"]:
        # League 77 is World Cup (can vary, we check by name or just fetch all international matches for now)
        # For this logic, let's just grab all matches in "World Cup" or "International"
        league_name = league.get("name", "").lower()
        if "world cup" in league_name or "international" in league_name or "euro" in league_name or "copa" in league_name:
            for match in league.get("matches", []):
                match_ids.append(match["id"])
                
    return match_ids

def parse_player_match_stats(match_data: dict) -> dict:
    """Extract player stats from match details JSON."""
    stats = {}
    content = match_data.get("content", {})
    lineup = content.get("lineup", {})
    
    teams = lineup.get("lineup", [])
    for team in teams:
        # Team can have starters and bench
        all_players = []
        for row in team.get("players", []):
            for p in row:
                all_players.append(p)
        for p in team.get("bench", []):
            all_players.append(p)
            
        for p in all_players:
            pid = p.get("id")
            if not pid: continue
            
            p_stats = {}
            # FotMob puts stats in a list of dicts: [{"key": "minutes_played", "value": 90}, ...]
            raw_stats = p.get("stats", [])
            for st in raw_stats:
                key = st.get("key")
                val = st.get("value")
                if key and val is not None:
                    p_stats[key] = val
                    
            stats[pid] = {
                "fotmob_id": pid,
                "name": p.get("name", {}).get("fullName", p.get("name", "")),
                "minutes_played": p_stats.get("minutes_played", 0),
                "goals": p_stats.get("goals", 0),
                "assists": p_stats.get("assists", 0),
                "yellow_cards": p_stats.get("yellow_cards", 0),
                "red_cards": p_stats.get("red_cards", 0),
                "saves": p_stats.get("saves", 0),
                "goals_conceded": p_stats.get("goals_conceded", 0),
                "clean_sheet": p_stats.get("clean_sheet", False) or p_stats.get("goals_conceded") == 0 and p_stats.get("minutes_played", 0) >= 60,
                "own_goals": p_stats.get("own_goals", 0),
                "penalties_saved": p_stats.get("penalties_saved", 0),
                "penalties_missed": p_stats.get("penalties_missed", 0)
            }
            
    return stats

def calculate_actual_points(pos: str, stats: dict) -> int:
    """Calculate Fantasy Points based on actual match stats."""
    pts = 0
    mins = stats.get("minutes_played", 0)
    
    if mins == 0:
        return 0
        
    # Minutes
    if mins >= 60:
        pts += 2
    elif mins > 0:
        pts += 1
        
    # Yellow/Red cards
    pts -= stats.get("yellow_cards", 0) * 1
    pts -= stats.get("red_cards", 0) * 3
    
    # Own goals
    pts -= stats.get("own_goals", 0) * 2
    
    # Position specific
    goals = stats.get("goals", 0)
    assists = stats.get("assists", 0)
    
    if pos == "GK":
        pts += goals * SCORING_GK["goal"]
        pts += assists * SCORING_ALL["assist"]
        if stats.get("clean_sheet"): pts += SCORING_GK["clean_sheet"]
        pts += (stats.get("saves", 0) // 3) * 1
        pts -= (stats.get("goals_conceded", 0) // 2) * 1
        pts += stats.get("penalties_saved", 0) * 5
    elif pos == "DEF":
        pts += goals * SCORING_DEF["goal"]
        pts += assists * SCORING_ALL["assist"]
        if stats.get("clean_sheet"): pts += SCORING_DEF["clean_sheet"]
        pts -= (stats.get("goals_conceded", 0) // 2) * 1
    elif pos == "MID":
        pts += goals * SCORING_MID["goal"]
        pts += assists * SCORING_ALL["assist"]
        if stats.get("clean_sheet"): pts += SCORING_MID["clean_sheet"]
    elif pos == "FWD":
        pts += goals * SCORING_FWD["goal"]
        pts += assists * SCORING_ALL["assist"]
        
    pts -= stats.get("penalties_missed", 0) * 2
    return pts

async def run_live_sync():
    """Main live sync function to be called from API or cron."""
    print("[Live Sync] Starting...")
    conn = get_connection()
    
    try:
        # 1. Get all players that have a fotmob_id (from player_xstats)
        # Because we need fotmob_id to map match stats back to our DB
        rows = conn.execute("SELECT p.id, p.position, x.fotmob_id FROM players p JOIN player_xstats x ON p.id = x.player_id WHERE x.source = 'fotmob'").fetchall()
        fotmob_to_db = {r["fotmob_id"]: {"id": r["id"], "position": r["position"]} for r in rows}
        
        async with FotMobClient() as client:
            # 2. Get active matches
            match_ids = await fetch_live_matches(client)
            if not match_ids:
                print("[Live Sync] No active/recent World Cup matches found today.")
                return {"status": "no_matches"}
                
            print(f"[Live Sync] Found {len(match_ids)} matches. Fetching details...")
            
            # 3. Process each match
            updated_count = 0
            for mid in match_ids:
                url = f"https://www.fotmob.com/api/matchDetails?matchId={mid}"
                mdata = await client.get(url, cache_hours=0.05) # 3 mins cache
                if not mdata: continue
                
                # Check match status
                status_obj = mdata.get("general", {}).get("matchTime", {})
                is_finished = status_obj.get("finished", False)
                # status could be 'playing' or 'finished'
                db_status = 'finished' if is_finished else 'playing'
                
                player_stats = parse_player_match_stats(mdata)
                
                # 4. Map to DB players and calculate points
                for f_id, stats in player_stats.items():
                    if f_id in fotmob_to_db:
                        db_p = fotmob_to_db[f_id]
                        pts = calculate_actual_points(db_p["position"], stats)
                        
                        # Update DB
                        conn.execute(
                            "UPDATE players SET mock_points = ?, mock_match_status = ? WHERE id = ?",
                            (pts, db_status, db_p["id"])
                        )
                        updated_count += 1
                        
            conn.commit()
            print(f"[Live Sync] Complete! Updated live points for {updated_count} players.")
            return {"status": "ok", "updated_players": updated_count, "matches": len(match_ids)}
            
    finally:
        conn.close()

if __name__ == "__main__":
    asyncio.run(run_live_sync())
