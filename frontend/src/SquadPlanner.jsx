import React, { useState, useMemo, useRef, useEffect } from 'react';

// ══════════════════════════════════════════════
// Transfer rules per stage (WC 2026 Fantasy)
// ══════════════════════════════════════════════
const TRANSFER_RULES = {
  GROUP_MD1: { label: 'Group MD1', freeOptions: ['unlimited'], default: 'unlimited', maxCountry: 3 },
  GROUP_MD2: { label: 'Group MD2', freeOptions: [0, 1, 2, 3], default: 2, maxCountry: 3 },
  GROUP_MD3: { label: 'Group MD3', freeOptions: [0, 1, 2, 3], default: 2, maxCountry: 3 },
  R32:       { label: 'Round of 32', freeOptions: ['unlimited'], default: 'unlimited', maxCountry: 3 },
  R16:       { label: 'Round of 16', freeOptions: [0, 1, 2, 3, 4], default: 4, maxCountry: 4 },
  QF:        { label: 'Quarter-Finals', freeOptions: [0, 1, 2, 3, 4], default: 4, maxCountry: 5 },
  SF:        { label: 'Semi-Finals', freeOptions: [0, 1, 2, 3, 4, 5], default: 5, maxCountry: 6 },
  FINAL:     { label: 'Final', freeOptions: [0, 1, 2, 3, 4, 5, 6], default: 6, maxCountry: 8 },
};

const TRANSFER_PENALTY = -3; // pts per extra transfer

// ══════════════════════════════════════════════
// Sort logic (Points-based best XI)
// ══════════════════════════════════════════════
export function autoSortSquad(teamPlayers) {
  const sorted = [...teamPlayers].sort((a, b) => (b.projected_pts || 0) - (a.projected_pts || 0));
  
  const gks = sorted.filter(p => p.position === 'GK');
  const defs = sorted.filter(p => p.position === 'DEF');
  const mids = sorted.filter(p => p.position === 'MID');
  const fwds = sorted.filter(p => p.position === 'FWD');

  const xi = [];
  const bench = [];

  // Pick top GK
  if (gks.length > 0) xi.push(gks[0]);
  if (gks.length > 1) bench.push(...gks.slice(1));

  // Pick minimum required for valid formation
  const outfields = [];
  if (defs.length > 0) { xi.push(...defs.slice(0, Math.min(3, defs.length))); outfields.push(...defs.slice(3)); }
  if (mids.length > 0) { xi.push(...mids.slice(0, Math.min(2, mids.length))); outfields.push(...mids.slice(2)); }
  if (fwds.length > 0) { xi.push(...fwds.slice(0, Math.min(1, fwds.length))); outfields.push(...fwds.slice(1)); }

  // Sort remaining outfields by pts descending
  outfields.sort((a, b) => (b.projected_pts || 0) - (a.projected_pts || 0));

  // Fill up to 11
  while (xi.length < 11 && outfields.length > 0) {
    xi.push(outfields.shift());
  }
  // Rest to bench
  bench.push(...outfields);

  return { xi, bench };
}

// Validation for substitutions
function isValidFormation(xi) {
  const gks = xi.filter(p => p.position === 'GK' && !p.isPlaceholder).length;
  const defs = xi.filter(p => p.position === 'DEF' && !p.isPlaceholder).length;
  const mids = xi.filter(p => p.position === 'MID' && !p.isPlaceholder).length;
  const fwds = xi.filter(p => p.position === 'FWD' && !p.isPlaceholder).length;
  
  const total = gks + defs + mids + fwds;
  if (total > 11) return false;
  if (total < 11) {
    if (gks > 1 || defs > 5 || mids > 5 || fwds > 3) return false;
    return true; // Partial squad is valid
  }
  
  return gks === 1 && defs >= 3 && defs <= 5 && mids >= 2 && mids <= 5 && fwds >= 1 && fwds <= 3;
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

// ══════════════════════════════════════════════
// Player Search Modal
// ══════════════════════════════════════════════
function PlayerSelectModal({ isOpen, onClose, players, targetPos, onSelect, currentTeamIds }) {
  const [search, setSearch] = useState('');
  if (!isOpen) return null;

  const filtered = players.filter(p => {
    if (currentTeamIds.includes(p.id)) return false;
    if (targetPos && targetPos !== 'ANY' && p.position !== targetPos) return false;
    const normalizeStr = (str) => str ? str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase() : '';
    if (search && !normalizeStr(p.display_name).includes(normalizeStr(search))) return false;
    return true;
  }).sort((a,b) => (b.projected_pts||0) - (a.projected_pts||0)).slice(0, 50);

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, background: 'rgba(0,0,0,0.8)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--clr-bg-card)', padding: '20px', borderRadius: '12px', width: '90%', maxWidth: '500px', maxHeight: '80vh', overflowY: 'auto', border: '1px solid var(--clr-border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
          <h3 style={{ margin: 0 }}>Select {targetPos !== 'ANY' ? targetPos : 'Player'}</h3>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: 'white', cursor: 'pointer' }}>Close</button>
        </div>
        <input 
          type="text" 
          placeholder="Search players..." 
          value={search} 
          onChange={e => setSearch(e.target.value)}
          className="search-input" 
          style={{ width: '100%', marginBottom: '16px', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {filtered.map(p => (
            <div key={p.id} onClick={() => onSelect(p)} className="table-row-hover" style={{ display: 'flex', justifyContent: 'space-between', padding: '12px', background: 'var(--clr-bg-elevated)', borderRadius: '8px', cursor: 'pointer' }}>
              <div>
                <strong style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  {p.display_name}
                  {p.injury_status === 'INJURED' || p.injury_status === 'SUSPENDED' ? (
                    <span style={{ color: '#fff', background: 'var(--clr-danger)', borderRadius: '50%', width: '14px', height: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: 'bold' }} title={p.injury_text || 'Injured'}>!</span>
                  ) : p.injury_status === 'DOUBTFUL' ? (
                    <span style={{ color: '#000', background: 'var(--clr-gold)', borderRadius: '50%', width: '14px', height: '14px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '10px', fontWeight: 'bold' }} title={p.injury_text || 'Doubtful'}>?</span>
                  ) : null}
                </strong>
                <span style={{ fontSize: '0.75rem', color: 'var(--clr-text-muted)' }}>{p.team_abbr} • {p.position}</span>
              </div>
              <div style={{ textAlign: 'right' }}>
                <strong style={{ color: 'var(--clr-gold)', display: 'block' }}>${p.price}m</strong>
                <span style={{ color: 'var(--clr-teal)', fontSize: '0.75rem' }}>{p.projected_pts?.toFixed(1)} xPts</span>
              </div>
            </div>
          ))}
          {filtered.length === 0 && <div style={{ textAlign: 'center', color: 'var(--clr-text-muted)', padding: '20px 0' }}>No players found.</div>}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════
// Action Menu Modal (with Captain option)
// ══════════════════════════════════════════════
function ActionMenuModal({ player, isOpen, onClose, onTransfer, onSub, onSetCaptain, onSetViceCaptain, isInXI }) {
  if (!isOpen || !player) return null;
  return (
    <div className="action-modal-overlay">
      <div className="action-modal-card">
        <h3 style={{ marginTop: 0, marginBottom: '4px' }}>{player.display_name}</h3>
        <p style={{ color: 'var(--clr-text-muted)', fontSize: '0.85rem', marginBottom: '20px' }}>What would you like to do?</p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {/* Set Captain - only for XI players */}
          {isInXI && onSetCaptain && (
            <button className="action-modal-btn action-btn-cap" onClick={() => { onSetCaptain(player); onClose(); }}>
              Set Captain
            </button>
          )}
          {isInXI && onSetViceCaptain && (
            <button className="action-modal-btn action-btn-vcap" onClick={() => { onSetViceCaptain(player); onClose(); }}>
              Set Vice Captain
            </button>
          )}
          <button className="action-modal-btn action-btn-sub" onClick={() => { onSub(player); onClose(); }}>
            Substitute
          </button>
          <button className="action-modal-btn action-btn-trans" onClick={() => { onTransfer(player); onClose(); }}>
            Transfer
          </button>
          <button className="action-modal-btn" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════
// Country flags
// ══════════════════════════════════════════════
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

// ══════════════════════════════════════════════
// PitchPlayer component
// ══════════════════════════════════════════════
function PitchPlayer({ player: p, isCaptain, isViceCaptain, isSubSource, onClick, viewMode = 'xPts' }) {
  if (p.isPlaceholder) {
    return (
      <div className="pitch-player is-placeholder" onClick={onClick} style={{ cursor: 'pointer', opacity: 0.6 }}>
        <div className="pitch-jersey" style={{ background: 'rgba(255,255,255,0.1)', border: '1px dashed rgba(255,255,255,0.4)', borderRadius: '4px', width: '32px', height: '40px', margin: '0 auto' }}>
          <span style={{ fontSize: '1.2rem', lineHeight: '40px', color: 'rgba(255,255,255,0.5)' }}>+</span>
        </div>
        <div className="pitch-player-info">
          <div className="pitch-nameplate" style={{ background: 'var(--clr-text-dim)', color: '#fff' }}>Add {p.position}</div>
        </div>
      </div>
    );
  }

  const lastName = p.display_name?.split(' ').pop() || '?';
  const flagUrl = getFlagUrl(p.team_abbr);
  const pos = p.position?.toLowerCase();

  let displayValue = '';
  switch(viewMode) {
    case 'Price': displayValue = `$${p.price?.toFixed(1)}m`; break;
    case '% Selected': displayValue = `${p.percent_selected?.toFixed(1)}%`; break;
    case 'Date': displayValue = (p.next_match_date && p.next_match_date !== "2099-12-31T00:00:00Z") ? new Date(p.next_match_date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '-'; break;
    case 'xPts':
    default: 
      displayValue = p.projected_pts?.toFixed(1); 
      break;
  }

  const is12thMan = p.is_12th_man;

  return (
    <div className="pitch-player" onClick={onClick} style={{ cursor: 'pointer' }}>
      <div className={`pitch-jersey ${pos}`} style={{
        boxShadow: isSubSource ? '0 0 0 3px var(--clr-secondary), 0 0 15px var(--clr-secondary)' : 'none',
        transform: isSubSource ? 'scale(1.1)' : 'scale(1)',
      }}>
        {isCaptain && <div className="pitch-badge captain">C</div>}
        {isViceCaptain && <div className="pitch-badge vice">V</div>}
        {p.injury_status === 'INJURED' && <div className="pitch-badge injury" title="Injured">!</div>}
        {flagUrl ? (
          <img className="jersey-flag" src={flagUrl} alt={p.team_abbr} onError={e => { e.target.style.display = 'none'; e.target.parentNode.innerText = p.team_abbr; }} />
        ) : (
          <span style={{ fontSize: '0.8rem' }}>None</span>
        )}
      </div>
      <div className="pitch-player-info">
        <div className="pitch-nameplate" title={p.display_name} style={{
          background: (p.injury_status === 'INJURED' || p.injury_status === 'SUSPENDED') ? 'var(--clr-danger)' : 
                      p.injury_status === 'DOUBTFUL' ? 'var(--clr-gold)' : undefined,
          borderColor: (p.injury_status === 'INJURED' || p.injury_status === 'SUSPENDED') ? 'var(--clr-danger)' : 
                       p.injury_status === 'DOUBTFUL' ? 'var(--clr-gold)' : undefined,
          color: p.injury_status === 'DOUBTFUL' ? '#000' : undefined
        }}>
          {lastName}
        </div>
        <div className={`pitch-pts ${isCaptain ? 'is-captain' : ''}`} style={is12thMan ? { color: '#a78bfa' } : {}}>
          {displayValue}
          {is12thMan && <span style={{ fontSize: '0.55rem', display: 'block', marginTop: '1px' }}>12th</span>}
        </div>
      </div>
    </div>
  );
}

// ══════════════════════════════════════════════
// MAIN: SquadPlannerTab
// ══════════════════════════════════════════════
export default function SquadPlannerTab({ players, myTeamIds, setMyTeam, optimResult, setOptimResult }) {
  const [playerSelectModalOpen, setPlayerSelectModalOpen] = useState(false);
  const [actionModalOpen, setActionModalOpen] = useState(false);
  
  const [targetPos, setTargetPos] = useState('ANY');
  const [playerToAction, setPlayerToAction] = useState(null);
  
  const [subSourcePlayer, setSubSourcePlayer] = useState(null);

  // Manual captain override
  const [manualCaptainId, setManualCaptainId] = useState(null);
  const [manualViceCaptainId, setManualViceCaptainId] = useState(null);

  // Manage benched players state explicitly to allow manual subs
  const [benchedIds, setBenchedIds] = useState([]);
  const [viewMode, setViewMode] = useState('xPts');

  // Transfer planner state
  const [stage, setStage] = useState('GROUP_MD1');
  const [freeTransfers, setFreeTransfers] = useState('unlimited');
  const [transfersUsed, setTransfersUsed] = useState(0);

  // Flag to skip auto-sort when we manually set benchedIds (e.g. on Accept)
  const skipAutoSortRef = useRef(false);

  const [advisorData, setAdvisorData] = useState(null);

  const teamPlayers = useMemo(() => {
    return myTeamIds.map(id => players.find(p => p.id === id)).filter(Boolean);
  }, [myTeamIds, players]);

  // Derive initial benchedIds when myTeamIds changes (e.g. transfer)
  const prevTeamIdsRef = useRef(myTeamIds);
  if (prevTeamIdsRef.current !== myTeamIds) {
    prevTeamIdsRef.current = myTeamIds;
    
    if (skipAutoSortRef.current) {
      // Skip auto-sort: benchedIds was already set manually (e.g. Accept)
      skipAutoSortRef.current = false;
    } else {
      // Auto-sort to find best XI based on points
      const { bench } = autoSortSquad(teamPlayers);
      setBenchedIds(bench.map(p => p.id));
    }
    setSubSourcePlayer(null); // Cancel any active sub
  }

  // Update free transfers default when stage changes
  useEffect(() => {
    const rule = TRANSFER_RULES[stage];
    if (rule) {
      setFreeTransfers(rule.default);
    }
  }, [stage]);

  // Determine which squad to show: optimizer result OR myTeam
  const isOptimMode = !!optimResult;
  
  const rawXi = isOptimMode ? [...optimResult.starting_xi] : teamPlayers.filter(p => !benchedIds.includes(p.id));
  const rawBench = isOptimMode ? [...optimResult.bench] : teamPlayers.filter(p => benchedIds.includes(p.id));
  
  // Sort bench properly (GK first, then pts descending)
  rawBench.sort((a, b) => {
    if (a.position === 'GK' && b.position !== 'GK') return -1;
    if (b.position === 'GK' && a.position !== 'GK') return 1;
    return (b.projected_pts || 0) - (a.projected_pts || 0);
  });

  // Sort XI properly (by position, then pts descending) to prevent jumping around
  const posOrder = { 'GK': 1, 'DEF': 2, 'MID': 3, 'FWD': 4, 'ANY': 5 };
  rawXi.sort((a, b) => {
    if (posOrder[a.position] !== posOrder[b.position]) {
      return (posOrder[a.position] || 9) - (posOrder[b.position] || 9);
    }
    return (b.projected_pts || 0) - (a.projected_pts || 0);
  });

  const { xi, bench } = padSquad(rawXi, rawBench, isOptimMode ? rawXi.concat(rawBench) : teamPlayers);

  // Determine Captain
  const sortedXiByPts = [...rawXi].sort((a, b) => (b.projected_pts || 0) - (a.projected_pts || 0));
  
  let captain;
  let viceCaptain;
  if (isOptimMode) {
    captain = optimResult.captain;
    viceCaptain = optimResult.vice_captain;
  } else {
    // Determine Captain
    if (manualCaptainId) {
      captain = rawXi.find(p => p.id === manualCaptainId) || sortedXiByPts[0];
    } else {
      captain = sortedXiByPts[0];
    }
    
    // Determine Vice Captain
    if (manualViceCaptainId) {
      viceCaptain = rawXi.find(p => p.id !== captain?.id && p.id === manualViceCaptainId) 
                 || sortedXiByPts.find(p => p.id !== captain?.id) 
                 || sortedXiByPts[1];
    } else {
      viceCaptain = sortedXiByPts.find(p => p.id !== captain?.id) || sortedXiByPts[1];
    }
  }
  
  // Calculate total xPts (XI points + captain bonus)
  const xiTotalPts = rawXi.reduce((sum, p) => sum + (p.projected_pts || 0), 0);
  const captainBonus = captain?.projected_pts || 0;
  const totalXPts = isOptimMode ? optimResult.total_projected_pts : xiTotalPts + captainBonus;

  // Transfer penalty calculation
  const transferPenalty = useMemo(() => {
    if (freeTransfers === 'unlimited') return 0;
    const extra = Math.max(0, transfersUsed - Number(freeTransfers));
    return extra * TRANSFER_PENALTY;
  }, [freeTransfers, transfersUsed]);

  const gks = xi.filter(p => p.position === 'GK');
  const defs = xi.filter(p => p.position === 'DEF');
  const mids = xi.filter(p => p.position === 'MID');
  const fwds = xi.filter(p => p.position === 'FWD');

  const benchLabels = bench.map((p, i) => i === 0 || p.position === 'GK' ? 'GKP' : `${i}. ${p.position || 'SUB'}`);

  // Check if a player is in XI (for captain button visibility)
  const isPlayerInXI = (playerId) => {
    return rawXi.some(p => p.id === playerId);
  };

  const handleSlotClick = (p) => {
    if (isOptimMode) return; // Disable editing while viewing optimizer result
    
    // If in Sub mode
    if (subSourcePlayer) {
      if (p.id === subSourcePlayer.id) {
        setSubSourcePlayer(null); // click same player to cancel
        return;
      }
      if (p.isPlaceholder) return;
      
      const newBenchedIds = [...benchedIds];
      const sourceIsBench = benchedIds.includes(subSourcePlayer.id);
      const targetIsBench = benchedIds.includes(p.id);
      
      if (sourceIsBench && !targetIsBench) {
        newBenchedIds[newBenchedIds.indexOf(subSourcePlayer.id)] = p.id;
      } else if (!sourceIsBench && targetIsBench) {
        newBenchedIds[newBenchedIds.indexOf(p.id)] = subSourcePlayer.id;
      } else {
        // Both in XI or both in Bench -> swap doesn't affect benchedIds logic, just reset
        setSubSourcePlayer(null);
        return;
      }

      // Check if the resulting formation is valid
      const newXi = teamPlayers.filter(x => !newBenchedIds.includes(x.id));
      if (isValidFormation(newXi)) {
        setBenchedIds(newBenchedIds);
        // If we swapped out the captain, reset manual captain
        if (manualCaptainId && !newXi.some(p => p.id === manualCaptainId)) {
          setManualCaptainId(null);
        }
      } else {
        alert("Invalid substitution! Must maintain a valid formation (e.g. at least 3 DEF, 2 MID, 1 FWD).");
      }
      setSubSourcePlayer(null);
      return;
    }

    // Normal click
    if (p.isPlaceholder) {
      setPlayerToAction(null);
      setTargetPos(p.position);
      setPlayerSelectModalOpen(true);
    } else {
      setPlayerToAction(p);
      setActionModalOpen(true);
    }
  };

  const handleTransferClick = (player) => {
    setTargetPos(player.position);
    setPlayerSelectModalOpen(true);
  };

  const handleSubClick = (player) => {
    setSubSourcePlayer(player);
  };

  const handleSetCaptain = (player) => {
    if (player.id === manualViceCaptainId) setManualViceCaptainId(null);
    setManualCaptainId(player.id);
  };

  const handleSetViceCaptain = (player) => {
    if (player.id === manualCaptainId) setManualCaptainId(null);
    setManualViceCaptainId(player.id);
  };

  const handleSelectPlayer = (newPlayer) => {
    let newIds = [...myTeamIds];
    
    // Validate country limit
    const maxPerCountry = TRANSFER_RULES[stage]?.maxCountry || 3;
    const currentCountryCount = newIds.reduce((count, id) => {
      if (playerToAction && id === playerToAction.id) return count; // Ignore player being replaced
      const p = players.find(x => x.id === id);
      if (p && p.team_abbr === newPlayer.team_abbr) return count + 1;
      return count;
    }, 0);

    if (currentCountryCount >= maxPerCountry) {
      alert(`Rule violation: You can only select up to ${maxPerCountry} players from ${newPlayer.team_abbr} in ${TRANSFER_RULES[stage]?.label}.`);
      return;
    }

    if (playerToAction) {
      // If transferring out the manual captain, clear captain override
      if (playerToAction.id === manualCaptainId) {
        setManualCaptainId(null);
      }
      if (playerToAction.id === manualViceCaptainId) {
        setManualViceCaptainId(null);
      }
      newIds = newIds.filter(id => id !== playerToAction.id);
    }
    if (!newIds.includes(newPlayer.id)) {
      newIds.push(newPlayer.id);
    }
    setMyTeam(newIds);
    setPlayerSelectModalOpen(false);
    setPlayerToAction(null);
  };

  // Fetch Gameweek Advisor recommendations
  useEffect(() => {
    if (isOptimMode || myTeamIds.length !== 15) {
      setAdvisorData(null);
      return;
    }
    const fetchAdvisor = async () => {
      try {
        const xi_ids = teamPlayers.filter(p => !benchedIds.includes(p.id)).map(p => p.id);
        const bench_ids = teamPlayers.filter(p => benchedIds.includes(p.id)).map(p => p.id);
        
        let cId = manualCaptainId;
        if (!cId) {
          const sortedXi = [...teamPlayers.filter(p => !benchedIds.includes(p.id))].sort((a,b) => (b.projected_pts||0) - (a.projected_pts||0));
          if (sortedXi.length > 0) cId = sortedXi[0].id;
        }

        const res = await fetch('/api/advisor', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            xi_ids,
            bench_ids,
            captain_id: cId
          })
        });
        if (res.ok) {
          const data = await res.json();
          setAdvisorData(data);
        }
      } catch (e) {
        console.error("Advisor error", e);
      }
    };
    fetchAdvisor();
  }, [myTeamIds, benchedIds, manualCaptainId, teamPlayers, isOptimMode]);

  const handleAccept = () => {
    // Set benchedIds from optimizer result BEFORE setting myTeam
    // This prevents auto-sort from overriding with stale data
    const newIds = optimResult.squad.map(p => p.id);
    const newBenchIds = optimResult.bench.map(p => p.id);
    
    skipAutoSortRef.current = true;
    setBenchedIds(newBenchIds);
    
    // Set captain from optimizer's pick
    if (optimResult.captain) {
      setManualCaptainId(optimResult.captain.id);
    }
    
    setMyTeam(newIds);
    setOptimResult(null);
  };

  const handleReset = () => {
    if (!window.confirm('Reset will clear your current squad. Continue?')) return;
    setMyTeam([]);
    setBenchedIds([]);
    setManualCaptainId(null);
    setSubSourcePlayer(null);
    setOptimResult(null);
    setTransfersUsed(0);
  };

  return (
    <div className="fade-in">
      {isOptimMode && (
        <div style={{ marginBottom: '16px', padding: '16px', background: 'linear-gradient(135deg, rgba(45, 212, 191, 0.15), rgba(15, 118, 110, 0.2))', border: '1px solid rgba(45, 212, 191, 0.3)', borderRadius: '12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
          <div>
            <h3 style={{ color: 'var(--clr-teal)', margin: '0 0 6px 0', display: 'flex', alignItems: 'center', gap: '8px' }}>
              Optimizer Suggestion
            </h3>
            <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--clr-text-muted)' }}>Review the suggested squad. Accept to overwrite your team.</p>
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button 
              onClick={handleAccept}
              style={{ background: 'linear-gradient(135deg, #10b981, #059669)', color: 'white', border: 'none', padding: '10px 20px', borderRadius: '8px', fontWeight: '700', fontSize: '0.9rem', cursor: 'pointer', boxShadow: '0 4px 10px rgba(16, 185, 129, 0.3)', transition: 'all 0.2s ease', display: 'flex', alignItems: 'center', gap: '6px' }}
              onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-2px)'; e.currentTarget.style.boxShadow = '0 6px 14px rgba(16, 185, 129, 0.4)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 10px rgba(16, 185, 129, 0.3)'; }}
            >
              Accept
            </button>
            <button 
              onClick={() => setOptimResult(null)} 
              style={{ background: 'rgba(239, 68, 68, 0.1)', color: '#fca5a5', border: '1px solid rgba(239, 68, 68, 0.3)', padding: '10px 20px', borderRadius: '8px', fontWeight: '600', fontSize: '0.9rem', cursor: 'pointer', transition: 'all 0.2s ease', display: 'flex', alignItems: 'center', gap: '6px' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)'; e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.5)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'; e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)'; }}
            >
              Discard
            </button>
          </div>
        </div>
      )}

      {subSourcePlayer && (
        <div style={{ marginBottom: '16px', padding: '12px 16px', background: 'rgba(45, 212, 191, 0.15)', border: '1px dashed var(--clr-teal)', borderRadius: '8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <span style={{ fontSize: '0.9rem', color: 'var(--clr-text)' }}>
              Select a player to substitute with <strong style={{color: 'var(--clr-teal)'}}>{subSourcePlayer.display_name}</strong>
            </span>
          </div>
          <button onClick={() => setSubSourcePlayer(null)} style={{ background: 'transparent', border: '1px solid var(--clr-border)', color: 'var(--clr-text-muted)', padding: '4px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: '0.75rem' }}>Cancel</button>
        </div>
      )}

      {/* Captain & Points Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 16px', marginBottom: '12px', background: 'var(--clr-bg-card)', borderRadius: 'var(--r-sm)', border: '1px solid var(--clr-border)', fontSize: '0.75rem' }}>
        <span style={{ color: 'var(--clr-text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>C: <strong style={{ color: 'var(--clr-gold)' }}>{captain?.display_name || '-'}</strong></span>
          {manualCaptainId && !isOptimMode && (
            <span style={{ fontSize: '0.6rem', color: 'var(--clr-teal)', background: 'rgba(45,212,191,0.15)', padding: '2px 6px', borderRadius: '4px' }}>MANUAL</span>
          )}
          <span style={{ color: 'var(--clr-text-muted)' }}>|</span>
          <span>V: <strong style={{ color: 'var(--clr-gold)' }}>{viceCaptain?.display_name || '-'}</strong></span>
          {manualViceCaptainId && !isOptimMode && (
            <span style={{ fontSize: '0.6rem', color: '#a78bfa', background: 'rgba(167, 139, 250, 0.15)', padding: '2px 6px', borderRadius: '4px' }}>MANUAL</span>
          )}
        </span>
        <span style={{ color: 'var(--clr-text-muted)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span>View:</span>
          <select 
            value={viewMode} 
            onChange={e => setViewMode(e.target.value)}
            style={{ background: 'var(--clr-bg-elevated)', color: 'var(--clr-text)', border: '1px solid var(--clr-border)', borderRadius: '4px', padding: '2px 4px', fontSize: '0.7rem', cursor: 'pointer' }}
          >
            <option value="xPts">xPts</option>
            <option value="Price">Price</option>
            <option value="% Selected">% Selected</option>
            <option value="Date">Date</option>
          </select>
          <span style={{ color: 'var(--clr-text-muted)' }}>|</span>
          Total xPts: <strong style={{ color: 'var(--clr-teal)' }}>{totalXPts?.toFixed(1) || '0.0'}</strong>
          {transferPenalty < 0 && (
            <span style={{ color: '#ef4444', fontWeight: 600, marginLeft: '4px' }}>
              Hit: {transferPenalty} pts
            </span>
          )}
        </span>
      </div>

      {/* Gameweek Advisor Banner */}
      {advisorData && (advisorData.captain_advice || (advisorData.sub_advice && advisorData.sub_advice.length > 0)) && !isOptimMode && (
        <div style={{ marginBottom: '12px', padding: '12px', background: 'linear-gradient(135deg, rgba(250, 204, 21, 0.1), rgba(250, 204, 21, 0.05))', borderRadius: '8px', border: '1px solid rgba(250, 204, 21, 0.3)', fontSize: '0.8rem', boxShadow: '0 4px 12px rgba(0,0,0,0.1)' }}>
          <strong style={{ color: 'var(--clr-gold)', display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', fontSize: '0.9rem' }}>
            Gameweek Advisor
          </strong>
          {advisorData.captain_advice && (
            <div style={{ marginBottom: '6px', background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '4px' }}>
               <span style={{ color: '#fca5a5' }}>Twist Captain:</span> <strong>{advisorData.captain_advice.from_name}</strong> ({advisorData.captain_advice.from_pts} pts) 
               {' ➔ '} <strong style={{color: 'var(--clr-teal)'}}>{advisorData.captain_advice.to_name}</strong> <span style={{ color: 'var(--clr-gold)' }}>(Gain EV: +{advisorData.captain_advice.ev_gain})</span>
            </div>
          )}
          {advisorData.sub_advice && advisorData.sub_advice.map((sub, i) => (
             <div key={i} style={{ marginBottom: '4px', background: 'rgba(0,0,0,0.2)', padding: '6px 10px', borderRadius: '4px' }}>
                <span style={{ color: '#fca5a5' }}>Sub Out:</span> <strong>{sub.out_name}</strong> ({sub.out_pts} pts) 
                {' ➔ '} <span style={{ color: 'var(--clr-teal)' }}>Sub In:</span> <strong>{sub.in_name}</strong> <span style={{ color: 'var(--clr-gold)' }}>(Gain EV: +{sub.ev_gain})</span>
             </div>
          ))}
        </div>
      )}

      {/* Transfer Planner Controls */}
      {!isOptimMode && myTeamIds.length > 0 && (
        <div style={{ marginBottom: '12px', padding: '10px 16px', background: 'rgba(255,255,255,0.03)', borderRadius: '8px', border: '1px solid var(--clr-border)', display: 'flex', gap: '16px', alignItems: 'center', flexWrap: 'wrap', fontSize: '0.75rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ color: 'var(--clr-text-muted)' }}>Stage:</span>
            <select 
              value={stage} 
              onChange={e => setStage(e.target.value)}
              style={{ background: 'var(--clr-bg-elevated)', color: 'var(--clr-text)', border: '1px solid var(--clr-border)', borderRadius: '4px', padding: '3px 6px', fontSize: '0.72rem', cursor: 'pointer' }}
            >
              {Object.entries(TRANSFER_RULES).map(([key, rule]) => (
                <option key={key} value={key}>{rule.label}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ color: 'var(--clr-text-muted)' }}>Free:</span>
            <select 
              value={freeTransfers} 
              onChange={e => setFreeTransfers(e.target.value === 'unlimited' ? 'unlimited' : Number(e.target.value))}
              style={{ background: 'var(--clr-bg-elevated)', color: 'var(--clr-text)', border: '1px solid var(--clr-border)', borderRadius: '4px', padding: '3px 6px', fontSize: '0.72rem', cursor: 'pointer' }}
            >
              {TRANSFER_RULES[stage].freeOptions.map(opt => (
                <option key={opt} value={opt}>{opt === 'unlimited' ? 'Unlimited' : opt}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ color: 'var(--clr-text-muted)' }}>Used:</span>
            <input 
              type="number" 
              value={transfersUsed} 
              onChange={e => setTransfersUsed(Number(e.target.value))}
              style={{ background: 'var(--clr-bg-elevated)', color: 'var(--clr-text)', border: '1px solid var(--clr-border)', borderRadius: '4px', padding: '3px 6px', width: '40px', fontSize: '0.72rem' }}
            />
          </div>
          {transferPenalty < 0 && (
            <div style={{ marginLeft: 'auto', color: '#ef4444', fontWeight: 700, fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              Hit: {transferPenalty} pts
            </div>
          )}
        </div>
      )}

      {/* Pitch */}
      <div style={{ position: 'relative' }}>
        <div className={`pitch ${subSourcePlayer ? 'sub-mode' : ''}`}>
          <div className="pitch-markings">
            <div className="pitch-box-top" />
            <div className="pitch-goal-top" />
            <div className="pitch-box-bottom" />
            <div className="pitch-goal-bottom" />
          </div>

          <div className="pitch-row" style={{ paddingTop: '16px' }}>
            {fwds.map((p, i) => <PitchPlayer key={p.id || `fwd-${i}`} player={p} isCaptain={captain?.id === p.id} isViceCaptain={viceCaptain?.id === p.id} isSubSource={subSourcePlayer?.id === p.id} viewMode={viewMode} onClick={() => handleSlotClick(p)} />)}
          </div>
          <div className="pitch-row">
            {mids.map((p, i) => <PitchPlayer key={p.id || `mid-${i}`} player={p} isCaptain={captain?.id === p.id} isViceCaptain={viceCaptain?.id === p.id} isSubSource={subSourcePlayer?.id === p.id} viewMode={viewMode} onClick={() => handleSlotClick(p)} />)}
          </div>
          <div className="pitch-row">
            {defs.map((p, i) => <PitchPlayer key={p.id || `def-${i}`} player={p} isCaptain={captain?.id === p.id} isViceCaptain={viceCaptain?.id === p.id} isSubSource={subSourcePlayer?.id === p.id} viewMode={viewMode} onClick={() => handleSlotClick(p)} />)}
          </div>
          <div className="pitch-row" style={{ paddingBottom: '16px' }}>
            {gks.map((p, i) => <PitchPlayer key={p.id || `gk-${i}`} player={p} isCaptain={captain?.id === p.id} isViceCaptain={viceCaptain?.id === p.id} isSubSource={subSourcePlayer?.id === p.id} viewMode={viewMode} onClick={() => handleSlotClick(p)} />)}
          </div>
        </div>

        {/* Reset Button - floating on the pitch */}
        {!isOptimMode && myTeamIds.length > 0 && (
          <button 
            onClick={handleReset}
            title="Reset squad to empty"
            style={{
              position: 'absolute',
              top: '12px',
              right: '12px',
              background: 'rgba(239, 68, 68, 0.15)',
              color: '#fca5a5',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              padding: '6px 14px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.72rem',
              transition: 'all 0.2s ease',
              zIndex: 10,
              backdropFilter: 'blur(4px)',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
            }}
            onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.3)'; e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.6)'; e.currentTarget.style.transform = 'translateY(-1px)'; }}
            onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)'; e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)'; e.currentTarget.style.transform = 'translateY(0)'; }}
          >
            Reset
          </button>
        )}
      </div>

      <div className="bench-section">
        <div className="bench-row">
          {bench.map((p, i) => (
            <div key={p.id || `bench-${i}`} className="bench-player-wrapper">
              <div className="bench-slot-label">{benchLabels[i]}</div>
              <PitchPlayer player={p} isSubSource={subSourcePlayer?.id === p.id} viewMode={viewMode} onClick={() => handleSlotClick(p)} />
            </div>
          ))}
        </div>
      </div>

      <ActionMenuModal 
        isOpen={actionModalOpen}
        player={playerToAction}
        onClose={() => setActionModalOpen(false)}
        onTransfer={handleTransferClick}
        onSub={handleSubClick}
        onSetCaptain={handleSetCaptain}
        onSetViceCaptain={handleSetViceCaptain}
        isInXI={playerToAction ? isPlayerInXI(playerToAction.id) : false}
      />

      <PlayerSelectModal 
        isOpen={playerSelectModalOpen} 
        onClose={() => setPlayerSelectModalOpen(false)} 
        players={players} 
        targetPos={targetPos} 
        onSelect={handleSelectPlayer} 
        currentTeamIds={myTeamIds} 
      />
    </div>
  );
}
