import React from "react";
import { api } from "./api.js";
import { Avatar } from "./icons.jsx";

export default function Lobby({ boot, onPlay, onCreate, onDeleted, onError }) {
  const scenEmoji = Object.fromEntries(boot.scenarios.map((s) => [s.key, s.emoji]));

  const del = async (e, hero) => {
    e.stopPropagation();
    if (!window.confirm(`Burn ${hero.name}'s thread forever? This deletes the save.`)) return;
    try { await api.deleteHero(hero.id); onDeleted(); }
    catch (err) { onError(String(err.message || err)); }
  };

  return (
    <div className="lobby">
      <h1>Fateweaver</h1>
      <p className="strap">any story, real dice</p>

      {boot.heroes.length > 0 && <div className="rowlabel">Resume a thread</div>}
      {boot.heroes.map((h) => (
        <button key={h.id} className="hero-card" onClick={() => onPlay(h.id)}>
          <Avatar name={h.name} size={44} />
          <span>
            <div className="h-name">{h.name} <span className="h-emoji">{scenEmoji[h.scenario] || "🎲"}</span></div>
            <div className="h-sub">
              level {h.level} {h.race !== "—" ? `${h.race} ` : ""}{h.class}
              {h.lang === "canto" ? " · 廣東話" : ""}
            </div>
          </span>
          <span className="h-hp">HP {h.hp}/{h.max_hp}</span>
          <span className="h-del" onClick={(e) => del(e, h)}>burn</span>
        </button>
      ))}

      <div className="rowlabel">Begin anew</div>
      <button className="big-cta" onClick={onCreate}>⚭ Weave a new hero</button>

      <p style={{ marginTop: 40, textAlign: "center", color: "var(--mute)", fontSize: 13, fontFamily: "var(--mono)" }}>
        GM: {boot.backend} · {boot.model} · {boot.effort}
      </p>
    </div>
  );
}
