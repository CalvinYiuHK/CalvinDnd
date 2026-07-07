import React, { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { api } from "./api.js";

const LANGS = [["en", "English"], ["canto", "廣東話 (繁體中文)"]];

// GM settings — storyteller backend, model, effort, and language. Writes the
// same settings the TUI's /backend, /model and /effort commands use.
// `hero` ({lang, setLang}) is passed when opened in-game: the language group
// then switches the current hero instead of the default for new heroes.
export default function Settings({ onClose, onError, onSaved, hero }) {
  const [s, setS] = useState(null);

  useEffect(() => {
    api.settings().then(setS).catch((e) => { onError(String(e.message || e)); onClose(); });
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async (patch) => {
    try { setS(await api.saveSettings(patch)); onSaved(); }
    catch (e) { onError(String(e.message || e)); }
  };

  if (!s) return null;
  const cur = s.backends.find((b) => b.name === s.backend);

  return (
    <div className="overlay" onClick={onClose}>
      <motion.div className="modal settings" onClick={(e) => e.stopPropagation()}
        initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
        <h3>Game Master settings</h3>

        <div className="set-group">
          <label>Storyteller</label>
          <div className="pillrow">
            {s.backends.map((b) => (
              <button key={b.name} disabled={!b.installed}
                className={`pill ${b.name === s.backend ? "sel" : ""}`}
                title={b.installed ? (b.mode === "session" ? "persistent session" : "stateless — replays the transcript") : `not installed — ${b.install}`}
                onClick={() => save({ backend: b.name })}>
                {b.name}
              </button>
            ))}
          </div>
          {s.backends.some((b) => !b.installed) && (
            <div className="set-hint">
              {s.backends.filter((b) => !b.installed)
                .map((b) => `${b.name}: not installed (${b.install})`).join(" · ")}
            </div>
          )}
        </div>

        <div className="set-group">
          <label>Model</label>
          <div className="pillrow">
            {cur.models.map((m) => (
              <button key={m} className={`pill ${m === cur.model ? "sel" : ""}`}
                onClick={() => save({ model: m })}>{m}</button>
            ))}
          </div>
        </div>

        {s.backend === "claude" && (
          <div className="set-group">
            <label>Effort</label>
            <div className="pillrow">
              {s.effort_levels.map((e) => (
                <button key={e} className={`pill ${e === s.effort ? "sel" : ""}`}
                  onClick={() => save({ effort: e })}>{e}</button>
              ))}
            </div>
            <div className="set-hint">lower = snappier turns, higher = richer storytelling</div>
          </div>
        )}

        <div className="set-group">
          <label>{hero ? "Story language (this hero)" : "Language (new heroes)"}</label>
          <div className="pillrow">
            {LANGS.map(([key, label]) => {
              const active = hero ? hero.lang === key : s.default_lang === key;
              return (
                <button key={key} className={`pill ${active ? "sel" : ""}`}
                  onClick={() => (hero ? hero.setLang(key) : save({ default_lang: key }))}>
                  {label}
                </button>
              );
            })}
          </div>
        </div>

        <p className="set-note">
          Applies to every hero from their next turn. The terminal commands
          /backend, /model and /effort change the same settings.
        </p>
        <div className="btnrow">
          <button className="btn primary" onClick={onClose}>Done</button>
        </div>
      </motion.div>
    </div>
  );
}
