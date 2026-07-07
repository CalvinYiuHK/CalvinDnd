import React, { useState } from "react";
import { motion } from "framer-motion";
import { api } from "./api.js";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"];

export default function Create({ boot, onDone, onBack, onError }) {
  const [scen, setScen] = useState(null);
  const [name, setName] = useState("");
  const [race, setRace] = useState("");
  const [role, setRole] = useState("");
  const [lang, setLang] = useState(boot.default_lang || "en");
  const [premise, setPremise] = useState("");
  const [stats, setStats] = useState(null);
  const [rolling, setRolling] = useState(false);
  const [creating, setCreating] = useState(false);
  const [rollKey, setRollKey] = useState(0);

  const rollStats = async () => {
    setRolling(true);
    try {
      const r = await api.rollStats();
      setStats(r);
      setRollKey((k) => k + 1);
    } catch (e) { onError(String(e.message || e)); }
    setRolling(false);
  };

  const pickScen = (s) => {
    setScen(s);
    setRace(s.races ? "" : "—");
    setRole(s.roles.length === 1 ? s.roles[0] : "");
    if (!stats) rollStats();
  };

  const ready = scen && name.trim() && role && (!scen.races || race) &&
    (scen.key !== "custom" || premise.trim()) && stats;

  const create = async () => {
    setCreating(true);
    try {
      const { id } = await api.createHero({
        name: name.trim(), scenario: scen.key, race: race || "—",
        char_class: role, lang, premise: premise.trim(), scores: stats.scores,
      });
      onDone(id);
    } catch (e) { onError(String(e.message || e)); setCreating(false); }
  };

  return (
    <div className="create">
      <h2>Weave a hero</h2>
      <div className="step">every thread begins with a story</div>

      <div className="field"><label>Tonight's story</label>
        <div className="scen-grid">
          {boot.scenarios.map((s) => (
            <button key={s.key} className={`scen-card ${scen?.key === s.key ? "sel" : ""}`}
              onClick={() => pickScen(s)}>
              <div className="s-emoji">{s.emoji}</div>
              <div className="s-title">{s.title}</div>
              <div className="s-tag">{s.tagline}</div>
            </button>
          ))}
        </div>
      </div>

      {scen?.key === "custom" && (
        <div className="field"><label>Your premise</label>
          <textarea rows={3} value={premise} onChange={(e) => setPremise(e.target.value)}
            placeholder="Setting, tone, who you are — the GM builds the world around it." />
        </div>
      )}

      {scen && (
        <>
          <div className="field"><label>Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)}
              placeholder="What is your hero called?" maxLength={40} />
          </div>

          {scen.races && (
            <div className="field"><label>Race</label>
              <div className="pillrow">
                {scen.races.map((r) => (
                  <button key={r} className={`pill ${race === r ? "sel" : ""}`}
                    onClick={() => setRace(r)}>{r}</button>
                ))}
              </div>
            </div>
          )}

          <div className="field"><label>Background</label>
            <div className="pillrow">
              {scen.roles.map((r) => (
                <button key={r} className={`pill ${role === r ? "sel" : ""}`}
                  onClick={() => setRole(r)}>{r}</button>
              ))}
            </div>
          </div>

          <div className="field"><label>Story language</label>
            <div className="pillrow">
              <button className={`pill ${lang === "en" ? "sel" : ""}`} onClick={() => setLang("en")}>English</button>
              <button className={`pill ${lang === "canto" ? "sel" : ""}`} onClick={() => setLang("canto")}>廣東話 (繁體中文)</button>
            </div>
          </div>

          <div className="field"><label>Ability scores — 4d6, drop the lowest</label>
            <div className="stats-roller">
              {stats ? ABILITIES.map((a, i) => (
                <motion.div className="stat-line" key={`${rollKey}-${a}`}
                  initial={{ opacity: 0, x: -14 }} animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: i * 0.06 }}>
                  <span className="a-name">{a.toUpperCase()}</span>
                  <span className="a-score">{stats.scores[a]}</span>
                  <span className="a-detail">{stats.details[a]}</span>
                </motion.div>
              )) : <div className="empty">the dice wait…</div>}
              <div className="btnrow">
                <button className="btn" onClick={rollStats} disabled={rolling}>
                  {stats ? "↻ Reroll the lot" : "Roll the dice"}
                </button>
              </div>
            </div>
          </div>
        </>
      )}

      <div className="btnrow">
        <button className="btn" onClick={onBack}>Back</button>
        <button className="btn primary" disabled={!ready || creating} onClick={create}>
          {creating ? "Weaving…" : "Begin the story"}
        </button>
      </div>
    </div>
  );
}
