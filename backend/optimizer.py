"""
Squad Optimizer — Find the best Fantasy WC2026 squad using Linear Programming.
===============================================================================

Uses PuLP to solve the constrained optimization problem:
  Maximize: sum of xPts (or points-per-million) for 15 players
  Subject to:
    - Budget: <= $100m (group) / $105m (knockout)
    - Positions: exactly 2 GK, 5 DEF, 5 MID, 3 FWD
    - Country limit: max N per country (varies by stage)
    - Starting XI: 11 players in a valid formation

Presets:
  - default:   Balanced, maximize total xPts
  - value:     Maximize points-per-million (budget gems)
  - safe:      Prefer high-ownership, consistent players
  - risky:     Prefer low-ownership, high-ceiling differentials
  - template:  Popular picks + budget enablers
"""

import sqlite3
from datetime import datetime, timezone

from database import get_connection, init_db
from rules import (
    SQUAD_RULES, GOAL_POINTS,
    calculate_simple_xpts, calculate_xpts_from_db,
    validate_squad,
)

# Try PuLP, fallback to greedy
try:
    import pulp
    HAS_PULP = True
except ImportError:
    HAS_PULP = False
    print("[!] PuLP not installed. Using greedy optimizer. Install: pip install pulp")


# ══════════════════════════════════════════════
# TEAM STRENGTH RATINGS (FIFA ranking-based)
# ══════════════════════════════════════════════

# Simplified strength ratings (0-1) based on FIFA rankings / Elo
# Will be used for xPts calculations
TEAM_STRENGTH = {
    # Top tier (0.85-0.95) - FDR 5
    "FRA": 0.95, "ESP": 0.94, "ARG": 0.93, "ENG": 0.92,
    "POR": 0.91, "BRA": 0.90, "NED": 0.89, "MAR": 0.88,
    # Strong (0.75-0.84) - FDR 4
    "BEL": 0.84, "GER": 0.83, "CRO": 0.82, "COL": 0.81,
    "SEN": 0.80, "MEX": 0.79, "USA": 0.78, "URU": 0.77,
    # Mid tier (0.60-0.74) - FDR 3
    "JPN": 0.74, "SUI": 0.73, "IRN": 0.72, "TUR": 0.71,
    "ECU": 0.70, "AUT": 0.69, "KOR": 0.68, "AUS": 0.67,
    "ALG": 0.66, "EGY": 0.65, "CAN": 0.64, "NOR": 0.63,
    "PAN": 0.62, "CIV": 0.61, "SWE": 0.61, "PAR": 0.60, "CZE": 0.60,
    # Lower Mid tier (0.50-0.59) - FDR 2
    "SCO": 0.59, "TUN": 0.58, "COD": 0.57, "UZB": 0.56,
    "QAT": 0.55, "IRQ": 0.54, "KSA": 0.53, "RSA": 0.52,
    "GHA": 0.51, "CPV": 0.50,
    # Lower tier (0.40-0.49) - FDR 1
    "BIH": 0.49, "JOR": 0.48, "HAI": 0.46, "CUW": 0.44, "NZL": 0.42,
}


def get_team_strength(abbr: str) -> float:
    """Get team strength rating, default 0.50 for unknown teams."""
    return TEAM_STRENGTH.get(abbr, 0.50)


# ══════════════════════════════════════════════
# PLAYER SCORING — Calculate projected points
# ══════════════════════════════════════════════

def project_player_points(player: dict, conn: sqlite3.Connection = None,
                          opponent_abbr: str = None) -> float:
    """
    Project Fantasy points for a player for their next match.
    Uses xPts engine with real stats if available.
    """
    team_str = get_team_strength(player.get("team_abbr", ""))
    opp_str = get_team_strength(opponent_abbr) if opponent_abbr else 0.50

    result = calculate_xpts_from_db(
        player_id=player["id"],
        position=player["position"],
        price=player["price"],
        percent_selected=player.get("percent_selected", 50),
        team_strength=team_str,
        opponent_strength=opp_str,
        is_home=True,  # Simplified — could check from fixtures
        conn=conn,
    )

    return result.get("xPts", 2.0)


# ══════════════════════════════════════════════
# GREEDY OPTIMIZER (fallback when PuLP unavailable)
# ══════════════════════════════════════════════

def optimize_greedy(players: list[dict], stage: str = "GROUP_MD1", preset: str = "default", chip: str = "none", locked_in: list[int] = None, locked_out: list[int] = None) -> dict:
    """
    Fallback greedy optimizer if PuLP is not available or fails.
    """
    locked_in = set(locked_in or [])
    locked_out = set(locked_out or [])

    # Filter out locked_out players immediately
    players = [p for p in players if p["id"] not in locked_out]

    # ─── PRE-SELECT 12TH MAN ───
    twelfth_man = None
    if chip == "12th_man":
        if players:
            twelfth_man = max(players, key=lambda p: p.get("projected_pts", 0))
            players = [p for p in players if p["id"] != twelfth_man["id"]]

    budget = SQUAD_RULES["budget"]["group_stage"]
    if stage in ("ROUND_OF_32", "ROUND_OF_16", "QUARTER_FINAL", "SEMI_FINAL", "FINAL"):
        budget = SQUAD_RULES["budget"]["knockout_stage"]

    max_per_country = SQUAD_RULES["max_per_country"].get(stage, 3)
    requirements = {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}

    # Score each player based on preset
    for p in players:
        xpts = p.get("projected_pts", 2.0)
        price = p.get("price", 4.0)
        pct = p.get("percent_selected", 50)

        if preset == "value":
            p["_score"] = (xpts / max(price, 3.5)) * 10  # Points per million
        elif preset == "safe":
            p["_score"] = xpts * (1 + pct / 200)  # Boost popular picks
        elif preset == "risky":
            p["_score"] = xpts * (1 + (100 - pct) / 200)  # Boost differentials
        elif preset == "template":
            p["_score"] = xpts + (pct / 15.0)
        else:
            p["_score"] = xpts

        # Qualification booster EV for Greedy
        if chip == "qualification" and stage not in ("GROUP_MD1", "GROUP_MD2", "GROUP_MD3"):
            p["_score"] += 1.0

        # Boost locked_in players so they are always picked
        if p["id"] in locked_in:
            p["_score"] += 1000.0

    selected = []
    country_counts = {}
    spent = 0.0

    for pos, count in requirements.items():
        # Get candidates for this position, sorted by score
        candidates = sorted(
            [p for p in players if p["position"] == pos and p["id"] not in {s["id"] for s in selected}],
            key=lambda x: x["_score"],
            reverse=True,
        )

        picked = 0
        for p in candidates:
            if picked >= count:
                break

            sid = p.get("squad_id", 0)
            cc = country_counts.get(sid, 0)

            if cc >= max_per_country:
                continue
            if spent + p["price"] > budget - (sum(requirements.values()) - len(selected) - 1) * 3.5:
                # Reserve minimum budget for remaining slots
                remaining_slots = sum(requirements.values()) - len(selected) - 1
                if remaining_slots > 0 and spent + p["price"] > budget - remaining_slots * 3.5:
                    continue

            selected.append(p)
            spent += p["price"]
            country_counts[sid] = cc + 1
            picked += 1

    # Select starting XI (best 11 in a valid formation)
    starting_xi, bench = _select_starting_xi(selected, chip, stage)

    # Captain = highest projected points in starting XI
    captain = max(starting_xi, key=lambda p: p.get("projected_pts", 0)) if starting_xi else None
    
    vice_candidates = [p for p in starting_xi if not captain or p["id"] != captain["id"]]
    vice_captain = max(vice_candidates, key=lambda p: p.get("projected_pts", 0)) if vice_candidates else None

    # Handle 12th Man Booster
    if twelfth_man:
        twelfth_man["is_12th_man"] = True
        starting_xi.append(twelfth_man)
        selected.append(twelfth_man)

    total_xpts = sum(p.get("projected_pts", 0) for p in starting_xi)

    # Handle Maximum Captain Booster (captain scores double xPts: 1x base + 1x bonus)
    if chip == "max_captain":
        if captain:
            total_xpts += captain.get("projected_pts", 0)  # Max captain is identical to normal captain in EV terms
    else:
        if captain:
            total_xpts += captain.get("projected_pts", 0)  # Normal double for captain

    # Handle Qualification Booster
    if chip == "qualification" and stage not in ("GROUP_MD1", "GROUP_MD2", "GROUP_MD3"):
        for p in starting_xi:
            total_xpts += 1.0  # +1.0 EV for advancing
            p["projected_pts"] += 1.0

    return {
        "squad": selected,
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "budget_used": spent,
        "budget_remaining": budget - spent,
        "total_projected_pts": round(total_xpts, 1),
        "preset": preset,
        "stage": stage,
        "chip": chip,
        "method": "greedy",
    }


# ══════════════════════════════════════════════
# LP OPTIMIZER (PuLP — globally optimal)
# ══════════════════════════════════════════════

def optimize_lp(players: list[dict], stage: str = "GROUP_MD1",
                preset: str = "default",
                locked_in: list[int] = None,
                locked_out: list[int] = None,
                chip: str = "none",
                current_squad: list[int] = None,
                free_transfers: int = 2) -> dict:
    """
    Linear Programming squad optimizer using PuLP.
    Finds the globally optimal squad.
    
    Args:
        players: list of player dicts with projected_pts
        stage: tournament stage for constraints
        preset: scoring preset (affects objective weights)
        locked_in: player IDs that must be in the squad
        locked_out: player IDs that must NOT be in the squad
    """
    if not HAS_PULP:
        return optimize_greedy(players, stage, preset, chip, list(locked_in) if locked_in else None, list(locked_out) if locked_out else None)

    budget = SQUAD_RULES["budget"]["group_stage"]
    if stage in ("ROUND_OF_32", "ROUND_OF_16", "QUARTER_FINAL", "SEMI_FINAL", "FINAL"):
        budget = SQUAD_RULES["budget"]["knockout_stage"]

    max_per_country = SQUAD_RULES["max_per_country"].get(stage, 3)
    locked_in = set(locked_in or [])
    locked_out = set(locked_out or [])
    current_squad = set(current_squad or [])

    # Calculate objective values based on preset
    obj_values = {}
    for p in players:
        pid = p["id"]
        xpts = p.get("projected_pts", 2.0)
        price = p.get("price", 4.0)
        pct = p.get("percent_selected", 50)

        if preset == "value":
            obj_values[pid] = xpts + (15.0 - price) * 0.2  # Additive bonus for cheap players
        elif preset == "safe":
            obj_values[pid] = xpts + (pct / 30.0)  # Additive bonus for popular (up to +3.3)
        elif preset == "risky":
            obj_values[pid] = xpts + ((100.0 - pct) / 30.0)  # Additive bonus for differentials (up to +3.3)
        elif preset == "template":
            obj_values[pid] = xpts + (pct / 15.0)  # Strong additive bonus for popular (up to +6.6)
        else:
            obj_values[pid] = xpts
            
        # Qualification booster: players in XI get +2 if team advances (~50% chance = +1.0 EV)
        if chip == "qualification" and stage not in ("GROUP_MD1", "GROUP_MD2", "GROUP_MD3"):
            obj_values[pid] += 1.0

    # Create problem
    prob = pulp.LpProblem("WC2026_Fantasy_Optimizer", pulp.LpMaximize)

    # Decision variables
    squad_vars = {}     # x[i] = 1 if player i is in the 15-man squad
    xi_vars = {}        # xi[i] = 1 if player i is in the Starting XI
    cap_vars = {}       # c[i] = 1 if player i is the Captain
    twelfth_vars = {}   # t[i] = 1 if player i is the 12th man
    
    for p in players:
        pid = p["id"]
        squad_vars[pid] = pulp.LpVariable(f"squad_{pid}", cat="Binary")
        xi_vars[pid] = pulp.LpVariable(f"xi_{pid}", cat="Binary")
        cap_vars[pid] = pulp.LpVariable(f"cap_{pid}", cat="Binary")
        twelfth_vars[pid] = pulp.LpVariable(f"12th_{pid}", cat="Binary")
        
        # Constraints tying variables together
        prob += xi_vars[pid] <= squad_vars[pid], f"Xi_in_Squad_{pid}"
        prob += cap_vars[pid] <= xi_vars[pid], f"Cap_in_Xi_{pid}"
        prob += twelfth_vars[pid] + squad_vars[pid] <= 1, f"Mutually_Exclusive_12th_{pid}"

    if chip == "12th_man":
        prob += pulp.lpSum(twelfth_vars[p["id"]] for p in players) == 1, "One12thMan"
    else:
        prob += pulp.lpSum(twelfth_vars[p["id"]] for p in players) == 0, "No12thMan"

    # Objective: maximize weighted projected points from Starting XI + Captain bonus + 12th man
    objective = pulp.lpSum(
        obj_values.get(p["id"], 0) * xi_vars[p["id"]] + 
        obj_values.get(p["id"], 0) * cap_vars[p["id"]] +
        obj_values.get(p["id"], 0) * twelfth_vars[p["id"]]
        for p in players
    )
    
    # ─── SMART BENCHING (Manual Sub Optimization) ───
    try:
        import json
        from pathlib import Path
        stage_filename = stage.lower() + ".json"
        fixtures_path = Path(__file__).parent.parent / "fixtures" / stage_filename
        if not fixtures_path.exists():
            fixtures_path = Path(__file__).parent.parent / "fixtures" / "matchday_1.json"
            
        with open(fixtures_path, "r", encoding="utf-8") as f:
            fixtures = json.load(f)
            
        team_day_map = {}
        for match in fixtures:
            team_day_map[match["team_1"]] = match["day_index"]
            team_day_map[match["team_2"]] = match["day_index"]
            
        # Get squad ID -> team Name mapping from DB
        conn = sqlite3.connect(Path(__file__).parent / "wc2026.db")
        squads = {row[0]: row[1] for row in conn.execute("SELECT id, name FROM squads")}
        conn.close()
        
        # Identify MAX_DAY for fallback (teams not in fixture file)
        MAX_DAY = max(team_day_map.values()) if team_day_map else 7
        
        # ─── DYNAMIC BENCH WEIGHTING (The WC Fantasy Secret) ───
        # In FPL, the bench is largely useless (weight ~0.1).
        # In World Cup (Manual Subs), the bench is incredibly valuable, BUT ONLY if they play LATE.
        # Scale from 0.1 (Day 1) to 0.4 (Max Day) to ensure Starting XI is still prioritized.
        for p in players:
            pid = p["id"]
            team_name = squads.get(p.get("squad_id", 0), "")
            day_idx = team_day_map.get(team_name, 1)
            
            # Increase bench weight to 0.4 (from 0.1) to encourage better bench quality
            bench_weight = 0.4 + 0.2 * ((day_idx - 1) / max(1, MAX_DAY - 1))
            
            objective += obj_values.get(pid, 0) * bench_weight * (squad_vars[pid] - xi_vars[pid])

        # Formula: 0.01 * (MAX_DAY - day_index) * xi_vars[pid]
        # This rewards putting EARLY players (day_index = 1) in the Starting XI (xi_vars = 1)
        objective += pulp.lpSum(
            0.01 * (MAX_DAY - team_day_map.get(squads.get(p.get("squad_id"), ""), MAX_DAY)) * xi_vars[p["id"]]
            for p in players
        )
    except Exception as e:
        print(f"  [!] Could not load fixtures for smart benching: {e}")
        # Fallback to simple bench weight if fixtures fail
        objective += pulp.lpSum(
            obj_values.get(p["id"], 0) * 0.4 * (squad_vars[p["id"]] - xi_vars[p["id"]])
            for p in players
        )

    # Transfer Optimization (if current squad exists and not on Wildcard)
    extra_transfers_var = None
    if current_squad and chip != "wildcard":
        extra_transfers_var = pulp.LpVariable("ExtraTransfers", lowBound=0, cat="Continuous")
        
        # Transfers made = 15 - (players kept from current squad)
        players_kept = pulp.lpSum(squad_vars[pid] for pid in current_squad if pid in squad_vars)
        transfers_made = 15 - players_kept
        
        # ExtraTransfers >= TransfersMade - free_transfers
        prob += extra_transfers_var >= transfers_made - free_transfers, "TransferHitCalc"
        
        # Subtract 3 pts per extra transfer from objective
        objective -= 3.0 * extra_transfers_var

    prob += objective, "TotalProjectedPoints"

    # Constraint 1: Squad sizes
    prob += pulp.lpSum(squad_vars[p["id"]] for p in players) == 15, "SquadSize"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in players) == 11, "StartingXiSize"
    prob += pulp.lpSum(cap_vars[p["id"]] for p in players) == 1, "OneCaptain"

    # Constraint 2: Budget
    prob += pulp.lpSum(
        p["price"] * squad_vars[p["id"]] for p in players
    ) <= budget, "Budget"

    # Constraint 3: Position requirements for 15-man squad
    for pos, limits in SQUAD_RULES["positions"].items():
        pos_players = [p for p in players if p["position"] == pos]
        prob += pulp.lpSum(
            squad_vars[p["id"]] for p in pos_players
        ) == limits["min"], f"Position_{pos}"

    # Constraint 3b: Valid formation for Starting XI
    gk_players = [p for p in players if p["position"] == "GK"]
    def_players = [p for p in players if p["position"] == "DEF"]
    mid_players = [p for p in players if p["position"] == "MID"]
    fwd_players = [p for p in players if p["position"] == "FWD"]

    prob += pulp.lpSum(xi_vars[p["id"]] for p in gk_players) == 1, "Xi_GK"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in def_players) >= 3, "Xi_DEF_Min"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in def_players) <= 5, "Xi_DEF_Max"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in mid_players) >= 2, "Xi_MID_Min"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in mid_players) <= 5, "Xi_MID_Max"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in fwd_players) >= 1, "Xi_FWD_Min"
    prob += pulp.lpSum(xi_vars[p["id"]] for p in fwd_players) <= 3, "Xi_FWD_Max"

    # Constraint 4: Max per country
    squad_ids = set(p.get("squad_id", 0) for p in players)
    for sid in squad_ids:
        country_players = [p for p in players if p.get("squad_id") == sid]
        prob += pulp.lpSum(
            squad_vars[p["id"]] for p in country_players
        ) <= max_per_country, f"Country_{sid}"
        
        # Hard constraint: Max 1 LB and Max 1 RB per team
        team_lbs = [p for p in country_players if p.get("raw_position") in ["Left Back", "Left Wing-Back"]]
        if team_lbs:
            prob += pulp.lpSum(squad_vars[p["id"]] for p in team_lbs) <= 1, f"MaxLB_{sid}"
            
        team_rbs = [p for p in country_players if p.get("raw_position") in ["Right Back", "Right Wing-Back"]]
        if team_rbs:
            prob += pulp.lpSum(squad_vars[p["id"]] for p in team_rbs) <= 1, f"MaxRB_{sid}"

    # Constraint 5: Locked in/out
    for pid in locked_in:
        if pid in squad_vars:
            prob += squad_vars[pid] + twelfth_vars[pid] == 1, f"LockedIn_{pid}"
    for pid in locked_out:
        if pid in squad_vars:
            prob += squad_vars[pid] + twelfth_vars[pid] == 0, f"LockedOut_{pid}"

    # Solve
    prob.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=10))

    if prob.status != pulp.constants.LpStatusOptimal:
        print(f"  [!] LP solver status: {pulp.LpStatus[prob.status]}. Falling back to greedy.")
        return optimize_greedy(players, stage, preset, chip)

    # Extract selected players
    selected = []
    starting_xi = []
    captain = None
    twelfth_man = None
    for p in players:
        pid = p["id"]
        if twelfth_vars[pid].varValue and twelfth_vars[pid].varValue > 0.5:
            twelfth_man = p
            twelfth_man["is_12th_man"] = True
            
        if squad_vars[pid].varValue and squad_vars[pid].varValue > 0.5:
            selected.append(p)
            if xi_vars[pid].varValue and xi_vars[pid].varValue > 0.5:
                starting_xi.append(p)
                if cap_vars[pid].varValue and cap_vars[pid].varValue > 0.5:
                    captain = p

    # Ensure starting_xi format matches what greedy would return
    if len(starting_xi) != 11:
        starting_xi, bench = _select_starting_xi(selected, chip, stage)
        captain = max(starting_xi, key=lambda p: p.get("projected_pts", 0)) if starting_xi else None
    else:
        bench = [p for p in selected if p not in starting_xi]

    vice_candidates = [p for p in starting_xi if not captain or p["id"] != captain["id"]]
    vice_captain = max(vice_candidates, key=lambda p: p.get("projected_pts", 0)) if vice_candidates else None

    # Handle 12th Man Booster
    if twelfth_man:
        starting_xi.append(twelfth_man)
        selected.append(twelfth_man)

    spent = sum(p["price"] for p in selected if not p.get("is_12th_man"))
    total_xpts = sum(p.get("projected_pts", 0) for p in starting_xi)

    # Handle Maximum Captain Booster (captain scores double xPts: 1x base + 1x bonus)
    if chip == "max_captain":
        if captain:
            total_xpts += captain.get("projected_pts", 0)  # Max captain is identical to normal captain in EV terms
    else:
        if captain:
            total_xpts += captain.get("projected_pts", 0)  # Normal double for captain
        
    # Handle Qualification Booster
    if chip == "qualification" and stage not in ("GROUP_MD1", "GROUP_MD2", "GROUP_MD3"):
        for p in starting_xi:
            total_xpts += 1.0  # +1.0 EV for advancing
            p["projected_pts"] += 1.0

    # Calculate actual transfers
    transfers_in = []
    transfers_out = []
    transfer_cost = 0
    if current_squad:
        selected_ids = {p["id"] for p in selected if not p.get("is_12th_man")}
        transfers_in = [p for p in selected if p["id"] not in current_squad and not p.get("is_12th_man")]
        transfers_out = list(current_squad - selected_ids)
        if chip != "wildcard":
            extra = max(0, len(transfers_in) - free_transfers)
            transfer_cost = extra * 3

    return {
        "squad": selected,
        "starting_xi": starting_xi,
        "bench": bench,
        "captain": captain,
        "vice_captain": vice_captain,
        "budget_used": round(spent, 1),
        "budget_remaining": round(budget - spent, 1),
        "total_projected_pts": round(total_xpts, 1),
        "transfers_in": transfers_in,
        "transfers_out": transfers_out,
        "transfer_cost": transfer_cost,
        "preset": preset,
        "stage": stage,
        "chip": chip,
        "method": "lp" if HAS_PULP else "greedy",
        "solver_status": pulp.LpStatus[prob.status],
    }


# ══════════════════════════════════════════════
# STARTING XI SELECTION
# ══════════════════════════════════════════════

def _select_starting_xi(squad: list[dict], chip: str = "none", stage: str = "GROUP_MD1") -> tuple[list[dict], list[dict]]:
    """
    Select best starting XI from 15-player squad in a valid formation.
    Returns (starting_xi, bench).
    """
    valid_formations = [
        {"GK": 1, "DEF": 4, "MID": 4, "FWD": 2},
        {"GK": 1, "DEF": 4, "MID": 3, "FWD": 3},
        {"GK": 1, "DEF": 4, "MID": 5, "FWD": 1},
        {"GK": 1, "DEF": 3, "MID": 4, "FWD": 3},
        {"GK": 1, "DEF": 3, "MID": 5, "FWD": 2},
        {"GK": 1, "DEF": 5, "MID": 4, "FWD": 1},
        {"GK": 1, "DEF": 5, "MID": 3, "FWD": 2},
    ]

    # Group by position
    by_pos = {"GK": [], "DEF": [], "MID": [], "FWD": []}
    for p in squad:
        pos = p.get("position", "MID")
        if pos in by_pos:
            by_pos[pos].append(p)

    # Sort each position group by next_match_date (earliest first), then projected points (boosted by qualification)
    qual_bonus = 1.0 if (chip == "qualification" and stage not in ("GROUP_MD1", "GROUP_MD2", "GROUP_MD3")) else 0.0
    for pos in by_pos:
        by_pos[pos].sort(key=lambda p: (
            p.get("next_match_date") or "2099-12-31T00:00:00Z",
            -(p.get("projected_pts", 0) + qual_bonus)
        ))

    # Try each formation, pick the one with highest total xPts from starters? 
    # Actually, we want to maximize early players, but valid formations must be met.
    # Since we sorted by_pos by earliest date first, the top players in by_pos 
    # are the ones playing earliest. So any valid formation will pick earliest players.
    best_xi = None
    best_score = -1

    for formation in valid_formations:
        xi = []
        feasible = True

        for pos, count in formation.items():
            if len(by_pos.get(pos, [])) < count:
                feasible = False
                break
            xi.extend(by_pos[pos][:count])

        if not feasible or len(xi) != 11:
            continue

        score = sum(p.get("projected_pts", 0) for p in xi)
        if score > best_score:
            best_score = score
            best_xi = xi

    if best_xi is None:
        # Fallback: just take top 11 by date
        best_xi = sorted(squad, key=lambda p: (
            p.get("next_match_date") or "2099-12-31T00:00:00Z",
            -(p.get("projected_pts", 0) + qual_bonus)
        ))[:11]

    xi_ids = {p["id"] for p in best_xi}
    bench = [p for p in squad if p["id"] not in xi_ids]

    # Re-sort Bench by date
    bench.sort(key=lambda p: (
        p.get("next_match_date") or "2099-12-31T00:00:00Z",
        -(p.get("projected_pts", 0) + qual_bonus)
    ))

    return best_xi, bench


# ══════════════════════════════════════════════
# PUBLIC API — Main optimization function
# ══════════════════════════════════════════════

def optimize_squad(stage: str = "GROUP_MD1",
                   preset: str = "default",
                   locked_in: list[int] = None,
                   locked_out: list[int] = None,
                   use_lp: bool = True,
                   chip: str = "none",
                   current_squad: list[int] = None,
                   free_transfers: int = 2) -> dict:
    """
    Main entry point for squad optimization.
    
    Args:
        stage: Tournament stage (GROUP_MD1, ROUND_OF_16, etc.)
        preset: Optimization preset (default, value, safe, risky, template)
        locked_in: Player IDs that must be included
        locked_out: Player IDs that must be excluded
        use_lp: Use LP solver if available (True) or force greedy (False)
        chip: Active booster chip (none, 12th_man, etc)
    
    Returns:
        dict with optimized squad, starting XI, captain, budget info
    """
    conn = get_connection()
    init_db(conn)

    stage_to_round = {
        "GROUP_MD1": 1, "GROUP_MD2": 2, "GROUP_MD3": 3,
        "ROUND_OF_32": 4, "ROUND_OF_16": 5, "QUARTER_FINAL": 6,
        "SEMI_FINAL": 7, "FINAL": 8,
    }
    round_id = stage_to_round.get(stage, 1)

    # Get all active players with their stats and next match date
    rows = conn.execute("""
        SELECT p.id, p.first_name, p.last_name, p.known_name,
               p.squad_id, p.position, p.price, p.status, p.raw_position,
               p.percent_selected, p.total_points, p.avg_points, p.form,
               s.name as team_name, s.abbr as team_abbr, s."group" as team_group,
               MIN(f.match_date) as next_match_date
        FROM players p
        LEFT JOIN squads s ON p.squad_id = s.id
        LEFT JOIN fixtures f ON (f.home_squad_id = s.id OR f.away_squad_id = s.id) AND f.round_id = ?
        WHERE p.is_active = 1 AND p.status = 'playing'
        GROUP BY p.id
        ORDER BY p.price DESC
    """, (round_id,)).fetchall()

    players = []
    for r in rows:
        p = dict(r)
        p["display_name"] = p["known_name"] or f"{p['first_name']} {p['last_name']}"
        p["projected_pts"] = project_player_points(p, conn)
        players.append(p)

    conn.close()

    # Run optimizer
    if use_lp and HAS_PULP:
        result = optimize_lp(players, stage, preset, locked_in, locked_out, chip, current_squad, free_transfers)
    else:
        result = optimize_greedy(players, stage, preset, chip, locked_in, locked_out)

    # Clean up internal fields
    for p in result.get("squad", []):
        p.pop("_score", None)

    return result


# ══════════════════════════════════════════════
# CLI TEST
# ══════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    preset = sys.argv[1] if len(sys.argv) > 1 else "default"
    stage = sys.argv[2] if len(sys.argv) > 2 else "GROUP_MD1"

    print(f"\n{'=' * 60}")
    print(f"  Squad Optimizer — Preset: {preset}, Stage: {stage}")
    print(f"{'=' * 60}\n")

    result = optimize_squad(stage=stage, preset=preset)

    print(f"  Method: {result['method']}")
    print(f"  Budget: ${result['budget_used']}m / ${result['budget_used'] + result['budget_remaining']}m")
    print(f"  Remaining: ${result['budget_remaining']}m")
    print(f"  Projected Points: {result['total_projected_pts']}")

    if result.get("captain"):
        cap = result["captain"]
        print(f"\n  Captain: {cap['display_name']} ({cap['position']}, {cap['team_name']})")
    if result.get("vice_captain"):
        vc = result["vice_captain"]
        print(f"  Vice-Captain: {vc['display_name']} ({vc['position']}, {vc['team_name']})")

    print(f"\n  Starting XI:")
    print(f"  {'Name':25s} {'Team':15s} {'Pos':4s} {'Price':6s} {'xPts':5s} {'Own%':5s}")
    print(f"  {'-' * 65}")
    for p in sorted(result["starting_xi"], key=lambda x: ["GK", "DEF", "MID", "FWD"].index(x["position"])):
        marker = " (C)" if result.get("captain") and p["id"] == result["captain"]["id"] else ""
        marker = " (VC)" if result.get("vice_captain") and p["id"] == result["vice_captain"]["id"] else marker
        print(f"  {p['display_name']:25s} {p.get('team_name', '?'):15s} {p['position']:4s} "
              f"${p['price']:<5.1f} {p.get('projected_pts', 0):5.1f} {p.get('percent_selected', 0):5.1f}{marker}")

    print(f"\n  Bench:")
    for p in result["bench"]:
        print(f"  {p['display_name']:25s} {p.get('team_name', '?'):15s} {p['position']:4s} "
              f"${p['price']:<5.1f} {p.get('projected_pts', 0):5.1f}")

    print()
