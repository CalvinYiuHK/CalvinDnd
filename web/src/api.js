async function req(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return res.json();
}

export const api = {
  bootstrap: () => req("GET", "/api/bootstrap"),
  rollStats: () => req("POST", "/api/roll-stats"),
  createHero: (body) => req("POST", "/api/heroes", body),
  deleteHero: (id) => req("DELETE", `/api/heroes/${id}`),
  state: (id) => req("GET", `/api/heroes/${id}/state`),
  log: (id) => req("GET", `/api/heroes/${id}/log`),
  equip: (id, equipment_id) => req("POST", `/api/heroes/${id}/equip`, { equipment_id }),
  forget: (id, skill_id) => req("POST", `/api/heroes/${id}/forget`, { skill_id }),
  allocate: (id, allocation) => req("POST", `/api/heroes/${id}/allocate`, { allocation }),
  setLang: (id, lang) => req("POST", `/api/heroes/${id}/lang`, { lang }),
};

export function gameSocket(heroId, onMessage, onClose) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/${heroId}`);
  ws.onmessage = (e) => onMessage(JSON.parse(e.data));
  ws.onclose = () => onClose && onClose();
  return {
    raw: ws,
    send: (msg) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify(msg)),
    close: () => ws.close(),
  };
}
