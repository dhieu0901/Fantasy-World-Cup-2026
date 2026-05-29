"""Quick test script for optimizer logic."""
from optimizer import optimize_squad

def test_preset(preset, chip="none", stage="GROUP_MD1"):
    r = optimize_squad(stage=stage, preset=preset, chip=chip)
    cap = r["captain"]
    vc = r["vice_captain"]
    print(f"\n=== {preset.upper()} | chip={chip} | stage={stage} ===")
    print(f"  Total xPts: {r['total_projected_pts']}")
    print(f"  Budget: ${r['budget_used']}m used / ${r['budget_remaining']}m left")
    print(f"  Captain: {cap['display_name']} ({cap['projected_pts']:.1f} xPts, {cap['percent_selected']:.1f}%)")
    print(f"  Vice Cap: {vc['display_name']} ({vc['projected_pts']:.1f} xPts)")
    print(f"  Method: {r['method']}")
    print(f"  Chip: {r.get('chip', 'N/A')}")
    
    print(f"  Starting XI ({len(r['starting_xi'])}):")
    for p in sorted(r['starting_xi'], key=lambda x: x['projected_pts'], reverse=True):
        marker = " (C)" if p['id'] == cap['id'] else " (VC)" if p['id'] == vc['id'] else ""
        twelfth = " [12th]" if p.get('is_12th_man') else ""
        print(f"    {p['display_name']:22s} {p['position']:4s} ${p['price']:.1f}m  {p['projected_pts']:.2f} xPts  {p['percent_selected']:.1f}%{marker}{twelfth}")
    
    print(f"  Bench ({len(r['bench'])}):")
    for p in r['bench']:
        print(f"    {p['display_name']:22s} {p['position']:4s} ${p['price']:.1f}m  {p['projected_pts']:.2f} xPts  {p['percent_selected']:.1f}%")
    
    return r

# Run all presets
results = {}
for preset in ["default", "template", "value", "safe", "risky"]:
    results[preset] = test_preset(preset)

# Comparison
print("\n" + "="*60)
print("COMPARISON TABLE")
print("="*60)
print(f"{'Preset':<12} {'xPts':>8} {'Budget':>8} {'Remaining':>10} {'Captain':>20}")
for name, r in results.items():
    print(f"{name:<12} {r['total_projected_pts']:>8.1f} ${r['budget_used']:>6.1f}m ${r['budget_remaining']:>7.1f}m  {r['captain']['display_name']:>20}")

# Check overlap between presets
xi_ids = {name: {p['id'] for p in r['starting_xi']} for name, r in results.items()}
print("\nOverlap Matrix (Starting XI):")
for n1 in xi_ids:
    for n2 in xi_ids:
        if n1 < n2:
            overlap = len(xi_ids[n1] & xi_ids[n2])
            print(f"  {n1} vs {n2}: {overlap}/11")

# Test boosters
print("\n" + "="*60)
print("BOOSTER TESTS")
print("="*60)
r_base = test_preset("default", chip="none")
r_maxcap = test_preset("default", chip="max_captain")
r_12th = test_preset("default", chip="12th_man")
r_wc = test_preset("default", chip="wildcard")
r_qual = test_preset("default", chip="qualification", stage="ROUND_OF_16")

print("\nBooster Impact:")
print(f"  No booster:     {r_base['total_projected_pts']:.1f} xPts")
print(f"  Max Captain:    {r_maxcap['total_projected_pts']:.1f} xPts  (+{r_maxcap['total_projected_pts'] - r_base['total_projected_pts']:.1f})")
print(f"  12th Man:       {r_12th['total_projected_pts']:.1f} xPts  (+{r_12th['total_projected_pts'] - r_base['total_projected_pts']:.1f}), XI size: {len(r_12th['starting_xi'])}")
print(f"  Qualification:  {r_qual['total_projected_pts']:.1f} xPts  (R16, different stage)")
