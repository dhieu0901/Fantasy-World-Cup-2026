import json
import sqlite3
import glob
import os
import difflib
from pathlib import Path

DB_PATH = Path(__file__).parent / "wc2026.db"
CLUB_DIR = Path(__file__).parent.parent / "club"

COUNTRY_MAP = {
    "USA": "USA",
    "South_Korea": "Korea Republic",
    "Korea Republic": "Korea Republic",
    "DR_Congo": "Congo DR",
    "Ivory_Coast": "Cte d'Ivoire",
    "Cape_Verde": "Cabo Verde",
    "Bosnia": "Bosnia and Herzegovina",
    "Czech_Republic": "Czechia",
    "Saudi_Arabia": "Saudi Arabia",
    "South_Africa": "South Africa",
    "New_Zealand": "New Zealand",
    "Curacao": "Curaao",
    "Iran": "IR Iran",
    "Turkey": "Trkiye"
}

def normalize_name(name):
    if not name: return ""
    import unicodedata
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    return name.lower().replace("-", " ").strip()

def match_player(fotmob_name, db_players):
    """Match fotmob_name against a list of db_players (dicts)."""
    norm_f_name = normalize_name(fotmob_name)
    best_match = None
    best_ratio = 0.0
    
    for db_p in db_players:
        # Check against known_name
        n_known = normalize_name(db_p['known_name'])
        # Check against full name
        n_full = normalize_name(f"{db_p['first_name']} {db_p['last_name']}")
        
        # Exact match
        if norm_f_name == n_known or norm_f_name == n_full:
            return db_p
        
        # Substring match (e.g. "Son Heung-min" vs "Heung-Min Son")
        if n_known and (norm_f_name in n_known or n_known in norm_f_name):
            ratio = 0.95
        elif n_full and (norm_f_name in n_full or n_full in norm_f_name):
            ratio = 0.9
        else:
            r1 = difflib.SequenceMatcher(None, norm_f_name, n_known).ratio() if n_known else 0
            r2 = difflib.SequenceMatcher(None, norm_f_name, n_full).ratio() if n_full else 0
            ratio = max(r1, r2)
            
        if ratio > best_ratio:
            best_ratio = ratio
            best_match = db_p

    if best_ratio > 0.75:
        return best_match
    return None

def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    # Load squads
    squads = {row['name']: dict(row) for row in conn.execute("SELECT * FROM squads")}
    
    # Load players by squad_id
    players_by_squad = {}
    for row in conn.execute("SELECT * FROM players"):
        sid = row['squad_id']
        if sid not in players_by_squad:
            players_by_squad[sid] = []
        players_by_squad[sid].append(dict(row))
        
    # Clear existing fotmob data
    conn.execute("DELETE FROM player_xstats WHERE source = 'fotmob'")
    
    matched_count = 0
    total_scraped = 0
    unmatched_players = []
    
    for filepath in glob.glob(str(CLUB_DIR / "*.json")):
        filename = os.path.basename(filepath)
        nationality_raw = filename.replace(".json", "")
        
        # Map nationality to db squad name
        squad_name = nationality_raw.replace("_", " ")
        if nationality_raw in COUNTRY_MAP:
            squad_name = COUNTRY_MAP[nationality_raw]
            
        if squad_name not in squads:
            print(f"Warning: Squad '{squad_name}' not found in DB! Skipping.")
            continue
            
        squad_id = squads[squad_name]['id']
        db_squad_players = players_by_squad.get(squad_id, [])
        
        with open(filepath, 'r', encoding='utf-8') as f:
            scraped_players = json.load(f)
            
        for sp in scraped_players:
            if not isinstance(sp, dict):
                continue
            total_scraped += 1
            db_p = match_player(sp['name'], db_squad_players)
            
            if not db_p:
                unmatched_players.append(f"{sp['name']} ({squad_name})")
                continue
                
            matched_count += 1
            
            # Extract stats
            pid = db_p['id']
            mins = sp.get('appearances', {}).get('minutes_played') or 0
            matches = sp.get('appearances', {}).get('matches_played') or 0
            
            # Safe per90 division
            nineties = mins / 90.0 if mins > 0 else 1.0
            
            c_stats = sp.get('core_stats', {})
            d_actions = sp.get('detailed_actions', {})
            disc = sp.get('discipline', {})
            gk_stats = sp.get('goalkeeping_metrics', {})
            
            goals = c_stats.get('goals') or 0
            assists = c_stats.get('assists') or 0
            xg = c_stats.get('xg') or 0.0
            xa = c_stats.get('xa') or 0.0
            
            shots = d_actions.get('shots') or 0
            shots_on_target = d_actions.get('shots_on_target') or 0
            chances = d_actions.get('chances_created') or 0
            tackles = d_actions.get('tackles') or 0
            interceptions = d_actions.get('interceptions') or 0
            clearances = d_actions.get('clearances') or 0
            
            saves = gk_stats.get('saves') or 0
            clean_sheets = c_stats.get('clean_sheets') or 0
            goals_conceded = c_stats.get('goals_conceded') or 0
            xgc = c_stats.get('xgc') or 0.0
            
            yellows = disc.get('yellow_cards') or 0
            reds = disc.get('red_cards') or 0
            
            MIN_MINUTES = 45
            
            if mins >= MIN_MINUTES:
                nineties = mins / 90.0
                xg_per90 = float(xg)/nineties
                xa_per90 = float(xa)/nineties
                shots_per90 = shots/nineties
                tackles_per90 = tackles/nineties
                chances_per90 = chances/nineties
                saves_per90 = saves/nineties
                yellows_per90 = yellows/nineties
            else:
                nineties = 1.0
                xg_per90 = 0.0
                xa_per90 = 0.0
                shots_per90 = 0.0
                tackles_per90 = 0.0
                chances_per90 = 0.0
                saves_per90 = 0.0
                yellows_per90 = 0.0
            
            # Upsert
            conn.execute("""
                INSERT OR REPLACE INTO player_xstats (
                    player_id, source, season, competition,
                    matches_played, minutes_played, goals, assists,
                    xG, xA, xG_per90, xA_per90, shots, shots_on_target, shots_per90,
                    tackles, tackles_per90, interceptions, clearances,
                    chances_created, chances_created_per90,
                    saves, saves_per90, clean_sheets, goals_conceded, xGC,
                    yellow_cards, red_cards, yellow_per90
                ) VALUES (
                    ?, 'fotmob', '2025-26', 'Club',
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?
                )
            """, (
                pid, matches, mins, goals, assists,
                float(xg), float(xa), xg_per90, xa_per90, shots, shots_on_target, shots_per90,
                tackles, tackles_per90, interceptions, clearances,
                chances, chances_per90,
                saves, saves_per90, clean_sheets, goals_conceded, float(xgc),
                yellows, reds, yellows_per90
            ))
            
    conn.commit()
    conn.close()
    
    with open('unmatched_players.txt', 'w', encoding='utf-8') as f:
        for p in unmatched_players:
            f.write(f"{p}\n")
            
    print("\n--- IMPORT COMPLETE ---")
    print(f"Total FotMob players scanned: {total_scraped}")
    print(f"Matched with DB players: {matched_count}")
    print(f"Unmatched (skipped): {total_scraped - matched_count}")
    print(f"Coverage: {matched_count/total_scraped*100:.1f}%")

if __name__ == "__main__":
    main()
