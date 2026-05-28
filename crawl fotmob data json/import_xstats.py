import sqlite3
import json
import unicodedata

def normalize(name):
    """Normalize diacritics for matching"""
    if not name:
        return ""
    return ''.join(c for c in unicodedata.normalize('NFD', name)
                   if unicodedata.category(c) != 'Mn').lower().strip()

def main():
    conn = sqlite3.connect('d:/code/fantasy wc/backend/wc2026.db')
    conn.row_factory = sqlite3.Row
    
    # Get all squads
    squads = {r['name'].lower(): r['id'] for r in conn.execute("SELECT id, name FROM squads").fetchall()}
    
    # Fix squad name mapping for Curacao if needed (e.g. "Curaçao")
    # Actually, we can normalize squad names too
    squads_norm = {normalize(name): sid for name, sid in squads.items()}
    
    # Get all players
    players = conn.execute("SELECT p.id, p.first_name, p.last_name, p.known_name, s.name as squad_name FROM players p JOIN squads s ON p.squad_id = s.id").fetchall()
    
    db_players = []
    for p in players:
        db_players.append({
            'id': p['id'],
            'first': normalize(p['first_name']),
            'last': normalize(p['last_name']),
            'known': normalize(p['known_name']),
            'squad': normalize(p['squad_name'])
        })
    
    # Read cleaned data
    with open('cleaned/all_players_clean.json', 'r', encoding='utf-8') as f:
        cleaned = json.load(f)
    
    matched_count = 0
    not_matched = []
    
    # Clear old fotmob data for these countries just to be safe
    # Though player_xstats has a unique constraint on (player_id, source, competition)
    # We will use INSERT OR REPLACE
    
    for c in cleaned:
        c_name = normalize(c['name'])
        c_squad = normalize(c['country'])
        
        # Find matching player in db
        match = None
        for p in db_players:
            if p['squad'] == c_squad:
                if c_name == p['known'] or c_name == p['last'] or c_name == p['first'] + ' ' + p['last'] or c_name == p['first']:
                    match = p
                    break
                # Try partial match (e.g. "Eric Garcia" vs "Eric Garcia")
                if p['known'] and p['known'] in c_name:
                    match = p
                    break
                if p['last'] and p['last'] in c_name and p['first'] and p['first'] in c_name:
                    match = p
                    break

        if match:
            # Insert into player_xstats
            conn.execute("""
                INSERT OR REPLACE INTO player_xstats (
                    player_id, source, competition,
                    matches_played, minutes_played, goals, assists,
                    xG, xA, xG_per90, xA_per90, shots, shots_on_target, shots_per90,
                    tackles, tackles_per90, interceptions, clearances,
                    chances_created, chances_created_per90,
                    saves, saves_per90, clean_sheets, goals_conceded, xGC,
                    yellow_cards, red_cards, yellow_per90, fotmob_id, updated_at
                ) VALUES (
                    ?, 'fotmob', 'WC2026',
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, datetime('now')
                )
            """, (
                match['id'],
                c['matches_played'], c['minutes_played'], c['goals'], c['assists'],
                c['xG'], c['xA'], c['xG_per90'], c['xA_per90'], c['shots'], c['shots_on_target'], c['shots_per90'],
                c['tackles'], c['tackles_per90'], c['interceptions'], c['clearances'],
                c['chances_created'], c['chances_created_per90'],
                c['saves'], c['saves_per90'], c['clean_sheets'], c['goals_conceded'], c['xGC'],
                c['yellow_cards'], c['red_cards'], c['yellow_per90'], c['fotmob_id']
            ))
            matched_count += 1
        else:
            not_matched.append(c['name'] + " (" + c['country'] + ")")
    
    conn.commit()
    print(f"Matched and imported: {matched_count}/{len(cleaned)}")
    if not_matched:
        print("Not matched:")
        for nm in not_matched:
            print("  ", nm)
            
if __name__ == '__main__':
    main()
