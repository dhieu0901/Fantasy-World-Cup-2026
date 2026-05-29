const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API ${res.status}: ${res.statusText}`);
  return res.json();
}

export async function getPlayers({ position, search, sortBy = 'total_points', sortDesc = true, limit } = {}) {
  const params = new URLSearchParams();
  if (position) params.set('position', position);
  if (search) params.set('search', search);
  if (sortBy) params.set('sort_by', sortBy);
  params.set('sort_desc', sortDesc);
  if (limit) params.set('limit', limit);
  return fetchJSON(`${API_BASE}/players?${params}`);
}

export async function getPlayer(id) {
  return fetchJSON(`${API_BASE}/players/${id}`);
}

export async function getSquads() {
  return fetchJSON(`${API_BASE}/squads`);
}

export async function getRounds() {
  return fetchJSON(`${API_BASE}/rounds`);
}

export async function getFixtures() {
  return fetchJSON(`${API_BASE}/fixtures`);
}

export async function getStats() {
  return fetchJSON(`${API_BASE}/stats`);
}

export async function getRules() {
  return fetchJSON(`${API_BASE}/rules`);
}

export async function optimize({ stage = 'GROUP_MD1', preset = 'default', lockedIn = [], lockedOut = [], useLp = true } = {}) {
  const res = await fetch(`${API_BASE}/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      stage, preset,
      locked_in: lockedIn,
      locked_out: lockedOut,
      use_lp: useLp,
    }),
  });
  if (!res.ok) throw new Error(`Optimize failed: ${res.statusText}`);
  return res.json();
}

export async function saveTeam(deviceId, playerIds) {
  const res = await fetch(`${API_BASE}/team`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId, player_ids: playerIds })
  });
  if (!res.ok) throw new Error('Failed to save team');
  return res.json();
}

export async function getTeam(deviceId) {
  const res = await fetch(`${API_BASE}/team?device_id=${deviceId}`);
  if (!res.ok) return null;
  return res.json();
}

export async function getRecommendSubs(deviceId) {
  const res = await fetch(`${API_BASE}/recommend-subs?device_id=${deviceId}`);
  if (!res.ok) return { recommendations: [] };
  return res.json();
}

export async function triggerSync() {
  const res = await fetch(`${API_BASE}/sync`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to sync');
  return res.json();
}

export async function triggerLiveSync() {
  const res = await fetch(`${API_BASE}/live-sync`, { method: 'POST' });
  if (!res.ok) throw new Error('Failed to live sync');
  return res.json();
}
