"""
Database module — SQLite schema and query helpers for WC2026 Fantasy.
Tables: squads, players, rounds, fixtures, sync_log
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "wc2026.db"


def get_connection(db_path: str = None) -> sqlite3.Connection:
    """Get a SQLite connection with row_factory for dict-like access."""
    conn = sqlite3.connect(db_path or str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def init_db(conn: sqlite3.Connection = None):
    """Create all tables if they don't exist."""
    should_close = False
    if conn is None:
        conn = get_connection()
        should_close = True

    conn.executescript("""
        -- ─────────────────────────────────────────
        -- Squads / National Teams
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS squads (
            id            INTEGER PRIMARY KEY,   -- FIFA Fantasy squad ID
            name          TEXT NOT NULL,
            abbr          TEXT,                   -- 3-letter code (e.g. BRA, ARG)
            seed          INTEGER DEFAULT 0,
            squad_link    TEXT,
            is_active     INTEGER DEFAULT 1,
            "group"       TEXT,                   -- Group letter (a-l)
            group_position INTEGER,
            updated_at    TEXT
        );

        -- ─────────────────────────────────────────
        -- Players
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS players (
            id                INTEGER PRIMARY KEY,  -- FIFA Fantasy player ID
            first_name        TEXT,
            last_name         TEXT,
            known_name        TEXT,                  -- Display name override
            squad_id          INTEGER,
            position          TEXT,                  -- GK / DEF / MID / FWD
            price             REAL DEFAULT 0.0,
            status            TEXT DEFAULT 'playing', -- playing / injured / suspended / doubtful
            match_status      TEXT,
            percent_selected  REAL DEFAULT 0.0,
            one_to_watch      INTEGER DEFAULT 0,
            one_to_watch_text TEXT,
            fifa_id           INTEGER,               -- Official FIFA player ID

            -- Fantasy stats (updated after each round)
            total_points      REAL DEFAULT 0,
            avg_points        REAL DEFAULT 0,
            form              REAL DEFAULT 0,
            last_round_pts    REAL DEFAULT 0,
            round_points      TEXT DEFAULT '[]',     -- JSON array of per-round points

            -- Next fixture info
            next_fixture_active    INTEGER,
            next_fixture_scheduled INTEGER,

            -- Qualification round IDs
            qualification_round_ids TEXT DEFAULT '[]',

            -- Metadata
            first_seen_at     TEXT,
            updated_at        TEXT,
            is_active         INTEGER DEFAULT 1,

            -- NOTE: No FK to squads — players use sequential IDs (1-48),
            -- squads_fifa.json uses FIFA IDs (43817+). Different systems.
            squad_id_fifa     INTEGER,             -- FIFA squad ID for cross-ref

            -- Mock fields for testing Live Sub Recommender
            mock_points       INTEGER DEFAULT NULL,
            mock_match_status TEXT DEFAULT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_players_squad ON players(squad_id);
        CREATE INDEX IF NOT EXISTS idx_players_position ON players(position);
        CREATE INDEX IF NOT EXISTS idx_players_price ON players(price);
        CREATE INDEX IF NOT EXISTS idx_players_active ON players(is_active);

        -- ─────────────────────────────────────────
        -- Rounds (Matchdays)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS rounds (
            id          INTEGER PRIMARY KEY,
            status      TEXT,           -- scheduled / active / completed
            start_date  TEXT,
            end_date    TEXT,
            stage       TEXT,           -- GROUP / ROUND_OF_32 / ROUND_OF_16 / QF / SF / FINAL
            updated_at  TEXT
        );

        -- ─────────────────────────────────────────
        -- Fixtures (individual matches)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS fixtures (
            id                INTEGER PRIMARY KEY,  -- Match/tournament ID
            round_id          INTEGER,
            period            TEXT,                  -- pre_match / first_half / second_half / full_time
            minutes           INTEGER DEFAULT 0,
            extra_minutes     INTEGER DEFAULT 0,
            venue_name        TEXT,
            venue_city        TEXT,
            venue_id          INTEGER,
            match_date        TEXT,
            status            TEXT,

            home_squad_id     INTEGER,
            away_squad_id     INTEGER,
            home_squad_name   TEXT,
            away_squad_name   TEXT,
            home_squad_abbr   TEXT,
            away_squad_abbr   TEXT,

            home_score        INTEGER,
            away_score        INTEGER,
            home_penalty_score INTEGER,
            away_penalty_score INTEGER,
            home_scorers      TEXT,    -- JSON
            away_scorers      TEXT,    -- JSON

            updated_at        TEXT,

            -- NOTE: No FK constraints — fixture squad IDs are a third system
            -- different from both players.squadId and squads_fifa.id
            home_squad_id_fifa INTEGER,
            away_squad_id_fifa INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_fixtures_round ON fixtures(round_id);
        CREATE INDEX IF NOT EXISTS idx_fixtures_home ON fixtures(home_squad_id);
        CREATE INDEX IF NOT EXISTS idx_fixtures_away ON fixtures(away_squad_id);

        -- ─────────────────────────────────────────
        -- Sync Log (pipeline run history)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at      TEXT,
            source      TEXT DEFAULT 'fifa_fantasy',
            players_added     INTEGER DEFAULT 0,
            players_updated   INTEGER DEFAULT 0,
            players_deactivated INTEGER DEFAULT 0,
            squads_synced     INTEGER DEFAULT 0,
            rounds_synced     INTEGER DEFAULT 0,
            fixtures_synced   INTEGER DEFAULT 0,
            notes       TEXT,
            duration_ms INTEGER DEFAULT 0
        );

        -- ─────────────────────────────────────────
        -- Price History (track price changes daily)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS price_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id   INTEGER NOT NULL,
            old_price   REAL,
            new_price   REAL,
            changed_at  TEXT,
            -- No FK constraint for flexibility
            player_id_ref INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_price_history_player ON price_history(player_id);
        CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history(changed_at);

        -- ─────────────────────────────────────────
        -- Player Round Points (normalized from JSON)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS player_round_points (
            player_id   INTEGER NOT NULL,
            round_id    INTEGER NOT NULL,
            points      REAL DEFAULT 0,
            updated_at  TEXT,
            PRIMARY KEY (player_id, round_id)
        );

        CREATE INDEX IF NOT EXISTS idx_prp_player ON player_round_points(player_id);
        CREATE INDEX IF NOT EXISTS idx_prp_round ON player_round_points(round_id);

        -- ─────────────────────────────────────────
        -- Player Advanced Stats (from FotMob/Sofascore)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS player_xstats (
            player_id       INTEGER NOT NULL,
            source          TEXT NOT NULL,        -- 'fotmob' / 'sofascore' / 'manual'
            season          TEXT,                  -- '2025-26' club season
            competition     TEXT,                  -- 'Premier League' / 'La Liga' / 'WC2026'

            -- Attacking
            matches_played  INTEGER DEFAULT 0,
            minutes_played  INTEGER DEFAULT 0,
            goals           INTEGER DEFAULT 0,
            assists         INTEGER DEFAULT 0,
            xG              REAL DEFAULT 0,        -- Expected Goals (season total)
            xA              REAL DEFAULT 0,        -- Expected Assists (season total)
            xG_per90        REAL DEFAULT 0,        -- xG per 90 min
            xA_per90        REAL DEFAULT 0,
            shots           INTEGER DEFAULT 0,
            shots_on_target INTEGER DEFAULT 0,
            shots_per90     REAL DEFAULT 0,

            -- Defensive
            tackles         INTEGER DEFAULT 0,
            tackles_per90   REAL DEFAULT 0,
            interceptions   INTEGER DEFAULT 0,
            clearances      INTEGER DEFAULT 0,

            -- Creative
            chances_created     INTEGER DEFAULT 0,
            chances_created_per90 REAL DEFAULT 0,
            passes_completed    INTEGER DEFAULT 0,
            pass_accuracy       REAL DEFAULT 0,

            -- GK specific
            saves           INTEGER DEFAULT 0,
            saves_per90     REAL DEFAULT 0,
            clean_sheets    INTEGER DEFAULT 0,
            goals_conceded  INTEGER DEFAULT 0,
            xGC             REAL DEFAULT 0,        -- Expected Goals Conceded

            -- Cards
            yellow_cards    INTEGER DEFAULT 0,
            red_cards       INTEGER DEFAULT 0,
            yellow_per90    REAL DEFAULT 0,

            -- Misc
            rating          REAL DEFAULT 0,        -- FotMob/Sofascore rating
            fotmob_id       INTEGER,               -- FotMob player ID for linking
            sofascore_id    INTEGER,                -- Sofascore player ID

            updated_at      TEXT,
            PRIMARY KEY (player_id, source, competition)
        );

        CREATE INDEX IF NOT EXISTS idx_xstats_player ON player_xstats(player_id);
        CREATE INDEX IF NOT EXISTS idx_xstats_source ON player_xstats(source);
        
        -- ─────────────────────────────────────────
        -- User Teams (Saved Squads)
        -- ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS user_teams (
            device_id   TEXT PRIMARY KEY,
            player_ids  TEXT,
            updated_at  TEXT
        );
    """)
    
    # Alter existing players table to add mock columns if they don't exist
    try:
        conn.execute("ALTER TABLE players ADD COLUMN mock_points INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("ALTER TABLE players ADD COLUMN mock_match_status TEXT DEFAULT NULL")
    except sqlite3.OperationalError:
        pass

    conn.commit()

    if should_close:
        conn.close()


# ─────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────

def get_all_players(conn: sqlite3.Connection, active_only: bool = True,
                    position: str = None, squad_id: int = None,
                    sort_by: str = "total_points", sort_desc: bool = True,
                    limit: int = None) -> list[dict]:
    """Get players with optional filters."""
    query = "SELECT p.*, s.name as team_name, s.abbr as team_abbr, s.\"group\" as team_group FROM players p LEFT JOIN squads s ON p.squad_id = s.id WHERE 1=1"
    params = []

    if active_only:
        query += " AND p.is_active = 1"
    if position:
        query += " AND p.position = ?"
        params.append(position.upper())
    if squad_id:
        query += " AND p.squad_id = ?"
        params.append(squad_id)

    # Validate sort column
    valid_sorts = {"total_points", "price", "avg_points", "form", "percent_selected", "last_name"}
    if sort_by not in valid_sorts:
        sort_by = "total_points"
    direction = "DESC" if sort_desc else "ASC"
    query += f" ORDER BY p.{sort_by} {direction}"

    if limit:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_player_by_id(conn: sqlite3.Connection, player_id: int) -> dict | None:
    """Get a single player by ID."""
    row = conn.execute(
        "SELECT p.*, s.name as team_name, s.abbr as team_abbr, s.\"group\" as team_group "
        "FROM players p LEFT JOIN squads s ON p.squad_id = s.id "
        "WHERE p.id = ?", (player_id,)
    ).fetchone()
    return dict(row) if row else None


def get_all_squads(conn: sqlite3.Connection) -> list[dict]:
    """Get all squads/teams."""
    rows = conn.execute(
        'SELECT * FROM squads ORDER BY "group", name'
    ).fetchall()
    return [dict(row) for row in rows]


def get_all_rounds(conn: sqlite3.Connection) -> list[dict]:
    """Get all rounds with their fixtures."""
    rounds = []
    round_rows = conn.execute(
        "SELECT * FROM rounds ORDER BY id"
    ).fetchall()

    for r in round_rows:
        rd = dict(r)
        fixtures = conn.execute(
            "SELECT * FROM fixtures WHERE round_id = ? ORDER BY match_date",
            (rd["id"],)
        ).fetchall()
        rd["fixtures"] = [dict(f) for f in fixtures]
        rounds.append(rd)

    return rounds


def get_fixtures_for_squad(conn: sqlite3.Connection, squad_id: int) -> list[dict]:
    """Get all fixtures for a specific team."""
    rows = conn.execute(
        "SELECT f.*, r.stage FROM fixtures f "
        "JOIN rounds r ON f.round_id = r.id "
        "WHERE f.home_squad_id = ? OR f.away_squad_id = ? "
        "ORDER BY f.match_date",
        (squad_id, squad_id)
    ).fetchall()
    return [dict(row) for row in rows]


def get_squad_player_counts(conn: sqlite3.Connection) -> dict:
    """Get count of active players per squad."""
    rows = conn.execute(
        "SELECT squad_id, COUNT(*) as count FROM players "
        "WHERE is_active = 1 GROUP BY squad_id"
    ).fetchall()
    return {row["squad_id"]: row["count"] for row in rows}


def get_sync_history(conn: sqlite3.Connection, limit: int = 10) -> list[dict]:
    """Get recent sync log entries."""
    rows = conn.execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def get_stats_summary(conn: sqlite3.Connection) -> dict:
    """Get summary statistics about the database."""
    result = {}

    row = conn.execute(
        "SELECT COUNT(*) as total, "
        "SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active, "
        "MIN(price) as min_price, MAX(price) as max_price, AVG(price) as avg_price "
        "FROM players"
    ).fetchone()
    result["players"] = dict(row)

    # Position breakdown
    pos_rows = conn.execute(
        "SELECT position, COUNT(*) as count FROM players "
        "WHERE is_active = 1 GROUP BY position"
    ).fetchall()
    result["positions"] = {r["position"]: r["count"] for r in pos_rows}

    # Squad count
    row = conn.execute("SELECT COUNT(*) as count FROM squads WHERE is_active = 1").fetchone()
    result["squads"] = row["count"]

    # Rounds
    row = conn.execute("SELECT COUNT(*) as count FROM rounds").fetchone()
    result["rounds"] = row["count"]

    # Fixtures
    row = conn.execute("SELECT COUNT(*) as count FROM fixtures").fetchone()
    result["fixtures"] = row["count"]

    # Last sync
    sync = conn.execute("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1").fetchone()
    result["last_sync"] = dict(sync) if sync else None

    return result


if __name__ == "__main__":
    print("Initializing database...")
    init_db()
    print(f"✅ Database created at: {DB_PATH}")
