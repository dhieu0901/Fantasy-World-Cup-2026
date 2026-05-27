"""
FIFA World Cup Fantasy 2026™ — Complete Game Rules & Expected Points (xPts) Engine
=====================================================================================

This module contains:
1. Official scoring rules (all positions)
2. Tournament structure & constraints
3. Expected Points (xPts) calculation engine
4. Data sources mapping

Source: https://play.fifa.com/fantasy - Official "How to Play" rules
"""

# ══════════════════════════════════════════════
# 1. TOURNAMENT STRUCTURE
# ══════════════════════════════════════════════

TOURNAMENT = {
    "name": "FIFA World Cup 2026™",
    "hosts": ["USA", "Canada", "Mexico"],
    "dates": {"start": "2026-06-11", "end": "2026-07-19"},
    "total_teams": 48,
    "groups": 12,
    "teams_per_group": 4,
    "stages": [
        "GROUP_MD1", "GROUP_MD2", "GROUP_MD3",
        "ROUND_OF_32", "ROUND_OF_16",
        "QUARTER_FINAL", "SEMI_FINAL", "FINAL"
    ],
}

# ══════════════════════════════════════════════
# 2. SQUAD RULES
# ══════════════════════════════════════════════

SQUAD_RULES = {
    "squad_size": 15,
    "starting_xi": 11,
    "bench_size": 4,
    "budget": {
        "group_stage": 100.0,       # $100m
        "knockout_stage": 105.0,    # $105m (budget increase after MD3)
    },
    "positions": {
        "GK": {"min": 2, "max": 2},
        "DEF": {"min": 5, "max": 5},
        "MID": {"min": 5, "max": 5},
        "FWD": {"min": 3, "max": 3},
    },
    "formations": [
        "4-4-2", "4-3-3", "4-5-1",
        "3-4-3", "3-5-2",
        "5-4-1", "5-3-2",
    ],
    # Max players from the same country
    "max_per_country": {
        "GROUP_MD1": 3, "GROUP_MD2": 3, "GROUP_MD3": 3,
        "ROUND_OF_32": 3,
        "ROUND_OF_16": 4,
        "QUARTER_FINAL": 5,
        "SEMI_FINAL": 6,
        "FINAL": 8,
    },
}

# ══════════════════════════════════════════════
# 3. TRANSFER RULES
# ══════════════════════════════════════════════

TRANSFER_RULES = {
    "allocations": {
        "pre_tournament": float("inf"),     # Unlimited
        "before_md2": 2,
        "before_md3": 2,
        "before_r32": float("inf"),         # Unlimited
        "before_r16": 4,
        "before_qf": 4,
        "before_sf": 5,
        "before_final": 6,
    },
    "extra_transfer_cost": -3,              # -3 points per extra transfer
    "carry_over": {
        "group_stage": 1,                   # Can carry 1 unused transfer in group stage
        "knockout": 0,                      # No carry-over into knockout
    },
    "prices_fixed": True,                   # Player prices do NOT change during tournament
}

# ══════════════════════════════════════════════
# 4. BOOSTERS (CHIPS)
# ══════════════════════════════════════════════

BOOSTERS = {
    "wildcard": {
        "name": "Wildcard",
        "description": "Unlimited transfers for a specific round",
        "restrictions": "Cannot be used for MD1 or Round of 32",
        "reversible": False,
    },
    "12th_man": {
        "name": "12th Man",
        "description": "Select 1 additional player to score points",
        "restrictions": "Player cannot be substituted, captained, or transferred. No budget/team restrictions.",
        "reversible": True,
    },
    "max_captain": {
        "name": "Maximum Captain",
        "description": "Double points for highest scorer in starting XI (auto-captained)",
        "restrictions": None,
        "reversible": True,
    },
    "qualification_booster": {
        "name": "Qualification Booster",
        "description": "+2 pts for each starting XI player whose team advances (must play 1+ min)",
        "restrictions": "Available from Round of 32 onwards",
        "reversible": True,
    },
    "mystery_booster": {
        "name": "Mystery Booster",
        "description": "Revealed when Round of 32 opens. Can be used once in knockout stage.",
        "restrictions": "Available from Round of 32 onwards",
        "reversible": True,
    },
}

# ══════════════════════════════════════════════
# 5. SCORING SYSTEM (Official FIFA WC Fantasy)
# ══════════════════════════════════════════════

# --- Universal (all positions) ---
SCORING_ALL = {
    "appearance_under_60":  1,      # Played < 60 min
    "appearance_over_60":   1,      # Played 60+ min (cumulative = +2 total)
    "assist":               3,
    "yellow_card":         -1,
    "red_card":            -2,
    "own_goal":            -2,
    "winning_penalty":      2,      # Won a penalty
    "conceding_penalty":   -1,      # Gave away a penalty
}

# --- Goalkeeper ---
SCORING_GK = {
    "clean_sheet":          5,      # 60+ min required
    "first_goal_conceded":  0,      # No penalty for first goal
    "additional_goal_conceded": -1, # Each goal after the first
    "goal_scored":          9,
    "penalty_save":         3,      # Not including shootouts
    "every_3_saves":        1,
}

# --- Defender ---
SCORING_DEF = {
    "clean_sheet":          5,      # 60+ min required
    "first_goal_conceded":  0,
    "additional_goal_conceded": -1,
    "goal_scored":          7,
}

# --- Midfielder ---
SCORING_MID = {
    "clean_sheet":          1,      # 60+ min required
    "goal_scored":          6,
    "every_3_tackles":      1,
    "every_2_chances_created": 1,
}

# --- Forward ---
SCORING_FWD = {
    "goal_scored":          5,
    "every_2_shots_on_target": 1,
}

# --- Bonus Points ---
SCORING_BONUS = {
    "free_kick_goal":       1,      # Goal from direct free-kick
    "scouting_bonus":       2,      # >4pts in match AND <5% selection
}

# Convenience: goal points by position
GOAL_POINTS = {"GK": 9, "DEF": 7, "MID": 6, "FWD": 5}


# ══════════════════════════════════════════════
# 6. EXPECTED POINTS (xPts) FORMULA
# ══════════════════════════════════════════════
#
# Inspired by xFPL but adapted for WC Fantasy scoring.
# Instead of just xG + xA, we model EVERY scoring action.
#
# Required input stats per player per match:
#   - xG (expected goals)
#   - xA (expected assists)
#   - P(start): probability of starting
#   - P(60+): probability of playing 60+ minutes given they play
#   - xCS: expected clean sheet probability (for team)
#   - xGC: expected goals conceded by team
#   - xSaves: expected saves (GK only)
#   - xTackles: expected tackles (MID only)
#   - xChancesCreated: expected chances created (MID only)
#   - xShotsOnTarget: expected shots on target (FWD only)
#   - P(yellow): probability of yellow card
#   - P(red): probability of red card
#   - P(own_goal): probability of own goal
#   - P(pen_won): probability of winning a penalty
#   - P(pen_conceded): probability of conceding a penalty
#   - P(pen_save): probability of saving a penalty (GK)
#   - P(fk_goal): probability of free-kick goal
#

def calculate_xpts(player_stats: dict, position: str) -> dict:
    """
    Calculate Expected Points (xPts) for a single player for a single match.
    
    Args:
        player_stats: dict with keys matching the required stats above
        position: "GK", "DEF", "MID", or "FWD"
    
    Returns:
        dict with breakdown of xPts components and total
    """
    s = player_stats  # shorthand

    # Probabilities
    p_play = s.get("p_start", 0.0)              # Probability of playing any minutes
    p_60 = s.get("p_60_plus", 0.0)              # Probability of playing 60+ min (given they play)
    p_sub = p_play * (1 - p_60)                  # Probability of playing but < 60 min

    breakdown = {}

    # ── 1. Appearance points ──
    # If they play at all: +1. If 60+: another +1
    breakdown["xAppearance"] = p_play * 1 + p_play * p_60 * 1

    # ── 2. Goals ──
    xg = s.get("xG", 0.0)
    goal_pts = GOAL_POINTS.get(position, 5)
    breakdown["xGoals"] = xg * goal_pts

    # ── 3. Assists ──
    xa = s.get("xA", 0.0)
    breakdown["xAssists"] = xa * SCORING_ALL["assist"]

    # ── 4. Clean Sheet ──
    xcs = s.get("xCS", 0.0)
    if position == "GK":
        breakdown["xCleanSheet"] = xcs * p_play * p_60 * SCORING_GK["clean_sheet"]
    elif position == "DEF":
        breakdown["xCleanSheet"] = xcs * p_play * p_60 * SCORING_DEF["clean_sheet"]
    elif position == "MID":
        breakdown["xCleanSheet"] = xcs * p_play * p_60 * SCORING_MID["clean_sheet"]
    else:
        breakdown["xCleanSheet"] = 0.0

    # ── 5. Goals Conceded (GK, DEF only) ──
    if position in ("GK", "DEF"):
        xgc = s.get("xGC", 0.0)  # Expected goals conceded by team
        # Expected additional goals conceded (beyond the first)
        # E[max(0, GC - 1)] ≈ max(0, xGC - 1) for simplification
        # More accurately: sum over k>=2 of P(GC=k) * (k-1)
        # Using Poisson approximation: E[max(0, GC-1)] = xGC - (1 - e^(-xGC))
        import math
        if xgc > 0:
            expected_additional_gc = xgc - (1 - math.exp(-xgc))
        else:
            expected_additional_gc = 0.0
        breakdown["xGoalsConceded"] = -expected_additional_gc * p_play * p_60
    else:
        breakdown["xGoalsConceded"] = 0.0

    # ── 6. Saves (GK only) ──
    if position == "GK":
        x_saves = s.get("xSaves", 0.0)
        breakdown["xSaves"] = (x_saves / 3) * p_play * SCORING_GK["every_3_saves"]
    else:
        breakdown["xSaves"] = 0.0

    # ── 7. Penalty Save (GK only) ──
    if position == "GK":
        p_pen_save = s.get("p_pen_save", 0.0)
        breakdown["xPenaltySave"] = p_pen_save * SCORING_GK["penalty_save"]
    else:
        breakdown["xPenaltySave"] = 0.0

    # ── 8. Tackles (MID only) ──
    if position == "MID":
        x_tackles = s.get("xTackles", 0.0)
        breakdown["xTackles"] = (x_tackles / 3) * p_play * SCORING_MID["every_3_tackles"]
    else:
        breakdown["xTackles"] = 0.0

    # ── 9. Chances Created (MID only) ──
    if position == "MID":
        x_cc = s.get("xChancesCreated", 0.0)
        breakdown["xChancesCreated"] = (x_cc / 2) * p_play * SCORING_MID["every_2_chances_created"]
    else:
        breakdown["xChancesCreated"] = 0.0

    # ── 10. Shots on Target (FWD only) ──
    if position == "FWD":
        x_sot = s.get("xShotsOnTarget", 0.0)
        breakdown["xShotsOnTarget"] = (x_sot / 2) * p_play * SCORING_FWD["every_2_shots_on_target"]
    else:
        breakdown["xShotsOnTarget"] = 0.0

    # ── 11. Cards ──
    p_yellow = s.get("p_yellow", 0.0)
    p_red = s.get("p_red", 0.0)
    breakdown["xCards"] = -(p_yellow * abs(SCORING_ALL["yellow_card"]) +
                            p_red * abs(SCORING_ALL["red_card"])) * p_play

    # ── 12. Own Goal ──
    p_og = s.get("p_own_goal", 0.0)
    breakdown["xOwnGoal"] = -p_og * abs(SCORING_ALL["own_goal"]) * p_play

    # ── 13. Penalty Won ──
    p_pen_won = s.get("p_pen_won", 0.0)
    breakdown["xPenaltyWon"] = p_pen_won * SCORING_ALL["winning_penalty"]

    # ── 14. Penalty Conceded ──
    p_pen_conc = s.get("p_pen_conceded", 0.0)
    breakdown["xPenaltyConceded"] = -p_pen_conc * abs(SCORING_ALL["conceding_penalty"]) * p_play

    # ── 15. Free-kick Goal Bonus ──
    p_fk = s.get("p_fk_goal", 0.0)
    breakdown["xFreeKickBonus"] = p_fk * SCORING_BONUS["free_kick_goal"]

    # ── 16. Scouting Bonus (estimated) ──
    # +2 if player scores >4pts AND is in <5% of teams
    pct_selected = s.get("percent_selected", 50.0)
    if pct_selected < 5.0:
        # Rough estimate: probability of scoring >4 pts
        p_over_4 = s.get("p_over_4pts", 0.1)  # Default 10%
        breakdown["xScoutingBonus"] = p_over_4 * SCORING_BONUS["scouting_bonus"]
    else:
        breakdown["xScoutingBonus"] = 0.0

    # ── TOTAL ──
    breakdown["xPts"] = sum(breakdown.values())

    return breakdown


def calculate_simple_xpts(price: float, position: str, team_strength: float = 0.5,
                          opponent_strength: float = 0.5, is_home: bool = True,
                          percent_selected: float = 0.0) -> float:
    """
    Simplified xPts when we don't have detailed stats.
    Uses price as a proxy for quality, ownership as a quality signal,
    and basic match context.
    
    Args:
        price: player's Fantasy price ($m)
        position: GK/DEF/MID/FWD
        team_strength: 0-1 (higher = stronger team)
        opponent_strength: 0-1 (higher = stronger opponent)
        is_home: home advantage
        percent_selected: ownership % (0-100) — collective intelligence signal
        
    Returns:
        Estimated xPts (float)
    """
    # Base xPts from price tier (empirical FPL-like correlation)
    base_by_price = {
        (0, 4.0):   1.5,
        (4.0, 5.0): 2.0,
        (5.0, 6.0): 2.8,
        (6.0, 7.0): 3.5,
        (7.0, 8.0): 4.2,
        (8.0, 9.0): 5.0,
        (9.0, 10.0): 5.8,
        (10.0, 12.0): 6.5,
        (12.0, 20.0): 7.5,
    }
    
    base = 2.0
    for (lo, hi), pts in base_by_price.items():
        if lo <= price < hi:
            base = pts
            break

    # Position modifier
    position_mod = {"GK": 0.85, "DEF": 0.90, "MID": 1.05, "FWD": 1.15}
    base *= position_mod.get(position, 1.0)

    # Match context modifier
    strength_diff = team_strength - opponent_strength
    context_mod = 1.0 + (strength_diff * 0.3)
    if is_home:
        context_mod *= 1.05
    base *= context_mod

    # Ownership as quality/play-probability signal
    # Extremely low ownership usually means they don't play (0 points).
    # We must heavily penalize fodder so the optimizer doesn't pick non-starters.
    ownership = max(0.0, percent_selected or 0.0)
    if ownership < 0.5:
        ownership_mod = 0.1   # <0.5%: Almost certainly won't play (xPts ~ 0)
    elif ownership < 2.0:
        ownership_mod = 0.4   # <2%: Unlikely to start / deep bench
    elif ownership < 5.0:
        ownership_mod = 0.75  # <5%: Rotation risk or weak team starter
    elif ownership < 10.0:
        ownership_mod = 0.9   # <10%: Regular starter, minor rotation risk
    else:
        ownership_mod = 1.0   # >10%: Nailed starter

    base *= ownership_mod

    return round(base, 2)


def calculate_xpts_from_db(player_id: int, position: str, price: float,
                           percent_selected: float = 50.0,
                           team_strength: float = 0.5,
                           opponent_strength: float = 0.5,
                           is_home: bool = True,
                           conn=None) -> dict:
    """
    Smart xPts: uses real stats from player_xstats if available,
    otherwise falls back to price-based estimation.
    
    This converts club-season per-90 stats into per-match probabilities,
    then feeds them to the full xPts engine.
    
    Args:
        player_id: FIFA Fantasy player ID
        position: GK/DEF/MID/FWD
        price: player's Fantasy price ($m)
        percent_selected: ownership %
        team_strength: 0-1 (higher = stronger team)
        opponent_strength: 0-1 (higher = stronger opponent)
        is_home: whether playing at home
        conn: SQLite connection (if None, returns simple estimate)
    
    Returns:
        dict with xPts breakdown and 'source' indicating data quality
    """
    # Try to load real stats from database
    xstats = None
    if conn is not None:
        row = conn.execute(
            "SELECT * FROM player_xstats WHERE player_id = ? ORDER BY "
            "CASE source WHEN 'fotmob' THEN 1 WHEN 'sofascore' THEN 2 ELSE 3 END "
            "LIMIT 1",
            (player_id,)
        ).fetchone()
        if row:
            xstats = dict(row)

    if xstats and xstats.get("minutes_played", 0) > 300:
        # ── We have real stats! Convert to per-match expected values ──
        minutes = xstats["minutes_played"]
        nineties = minutes / 90 if minutes > 0 else 1

        # Adjust for opponent strength (WC matches vs club matches)
        # Strong opponent → fewer goals, more defensive actions
        opp_factor = 1.0 - (opponent_strength - 0.5) * 0.4  # ±20%
        team_factor = 1.0 + (team_strength - 0.5) * 0.3  # ±15%

        # Starter probability from price + minutes pattern
        matches = xstats.get("matches_played", 0) or 1
        min_per_match = minutes / matches if matches > 0 else 0
        p_start = min(0.98, max(0.3, min_per_match / 90))
        p_60_plus = min(0.95, max(0.3, min_per_match / 85)) if p_start > 0.4 else 0.5

        # Build per-match stats from per-90 data
        xg_per90 = xstats.get("xG_per90", 0) or 0
        xa_per90 = xstats.get("xA_per90", 0) or 0

        # If no xG/xA per90, estimate from goals/assists
        if xg_per90 == 0 and (xstats.get("goals", 0) or 0) > 0:
            xg_per90 = (xstats["goals"] / nineties) * 0.9  # Slight regression
        if xa_per90 == 0 and (xstats.get("assists", 0) or 0) > 0:
            xa_per90 = (xstats["assists"] / nineties) * 0.85

        player_stats = {
            "p_start": p_start,
            "p_60_plus": p_60_plus,
            "xG": xg_per90 * opp_factor,
            "xA": xa_per90 * opp_factor,
            "xCS": _estimate_xcs(team_strength, opponent_strength),
            "xGC": _estimate_xgc(team_strength, opponent_strength),
            "xSaves": (xstats.get("saves_per90", 0) or 0) * opp_factor,
            "xTackles": (xstats.get("tackles_per90", 0) or 0) * opp_factor,
            "xChancesCreated": (xstats.get("chances_created_per90", 0) or 0) * team_factor,
            "xShotsOnTarget": (xstats.get("shots_per90", 0) or 0) * 0.4 * opp_factor,
            "p_yellow": min(0.3, (xstats.get("yellow_per90", 0) or 0)),
            "p_red": 0.005,
            "p_own_goal": 0.005 if position in ("DEF", "GK") else 0.001,
            "p_pen_won": 0.04 if position in ("FWD", "MID") else 0.01,
            "p_pen_conceded": 0.02 if position in ("DEF", "GK") else 0.005,
            "p_pen_save": 0.02 if position == "GK" else 0.0,
            "p_fk_goal": 0.005,
            "percent_selected": percent_selected,
        }

        result = calculate_xpts(player_stats, position)
        result["source"] = "xstats"
        result["data_quality"] = "high" if xg_per90 > 0 else "medium"
        return result

    else:
        # ── Fallback: price-based estimate ──
        simple_xpts = calculate_simple_xpts(
            price, position, team_strength, opponent_strength, is_home,
            percent_selected=percent_selected,
        )
        return {
            "xPts": simple_xpts,
            "source": "price_estimate",
            "data_quality": "low",
        }


def _estimate_xcs(team_strength: float, opp_strength: float) -> float:
    """Estimate clean sheet probability from team/opponent strength."""
    # Base CS probability in international football: ~35%
    # Adjusted by strength differential
    base = 0.35
    diff = team_strength - opp_strength
    return max(0.05, min(0.75, base + diff * 0.25))


def _estimate_xgc(team_strength: float, opp_strength: float) -> float:
    """Estimate expected goals conceded from team/opponent strength."""
    # Average goals per WC match: ~2.5 total, ~1.25 per team
    base = 1.25
    diff = opp_strength - team_strength  # Higher opponent = more goals conceded
    return max(0.2, base + diff * 0.8)


# ══════════════════════════════════════════════
# 7. DATA SOURCES — Where to get stats for xPts
# ══════════════════════════════════════════════
#
# Priority order for enriching player data:
#
# ┌─────────────────────┬──────────────────┬──────────────────────────────────────┐
# │ Source              │ Access           │ Data Available                       │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ FIFA Fantasy API    │ Public, free     │ Price, position, points, % selected  │
# │ play.fifa.com       │ No auth          │ Round scores, status                 │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ FotMob              │ Unofficial API   │ xG, xA, shots, tackles, saves,      │
# │ fotmob.com          │ (reverse eng.)   │ chances created, heatmaps, ratings   │
# │                     │ Rate limit!      │ Per-match + season aggregates        │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ Sofascore           │ Unofficial API   │ Player ratings, xG, shots on target, │
# │ sofascore.com       │ (reverse eng.)   │ tackles, passes, dribbles, cards     │
# │                     │ Anti-bot!        │ Live match data                      │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ Understat           │ Scrape-friendly  │ xG, xA per shot (best granularity)   │
# │ understat.com       │ Public           │ Top 5 leagues only (not WC)          │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ FBref               │ Scrape (3s rate) │ Standard stats, match logs           │
# │ fbref.com           │ Anti-bot         │ xG/xA REMOVED as of Jan 2026        │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ API-Football        │ Free tier        │ Match events, lineups, stats         │
# │ api-sports.io       │ 100 req/day      │ Cards, goals, substitutions          │
# ├─────────────────────┼──────────────────┼──────────────────────────────────────┤
# │ BallDontLie         │ Free tier        │ Basic stats (goals, assists, cards)  │
# │ balldontlie.io      │ API key needed   │ WC-specific endpoint                 │
# └─────────────────────┴──────────────────┴──────────────────────────────────────┘
#
# RECOMMENDED STRATEGY:
#   Phase 1 (now):    FIFA Fantasy API → prices, points, ownership
#   Phase 2 (pre-WC): FotMob unofficial API → xG, xA, defensive stats (club season)
#   Phase 3 (live):   FotMob/Sofascore → live match xG, tackles, saves for xPts
#   Fallback:         Simple price-based xPts when detailed stats unavailable
#


# ══════════════════════════════════════════════
# 8. FOTMOB SCRAPER ENDPOINTS (for future use)
# ══════════════════════════════════════════════
#
# FotMob internal API (discovered via browser DevTools):
#
# Player profile:
#   GET https://www.fotmob.com/api/playerData?id={fotmob_player_id}
#   → seasons, stats (goals, assists, xG, xA, tackles, saves, etc.)
#
# Match details:
#   GET https://www.fotmob.com/api/matchDetails?matchId={match_id}
#   → lineups, events, stats per player
#
# League/competition:
#   GET https://www.fotmob.com/api/leagues?id={league_id}
#   → standings, top scorers, fixtures
#
# World Cup 2026 league ID: TBD (check fotmob.com when tournament starts)
#
# IMPORTANT: These are unofficial. Use rate limiting (1 req/sec) and
# cache responses aggressively. Do NOT hammer their servers.
#

# ══════════════════════════════════════════════
# 9. HELPER FUNCTIONS
# ══════════════════════════════════════════════

def get_scoring_rules(position: str) -> dict:
    """Get combined scoring rules for a position."""
    rules = dict(SCORING_ALL)
    if position == "GK":
        rules.update(SCORING_GK)
    elif position == "DEF":
        rules.update(SCORING_DEF)
    elif position == "MID":
        rules.update(SCORING_MID)
    elif position == "FWD":
        rules.update(SCORING_FWD)
    rules["bonus"] = dict(SCORING_BONUS)
    return rules


def calculate_match_points(events: dict, position: str) -> int:
    """
    Calculate actual Fantasy points from match events.
    
    Args:
        events: dict of actual match events, e.g.:
            {
                "minutes_played": 78,
                "goals": 1,
                "assists": 0,
                "yellow_cards": 1,
                "red_cards": 0,
                "own_goals": 0,
                "penalties_won": 0,
                "penalties_conceded": 0,
                "clean_sheet": True,      # team didn't concede
                "goals_conceded": 0,      # team total goals conceded
                "saves": 4,              # GK only
                "penalty_saves": 0,       # GK only
                "tackles": 5,            # MID only
                "chances_created": 3,     # MID only
                "shots_on_target": 2,     # FWD only
                "free_kick_goal": False,
                "percent_selected": 3.2,  # For scouting bonus
            }
        position: GK/DEF/MID/FWD
        
    Returns:
        Total fantasy points (int)
    """
    pts = 0
    mins = events.get("minutes_played", 0)

    if mins <= 0:
        return 0

    # Appearance
    pts += 1  # Played any minutes
    if mins >= 60:
        pts += 1

    # Goals
    goals = events.get("goals", 0)
    pts += goals * GOAL_POINTS.get(position, 5)

    # Assists
    pts += events.get("assists", 0) * SCORING_ALL["assist"]

    # Cards
    pts += events.get("yellow_cards", 0) * SCORING_ALL["yellow_card"]
    pts += events.get("red_cards", 0) * SCORING_ALL["red_card"]

    # Own goals
    pts += events.get("own_goals", 0) * SCORING_ALL["own_goal"]

    # Penalties
    pts += events.get("penalties_won", 0) * SCORING_ALL["winning_penalty"]
    pts += events.get("penalties_conceded", 0) * SCORING_ALL["conceding_penalty"]

    # Clean sheet (60+ min required)
    if mins >= 60 and events.get("clean_sheet", False):
        if position == "GK":
            pts += SCORING_GK["clean_sheet"]
        elif position == "DEF":
            pts += SCORING_DEF["clean_sheet"]
        elif position == "MID":
            pts += SCORING_MID["clean_sheet"]

    # Goals conceded (GK, DEF)
    if position in ("GK", "DEF") and mins >= 60:
        gc = events.get("goals_conceded", 0)
        if gc > 1:
            pts += (gc - 1) * -1  # -1 per additional goal conceded

    # GK specifics
    if position == "GK":
        saves = events.get("saves", 0)
        pts += (saves // 3) * SCORING_GK["every_3_saves"]
        pts += events.get("penalty_saves", 0) * SCORING_GK["penalty_save"]

    # MID specifics
    if position == "MID":
        tackles = events.get("tackles", 0)
        pts += (tackles // 3) * SCORING_MID["every_3_tackles"]
        chances = events.get("chances_created", 0)
        pts += (chances // 2) * SCORING_MID["every_2_chances_created"]

    # FWD specifics
    if position == "FWD":
        sot = events.get("shots_on_target", 0)
        pts += (sot // 2) * SCORING_FWD["every_2_shots_on_target"]

    # Bonus: free-kick goal
    if events.get("free_kick_goal", False):
        pts += SCORING_BONUS["free_kick_goal"]

    # Bonus: scouting (>4pts, <5% selected)
    pct = events.get("percent_selected", 100)
    if pts > 4 and pct < 5.0:
        pts += SCORING_BONUS["scouting_bonus"]

    return pts


def validate_squad(players: list[dict], stage: str = "GROUP_MD1") -> dict:
    """
    Validate a squad against Fantasy rules.
    
    Args:
        players: list of player dicts with keys: position, price, squad_id
        stage: tournament stage for country limit check
    
    Returns:
        dict with 'valid' bool and 'errors' list
    """
    errors = []
    
    # Check squad size
    if len(players) != SQUAD_RULES["squad_size"]:
        errors.append(f"Squad must have {SQUAD_RULES['squad_size']} players, got {len(players)}")

    # Check position counts
    pos_counts = {}
    for p in players:
        pos = p.get("position", "")
        pos_counts[pos] = pos_counts.get(pos, 0) + 1

    for pos, limits in SQUAD_RULES["positions"].items():
        count = pos_counts.get(pos, 0)
        if count < limits["min"]:
            errors.append(f"Need at least {limits['min']} {pos}, got {count}")
        if count > limits["max"]:
            errors.append(f"Max {limits['max']} {pos}, got {count}")

    # Check budget
    budget_limit = SQUAD_RULES["budget"]["group_stage"]
    if stage in ("ROUND_OF_32", "ROUND_OF_16", "QUARTER_FINAL", "SEMI_FINAL", "FINAL"):
        budget_limit = SQUAD_RULES["budget"]["knockout_stage"]

    total_cost = sum(p.get("price", 0) for p in players)
    if total_cost > budget_limit:
        errors.append(f"Budget exceeded: ${total_cost:.1f}m > ${budget_limit:.1f}m limit")

    # Check country limits
    max_per_country = SQUAD_RULES["max_per_country"].get(stage, 3)
    country_counts = {}
    for p in players:
        sid = p.get("squad_id", 0)
        country_counts[sid] = country_counts.get(sid, 0) + 1

    for sid, count in country_counts.items():
        if count > max_per_country:
            errors.append(f"Max {max_per_country} players from squad {sid}, got {count}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "budget_used": total_cost,
        "budget_remaining": budget_limit - total_cost,
        "position_counts": pos_counts,
        "country_counts": country_counts,
    }


# ══════════════════════════════════════════════
# DEMO / TEST
# ══════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("FIFA WC Fantasy 2026 — Rules & xPts Engine")
    print("=" * 60)

    # Test: Calculate xPts for Mbappé (FWD, ~$12m)
    mbappe_stats = {
        "p_start": 0.95,
        "p_60_plus": 0.85,
        "xG": 0.65,
        "xA": 0.18,
        "xCS": 0.0,                 # FWD doesn't care
        "xShotsOnTarget": 1.8,
        "p_yellow": 0.08,
        "p_red": 0.005,
        "p_own_goal": 0.002,
        "p_pen_won": 0.05,
        "p_pen_conceded": 0.0,
        "percent_selected": 45.0,
    }
    
    result = calculate_xpts(mbappe_stats, "FWD")
    print(f"\n🇫🇷 Mbappé (FWD) xPts Breakdown:")
    for key, val in result.items():
        if key != "xPts":
            print(f"   {key:25s}: {val:+.3f}")
    print(f"   {'─' * 35}")
    print(f"   {'TOTAL xPts':25s}: {result['xPts']:.2f}")

    # Test: Calculate actual points
    print(f"\n{'─' * 60}")
    print("Test: Match points calculation")
    events = {
        "minutes_played": 90,
        "goals": 1,
        "assists": 1,
        "yellow_cards": 0,
        "red_cards": 0,
        "own_goals": 0,
        "penalties_won": 0,
        "penalties_conceded": 0,
        "clean_sheet": True,
        "goals_conceded": 0,
        "saves": 0,
        "tackles": 4,
        "chances_created": 3,
        "shots_on_target": 3,
        "free_kick_goal": False,
        "percent_selected": 45.0,
    }

    for pos in ["GK", "DEF", "MID", "FWD"]:
        pts = calculate_match_points(events, pos)
        print(f"   {pos}: {pts} pts (1 goal + 1 assist + CS + 90min)")

    # Test: Simple xPts
    print(f"\n{'─' * 60}")
    print("Simple xPts (with ownership_mod):")
    test_cases = [
        (10.5, "FWD", 51.4, "Mbappé-like"),
        (10.5, "FWD",  0.5, "Bench FWD same price"),
        (8.5,  "MID", 53.8, "Bruno Fernandes-like"),
        (8.5,  "MID",  1.0, "Bench MID same price"),
        (5.5,  "DEF", 30.6, "Gabriel-like"),
        (4.0,  "GK",  21.3, "Emi Martinez-like"),
    ]
    for price, pos, own, label in test_cases:
        xpts = calculate_simple_xpts(price, pos, team_strength=0.8, opponent_strength=0.3, percent_selected=own)
        print(f"   ${price}m {pos} ({own}% owned): {xpts:.2f} xPts  ← {label}")

    # Test: Squad validation
    print(f"\n{'─' * 60}")
    print("Squad validation test:")
    fake_squad = [
        {"position": "GK", "price": 5.0, "squad_id": 1},
        {"position": "GK", "price": 4.0, "squad_id": 2},
        {"position": "DEF", "price": 6.0, "squad_id": 1},
        {"position": "DEF", "price": 5.5, "squad_id": 1},
        {"position": "DEF", "price": 5.0, "squad_id": 3},
        {"position": "DEF", "price": 4.5, "squad_id": 4},
        {"position": "DEF", "price": 4.0, "squad_id": 5},
        {"position": "MID", "price": 8.0, "squad_id": 1},  # 4th from squad 1 = violation!
        {"position": "MID", "price": 7.5, "squad_id": 6},
        {"position": "MID", "price": 7.0, "squad_id": 7},
        {"position": "MID", "price": 6.5, "squad_id": 8},
        {"position": "MID", "price": 6.0, "squad_id": 9},
        {"position": "FWD", "price": 12.0, "squad_id": 10},
        {"position": "FWD", "price": 10.0, "squad_id": 11},
        {"position": "FWD", "price": 9.0, "squad_id": 12},
    ]
    result = validate_squad(fake_squad, "GROUP_MD1")
    print(f"   Valid: {result['valid']}")
    print(f"   Budget: ${result['budget_used']:.1f}m / $100m")
    for err in result["errors"]:
        print(f"   ❌ {err}")
