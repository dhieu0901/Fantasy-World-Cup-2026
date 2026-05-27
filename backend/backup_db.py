import shutil
from datetime import datetime
from pathlib import Path

db_path = Path(__file__).parent / "wc2026.db"
backups_dir = Path(__file__).parent / "backups"

if not backups_dir.exists():
    backups_dir.mkdir()

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = backups_dir / f"wc2026_{timestamp}.db"

if db_path.exists():
    shutil.copy2(db_path, backup_path)
    print(f"Backed up wc2026.db to {backup_path.name}")
else:
    print("No wc2026.db found to backup.")
