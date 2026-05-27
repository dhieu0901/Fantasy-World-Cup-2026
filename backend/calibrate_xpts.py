import sqlite3
from database import get_connection

def main():
    conn = get_connection()
    try:
        players = conn.execute("SELECT position, price, total_points, projected_pts, display_name FROM players WHERE is_active=1").fetchall()
        
        played = [p for p in players if p["total_points"] > 0]
        
        print("=== WC2026 Fantasy xPts Calibration ===")
        if not played:
            print("Waiting for MD1 data...")
            print(f"Players with actual points: 0 / {len(players)}")
            print("Will calibrate after: 2026-06-12")
            return
            
        print(f"Analyzing {len(played)} players with points...")
        
        mae_sum = 0
        errors = {"GK": [], "DEF": [], "MID": [], "FWD": []}
        
        for p in played:
            err = abs(p["total_points"] - p["projected_pts"])
            mae_sum += err
            if p["position"] in errors:
                errors[p["position"]].append(err)
                
        print(f"\nOverall MAE: {mae_sum / len(played):.2f} pts")
        
        print("\nMAE by Position:")
        for pos, errs in errors.items():
            if errs:
                print(f"  {pos}: {sum(errs) / len(errs):.2f} pts (n={len(errs)})")
            
        print("\nCalibration suggests adjusting TEAM_STRENGTH weights based on these errors.")
    finally:
        conn.close()
        
if __name__ == "__main__":
    main()
