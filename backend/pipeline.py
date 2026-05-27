"""
FIFA Fantasy World Cup 2026 — Data Pipeline
=============================================
Cào data từ FIFA Fantasy API (public, không cần auth).
Chạy hàng ngày để tự động phát hiện:
  - Cầu thủ mới được thêm vào game
  - Thay đổi giá (price changes)
  - Cầu thủ bị loại / injured / status thay đổi
  - Kết quả trận đấu mới

Endpoints:
  1. play.fifa.com/json/fantasy/players.json     → players + price + stats
  2. play.fifa.com/json/fantasy/squads_fifa.json  → teams / national squads
  3. play.fifa.com/json/fantasy/rounds.json       → schedule + results

Usage:
  python pipeline.py                # Full sync (players + squads + fixtures)
  python pipeline.py --players-only # Only sync players (faster)
  python pipeline.py --schedule     # Run auto-sync every 4 hours
"""

import httpx
import asyncio
import sqlite3
import json
import sys
import time
import pandas as pd
from datetime import datetime, timezone
from pathlib import Path

# Import our database module
from database import get_connection, init_db, get_stats_summary

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
FIFA_BASE = "https://play.fifa.com/json/fantasy"
ENDPOINTS = {
    "players": f"{FIFA_BASE}/players.json",
    "squads":  f"{FIFA_BASE}/squads.json",       # IDs 1-48, matches players.squadId
    "squads_fifa": f"{FIFA_BASE}/squads_fifa.json", # FIFA IDs (43000+), has seed info
    "rounds":  f"{FIFA_BASE}/rounds.json",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

CSV_EXPORT_PATH = Path(__file__).parent / "exports"
CACHE_PATH = Path(__file__).parent / "cache"   # JSON snapshot fallback


# ──────────────────────────────────────────────
# FETCH — Download data from FIFA Fantasy API
# ──────────────────────────────────────────────
def _save_cache(name: str, data: list):
    """Save successful API response as JSON snapshot for fallback."""
    CACHE_PATH.mkdir(exist_ok=True)
    cache_file = CACHE_PATH / f"{name}.json"
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load_cache(name: str) -> list | None:
    """Load last successful JSON snapshot as fallback."""
    cache_file = CACHE_PATH / f"{name}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            print(f"  ↩ {name}: Loaded cache ({len(data)} records, {age_hours:.1f}h old)")
            return data
        except Exception as e:
            print(f"  ✗ {name}: Cache read error: {e}")
    return None


async def fetch_endpoint(client: httpx.AsyncClient, name: str, url: str) -> list | None:
    """Fetch a single endpoint with retry logic + fallback to cached JSON."""
    for attempt in range(3):
        try:
            resp = await client.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
            if resp.status_code == 200:
                data = resp.json()
                print(f"  ✓ {name}: {len(data)} records")
                _save_cache(name, data)  # Save snapshot for fallback
                return data
            else:
                print(f"  ⚠ {name}: HTTP {resp.status_code} (attempt {attempt + 1}/3)")
        except Exception as e:
            print(f"  ✗ {name}: {e} (attempt {attempt + 1}/3)")
        
        if attempt < 2:
            await asyncio.sleep(2 ** attempt)  # Exponential backoff

    # All retries failed — try fallback cache
    print(f"  ✗ {name}: FAILED after 3 attempts — trying cache fallback...")
    return _load_cache(name)


async def fetch_all_data(players_only: bool = False) -> dict:
    """Fetch all FIFA Fantasy endpoints."""
    async with httpx.AsyncClient() as client:
        if players_only:
            players = await fetch_endpoint(client, "players", ENDPOINTS["players"])
            return {"players": players, "squads": None, "rounds": None}
        
        # Fetch all endpoints concurrently
        results = await asyncio.gather(
            fetch_endpoint(client, "players", ENDPOINTS["players"]),
            fetch_endpoint(client, "squads",  ENDPOINTS["squads"]),
            fetch_endpoint(client, "squads_fifa", ENDPOINTS["squads_fifa"]),
            fetch_endpoint(client, "rounds",  ENDPOINTS["rounds"]),
        )
        return {
            "players":    results[0],
            "squads":     results[1],  # IDs 1-48 (matches players.squadId)
            "squads_fifa": results[2], # FIFA IDs (43000+), has seed/link info
            "rounds":     results[3],
        }


# ──────────────────────────────────────────────
# SYNC SQUADS — Upsert national teams
# ──────────────────────────────────────────────
def sync_squads(conn: sqlite3.Connection, squads: list) -> int:
    """Upsert squads. Handles both squads.json and squads_fifa.json formats."""
    if not squads:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    for s in squads:
        # Handle both formats:
        # squads.json: {id, name, group, abbr, isEliminated}
        # squads_fifa.json: {id, name, abbr, seed, squadLink, isActive, group, groupPosition}
        is_active = 1
        if "isEliminated" in s:
            is_active = 0 if s.get("isEliminated", False) else 1
        elif "isActive" in s:
            is_active = 1 if s.get("isActive", True) else 0

        cur.execute("""
            INSERT INTO squads (id, name, abbr, seed, squad_link, is_active, "group", group_position, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                abbr = excluded.abbr,
                seed = COALESCE(excluded.seed, squads.seed),
                squad_link = COALESCE(excluded.squad_link, squads.squad_link),
                is_active = excluded.is_active,
                "group" = excluded."group",
                group_position = COALESCE(excluded.group_position, squads.group_position),
                updated_at = excluded.updated_at
        """, (
            s.get("id"),
            s.get("name"),
            s.get("abbr"),
            s.get("seed"),
            s.get("squadLink"),
            is_active,
            s.get("group"),
            s.get("groupPosition"),
            now,
        ))

    conn.commit()
    return len(squads)


# ──────────────────────────────────────────────
# SYNC ROUNDS + FIXTURES — Upsert schedule
# ──────────────────────────────────────────────
def sync_rounds(conn: sqlite3.Connection, rounds: list) -> tuple[int, int]:
    """Upsert rounds and fixtures. Returns (rounds_count, fixtures_count)."""
    if not rounds:
        return 0, 0

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    total_fixtures = 0

    for r in rounds:
        # Upsert round
        cur.execute("""
            INSERT INTO rounds (id, status, start_date, end_date, stage, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                start_date = excluded.start_date,
                end_date = excluded.end_date,
                stage = excluded.stage,
                updated_at = excluded.updated_at
        """, (
            r.get("id"),
            r.get("status"),
            r.get("startDate"),
            r.get("endDate"),
            r.get("stage"),
            now,
        ))

        # Upsert each fixture/tournament in this round
        for t in r.get("tournaments", []):
            cur.execute("""
                INSERT INTO fixtures (
                    id, round_id, period, minutes, extra_minutes,
                    venue_name, venue_city, venue_id, match_date, status,
                    home_squad_id, away_squad_id,
                    home_squad_name, away_squad_name,
                    home_squad_abbr, away_squad_abbr,
                    home_score, away_score,
                    home_penalty_score, away_penalty_score,
                    home_scorers, away_scorers,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    period = excluded.period,
                    minutes = excluded.minutes,
                    extra_minutes = excluded.extra_minutes,
                    status = excluded.status,
                    home_score = excluded.home_score,
                    away_score = excluded.away_score,
                    home_penalty_score = excluded.home_penalty_score,
                    away_penalty_score = excluded.away_penalty_score,
                    home_scorers = excluded.home_scorers,
                    away_scorers = excluded.away_scorers,
                    updated_at = excluded.updated_at
            """, (
                t.get("id"),
                r.get("id"),
                t.get("period"),
                t.get("minutes", 0),
                t.get("extraMinutes", 0),
                t.get("venueName"),
                t.get("venueCity"),
                t.get("venueId"),
                t.get("date"),
                t.get("status"),
                t.get("homeSquadId"),
                t.get("awaySquadId"),
                t.get("homeSquadName"),
                t.get("awaySquadName"),
                t.get("homeSquadAbbr"),
                t.get("awaySquadAbbr"),
                t.get("homeScore"),
                t.get("awayScore"),
                t.get("homePenaltyScore"),
                t.get("awayPenaltyScore"),
                json.dumps(t.get("homeGoalScorersAssists")) if t.get("homeGoalScorersAssists") else None,
                json.dumps(t.get("awayGoalScorersAssists")) if t.get("awayGoalScorersAssists") else None,
                now,
            ))
            total_fixtures += 1

    conn.commit()
    return len(rounds), total_fixtures


# ──────────────────────────────────────────────
# SYNC PLAYERS — The core upsert logic
# ──────────────────────────────────────────────
def sync_players(conn: sqlite3.Connection, players: list) -> dict:
    """
    Upsert players with full change detection:
    - New player → INSERT + log as 'added'
    - Price changed → UPDATE + record in price_history
    - Status changed → UPDATE
    - Player removed from API → deactivate (is_active=0)
    
    Returns dict with counts: {added, updated, deactivated, price_changes}
    """
    if not players:
        return {"added": 0, "updated": 0, "deactivated": 0, "price_changes": 0}

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()

    # Get current active player IDs and their prices for change detection
    cur.execute("SELECT id, price, status FROM players WHERE is_active = 1")
    existing = {}
    for row in cur.fetchall():
        existing[row[0]] = {"price": row[1], "status": row[2]}

    new_ids = set()
    added = 0
    updated = 0
    price_changes = 0
    new_players_list = []
    price_change_list = []

    for p in players:
        pid = p["id"]
        new_ids.add(pid)
        stats = p.get("stats", {})

        player_data = {
            "id": pid,
            "first_name": p.get("firstName", ""),
            "last_name": p.get("lastName", ""),
            "known_name": p.get("knownName"),
            "squad_id": p.get("squadId"),
            "position": p.get("position", ""),
            "price": p.get("price", 0.0),
            "status": p.get("status", "unknown"),
            "match_status": p.get("matchStatus"),
            "percent_selected": p.get("percentSelected", 0.0),
            "one_to_watch": 1 if p.get("oneToWatch") else 0,
            "one_to_watch_text": p.get("oneToWatchText"),
            "fifa_id": p.get("fifaId"),
            "total_points": stats.get("totalPoints", 0),
            "avg_points": stats.get("avgPoints", 0),
            "form": stats.get("form", 0),
            "last_round_pts": stats.get("lastRoundPoints", 0),
            "round_points": json.dumps(stats.get("roundPoints", [])),
            "next_fixture_active": stats.get("nextFixtureFromActiveRound"),
            "next_fixture_scheduled": stats.get("nextFixtureFromScheduledRound"),
            "qualification_round_ids": json.dumps(p.get("qualificationRoundIds", [])),
            "updated_at": now,
        }

        if pid in existing:
            # ─── EXISTING PLAYER: check for changes ───
            old = existing[pid]

            # Detect price change
            old_price = old["price"]
            new_price = player_data["price"]
            if old_price is not None and new_price is not None and abs(old_price - new_price) > 0.001:
                cur.execute(
                    "INSERT INTO price_history (player_id, old_price, new_price, changed_at) "
                    "VALUES (?, ?, ?, ?)",
                    (pid, old_price, new_price, now)
                )
                price_changes += 1
                price_change_list.append({
                    "name": player_data["known_name"] or f"{player_data['first_name']} {player_data['last_name']}",
                    "old": old_price,
                    "new": new_price,
                    "diff": new_price - old_price,
                })

            # Update all fields
            cur.execute("""
                UPDATE players SET
                    first_name = :first_name,
                    last_name = :last_name,
                    known_name = :known_name,
                    squad_id = :squad_id,
                    position = :position,
                    price = :price,
                    status = :status,
                    match_status = :match_status,
                    percent_selected = :percent_selected,
                    one_to_watch = :one_to_watch,
                    one_to_watch_text = :one_to_watch_text,
                    fifa_id = :fifa_id,
                    total_points = :total_points,
                    avg_points = :avg_points,
                    form = :form,
                    last_round_pts = :last_round_pts,
                    round_points = :round_points,
                    next_fixture_active = :next_fixture_active,
                    next_fixture_scheduled = :next_fixture_scheduled,
                    qualification_round_ids = :qualification_round_ids,
                    updated_at = :updated_at,
                    is_active = 1
                WHERE id = :id
            """, player_data)
            updated += 1
        else:
            # ─── NEW PLAYER: insert ───
            player_data["first_seen_at"] = now
            cur.execute("""
                INSERT INTO players (
                    id, first_name, last_name, known_name, squad_id,
                    position, price, status, match_status,
                    percent_selected, one_to_watch, one_to_watch_text, fifa_id,
                    total_points, avg_points, form, last_round_pts, round_points,
                    next_fixture_active, next_fixture_scheduled,
                    qualification_round_ids,
                    first_seen_at, updated_at, is_active
                ) VALUES (
                    :id, :first_name, :last_name, :known_name, :squad_id,
                    :position, :price, :status, :match_status,
                    :percent_selected, :one_to_watch, :one_to_watch_text, :fifa_id,
                    :total_points, :avg_points, :form, :last_round_pts, :round_points,
                    :next_fixture_active, :next_fixture_scheduled,
                    :qualification_round_ids,
                    :first_seen_at, :updated_at, 1
                )
            """, player_data)
            added += 1
            display_name = player_data["known_name"] or f"{player_data['first_name']} {player_data['last_name']}"
            new_players_list.append(f"{display_name} ({player_data['position']}, ${player_data['price']}m)")

            # Also record initial price in price_history
            cur.execute(
                "INSERT INTO price_history (player_id, old_price, new_price, changed_at) "
                "VALUES (?, ?, ?, ?)",
                (pid, None, player_data["price"], now)
            )

    # ─── DEACTIVATE removed players ───
    old_active_ids = set(existing.keys())
    removed_ids = old_active_ids - new_ids
    deactivated = 0
    deactivated_names = []
    for pid in removed_ids:
        cur.execute("UPDATE players SET is_active = 0, updated_at = ? WHERE id = ?", (now, pid))
        # Get name for logging
        row = cur.execute("SELECT first_name, last_name, known_name FROM players WHERE id = ?", (pid,)).fetchone()
        if row:
            name = row[2] or f"{row[0]} {row[1]}"
            deactivated_names.append(name)
        deactivated += 1

    conn.commit()

    # ─── Print change report ───
    if new_players_list:
        print(f"\n  🆕 New players ({len(new_players_list)}):")
        for name in new_players_list[:20]:  # Show max 20
            print(f"     + {name}")
        if len(new_players_list) > 20:
            print(f"     ... and {len(new_players_list) - 20} more")

    if price_change_list:
        print(f"\n  💰 Price changes ({len(price_change_list)}):")
        for pc in sorted(price_change_list, key=lambda x: abs(x["diff"]), reverse=True)[:15]:
            arrow = "📈" if pc["diff"] > 0 else "📉"
            print(f"     {arrow} {pc['name']}: ${pc['old']:.1f}m → ${pc['new']:.1f}m ({pc['diff']:+.1f})")
        if len(price_change_list) > 15:
            print(f"     ... and {len(price_change_list) - 15} more")

    if deactivated_names:
        print(f"\n  ❌ Deactivated ({len(deactivated_names)}):")
        for name in deactivated_names[:10]:
            print(f"     - {name}")

    return {
        "added": added,
        "updated": updated,
        "deactivated": deactivated,
        "price_changes": price_changes,
    }


# ──────────────────────────────────────────────
# SYNC ROUND POINTS — Normalize JSON → table
# ──────────────────────────────────────────────
def sync_round_points(conn: sqlite3.Connection, players: list) -> int:
    """
    Extract roundPoints JSON from each player and populate
    the player_round_points table for efficient SQL queries.
    
    roundPoints format from API: [{"roundId": 1, "points": 5, ...}, ...]
    or sometimes just [points_int, points_int, ...]
    """
    if not players:
        return 0

    now = datetime.now(timezone.utc).isoformat()
    cur = conn.cursor()
    count = 0

    for p in players:
        pid = p["id"]
        stats = p.get("stats", {})
        round_points = stats.get("roundPoints", [])

        if not round_points:
            continue

        for idx, rp in enumerate(round_points):
            if isinstance(rp, dict):
                # Format: {"roundId": 1, "points": 5}
                round_id = rp.get("roundId", idx + 1)
                points = rp.get("points", 0)
            elif isinstance(rp, (int, float)):
                # Format: [5, 3, 0, ...]  (index = round_id - 1)
                round_id = idx + 1
                points = rp
            else:
                continue

            cur.execute("""
                INSERT INTO player_round_points (player_id, round_id, points, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id, round_id) DO UPDATE SET
                    points = excluded.points,
                    updated_at = excluded.updated_at
            """, (pid, round_id, points, now))
            count += 1

    conn.commit()
    return count


# ──────────────────────────────────────────────
# EXPORT — CSV for debugging/analysis
# ──────────────────────────────────────────────
def export_csv(conn: sqlite3.Connection):
    """Export players to CSV with team names joined."""
    CSV_EXPORT_PATH.mkdir(exist_ok=True)

    # Main player export
    df = pd.read_sql_query("""
        SELECT
            p.id,
            COALESCE(p.known_name, p.first_name || ' ' || p.last_name) AS name,
            s.name AS team,
            s.abbr AS team_abbr,
            s."group" AS team_group,
            p.position,
            p.price,
            p.status,
            ROUND(p.percent_selected, 2) AS pct_selected,
            p.total_points,
            p.avg_points,
            p.form,
            p.last_round_pts,
            p.one_to_watch,
            p.is_active,
            p.first_seen_at,
            p.updated_at
        FROM players p
        LEFT JOIN squads s ON p.squad_id = s.id
        ORDER BY p.total_points DESC, p.price DESC
    """, conn)

    csv_path = CSV_EXPORT_PATH / "wc2026_players.csv"
    df.to_csv(csv_path, index=False)

    # Price history export
    df_prices = pd.read_sql_query("""
        SELECT
            ph.player_id,
            COALESCE(p.known_name, p.first_name || ' ' || p.last_name) AS name,
            ph.old_price,
            ph.new_price,
            ROUND(ph.new_price - COALESCE(ph.old_price, ph.new_price), 1) AS change,
            ph.changed_at
        FROM price_history ph
        JOIN players p ON ph.player_id = p.id
        ORDER BY ph.changed_at DESC
    """, conn)

    if not df_prices.empty:
        prices_path = CSV_EXPORT_PATH / "wc2026_price_history.csv"
        df_prices.to_csv(prices_path, index=False)
        print(f"  📄 Price history → {prices_path} ({len(df_prices)} records)")

    # Summary
    active = df[df["is_active"] == 1]
    print(f"\n{'─' * 50}")
    print(f"📊 Database Summary ({len(active)} active players)")
    print(f"{'─' * 50}")

    pos_count = active["position"].value_counts()
    for pos in ["GK", "DEF", "MID", "FWD"]:
        print(f"   {pos}: {pos_count.get(pos, 0)}")

    print(f"   Teams: {active['team'].nunique()}")
    print(f"   Price range: ${active['price'].min():.1f}m – ${active['price'].max():.1f}m")
    print(f"   Avg price: ${active['price'].mean():.1f}m")

    print(f"\n   🏆 Top 10 by Fantasy Points:")
    top = active.nlargest(10, "total_points")[
        ["name", "team", "position", "price", "total_points", "pct_selected"]
    ]
    if not top.empty:
        print(top.to_string(index=False))
    else:
        print("   (No points data yet — tournament hasn't started)")

    print(f"\n   🔥 Most Selected:")
    popular = active.nlargest(10, "pct_selected")[
        ["name", "team", "position", "price", "pct_selected"]
    ]
    print(popular.to_string(index=False))

    print(f"\n  ✅ Full export → {csv_path}")


# ──────────────────────────────────────────────
# MAIN PIPELINE
# ──────────────────────────────────────────────
async def run_pipeline(players_only: bool = False):
    """Run the full data sync pipeline."""
    start_time = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'═' * 56}")
    print(f"  ⚽ WC2026 Fantasy Pipeline — {now_str}")
    print(f"{'═' * 56}\n")

    # 1. Init database
    conn = get_connection()
    init_db(conn)

    # 2. Fetch data from FIFA Fantasy API
    print("📥 Fetching FIFA Fantasy data...")
    data = await fetch_all_data(players_only=players_only)

    if data["players"] is None:
        print("\n❌ Failed to fetch players (API down, no cache) — aborting.")
        conn.close()
        return
        # Note: If cache existed, fetch_endpoint already loaded it.
        # Pipeline only aborts if both live API AND cache are unavailable.

    # 3. Sync squads (if fetched)
    squads_count = 0
    if data["squads"]:
        print("\n💾 Syncing squads...")
        squads_count = sync_squads(conn, data["squads"])
        print(f"  ✓ {squads_count} squads synced")
    
    # 3b. Merge squads_fifa data (seed info, FIFA IDs) - optional enrichment
    if data.get("squads_fifa"):
        # We store these separately but could merge later
        print(f"  ✓ {len(data['squads_fifa'])} FIFA squad records available for enrichment")

    # 4. Sync rounds + fixtures (if fetched)
    rounds_count = 0
    fixtures_count = 0
    if data["rounds"]:
        print("\n📅 Syncing rounds & fixtures...")
        rounds_count, fixtures_count = sync_rounds(conn, data["rounds"])
        print(f"  ✓ {rounds_count} rounds, {fixtures_count} fixtures synced")

    # 5. Sync players (the important part!)
    print("\n👥 Syncing players...")
    result = sync_players(conn, data["players"])
    print(f"\n  ✓ Added: {result['added']} | Updated: {result['updated']} | "
          f"Deactivated: {result['deactivated']} | Price changes: {result['price_changes']}")

    # 5b. Populate player_round_points (normalized from JSON)
    print("\n📊 Syncing round points...")
    rp_count = sync_round_points(conn, data["players"])
    print(f"  ✓ {rp_count} player-round records synced")

    # 6. Log this run
    duration_ms = int((time.time() - start_time) * 1000)
    notes_parts = []
    if players_only:
        notes_parts.append("players-only")
    if result["price_changes"] > 0:
        notes_parts.append(f"{result['price_changes']} price changes")
    if result["added"] > 0:
        notes_parts.append(f"{result['added']} new players")

    conn.execute("""
        INSERT INTO sync_log (
            run_at, source,
            players_added, players_updated, players_deactivated,
            squads_synced, rounds_synced, fixtures_synced,
            notes, duration_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        "fifa_fantasy",
        result["added"], result["updated"], result["deactivated"],
        squads_count, rounds_count, fixtures_count,
        "; ".join(notes_parts) if notes_parts else "routine sync",
        duration_ms,
    ))
    conn.commit()

    # 7. Export CSV
    print("\n📤 Exporting CSV...")
    export_csv(conn)

    # 8. Done
    print(f"\n{'═' * 56}")
    print(f"  ✅ Pipeline complete in {duration_ms}ms")
    print(f"{'═' * 56}\n")

    conn.close()


# ──────────────────────────────────────────────
# SCHEDULED AUTO-SYNC (every N hours)
# ──────────────────────────────────────────────
async def run_scheduled(interval_hours: int = 4):
    """Run pipeline on a schedule (every N hours)."""
    print(f"🔄 Starting scheduled sync every {interval_hours} hours.")
    print("   Press Ctrl+C to stop.\n")

    while True:
        try:
            await run_pipeline(players_only=False)
        except Exception as e:
            print(f"\n❌ Pipeline error: {e}")
            import traceback
            traceback.print_exc()

        next_run = datetime.now().strftime("%H:%M:%S")
        print(f"\n⏰ Next sync in {interval_hours}h (sleeping since {next_run})...\n")
        await asyncio.sleep(interval_hours * 3600)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
if __name__ == "__main__":
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print("""
Usage: python pipeline.py [OPTIONS]

Options:
  (no args)       Full sync — players + squads + fixtures
  --players-only  Only sync players (faster, for frequent updates)
  --schedule      Run auto-sync every 4 hours
  --schedule=N    Run auto-sync every N hours
  --help, -h      Show this help
        """)
        sys.exit(0)

    if "--schedule" in args or any(a.startswith("--schedule=") for a in args):
        # Parse interval
        hours = 4
        for a in args:
            if a.startswith("--schedule="):
                try:
                    hours = int(a.split("=")[1])
                except ValueError:
                    hours = 4
        asyncio.run(run_scheduled(hours))
    else:
        players_only = "--players-only" in args
        asyncio.run(run_pipeline(players_only=players_only))
