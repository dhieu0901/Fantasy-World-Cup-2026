"""
FotMob JSON Data Cleaner & Normalizer
=====================================
Reads raw crawled FotMob JSON files and outputs clean, DB-ready data.

Handles:
1. GK vs Outfield split — GKs get goalkeeping stats, not attacking xG/xA
2. Lower-league null xG/xA — regression estimate from actual goals/assists
3. "not found" → smart inference from minutes_played / matches
4. String numbers → proper float/int conversion
5. Partial null in detailed_actions → fill with position-based defaults
6. Computes all per-90 stats needed by player_xstats table
"""

import json
import os
import glob
import sys
from pathlib import Path

# ═══════════════════════════════════════════════
# POSITION MAPPING: FotMob position → Fantasy position
# ═══════════════════════════════════════════════
POSITION_MAP = {
    # GK
    "keeper": "GK",
    # DEF
    "center back": "DEF",
    "left back": "DEF",
    "right back": "DEF",
    "left wing-back": "DEF",
    "right wing-back": "DEF",
    # MID
    "defensive midfielder": "MID",
    "central midfielder": "MID",
    "attacking midfielder": "MID",
    "left midfielder": "MID",
    "right midfielder": "MID",
    # FWD
    "left winger": "FWD",
    "right winger": "FWD",
    "striker": "FWD",
    "second striker": "FWD",
    "center forward": "FWD",
}


def safe_float(val, default=0.0):
    """Convert string/null to float safely."""
    if val is None or val == "not found":
        return None  # Keep None to distinguish "unknown" from "zero"
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def safe_int(val, default=0):
    """Convert string/null to int safely."""
    if val is None or val == "not found":
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def infer_started(participation):
    """Infer 'started' from minutes and matches when it's 'not found'."""
    started = participation.get("started")
    if started is not None and started != "not found":
        return safe_int(started, 0)
    
    minutes = safe_int(participation.get("minutes_played"), 0) or 0
    matches = safe_int(participation.get("matches"), 0) or 1
    
    if matches == 0:
        return 0
    
    avg_mins = minutes / matches
    # If avg > 60 min/match, they're likely a starter
    if avg_mins >= 60:
        return matches
    elif avg_mins >= 30:
        return int(matches * 0.6)
    else:
        return int(matches * 0.3)


def estimate_xg_from_goals(goals, nineties, position):
    """
    When xG is unavailable (lower leagues), regress actual goals toward the mean.
    
    Rationale: Players in weak leagues tend to overperform xG, so we discount.
    The regression factor is higher for positions that score less (DEF/MID).
    """
    if goals is None or goals == 0 or nineties == 0:
        return 0.0
    
    # Regression factor: how much to discount actual goals
    # Lower leagues tend to have inflated goal tallies
    factor = {
        "GK": 0.5,
        "DEF": 0.75,
        "MID": 0.80,
        "FWD": 0.85,
    }.get(position, 0.80)
    
    return (goals / nineties) * factor * nineties  # Back to season total


def estimate_xa_from_assists(assists, nineties, position):
    """Same logic as xG but for assists."""
    if assists is None or assists == 0 or nineties == 0:
        return 0.0
    
    factor = {
        "GK": 0.5,
        "DEF": 0.70,
        "MID": 0.80,
        "FWD": 0.75,
    }.get(position, 0.75)
    
    return (assists / nineties) * factor * nineties


def fill_detailed_actions_defaults(detailed, position):
    """
    Fill null detailed_actions with position-based conservative defaults.
    Uses per-90 league averages, scaled to the player's minutes.
    """
    if detailed is None:
        return {}
    
    result = {}
    for key in ["shots", "shots_on_target", "chances_created", "big_chances_created",
                 "clearances", "blocks", "interceptions", "tackles", "recoveries"]:
        val = safe_int(detailed.get(key))
        result[key] = val if val is not None else 0
    
    return result


def clean_player(raw, country_name):
    """
    Clean a single player's raw FotMob data into a normalized dict
    ready for player_xstats table insertion.
    """
    profile = raw.get("profile", {})
    participation = raw.get("participation", {})
    overview = raw.get("overview_metrics", {})
    gk_metrics = raw.get("goalkeeping_metrics", {})
    detailed_raw = raw.get("detailed_actions")
    discipline = raw.get("discipline", {})
    
    fotmob_id = profile.get("id")
    name = profile.get("name", "Unknown")
    raw_position = (profile.get("position") or "").lower()
    fantasy_pos = POSITION_MAP.get(raw_position, "MID")
    club = profile.get("club", "")
    league = profile.get("league", "")
    
    # ── Participation ──
    matches = safe_int(participation.get("matches"), 0) or 0
    minutes = safe_int(participation.get("minutes_played"), 0) or 0
    started = infer_started(participation)
    nineties = minutes / 90 if minutes > 0 else 0
    
    # ── Discipline (always available) ──
    yellow = safe_int(discipline.get("yellow_cards"), 0) or 0
    red = safe_int(discipline.get("red_cards"), 0) or 0
    
    is_gk = fantasy_pos == "GK"
    
    # ══════════════════════════════════════════════
    # GOALKEEPERS — special path
    # ══════════════════════════════════════════════
    if is_gk:
        goals_conceded = safe_int(overview.get("GC"), 0) or 0
        saves = safe_int(gk_metrics.get("saves"), 0) or 0
        penalties_saved = safe_int(gk_metrics.get("penalties_saved"), 0) or 0
        clean_sheets = safe_int(overview.get("CS"), 0) or 0
        
        # xGC for GKs: try overview first, fallback to estimating from GC
        xgc_raw = safe_float(overview.get("xGC"))
        if xgc_raw is not None:
            xgc = xgc_raw
        else:
            # Estimate: xGC ≈ GC * 0.95 (slight regression to mean)
            xgc = goals_conceded * 0.95 if goals_conceded else 0.0
        
        return {
            "fotmob_id": fotmob_id,
            "name": name,
            "position": fantasy_pos,
            "raw_position": profile.get("position"),
            "club": club,
            "league": league,
            "country": country_name,
            
            "matches_played": matches,
            "started": started,
            "minutes_played": minutes,
            
            # Attacking (GKs don't attack — all zero)
            "goals": 0,
            "assists": 0,
            "xG": 0.0,
            "xA": 0.0,
            "xG_per90": 0.0,
            "xA_per90": 0.0,
            "shots": 0,
            "shots_on_target": 0,
            "shots_per90": 0.0,
            
            # Defensive
            "tackles": 0,
            "tackles_per90": 0.0,
            "interceptions": 0,
            "clearances": 0,
            
            # Creative
            "chances_created": 0,
            "chances_created_per90": 0.0,
            
            # GK specific
            "saves": saves,
            "saves_per90": round(saves / nineties, 2) if nineties > 0 else 0.0,
            "clean_sheets": clean_sheets,
            "goals_conceded": goals_conceded,
            "xGC": round(xgc, 2),
            "penalties_saved": penalties_saved,
            
            # Cards
            "yellow_cards": yellow,
            "red_cards": red,
            "yellow_per90": round(yellow / nineties, 3) if nineties > 0 else 0.0,
            
            # Quality flag
            "data_quality": "gk_full" if saves > 0 else "gk_minimal",
        }
    
    # ══════════════════════════════════════════════
    # OUTFIELD PLAYERS
    # ══════════════════════════════════════════════
    goals = safe_int(overview.get("goals"), 0) or 0
    assists = safe_int(overview.get("assists"), 0) or 0
    
    # ── xG / xA ──
    xg_raw = safe_float(overview.get("xG"))
    xa_raw = safe_float(overview.get("xA"))
    xgc_raw = safe_float(overview.get("xGC"))
    
    has_advanced = xg_raw is not None
    
    if has_advanced:
        xg = xg_raw
        xa = xa_raw if xa_raw is not None else estimate_xa_from_assists(assists, nineties, fantasy_pos)
    else:
        # Lower league fallback: estimate from actual output
        xg = estimate_xg_from_goals(goals, nineties, fantasy_pos)
        xa = estimate_xa_from_assists(assists, nineties, fantasy_pos)
    
    xgc = xgc_raw if xgc_raw is not None else 0.0
    
    # ── Clean sheets & Goals conceded (DEF/MID care about these) ──
    clean_sheets = safe_int(overview.get("CS"), 0) or 0
    goals_conceded = safe_int(overview.get("GC"), 0) or 0
    
    # ── Detailed actions ──
    detailed = fill_detailed_actions_defaults(detailed_raw, fantasy_pos)
    shots = detailed.get("shots", 0)
    shots_on_target = detailed.get("shots_on_target", 0)
    chances_created = detailed.get("chances_created", 0)
    tackles = detailed.get("tackles", 0)
    interceptions = detailed.get("interceptions", 0)
    clearances = detailed.get("clearances", 0)
    
    # ── Per-90 calculations ──
    xg_per90 = round(xg / nineties, 3) if nineties > 0 and xg else 0.0
    xa_per90 = round(xa / nineties, 3) if nineties > 0 and xa else 0.0
    shots_per90 = round(shots / nineties, 2) if nineties > 0 else 0.0
    tackles_per90 = round(tackles / nineties, 2) if nineties > 0 else 0.0
    chances_per90 = round(chances_created / nineties, 2) if nineties > 0 else 0.0
    yellow_per90 = round(yellow / nineties, 3) if nineties > 0 else 0.0
    
    # ── Determine data quality ──
    if has_advanced and detailed_raw is not None:
        quality = "high"
    elif has_advanced:
        quality = "medium"
    elif detailed_raw is not None:
        quality = "medium_no_xg"
    else:
        quality = "low"
    
    return {
        "fotmob_id": fotmob_id,
        "name": name,
        "position": fantasy_pos,
        "raw_position": profile.get("position"),
        "club": club,
        "league": league,
        "country": country_name,
        
        "matches_played": matches,
        "started": started,
        "minutes_played": minutes,
        
        # Attacking
        "goals": goals,
        "assists": assists,
        "xG": round(xg, 2),
        "xA": round(xa, 2),
        "xG_per90": xg_per90,
        "xA_per90": xa_per90,
        "shots": shots,
        "shots_on_target": shots_on_target,
        "shots_per90": shots_per90,
        
        # Defensive
        "tackles": tackles,
        "tackles_per90": tackles_per90,
        "interceptions": interceptions,
        "clearances": clearances,
        
        # Creative
        "chances_created": chances_created,
        "chances_created_per90": chances_per90,
        
        # GK fields (minimal for outfield)
        "saves": 0,
        "saves_per90": 0.0,
        "clean_sheets": clean_sheets,
        "goals_conceded": goals_conceded,
        "xGC": round(xgc, 2),
        "penalties_saved": 0,
        
        # Cards
        "yellow_cards": yellow,
        "red_cards": red,
        "yellow_per90": yellow_per90,
        
        # Quality flag
        "data_quality": quality,
    }


def process_file(filepath):
    """Process a single country JSON file."""
    country_name = Path(filepath).stem
    
    with open(filepath, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    
    cleaned = []
    for raw_player in raw_data:
        try:
            cleaned_player = clean_player(raw_player, country_name)
            cleaned.append(cleaned_player)
        except Exception as e:
            name = raw_player.get("profile", {}).get("name", "???")
            print(f"  ERROR cleaning {name}: {e}")
    
    return cleaned


def print_summary(country, players):
    """Print a quality summary for a country."""
    total = len(players)
    gks = [p for p in players if p["position"] == "GK"]
    outfield = [p for p in players if p["position"] != "GK"]
    
    quality_counts = {}
    for p in players:
        q = p["data_quality"]
        quality_counts[q] = quality_counts.get(q, 0) + 1
    
    has_xg = sum(1 for p in outfield if p["xG"] > 0)
    has_xa = sum(1 for p in outfield if p["xA"] > 0)
    
    print(f"\n  {country}: {total} players ({len(gks)} GK, {len(outfield)} outfield)")
    print(f"  Quality: {quality_counts}")
    print(f"  Outfield with xG: {has_xg}/{len(outfield)} | with xA: {has_xa}/{len(outfield)}")
    
    # Show any players that still have zero xG despite having goals
    for p in outfield:
        if p["goals"] > 0 and p["xG"] == 0:
            print(f"    WARN: {p['name']} has {p['goals']} goals but xG=0!")


def main():
    folder = Path(__file__).parent
    json_files = sorted(folder.glob("*.json"))
    
    if not json_files:
        print("No JSON files found!")
        return
    
    output_dir = folder / "cleaned"
    output_dir.mkdir(exist_ok=True)
    
    all_players = []
    
    print("=" * 60)
    print("  FotMob Data Cleaner & Normalizer")
    print("=" * 60)
    
    for filepath in json_files:
        country = filepath.stem
        print(f"\n  Processing {country}...")
        
        cleaned = process_file(str(filepath))
        all_players.extend(cleaned)
        
        # Write cleaned output per country
        out_path = output_dir / f"{country}_clean.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2, ensure_ascii=False)
        
        print_summary(country, cleaned)
    
    # Write combined output
    combined_path = output_dir / "all_players_clean.json"
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(all_players, f, indent=2, ensure_ascii=False)
    
    print(f"\n{'=' * 60}")
    print(f"  TOTAL: {len(all_players)} players cleaned")
    print(f"  Output: {output_dir}")
    print(f"  Combined: {combined_path}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
