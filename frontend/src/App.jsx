import { useState, useEffect, useCallback, useMemo } from 'react';
import './index.css';
import * as api from './api';
import SquadPlannerTab from './SquadPlanner';
/* ═══════════════════════════════════════════
   SVG Icons (inline for zero-dep)
   ═══════════════════════════════════════════ */
const Icon = {
  Search: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>,
  Trophy: () => <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M6 9H4.5a2.5 2.5 0 010-5H6"/><path d="M18 9h1.5a2.5 2.5 0 000-5H18"/><path d="M4 22h16"/><path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 19.24 7 20v2h10v-2c0-.76-.85-1.25-2.03-1.79C14.47 17.98 14 17.55 14 17v-2.34"/><path d="M18 2H6v7a6 6 0 1012 0V2z"/></svg>,
  Zap: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10"/></svg>,
  Users: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M16 21v-2a4 4 0 00-4-4H6a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/></svg>,
  Calendar: () => <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>,
  Star: () => <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26"/></svg>,
  ChevUp: () => <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="18 15 12 9 6 15"/></svg>,
  ChevDown: () => <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><polyline points="6 9 12 15 18 9"/></svg>,
  Loader: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" className="spin"><path d="M21 12a9 9 0 11-6.219-8.56"/></svg>,
  Football: () => <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="10"/><path d="M12 2a15.3 15.3 0 014 10 15.3 15.3 0 01-4 10 15.3 15.3 0 01-4-10 15.3 15.3 0 014-10z"/><path d="M2 12h20"/></svg>,
};

/* ═══════════════════════════════════════════
   Country Flag Emoji helper
   ═══════════════════════════════════════════ */
function countryFlag(abbr) {
  const map2 = {
    ARG:'ar', FRA:'fr', BRA:'br', ENG:'gb-eng', ESP:'es', POR:'pt', GER:'de', NED:'nl',
    URU:'uy', COL:'co', CRO:'hr', MAR:'ma', JPN:'jp', BEL:'be', SUI:'ch', USA:'us',
    SEN:'sn', TUR:'tr', AUT:'at', KOR:'kr', NOR:'no', EGY:'eg', MEX:'mx', SWE:'se',
    ECU:'ec', IRN:'ir', SCO:'gb-sct', CIV:'ci', PAR:'py', ALG:'dz', CZE:'cz', AUS:'au',
    RSA:'za', TUN:'tn', PAN:'pa', GHA:'gh', IRQ:'iq', QAT:'qa', CAN:'ca', BIH:'ba',
    JOR:'jo', UZB:'uz', KSA:'sa', NZL:'nz', COD:'cd', HAI:'ht', CUW:'cw', CPV:'cv',
  };
  const code = map2[abbr];
  if (!code) return '🏳️';
  return <img src={`https://flagcdn.com/w20/${code}.png`} width="20" alt={abbr} style={{ verticalAlign: 'middle', borderRadius: '2px', boxShadow: '0 0 1px rgba(255,255,255,0.5)', display: 'inline-block' }} />;
}

/* ═══════════════════════════════════════════
   MAIN APP
   ═══════════════════════════════════════════ */
export default function App() {
  const [tab, setTab] = useState('projections');
  const [players, setPlayers] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [posFilter, setPosFilter] = useState(null);
  const [sortBy, setSortBy] = useState('projected_pts');
  const [sortDesc, setSortDesc] = useState(true);
  const [selectedTeamFilter, setSelectedTeamFilter] = useState(null);

  // Optimizer State
  const [preset, setPreset] = useState('default');
  const [chip, setChip] = useState('none');
  const [optimResult, setOptimResult] = useState(null);
  const [optimizing, setOptimizing] = useState(false);

  // Transfer Planner & Live Subs
  const [deviceId] = useState(() => {
    let id = localStorage.getItem('deviceId');
    if (!id) {
      id = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).substring(2, 15);
      localStorage.setItem('deviceId', id);
    }
    return id;
  });

  const [myTeamState, setMyTeamState] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  
  const setMyTeam = useCallback((newTeam) => {
    setMyTeamState(newTeam);
    localStorage.setItem('myTeam', JSON.stringify(newTeam));
    if (newTeam.length > 0) {
      api.saveTeam(deviceId, newTeam).catch(e => console.error("Save team failed", e));
    }
  }, [deviceId]);
  const myTeam = myTeamState;

  const [transferMode, setTransferMode] = useState(false);
  const [freeTransfers, setFreeTransfers] = useState(2);

  // Fixtures
  const [squads, setSquads] = useState([]);
  const [fixtures, setFixtures] = useState([]);

  // Initial load
  useEffect(() => {
    async function load() {
      setLoading(true);
      try {
        const [pData, sData, sqData, fData, teamData, subData] = await Promise.all([
          api.getPlayers({ sortBy: 'price', sortDesc: true }),
          api.getStats(),
          api.getSquads(),
          api.getFixtures(),
          api.getTeam(deviceId),
          api.getRecommendSubs(deviceId)
        ]);
        setPlayers(pData.players || []);
        setStats(sData);
        setSquads(sqData.squads || []);
        setFixtures(fData.fixtures || []);
        
        if (teamData && teamData.player_ids) {
          setMyTeamState(teamData.player_ids);
          localStorage.setItem('myTeam', JSON.stringify(teamData.player_ids));
        } else {
          try {
            const localTeam = JSON.parse(localStorage.getItem('myTeam')) || [];
            setMyTeamState(localTeam);
            if (localTeam.length > 0) api.saveTeam(deviceId, localTeam);
          } catch(e) {}
        }
        setRecommendations(subData?.recommendations || []);
      } catch (e) {
        console.error('Load failed:', e);
      }
      setLoading(false);
    }
    load();
  }, [deviceId]);

  // Search (debounced)
  const [debouncedSearch, setDebouncedSearch] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  useEffect(() => {
    if (loading) return; // Prevent interfering with initial load
    async function searchPlayers() {
      try {
        const data = await api.getPlayers({
          search: debouncedSearch || undefined,
          position: posFilter || undefined,
          sortBy, sortDesc,
        });
        setPlayers(data.players || []);
      } catch (e) { console.error(e); }
    }
    searchPlayers();
  }, [debouncedSearch, posFilter, sortBy, sortDesc, loading]);

  // Optimize
  const runOptimize = useCallback(async () => {
    setOptimizing(true);
    try {
      const payload = { preset, stage: 'GROUP_MD1', chip };
      if (transferMode && myTeam.length > 0) {
        payload.current_squad = myTeam;
        payload.free_transfers = freeTransfers;
      }
      const result = await api.optimize(payload);
      setOptimResult(result);
      setTab('lineup');
    } catch (e) { console.error('Optimize failed:', e); }
    setOptimizing(false);
  }, [preset, chip, transferMode, myTeam, freeTransfers]);

  // Sort handler
  const handleSort = (col) => {
    if (sortBy === col) { setSortDesc(!sortDesc); }
    else { setSortBy(col); setSortDesc(true); }
  };

  // Filtered & sorted players (client-side for instant feel)
  const displayPlayers = useMemo(() => {
    let list = [...players];
    // client-side sort
    list.sort((a, b) => {
      const va = a[sortBy] ?? 0;
      const vb = b[sortBy] ?? 0;
      return sortDesc ? vb - va : va - vb;
    });
    return list; // Return all, let ProjectionsTab paginate
  }, [players, sortBy, sortDesc]);

  // Breadcrumb for projections tab
  const getTabLabel = (id, label) => {
    if (id === 'projections' && selectedTeamFilter) {
      return <span>{label} <span style={{ color: '#2dd4bf', fontSize: '0.7rem' }}>({selectedTeamFilter})</span></span>;
    }
    return label;
  };

  return (
    <div className="app-layout">
      {/* ── Header ── */}
      <header className="header">
        <div className="header-brand">
          <span style={{ fontSize: '1.3rem' }}>⚽</span>
          <h1>WC2026 Fantasy Planner</h1>
          <span className="badge">Beta</span>
        </div>
        <div className="header-meta">
          <div className="dot" />
          <span>{stats ? `${stats.players?.active ?? 0} players` : '...'}</span>
          <span>•</span>
          <span>{stats ? `${stats.squads ?? 0} teams` : '...'}</span>
          <span>•</span>
          <span>{stats?.last_sync ? `Synced ${new Date(stats.last_sync.run_at).toLocaleDateString()}` : ''}</span>
        </div>
      </header>

      {/* ── Main Content ── */}
      <div className="app-main">
        <main className="app-content">
          {recommendations.length > 0 && (
            <div className="slide-up" style={{ background: 'rgba(245, 158, 11, 0.15)', border: '1px solid rgba(245, 158, 11, 0.5)', color: '#fcd34d', padding: '12px 16px', borderRadius: '8px', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span style={{ fontSize: '1.4rem' }}>💡</span>
              <div>
                <strong style={{ display: 'block', fontSize: '0.9rem', marginBottom: '4px' }}>Live Sub Recommendation</strong>
                <span style={{ fontSize: '0.85rem', color: '#fde68a' }}>{recommendations[0].reason}</span>
              </div>
            </div>
          )}

          {/* ── Stat Cards ── */}
          <div className="stat-grid slide-up">
            <StatCard label="Total Players" value={stats?.players?.active ?? '—'} cls="teal" sub={`${stats?.positions?.FWD ?? 0} FWD · ${stats?.positions?.MID ?? 0} MID · ${stats?.positions?.DEF ?? 0} DEF · ${stats?.positions?.GK ?? 0} GK`} />
            <StatCard label="Avg Price" value={`$${(stats?.players?.avg_price ?? 0).toFixed(1)}m`} cls="gold" sub={`$${stats?.players?.min_price ?? 0}m – $${stats?.players?.max_price ?? 0}m`} />
            <StatCard label="Budget" value="$100m" cls="teal" sub="Group Stage · $105m KO" />
            <StatCard label="Squad" value="15" cls="gold" sub="2 GK · 5 DEF · 5 MID · 3 FWD" />
          </div>

          {/* ── Tabs ── */}
          <div className="tabs">
            {[
              { id: 'projections', label: '📊 Projections' },
              { id: 'lineup', label: '⚽ Lineup' },
              { id: 'fixtures', label: '📅 Fixtures' },
            ].map(t => (
              <button key={t.id} className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}>
                {getTabLabel(t.id, t.label)}
              </button>
            ))}
          </div>

          {/* ── Tab Content ── */}
          {loading ? (
            <LoadingSkeleton />
          ) : (
            <>
              {tab === 'projections' && (
                <ProjectionsTab
                  players={displayPlayers}
                  search={search}
                  setSearch={setSearch}
                  posFilter={posFilter}
                  setPosFilter={setPosFilter}
                  sortBy={sortBy}
                  sortDesc={sortDesc}
                  handleSort={handleSort}
                  selectedTeamFilter={selectedTeamFilter}
                  setSelectedTeamFilter={setSelectedTeamFilter}
                />
              )}
              {tab === 'lineup' && (
                <SquadPlannerTab 
                  players={players} 
                  myTeamIds={myTeamState} 
                  setMyTeam={setMyTeam}
                  optimResult={optimResult}
                  setOptimResult={setOptimResult}
                />
              )}
              {tab === 'fixtures' && (
                <FixturesTab 
                  squads={squads} 
                  fixtures={fixtures} 
                  setSelectedTeamFilter={setSelectedTeamFilter} 
                  setTab={setTab} 
                />
              )}
            </>
          )}
        </main>

        {/* ── Sidebar ── */}
        <aside className="app-sidebar">
          <OptimizerPanel
            preset={preset}
            setPreset={setPreset}
            chip={chip}
            setChip={setChip}
            transferMode={transferMode}
            setTransferMode={setTransferMode}
            myTeam={myTeam}
            freeTransfers={freeTransfers}
            setFreeTransfers={setFreeTransfers}
            optimizing={optimizing}
            runOptimize={runOptimize}
            result={optimResult}
          />
        </aside>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════
   STAT CARD
   ═══════════════════════════════════════════ */
function StatCard({ label, value, cls, sub }) {
  return (
    <div className="stat-card">
      <div className="label">{label}</div>
      <div className={`value ${cls}`}>{value}</div>
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}





/* ═══════════════════════════════════════════
   PROJECTIONS TAB — Data Table
   ═══════════════════════════════════════════ */
function ProjectionsTab({ players, search, setSearch, posFilter, setPosFilter, sortBy, sortDesc, handleSort, selectedTeamFilter, setSelectedTeamFilter }) {
  const [page, setPage] = useState(0);
  const pageSize = 50;

  // Additional filtering for selectedTeamFilter
  const filteredPlayers = useMemo(() => {
    let list = players;
    if (selectedTeamFilter) {
      list = list.filter(p => p.team_abbr === selectedTeamFilter);
    }
    return list;
  }, [players, selectedTeamFilter]);

  const totalPages = Math.ceil(filteredPlayers.length / pageSize);
  const pageData = filteredPlayers.slice(page * pageSize, (page + 1) * pageSize);

  // Reset page when filters change
  useEffect(() => { setPage(0); }, [search, posFilter, sortBy, sortDesc, selectedTeamFilter]);

  const SortIcon = ({ col }) => {
    if (sortBy !== col) return <span style={{ opacity: 0.3 }}>↕</span>;
    return sortDesc ? <span>↓</span> : <span>↑</span>;
  };

  return (
    <div className="fade-in">
      {/* Toolbar */}
      <div style={{ display: 'flex', gap: '16px', marginBottom: '16px', alignItems: 'center', flexWrap: 'wrap' }}>
        <input 
          type="text" 
          placeholder="🔍 Search players..." 
          value={search} 
          onChange={e => setSearch(e.target.value)}
          className="search-input"
        />
        
        <div className="pos-filters">
          {['ALL', 'GK', 'DEF', 'MID', 'FWD'].map(pos => (
            <button 
              key={pos} 
              className={`pos-btn ${posFilter === (pos === 'ALL' ? '' : pos) ? 'active' : ''}`}
              onClick={() => setPosFilter(pos === 'ALL' ? '' : pos)}
            >
              {pos}
            </button>
          ))}
        </div>

        {selectedTeamFilter && (
          <button 
            onClick={() => setSelectedTeamFilter(null)}
            style={{ background: 'rgba(239, 68, 68, 0.2)', color: '#fca5a5', border: '1px solid rgba(239, 68, 68, 0.4)', padding: '4px 12px', borderRadius: '16px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '4px' }}
          >
            × Clear Team Filter ({selectedTeamFilter})
          </button>
        )}
      </div>

      {/* Data Table */}
      <div style={{ overflowX: 'auto', background: 'var(--clr-bg-elevated)', borderRadius: '8px', border: '1px solid var(--clr-border)' }}>
        <table className="data-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', padding: '12px' }}>Player</th>
              <th style={{ padding: '12px' }}>Pos</th>
              <th style={{ padding: '12px', cursor: 'pointer' }} onClick={() => handleSort('price')}>Price <SortIcon col="price" /></th>
              <th style={{ padding: '12px', cursor: 'pointer' }} onClick={() => handleSort('percent_selected')}>Own% <SortIcon col="percent_selected" /></th>
              <th style={{ padding: '12px', cursor: 'pointer' }} onClick={() => handleSort('form')}>Form <SortIcon col="form" /></th>
              <th style={{ padding: '12px', cursor: 'pointer' }} onClick={() => handleSort('total_points')}>Pts <SortIcon col="total_points" /></th>
              <th style={{ padding: '12px', cursor: 'pointer', color: 'var(--clr-teal)' }} onClick={() => handleSort('projected_pts')}>xPts <SortIcon col="projected_pts" /></th>
            </tr>
          </thead>
          <tbody>
            {pageData.map(p => (
              <tr key={p.id} style={{ borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 600 }}>
                  <span style={{ marginRight: '8px' }}>{countryFlag(p.team_abbr)}</span>
                  {p.display_name} <span style={{ color: 'var(--clr-text-muted)', fontSize: '0.7rem', fontWeight: 400 }}>{p.team_abbr}</span>
                </td>
                <td style={{ padding: '8px 12px', textAlign: 'center' }}><span className={`pos-badge ${p.position?.toLowerCase()}`}>{p.position}</span></td>
                <td style={{ padding: '8px 12px', textAlign: 'center' }}>${p.price?.toFixed(1)}m</td>
                <td style={{ padding: '8px 12px', textAlign: 'center' }}>{p.percent_selected?.toFixed(1)}%</td>
                <td style={{ padding: '8px 12px', textAlign: 'center' }}>{p.form?.toFixed(1)}</td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700 }}>{p.total_points}</td>
                <td style={{ padding: '8px 12px', textAlign: 'center', fontWeight: 700, color: 'var(--clr-teal)' }}>{p.projected_pts?.toFixed(2)}</td>
              </tr>
            ))}
            {pageData.length === 0 && (
              <tr><td colSpan="7" style={{ textAlign: 'center', padding: '24px', color: 'var(--clr-text-muted)' }}>No players found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '16px', marginTop: '16px' }}>
          <button 
            disabled={page === 0} 
            onClick={() => setPage(p => p - 1)}
            style={{ padding: '6px 12px', background: 'var(--clr-bg-elevated)', border: '1px solid var(--clr-border)', borderRadius: '4px', cursor: page === 0 ? 'not-allowed' : 'pointer', opacity: page === 0 ? 0.5 : 1 }}
          >
            ← Prev
          </button>
          <span style={{ fontSize: '0.8rem', color: 'var(--clr-text-muted)' }}>Page {page + 1} of {totalPages}</span>
          <button 
            disabled={page === totalPages - 1} 
            onClick={() => setPage(p => p + 1)}
            style={{ padding: '6px 12px', background: 'var(--clr-bg-elevated)', border: '1px solid var(--clr-border)', borderRadius: '4px', cursor: page === totalPages - 1 ? 'not-allowed' : 'pointer', opacity: page === totalPages - 1 ? 0.5 : 1 }}
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}


/* ═══════════════════════════════════════════
   FIXTURES TAB — Difficulty Grid
   ═══════════════════════════════════════════ */
function FixturesTab({ squads, fixtures, setSelectedTeamFilter, setTab }) {
  // Build fixture difficulty map per squad
  const grouped = useMemo(() => {
    // Only include rounds that have at least 1 fixture scheduled
    const roundIds = [...new Set(fixtures.map(f => f.round_id))].sort((a, b) => a - b);

    // All squads
    const allSquads = squads.sort((a, b) => a.abbr.localeCompare(b.abbr));

    const rows = allSquads.map(sq => {
      const cells = roundIds.map(rid => {
        const f = fixtures.find(fx =>
          fx.round_id === rid && (fx.home_squad_id === sq.id || fx.away_squad_id === sq.id)
        );
        if (!f) return null; // No fixture in this round

        const isHome = f.home_squad_id === sq.id;
        const oppAbbr = isHome ? (f.away_squad_abbr || '?') : (f.home_squad_abbr || '?');
        const diff = isHome ? (f.home_fdr || 3) : (f.away_fdr || 3);

        return { opp: oppAbbr, diff, isHome };
      });

      return { squad: sq, cells };
    });

    return { rows, roundIds };
  }, [squads, fixtures]);

  const onTeamClick = (abbr) => {
    setSelectedTeamFilter(abbr);
    setTab('projections');
  };

  return (
    <div className="fade-in">
      <div style={{ marginBottom: 'var(--sp-4)' }}>
        <h3 style={{ marginBottom: 'var(--sp-2)' }}>Fixture Difficulty Rating</h3>
        <p className="text-dim" style={{ fontSize: '0.8rem' }}>
          Difficulty scaled 1-5 based on opponent's FIFA strength rating. Click a team to view their players.
        </p>
      </div>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 'var(--sp-2)', marginBottom: 'var(--sp-4)' }}>
        {[1,2,3,4,5].map(d => (
          <div key={d} className={`fixture-cell diff-${d}`} style={{ width: '50px', fontSize: '0.65rem' }}>
            FDR {d}
          </div>
        ))}
      </div>

      {/* Fixture rows */}
      <div style={{ overflowX: 'auto', background: 'var(--clr-bg-elevated)', borderRadius: '8px', border: '1px solid var(--clr-border)' }}>
        <div style={{ minWidth: '600px' }}>
          {/* Round headers */}
          <div className="fixture-row" style={{ position: 'sticky', top: 0, background: 'var(--clr-bg)', zIndex: 10, padding: '8px 0', borderBottom: '1px solid var(--clr-border)' }}>
            <div className="team-name text-muted" style={{ fontSize: '0.65rem', position: 'sticky', left: 0, background: 'var(--clr-bg)', zIndex: 11 }}>TEAM</div>
            <div className="fixture-cells">
              {grouped.roundIds.map(rid => (
                <div key={rid} style={{ flex: 1, textAlign: 'center', fontSize: '0.6rem', fontWeight: 700, color: 'var(--clr-text-muted)', textTransform: 'uppercase' }}>
                  R{rid}
                </div>
              ))}
            </div>
          </div>

          <div className="fixture-grid">
        {grouped.rows.map(({ squad: sq, cells }) => (
          <div key={sq.id} className="fixture-row table-row-hover" onClick={() => onTeamClick(sq.abbr)} style={{ cursor: 'pointer' }}>
            <div className="team-name" style={{ position: 'sticky', left: 0, background: 'var(--clr-bg)' }}>
              {countryFlag(sq.abbr)} {sq.abbr}
            </div>
            <div className="fixture-cells">
              {cells.map((c, i) => c ? (
                <div key={i} className={`fixture-cell diff-${c.diff}`} title={`vs ${c.opp} (${c.isHome ? 'H' : 'A'})`}>
                  {c.opp}
                </div>
              ) : (
                <div key={i} className="fixture-cell" style={{ opacity: 0.2 }}>-</div>
              ))}
            </div>
          </div>
        ))}
        </div>
      </div>
    </div>
  </div>
  );
}


/* ═══════════════════════════════════════════
   OPTIMIZER PANEL (Sidebar)
   ═══════════════════════════════════════════ */
function OptimizerPanel({ preset, setPreset, chip, setChip, transferMode, setTransferMode, myTeam, freeTransfers, setFreeTransfers, optimizing, runOptimize, result }) {
  const presets = [
    { id: 'default', label: '⚡ Balanced', desc: 'Max total xPts' },
    { id: 'value', label: '💎 Value', desc: 'Best pts per $' },
    { id: 'safe', label: '🛡️ Safe', desc: 'High ownership' },
    { id: 'risky', label: '🎯 Differential', desc: 'Low ownership gems' },
    { id: 'template', label: '👥 Template', desc: 'Popular picks' },
  ];

  return (
    <div>
      <div className="sidebar-section">
        <div className="section-title">
          <Icon.Trophy /> Squad Optimizer
        </div>

        <div className="optimizer-panel">
          {/* Preset Selection */}
          <div style={{ marginBottom: 'var(--sp-3)' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--clr-text-muted)', marginBottom: 'var(--sp-2)', fontWeight: 600 }}>STRATEGY</div>
            <div className="preset-grid">
              {presets.map(p => (
                <button
                  key={p.id}
                  className={`preset-btn ${preset === p.id ? 'active' : ''}`}
                  onClick={() => setPreset(p.id)}
                  title={p.desc}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Stage selector */}
          <div style={{ marginBottom: 'var(--sp-4)' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--clr-text-muted)', marginBottom: 'var(--sp-2)', fontWeight: 600 }}>STAGE</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--clr-text)', padding: 'var(--sp-2)', background: 'var(--clr-bg-elevated)', borderRadius: 'var(--r-sm)', textAlign: 'center', fontWeight: 600 }}>
              📍 Group Stage — Matchday 1
            </div>
          </div>
          
          {/* Transfer Planner Toggle */}
          <div style={{ marginBottom: 'var(--sp-4)', background: 'rgba(255, 255, 255, 0.03)', padding: '12px', borderRadius: '8px', border: '1px solid var(--clr-border)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <div style={{ fontSize: '0.8rem', fontWeight: 600 }}>🔄 Transfer Planner</div>
              <label className="switch" style={{ cursor: 'pointer' }}>
                <input type="checkbox" checked={transferMode} onChange={(e) => setTransferMode(e.target.checked)} />
                <span className="slider"></span>
              </label>
            </div>
            
            {transferMode && (
              <div style={{ marginTop: '12px', fontSize: '0.8rem' }}>
                {myTeam.length === 15 ? (
                  <div style={{ color: '#2dd4bf', marginBottom: '8px' }}>✓ My Team loaded (15 players)</div>
                ) : (
                  <div style={{ color: '#fb7185', marginBottom: '8px' }}>⚠️ Save a team first!</div>
                )}
                
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ color: 'var(--clr-text-muted)' }}>Free Transfers:</span>
                  <input type="number" min="0" max="15" value={freeTransfers} onChange={e => setFreeTransfers(parseInt(e.target.value) || 0)}
                         style={{ width: '50px', background: 'var(--clr-bg-dark)', color: 'white', border: '1px solid var(--clr-border)', padding: '4px', borderRadius: '4px', textAlign: 'center' }} />
                </div>
              </div>
            )}
          </div>

          {/* Chip/Booster Selection */}
          <div style={{ marginBottom: 'var(--sp-4)' }}>
            <div style={{ fontSize: '0.7rem', color: 'var(--clr-text-muted)', marginBottom: 'var(--sp-2)', fontWeight: 600 }}>BOOSTER (CHIP)</div>
            <select
              value={chip}
              onChange={e => setChip(e.target.value)}
              style={{
                width: '100%', padding: 'var(--sp-2)',
                background: 'var(--clr-bg-elevated)', color: 'var(--clr-text)',
                border: '1px solid var(--clr-border)', borderRadius: 'var(--r-sm)',
                fontSize: '0.8rem', outline: 'none', cursor: 'pointer'
              }}
            >
              <option value="none">🚫 No Booster</option>
              <option value="12th_man">👤 12th Man</option>
              <option value="max_captain">⭐ Maximum Captain</option>
              <option value="wildcard">🃏 Wildcard</option>
              <option value="qualification">📈 Qualification Booster</option>
              <option value="mystery">❓ Mystery Booster (TBA)</option>
            </select>
          </div>

          {/* Run button */}
          <button className="optimize-btn" onClick={runOptimize} disabled={optimizing}>
            {optimizing ? (
              <><Icon.Loader /> Optimizing...</>
            ) : (
              <><Icon.Zap /> Optimize Squad</>
            )}
          </button>

          {/* Result summary */}
          {result && (
            <div className="squad-summary" style={{ marginTop: 'var(--sp-3)' }}>
              <div className="item">
                <div className="val">{result.total_projected_pts?.toFixed(1)}</div>
                <div className="lbl">Proj. Pts</div>
              </div>
              <div className="item">
                <div className="val">${result.budget_used?.toFixed(1)}m</div>
                <div className="lbl">Budget</div>
              </div>
              <div className="item">
                <div className="val" style={{ color: 'var(--clr-teal)' }}>${result.budget_remaining?.toFixed(1)}m</div>
                <div className="lbl">Remaining</div>
              </div>
              <div className="item">
                <div className="val" style={{ color: 'var(--clr-text)', fontSize: '0.8rem' }}>{result.method?.toUpperCase()}</div>
                <div className="lbl">Method</div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Optimized Squad List */}
      {result && (
        <div className="sidebar-section">
          <div className="section-title">Selected Squad (15)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {(result.squad || [])
              .sort((a, b) => ['GK','DEF','MID','FWD'].indexOf(a.position) - ['GK','DEF','MID','FWD'].indexOf(b.position))
              .map(p => {
                const isXI = result.starting_xi?.some(x => x.id === p.id);
                const isCap = result.captain?.id === p.id;
                const isVC = result.vice_captain?.id === p.id;
                return (
                  <div key={p.id} style={{
                    display: 'flex', alignItems: 'center', gap: 'var(--sp-2)',
                    padding: '4px 8px', borderRadius: 'var(--r-sm)',
                    background: isXI ? 'var(--clr-bg-elevated)' : 'transparent',
                    opacity: isXI ? 1 : 0.5,
                    fontSize: '0.75rem',
                  }}>
                    <span className={`pos-badge ${p.position?.toLowerCase()}`} style={{ width: '26px', fontSize: '0.55rem' }}>{p.position}</span>
                    <span style={{ flex: 1, fontWeight: 600 }}>
                      {countryFlag(p.team_abbr)} {p.display_name?.split(' ').pop()}
                      {isCap && <span style={{ marginLeft: '4px', color: 'var(--clr-gold)', fontSize: '0.6rem', fontWeight: 800 }}>C</span>}
                      {isVC && <span style={{ marginLeft: '4px', color: 'var(--clr-teal)', fontSize: '0.6rem', fontWeight: 800 }}>VC</span>}
                    </span>
                    <span className="price" style={{ fontSize: '0.65rem' }}>${p.price?.toFixed(1)}</span>
                    <span className="xpts" style={{ fontSize: '0.65rem', width: '32px', textAlign: 'right' }}>{p.projected_pts?.toFixed(1)}</span>
                  </div>
                );
            })}
          </div>
        </div>
      )}

      {/* Rules Quick Reference */}
      <div className="sidebar-section">
        <div className="section-title">Quick Rules (WC 2026)</div>
        <div className="card" style={{ fontSize: '0.7rem', color: 'var(--clr-text-dim)' }}>
          <div style={{ marginBottom: '6px' }}>🔄 <strong>Rolling Lockout:</strong> Manual subs allowed during a round! Swap unlocked bench players for unlocked starters, OR for locked starters who have <em>finished</em> playing.</div>
          <div style={{ marginBottom: '6px', color: 'var(--clr-warning)' }}>⚠️ <strong>Warning:</strong> Making a manual sub or changing Captain cancels Auto-Subs for that matchday.</div>
          <div style={{ marginBottom: '6px' }}>⭐ <strong>Captaincy:</strong> Can be changed multiple times to players who haven't played yet.</div>
          <div style={{ marginBottom: '6px' }}>📉 <strong>Transfers:</strong> -3 pts per extra transfer (not -4 like FPL).</div>
          <div>🚀 <strong>Boosters:</strong> 12th Man (extra player), Max Captain (auto highest scorer), Wildcard, Qualification, Mystery.</div>
        </div>
      </div>
    </div>
  );
}


/* ═══════════════════════════════════════════
   LOADING SKELETON
   ═══════════════════════════════════════════ */
function LoadingSkeleton() {
  return (
    <div style={{ padding: 'var(--sp-5)' }}>
      {[...Array(8)].map((_, i) => (
        <div key={i} className="skeleton" style={{ height: '40px', marginBottom: '8px', animationDelay: `${i * 100}ms` }} />
      ))}
    </div>
  );
}
