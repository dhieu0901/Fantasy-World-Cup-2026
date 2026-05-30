import httpx
import asyncio
import sqlite3
import json
from datetime import datetime, timezone
from pathlib import Path

from fotmob_scraper import FotMobClient
from database import get_connection

async def fetch_world_cup_standings(client: FotMobClient) -> dict:
    """Fetch World Cup standings from FotMob API (League ID 77 is World Cup)."""
    # FotMob World Cup League ID is typically 77. If it changes for 2026, we will update it.
    url = "https://www.fotmob.com/api/leagues?id=77"
    data = await client.get(url, cache_hours=0.5) # Cache for 30 mins
    
    if not data or "overview" not in data:
        print("[Live Standings] Could not fetch league data.")
        return {}
        
    standings_data = data.get("overview", {}).get("leagueTable", [])
    if not standings_data:
        # Fallback if structure is different
        standings_data = data.get("overview", {}).get("table", [])
        
    # Group standings structure: [{"ccode": "...", "data": {"tables": [{"table": {"all": [...]}}]}}]
    # We need to extract the teams from each group.
    
    team_stats = {}
    
    # Try multiple structures as FotMob API varies
    try:
        # Structure 1: list of groups
        if isinstance(standings_data, list) and len(standings_data) > 0:
            tables = standings_data[0].get("data", {}).get("tables", [])
            for group in tables:
                group_table = group.get("table", {}).get("all", [])
                for team in group_table:
                    name = team.get("name")
                    pts = team.get("pts", 0)
                    played = team.get("played", 0)
                    gd = team.get("goalConDiff", 0)
                    rank = team.get("idx", 0)
                    team_stats[name] = {"pts": pts, "played": played, "gd": gd, "rank": rank}
                    
        # Structure 2: flat table
        elif isinstance(standings_data, dict):
            for team in standings_data.get("all", []):
                name = team.get("name")
                pts = team.get("pts", 0)
                played = team.get("played", 0)
                gd = team.get("goalConDiff", 0)
                rank = team.get("idx", 0)
                team_stats[name] = {"pts": pts, "played": played, "gd": gd, "rank": rank}
    except Exception as e:
        print(f"[Live Standings] Error parsing table: {e}")
        
    return team_stats

def determine_qualification_status(team_stats: dict) -> dict:
    """
    Determine qualification status based on points and matches played.
    In World Cup, top 2 advance.
    This is a simplistic heuristic for the pipeline.
    """
    statuses = {}
    
    # Group teams into sets of 4 (assuming standard groups of 4)
    # Since we only have a flat list here, we just use a heuristic based on points
    for name, stats in team_stats.items():
        played = stats["played"]
        pts = stats["pts"]
        
        status = "TBD"
        if played == 2:
            if pts >= 6:
                status = "QUALIFIED" # 2 wins almost always guarantees progression
            elif pts == 0:
                status = "ELIMINATED" # 2 losses almost always means elimination
            elif pts == 4:
                # 4 points is very strong, likely qualified or heavily favored
                status = "LIKELY_QUALIFIED"
            else:
                status = "MUST_WIN" # 1, 2, or 3 points means they need a result in MD3
        elif played == 3:
            if stats["rank"] <= 2:
                status = "QUALIFIED"
            else:
                status = "ELIMINATED"
                
        statuses[name] = status
        
    return statuses

async def run_live_standings_sync():
    print("[Live Standings] Starting sync...")
    conn = get_connection()
    try:
        async with FotMobClient() as client:
            team_stats = await fetch_world_cup_standings(client)
            if not team_stats:
                return {"status": "failed"}
                
            statuses = determine_qualification_status(team_stats)
            
            # Map FotMob team names to our DB names (might need fuzzy matching, but for now exact or LIKE)
            updated_count = 0
            for name, status in statuses.items():
                res = conn.execute("UPDATE squads SET qualification_status = ? WHERE name LIKE ?", (status, f"%{name}%"))
                if res.rowcount > 0:
                    updated_count += res.rowcount
                    
            conn.commit()
            print(f"[Live Standings] Updated {updated_count} squads.")
            
            # TODO: Add Injury Syncing here (e.g. fetching global news or parsing player data)
            # For this pipeline MVP, we simulate parsing a hypothetical injury feed
            print("[Live Standings] Injury feed sync not implemented yet (requires crawling 800+ profiles).")
            
            return {"status": "ok", "updated_squads": updated_count}
    finally:
        conn.close()

if __name__ == "__main__":
    asyncio.run(run_live_standings_sync())
