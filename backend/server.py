"""
FastAPI Server — REST API for WC2026 Fantasy Dashboard
========================================================

Endpoints:
  GET  /api/players              → All active players (filterable)
  GET  /api/players/{id}         → Single player details
  GET  /api/squads               → All teams with group info
  GET  /api/rounds               → Schedule + results
  GET  /api/fixtures             → All fixtures
  GET  /api/fixtures/{squad_id}  → Fixtures for a specific team
  GET  /api/stats                → Database summary stats
  GET  /api/sync-history         → Pipeline run history
  POST /api/optimize             → Run squad optimizer
  POST /api/sync                 → Trigger data pipeline re-sync

Usage:
  uvicorn server:app --reload --port 8000
  → http://localhost:8000/docs  (Swagger UI)
"""

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional
import asyncio
import unicodedata

from database import get_connection, init_db, get_all_players, get_player_by_id, \
    get_all_squads, get_all_rounds, get_fixtures_for_squad, get_stats_summary, \
    get_sync_history, get_squad_player_counts
from optimizer import optimize_squad, TEAM_STRENGTH
from rules import get_scoring_rules, validate_squad, calculate_xpts_from_db, \
    TOURNAMENT, SQUAD_RULES, TRANSFER_RULES, BOOSTERS, SCORING_ALL, \
    SCORING_GK, SCORING_DEF, SCORING_MID, SCORING_FWD, SCORING_BONUS

# ──────────────────────────────────────────────
# APP SETUP
# ──────────────────────────────────────────────

app = FastAPI(
    title="WC2026 Fantasy API",
    description="Fantasy World Cup 2026 Analytics & Optimization API",
    version="1.0.0",
)

# CORS — allow React dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────
# MODELS (Pydantic)
# ──────────────────────────────────────────────

class OptimizeRequest(BaseModel):
    stage: str = Field(default="GROUP_MD1", description="Tournament stage")
    preset: str = Field(default="default", description="Optimization preset: default, value, safe, risky, template")
    chip: str = Field(default="none", description="Booster chip to apply (none, 12th_man, max_captain, wildcard, etc)")
    locked_in: list[int] = Field(default=[], description="Player IDs that must be in the squad")
    locked_out: list[int] = Field(default=[], description="Player IDs to exclude")
    use_lp: bool = Field(default=True, description="Use LP solver (True) or greedy (False)")
    current_squad: Optional[list[int]] = Field(default=None, description="List of 15 player IDs in the current squad for transfer calc")
    free_transfers: int = Field(default=2, description="Number of free transfers available")


class ValidateSquadRequest(BaseModel):
    player_ids: list[int] = Field(..., description="List of 15 player IDs")
    stage: str = Field(default="GROUP_MD1")


# ──────────────────────────────────────────────
# ENDPOINTS — Players
# ──────────────────────────────────────────────

@app.get("/api/players")
def api_get_players(
    position: Optional[str] = Query(None, description="Filter by position: GK, DEF, MID, FWD"),
    squad_id: Optional[int] = Query(None, description="Filter by team/squad ID"),
    sort_by: str = Query("total_points", description="Sort by: total_points, price, avg_points, form, percent_selected"),
    sort_desc: bool = Query(True, description="Sort descending"),
    limit: Optional[int] = Query(None, description="Limit number of results"),
    search: Optional[str] = Query(None, description="Search by player name"),
    min_price: Optional[float] = Query(None, description="Minimum price filter"),
    max_price: Optional[float] = Query(None, description="Maximum price filter"),
):
    """Get all active players with optional filters."""
    conn = get_connection()
    try:
        # When searching, don't limit SQL query — limit AFTER filtering
        sql_limit = None if search else limit
        players = get_all_players(conn, position=position, squad_id=squad_id,
                                  sort_by=sort_by, sort_desc=sort_desc, limit=sql_limit)

        # Apply text search filter (with Unicode normalization for diacritics)
        if search:
            def _strip_diacritics(text: str) -> str:
                """Normalize 'Mbappé' → 'mbappe' for matching."""
                nfkd = unicodedata.normalize("NFKD", text.lower())
                return "".join(c for c in nfkd if not unicodedata.combining(c))

            search_norm = _strip_diacritics(search)
            players = [
                p for p in players
                if search_norm in _strip_diacritics(p.get("known_name") or "")
                or search_norm in _strip_diacritics(p.get("first_name") or "")
                or search_norm in _strip_diacritics(p.get("last_name") or "")
                or search_norm in _strip_diacritics(
                    f"{p.get('first_name', '')} {p.get('last_name', '')}")
            ]

        # Apply price filters
        if min_price is not None:
            players = [p for p in players if p.get("price", 0) >= min_price]
        if max_price is not None:
            players = [p for p in players if p.get("price", 0) <= max_price]

        # Load fixtures to find next opponent and date
        import json
        from pathlib import Path
        fixtures_path = Path(__file__).parent.parent / "fixtures" / "matchday_1.json"
        opp_map = {}
        date_map = {}
        if fixtures_path.exists():
            squad_names = {row["name"]: row["abbr"] for row in conn.execute("SELECT name, abbr FROM squads")}
            with open(fixtures_path, 'r', encoding='utf-8') as f:
                fixtures = json.load(f)
                for match in fixtures:
                    t1 = squad_names.get(match["team_1"])
                    t2 = squad_names.get(match["team_2"])
                    match_date_str = match.get("date", "")
                    if t1 and t2:
                        opp_map[t1] = t2
                        opp_map[t2] = t1
                        date_map[t1] = match_date_str
                        date_map[t2] = match_date_str

        # Add display_name, projected_pts, and next_opponent
        from rules import calculate_xpts_from_db
        for p in players:
            p["display_name"] = p.get("known_name") or f"{p.get('first_name', '')} {p.get('last_name', '')}"
            p["next_opponent"] = opp_map.get(p.get("team_abbr", ""), "")
            p["next_match_date"] = date_map.get(p.get("team_abbr", ""), "")
            xpts_data = calculate_xpts_from_db(
                player_id=p["id"],
                position=p.get("position", "MID"),
                price=p.get("price", 4.0),
                percent_selected=p.get("percent_selected", 0.0),
                team_strength=TEAM_STRENGTH.get(p.get("team_abbr", ""), 0.5),
                conn=conn
            )
            p["projected_pts"] = xpts_data.get("xPts", 2.0)

        # Apply limit AFTER all Python-side filters
        if limit and search:
            players = players[:limit]

        return {
            "count": len(players),
            "players": players,
        }
    finally:
        conn.close()


@app.get("/api/players/{player_id}")
def api_get_player(player_id: int):
    """Get detailed info for a single player, including xPts breakdown."""
    conn = get_connection()
    try:
        player = get_player_by_id(conn, player_id)
        if not player:
            raise HTTPException(status_code=404, detail="Player not found")

        player["display_name"] = player.get("known_name") or \
            f"{player.get('first_name', '')} {player.get('last_name', '')}"

        # Get xPts with full breakdown
        team_str = TEAM_STRENGTH.get(player.get("team_abbr", ""), 0.5)
        xpts_result = calculate_xpts_from_db(
            player_id=player_id,
            position=player["position"],
            price=player["price"],
            percent_selected=player.get("percent_selected", 50),
            team_strength=team_str,
            conn=conn,
        )
        player["xpts_breakdown"] = xpts_result

        # Get price history
        price_history = conn.execute(
            "SELECT old_price, new_price, changed_at FROM price_history "
            "WHERE player_id = ? ORDER BY changed_at DESC LIMIT 30",
            (player_id,)
        ).fetchall()
        player["price_history"] = [dict(r) for r in price_history]

        # Get round points
        round_pts = conn.execute(
            "SELECT round_id, points FROM player_round_points "
            "WHERE player_id = ? ORDER BY round_id",
            (player_id,)
        ).fetchall()
        player["round_points_detail"] = [dict(r) for r in round_pts]

        # Get xstats if available
        xstats = conn.execute(
            "SELECT * FROM player_xstats WHERE player_id = ? LIMIT 1",
            (player_id,)
        ).fetchone()
        if xstats:
            player["xstats"] = dict(xstats)

        return player
    finally:
        conn.close()


# ──────────────────────────────────────────────
# ENDPOINTS — Squads & Fixtures
# ──────────────────────────────────────────────

@app.get("/api/squads")
def api_get_squads():
    """Get all teams/squads with group info and player counts."""
    conn = get_connection()
    try:
        squads = get_all_squads(conn)
        player_counts = get_squad_player_counts(conn)

        for s in squads:
            s["player_count"] = player_counts.get(s["id"], 0)
            s["strength"] = TEAM_STRENGTH.get(s.get("abbr", ""), 0.5)

        return {
            "count": len(squads),
            "squads": squads,
        }
    finally:
        conn.close()


@app.get("/api/rounds")
def api_get_rounds():
    """Get all rounds with their fixtures."""
    conn = get_connection()
    try:
        rounds = get_all_rounds(conn)
        return {
            "count": len(rounds),
            "rounds": rounds,
        }
    finally:
        conn.close()


def get_fdr(strength: float) -> int:
    if strength >= 0.85: return 5
    if strength >= 0.75: return 4
    if strength >= 0.60: return 3
    if strength >= 0.50: return 2
    return 1

@app.get("/api/fixtures")
def api_get_all_fixtures():
    """Get all fixtures across all rounds."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT f.*, r.stage, r.status as round_status
            FROM fixtures f
            JOIN rounds r ON f.round_id = r.id
            ORDER BY f.match_date
        """).fetchall()
        fixtures = [dict(r) for r in rows]

        # Enrich with team strength
        for f in fixtures:
            f["home_strength"] = TEAM_STRENGTH.get(f.get("home_squad_abbr", ""), 0.5)
            f["away_strength"] = TEAM_STRENGTH.get(f.get("away_squad_abbr", ""), 0.5)
            
            f["home_fdr"] = get_fdr(f["away_strength"])
            f["away_fdr"] = get_fdr(f["home_strength"])

        return {
            "count": len(fixtures),
            "fixtures": fixtures,
        }
    finally:
        conn.close()


@app.get("/api/fixtures/{squad_id}")
def api_get_squad_fixtures(squad_id: int):
    """Get fixtures for a specific team."""
    conn = get_connection()
    try:
        fixtures = get_fixtures_for_squad(conn, squad_id)
        if not fixtures:
            raise HTTPException(status_code=404, detail="No fixtures found for this squad")

        # Add difficulty rating
        for f in fixtures:
            if f.get("home_squad_id") == squad_id:
                opp_abbr = f.get("away_squad_abbr", "")
                f["opponent"] = f.get("away_squad_name", "TBD")
                f["is_home"] = True
            else:
                opp_abbr = f.get("home_squad_abbr", "")
                f["opponent"] = f.get("home_squad_name", "TBD")
                f["is_home"] = False
            f["difficulty"] = get_fdr(TEAM_STRENGTH.get(opp_abbr, 0.5))

        return {
            "squad_id": squad_id,
            "count": len(fixtures),
            "fixtures": fixtures,
        }
    finally:
        conn.close()


# ──────────────────────────────────────────────
# ENDPOINTS — Optimizer
# ──────────────────────────────────────────────

@app.post("/api/optimize")
def api_optimize(req: OptimizeRequest):
    """Run the squad optimizer and return recommended squad."""
    valid_presets = {"default", "value", "safe", "risky", "template"}
    if req.preset not in valid_presets:
        raise HTTPException(status_code=400, detail=f"Invalid preset. Choose from: {valid_presets}")

    valid_stages = set(SQUAD_RULES["max_per_country"].keys())
    if req.stage not in valid_stages:
        raise HTTPException(status_code=400, detail=f"Invalid stage. Choose from: {valid_stages}")

    result = optimize_squad(
        stage=req.stage,
        preset=req.preset,
        locked_in=req.locked_in,
        locked_out=req.locked_out,
        use_lp=req.use_lp,
        chip=req.chip,
        current_squad=req.current_squad,
        free_transfers=req.free_transfers
    )

    # Serialize players for JSON response
    def serialize_player(p):
        return {
            "id": p["id"],
            "display_name": p.get("display_name", p.get("known_name", "")),
            "position": p["position"],
            "price": p["price"],
            "team_name": p.get("team_name"),
            "team_abbr": p.get("team_abbr"),
            "percent_selected": p.get("percent_selected", 0),
            "projected_pts": round(p.get("projected_pts", 0), 2),
            "total_points": p.get("total_points", 0),
        }

    return {
        "squad": [serialize_player(p) for p in result["squad"]],
        "starting_xi": [serialize_player(p) for p in result["starting_xi"]],
        "bench": [serialize_player(p) for p in result["bench"]],
        "captain": serialize_player(result["captain"]) if result.get("captain") else None,
        "vice_captain": serialize_player(result["vice_captain"]) if result.get("vice_captain") else None,
        "budget_used": result["budget_used"],
        "budget_remaining": result["budget_remaining"],
        "total_projected_pts": result["total_projected_pts"],
        "preset": result["preset"],
        "stage": result["stage"],
        "method": result["method"],
    }


@app.post("/api/validate")
def api_validate_squad(req: ValidateSquadRequest):
    """Validate a user's squad against Fantasy rules."""
    conn = get_connection()
    try:
        players = []
        for pid in req.player_ids:
            p = get_player_by_id(conn, pid)
            if p:
                players.append(p)

        if len(players) != len(req.player_ids):
            missing = set(req.player_ids) - {p["id"] for p in players}
            raise HTTPException(status_code=400, detail=f"Players not found: {missing}")

        result = validate_squad(players, req.stage)
        return result
    finally:
        conn.close()


# ──────────────────────────────────────────────
# ENDPOINTS — Stats & Meta
# ──────────────────────────────────────────────

@app.get("/api/stats")
def api_get_stats():
    """Get database summary statistics."""
    conn = get_connection()
    try:
        stats = get_stats_summary(conn)
        stats["team_strengths"] = TEAM_STRENGTH
        return stats
    finally:
        conn.close()


@app.get("/api/sync-history")
def api_get_sync_history(limit: int = Query(10, ge=1, le=100)):
    """Get recent pipeline sync history."""
    conn = get_connection()
    try:
        return {
            "history": get_sync_history(conn, limit=limit),
        }
    finally:
        conn.close()


@app.post("/api/sync")
async def api_trigger_sync():
    """Trigger a data pipeline re-sync."""
    try:
        from pipeline import run_pipeline
        await run_pipeline(players_only=False)
        return {"status": "ok", "message": "Pipeline sync completed"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")


# ──────────────────────────────────────────────
# ENDPOINTS — Rules Reference
# ──────────────────────────────────────────────

@app.get("/api/rules")
def api_get_rules():
    """Get complete game rules and scoring system."""
    return {
        "tournament": TOURNAMENT,
        "squad_rules": {
            **SQUAD_RULES,
            "formations": SQUAD_RULES["formations"],
        },
        "transfer_rules": TRANSFER_RULES,
        "boosters": BOOSTERS,
        "scoring": {
            "all_positions": SCORING_ALL,
            "goalkeeper": SCORING_GK,
            "defender": SCORING_DEF,
            "midfielder": SCORING_MID,
            "forward": SCORING_FWD,
            "bonus": SCORING_BONUS,
        },
    }


# ──────────────────────────────────────────────
# STARTUP
# ──────────────────────────────────────────────

@app.on_event("startup")
def startup():
    """Initialize database on server start."""
    conn = get_connection()
    init_db(conn)
    conn.close()
    print("[OK] WC2026 Fantasy API ready")
    print("   Docs: http://localhost:8000/docs")

# ──────────────────────────────────────────────
# ENDPOINTS — Teams & Live Subs
# ──────────────────────────────────────────────

class SaveTeamRequest(BaseModel):
    device_id: str = Field(..., description="Unique device ID for the user")
    player_ids: list[int] = Field(..., description="List of 15 player IDs")

@app.post('/api/mock-points')
def update_mock_points(req: dict):
    player_id = req.get('player_id')
    points = req.get('points')
    
    if not player_id:
        raise HTTPException(status_code=400, detail="Missing player_id")
        
    conn = get_connection()
    try:
        if points is None:
            conn.execute("UPDATE players SET mock_points = NULL, mock_match_status = NULL WHERE id = ?", (player_id,))
        else:
            conn.execute("UPDATE players SET mock_points = ?, mock_match_status = 'finished' WHERE id = ?", (points, player_id))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()

@app.post("/api/team")
def api_save_team(req: SaveTeamRequest):
    """Save a user's team by device_id."""
    conn = get_connection()
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO user_teams (device_id, player_ids, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(device_id) DO UPDATE SET player_ids=excluded.player_ids, updated_at=excluded.updated_at",
            (req.device_id, ",".join(map(str, req.player_ids)), now)
        )
        conn.commit()
        return {"status": "ok", "device_id": req.device_id}
    finally:
        conn.close()

@app.get("/api/team")
def api_get_team(device_id: str = Query(...)):
    """Get a user's team by device_id."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT player_ids FROM user_teams WHERE device_id = ?", (device_id,)).fetchone()
        if row:
            return {"device_id": device_id, "player_ids": [int(x) for x in row["player_ids"].split(",")]}
        return {"device_id": device_id, "player_ids": None}
    finally:
        conn.close()

@app.get("/api/health")
def api_health():
    """Health check endpoint."""
    conn = get_connection()
    try:
        players = conn.execute("SELECT COUNT(*) FROM players WHERE is_active=1").fetchone()[0]
        sync_row = conn.execute("SELECT MAX(updated_at) FROM sync_log").fetchone()
        sync = sync_row[0] if sync_row and sync_row[0] else None
        
        import os
        from database import DB_PATH
        size_mb = os.path.getsize(DB_PATH) / (1024 * 1024) if DB_PATH.exists() else 0
        
        return {
            "status": "ok",
            "players": players,
            "last_sync": sync,
            "db_size_mb": round(size_mb, 2)
        }
    finally:
        conn.close()

class AdvisorRequest(BaseModel):
    xi_ids: list[int]
    bench_ids: list[int]
    captain_id: int | None = None

@app.post("/api/advisor")
def api_advisor(req: AdvisorRequest):
    """Advanced In-Gameweek Assistant using Expected Points (xPts) vs Actual Points."""
    conn = get_connection()
    try:
        all_ids = req.xi_ids + req.bench_ids
        if not all_ids:
            return {"captain_advice": None, "sub_advice": []}
            
        placeholders = ",".join("?" for _ in all_ids)
        query = f"SELECT id, known_name, first_name, last_name, position, price, percent_selected, mock_points, mock_match_status, total_points, team_abbr FROM players WHERE id IN ({placeholders})"
        players = conn.execute(query, all_ids).fetchall()
        
        player_map = {}
        for p in players:
            p_dict = dict(p)
            p_dict["display_name"] = p_dict.get("known_name") or f"{p_dict.get('first_name', '')} {p_dict.get('last_name', '')}".strip()
            player_map[p["id"]] = p_dict
        
        recommendations = []
        available_bench = list(bench_ids)
        for sid in starters_ids:
            p = player_map.get(sid)
            if not p: continue
            
            pts = p["mock_points"] if p["mock_points"] is not None else p["total_points"]
            status = p["mock_match_status"] if p["mock_match_status"] is not None else "upcoming"
            
            if status == "finished" and pts < 3:
                for bid in available_bench:
                    bp = player_map.get(bid)
                    if not bp: continue
                    b_status = bp["mock_match_status"] if bp["mock_match_status"] is not None else "upcoming"
                    if b_status != "finished":
                        recommendations.append({
                            "out": p,
                            "in": bp,
                            "reason": f"Sub out {p['display_name']} ({pts} pts). Bring in {bp['display_name']} (hasn't played yet)."
                        })
                        available_bench.remove(bid)
                        break
                        
        return {"recommendations": recommendations}
    finally:
        conn.close()
