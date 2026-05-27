import sqlite3
conn = sqlite3.connect('wc2026.db')
conn.execute("UPDATE players SET mock_points=2, mock_match_status='finished' WHERE last_name LIKE '%Mbappe%'")
conn.commit()
conn.close()
