import React, { useState, useMemo } from 'react';

// Sort logic
export function autoSortSquad(teamPlayers) {
  const sorted = [...teamPlayers].sort((a, b) => new Date(a.next_match_date || '2099') - new Date(b.next_match_date || '2099'));
  
  const gks = sorted.filter(p => p.position === 'GK');
  const defs = sorted.filter(p => p.position === 'DEF');
  const mids = sorted.filter(p => p.position === 'MID');
  const fwds = sorted.filter(p => p.position === 'FWD');

  const xi = [];
  const bench = [];

  if (gks.length > 0) xi.push(gks[0]);
  if (gks.length > 1) bench.push(gks[1]);

  const outfields = [];
  if (defs.length > 0) { xi.push(...defs.slice(0, Math.min(3, defs.length))); outfields.push(...defs.slice(3)); }
  if (mids.length > 0) { xi.push(...mids.slice(0, Math.min(2, mids.length))); outfields.push(...mids.slice(2)); }
  if (fwds.length > 0) { xi.push(...fwds.slice(0, Math.min(1, fwds.length))); outfields.push(...fwds.slice(1)); }

  outfields.sort((a, b) => new Date(a.next_match_date || '2099') - new Date(b.next_match_date || '2099'));

  while (xi.length < 11 && outfields.length > 0) {
    xi.push(outfields.shift());
  }
  bench.push(...outfields);

  return { xi, bench };
}

function padSquad(xi, bench, teamPlayers) {
  let gks = teamPlayers.filter(p => p.position === 'GK').length;
  let defs = teamPlayers.filter(p => p.position === 'DEF').length;
  let mids = teamPlayers.filter(p => p.position === 'MID').length;
  let fwds = teamPlayers.filter(p => p.position === 'FWD').length;

  const paddedXi = [...xi];
  const paddedBench = [...bench];

  if (!paddedXi.find(p => p?.position === 'GK')) paddedXi.push({ isPlaceholder: true, position: 'GK' });
  if (!paddedBench.find(p => p?.position === 'GK')) paddedBench.unshift({ isPlaceholder: true, position: 'GK' });

  const addXi = (pos) => paddedXi.push({ isPlaceholder: true, position: pos });
  while (paddedXi.length < 11) {
    if (defs < 4) { addXi('DEF'); defs++; }
    else if (mids < 4) { addXi('MID'); mids++; }
    else if (fwds < 2) { addXi('FWD'); fwds++; }
    else if (defs < 5) { addXi('DEF'); defs++; }
    else if (mids < 5) { addXi('MID'); mids++; }
    else if (fwds < 3) { addXi('FWD'); fwds++; }
    else addXi('ANY');
  }

  const addBench = (pos) => paddedBench.push({ isPlaceholder: true, position: pos });
  while (paddedBench.length < 4) {
    if (defs < 5) { addBench('DEF'); defs++; }
    else if (mids < 5) { addBench('MID'); mids++; }
    else if (fwds < 3) { addBench('FWD'); fwds++; }
    else addBench('ANY');
  }

  return { xi: paddedXi.slice(0, 11), bench: paddedBench.slice(0, 4) };
}

// Player Modal
function PlayerSelectModal({ isOpen, onClose, players, targetPos, onSelect, currentTeamIds }) {
  const [search, setSearch] = useState('');
  if (!isOpen) return null;

  const filtered = players.filter(p => {
    if (currentTeamIds.includes(p.id)) return false;
    if (targetPos && targetPos !== 'ANY' && p.position !== targetPos) return false;
    if (search && !p.display_name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }).slice(0, 50);

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--clr-bg-card)', padding: '20px', borderRadius: '12px', width: '90%', maxWidth: '500px', maxHeight: '80vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h3 style={{ margin: 0 }}>Select {targetPos !== 'ANY' ? targetPos : 'Player'}</h3>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'white', cursor: 'pointer' }}>✖</button>
        </div>
        <input 
          type="text" 
          placeholder="Search..." 
          value={search} 
          onChange={e => setSearch(e.target.value)}
          className="search-input" 
          style={{ width: '100%', marginBottom: '16px', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {filtered.map(p => (
            <div key={p.id} onClick={() => onSelect(p)} className="table-row-hover" style={{ display: 'flex', justifyContent: 'space-between', padding: '12px', background: 'var(--clr-bg-elevated)', borderRadius: '8px', cursor: 'pointer' }}>
              <div>
                <strong style={{ display: 'block' }}>{p.display_name}</strong>
                <span style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)' }}>{p.team_abbr} • {p.position}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <strong style={{ color: 'var(--clr-gold)', display: 'block' }}>${p.price}m</strong>
                <span style={{ color: 'var(--clr-teal)', fontSize: '0.75rem' }}>{p.projected_pts?.toFixed(1)} xPts</span>
              </div>
            </div>
          ))}
          {filtered.length === 0 && <div style={{ textAlign: 'center', color: 'var(--clr-text-muted)' }}>No players found.</div>}
        </div>
      </div>
    </div>
  );
}

const COUNTRY_ISO = {
  ARG:'ar',FRA:'fr',BRA:'br',ENG:'gb-eng',ESP:'es',POR:'pt',GER:'de',NED:'nl',
  URU:'uy',COL:'co',CRO:'hr',MAR:'ma',JPN:'jp',BEL:'be',SUI:'ch',USA:'us',
  SEN:'sn',TUR:'tr',AUT:'at',KOR:'kr',NOR:'no',EGY:'eg',MEX:'mx',SWE:'se',
  ECU:'ec',IRN:'ir',SCO:'gb-sct',CIV:'ci',PAR:'py',ALG:'dz',CZE:'cz',AUS:'au',
  RSA:'za',TUN:'tn',PAN:'pa',GHA:'gh',IRQ:'iq',QAT:'qa',CAN:'ca',BIH:'ba',
  JOR:'jo',UZB:'uz',KSA:'sa',NZL:'nz',COD:'cd',HAI:'ht',CUW:'cw',CPV:'cv',
};

function getFlagUrl(abbr) {
  const iso = COUNTRY_ISO[abbr];
  if (!iso) return null;
  return `https://flagcdn.com/w80/${iso}.png`;
}

function PitchPlayer({ player: p, isCaptain, onClick }) {
  if (p.isPlaceholder) {
    return (
      <div className="pitch-player is-placeholder" onClick={onClick} style={{ cursor: 'pointer', opacity: 0.6 }}>
        <div className="pitch-jersey" style={{ background: 'rgba(255,255,255,0.1)', border: '1px dashed rgba(255,255,255,0.4)', borderRadius: '4px', width: '32px', height: '40px', margin: '0 auto' }}>
          <span style={{ fontSize: '1.2rem', lineHeight: '40px', color: 'rgba(255,255,255,0.5)' }}>+</span>
        </div>
        <div className="pitch-player-info">
          <div className="pitch-nameplate" style={{ background: 'transparent' }}>Add {p.position}</div>
        </div>
      </div>
    );
  }

  const lastName = p.display_name?.split(' ').pop() || '?';
  const flagUrl = getFlagUrl(p.team_abbr);
  const pos = p.position?.toLowerCase();

  return (
    <div className="pitch-player" onClick={onClick} style={{ cursor: 'pointer' }}>
      <div className={`pitch-jersey ${pos}`}>
        {isCaptain && <div className="pitch-badge captain">C</div>}
        {flagUrl ? (
          <img className="jersey-flag" src={flagUrl} alt={p.team_abbr} onError={e => { e.target.style.display = 'none'; e.target.parentNode.innerText = p.team_abbr; }} />
        ) : (
          <span style={{ fontSize: '1.1rem' }}>🏳️</span>
        )}
      </div>
      <div className="pitch-player-info">
        <div className="pitch-nameplate">{lastName}</div>
        <div className={`pitch-pts ${isCaptain ? 'is-captain' : ''}`}>{p.projected_pts?.toFixed(1)}</div>
        {p.next_match_date && p.next_match_date !== "2099-12-31T00:00:00Z" && (
          <div style={{ fontSize: '0.55rem', color: '#94a3b8', background: 'rgba(0,0,0,0.5)', width: '100%', textAlign: 'center', borderTop: '1px solid rgba(255,255,255,0.1)', padding: '1px 0' }}>
            {new Date(p.next_match_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function SquadPlannerTab({ players, myTeamIds, setMyTeam, optimResult, setOptimResult }) {
  const [modalOpen, setModalOpen] = useState(false);
  const [targetPos, setTargetPos] = useState('ANY');
  const [playerToReplace, setPlayerToReplace] = useState(null);

  const teamPlayers = useMemo(() => {
    return myTeamIds.map(id => players.find(p => p.id === id)).filter(Boolean);
  }, [myTeamIds, players]);

  // Determine which squad to show: optimizer result OR myTeam
  const isOptimMode = !!optimResult;
  
  const currentXi = isOptimMode ? optimResult.starting_xi : autoSortSquad(teamPlayers).xi;
  const currentBench = isOptimMode ? optimResult.bench : autoSortSquad(teamPlayers).bench;
  const captain = isOptimMode ? optimResult.captain : currentXi[0]; // simplistic captain for planner
  const totalXPts = isOptimMode ? optimResult.total_projected_pts : currentXi.reduce((sum, p) => sum + (p.projected_pts || 0), 0) + (captain?.projected_pts || 0);

  const { xi, bench } = isOptimMode 
    ? { xi: padSquad(currentXi, currentBench, currentXi.concat(currentBench)).xi, bench: padSquad(currentXi, currentBench, currentXi.concat(currentBench)).bench }
    : padSquad(currentXi, currentBench, teamPlayers);

  const gks = xi.filter(p => p.position === 'GK');
  const defs = xi.filter(p => p.position === 'DEF');
  const mids = xi.filter(p => p.position === 'MID');
  const fwds = xi.filter(p => p.position === 'FWD');

  const benchLabels = bench.map((p, i) => i === 0 || p.position === 'GK' ? 'GKP' : `${i}. ${p.position || 'SUB'}`);

  const handleSlotClick = (p) => {
    if (isOptimMode) return; // Disable editing while viewing optimizer result
    setPlayerToReplace(p.isPlaceholder ? null : p);
    setTargetPos(p.position);
    setModalOpen(true);
  };

  const handleSelectPlayer = (newPlayer) => {
    let newIds = [...myTeamIds];
    if (playerToReplace) {
      newIds = newIds.filter(id => id !== playerToReplace.id);
    }
    if (!newIds.includes(newPlayer.id)) {
      newIds.push(newPlayer.id);
    }
    setMyTeam(newIds);
    setModalOpen(false);
  };

  return (
    <div className="fade-in">
      {isOptimMode && (
        <div style={{ marginBottom: '16px', padding: '16px', background: 'linear-gradient(135deg, rgba(45, 212, 191, 0.15), rgba(15, 118, 110, 0.2))', border: '1px solid rgba(45, 212, 191, 0.3)', borderRadius: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
          <div>
            <h3 style={{ color: 'var(--clr-teal)', margin: '0 0 6px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
              ✨ Optimizer Suggestion
            </h3>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--clr-text-muted)' }}>Review the suggested squad. Accept to overwrite your team.</p>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button 
              onClick={() => { setMyTeam(optimResult.squad.map(p => p.id)); setOptimResult(null); }}
              style={{
                background: 'linear-gradient(135deg, #10b981, #059669)',
                color: 'white',
                border: 'none',
                padding: '10px 20px',
                borderRadius: '8px',
                fontWeight: '700',
                fontSize: '0.9rem',
                cursor: 'pointer',
                boxShadow: '0 4px 10px rgba(16, 185, 129, 0.3)',
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 14px rgba(16, 185, 129, 0.4)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 10px rgba(16, 185, 129, 0.3)'; }}
            >
              ✅ Accept
            </button>
            <button 
              onClick={() => setOptimResult(null)} 
              style={{ 
                background: 'rgba(239, 68, 68, 0.1)', 
                color: '#fca5a5', 
                border: '1px solid rgba(239, 68, 68, 0.3)', 
                padding: '10px 20px', 
                borderRadius: '8px', 
                fontWeight: '600',
                fontSize: '0.9rem',
                cursor: 'pointer',
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                gap: '6px'
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)'; e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.5)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'; e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)'; }}
            >
              ❌ Discard
            </button>
          </div>
        </div>
      )}

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', marginBottom: '12px', background: 'var(--clr-bg-card)', borderRadius: 'var(--r-sm)', border: '1px solid var(--clr-border)', fontSize: '0.75rem' }}>
        <span style={{ color: 'var(--clr-text-muted)' }}>
          ⭐ Captain: <strong style={{ color: 'var(--clr-gold)' }}>{captain?.display_name || '-'}</strong>
        </span>
        <span style={{ color: 'var(--clr-text-muted)' }}>
          Total xPts: <strong style={{ color: 'var(--clr-teal)' }}>{totalXPts?.toFixed(1) || '0.0'}</strong>
        </span>
      </div>

      <div className="pitch">
        <div className="pitch-markings">
          <div className="pitch-box-top" />
          <div className="pitch-goal-top" />
          <div className="pitch-box-bottom" />
          <div className="pitch-goal-bottom" />
        </div>

        <div className="pitch-row" style={{ paddingTop: '16px' }}>
          {fwds.map((p, i) => <PitchPlayer key={p.id || `fwd-${i}`} player={p} isCaptain={captain?.id === p.id} onClick={() => handleSlotClick(p)} />)}
        </div>
        <div className="pitch-row">
          {mids.map((p, i) => <PitchPlayer key={p.id || `mid-${i}`} player={p} isCaptain={captain?.id === p.id} onClick={() => handleSlotClick(p)} />)}
        </div>
        <div className="pitch-row">
          {defs.map((p, i) => <PitchPlayer key={p.id || `def-${i}`} player={p} isCaptain={captain?.id === p.id} onClick={() => handleSlotClick(p)} />)}
        </div>
        <div className="pitch-row" style={{ paddingBottom: '16px' }}>
          {gks.map((p, i) => <PitchPlayer key={p.id || `gk-${i}`} player={p} isCaptain={captain?.id === p.id} onClick={() => handleSlotClick(p)} />)}
        </div>
      </div>

      <div className="bench-section">
        <div className="bench-header">
          {benchLabels.map((lbl, i) => <div key={i} className="slot-label">{lbl}</div>)}
        </div>
        <div className="bench-row">
          {bench.map((p, i) => (
            <div key={p.id || `bench-${i}`} className="bench-player">
              <PitchPlayer player={p} onClick={() => handleSlotClick(p)} />
            </div>
          ))}
        </div>
      </div>

      <PlayerSelectModal 
        isOpen={modalOpen} 
        onClose={() => setModalOpen(false)} 
        players={players} 
        targetPos={targetPos} 
        onSelect={handleSelectPlayer} 
        currentTeamIds={myTeamIds} 
      />
    </div>
  );
}
