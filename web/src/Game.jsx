import React, { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { api, gameSocket } from "./api.js";
import Feed from "./Feed.jsx";
import Sidebar from "./Sidebar.jsx";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"];

function ChoiceCards({ choices, busy, onPick }) {
  if (choices.length === 0) return null;
  return (
    <div className="choices">
      {choices.map((c, i) => {
        const chipCls = c.trait == null ? "norm" : c.mod > 0 ? "pos" : c.mod < 0 ? "neg" : "neu";
        return (
          <motion.button key={`${i}-${c.text}`} className="choice" disabled={busy}
            onClick={() => onPick(i, false)}
            initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05 }}>
            <span className="c-text"><span className="c-num">{i + 1}</span>{c.text}</span>
            <span className="c-meta">
              {c.trait == null ? (
                <span className="chip norm">no roll</span>
              ) : (
                <>
                  <span className={`chip ${chipCls}`}>
                    ⚅ {c.trait.toUpperCase()} {c.mod >= 0 ? `+${c.mod}` : c.mod}
                    {c.prof && <span className="c-star">★</span>}
                  </span>
                  <span className="c-need">need {c.need}+</span>
                  <span
                    className="c-power"
                    role="button"
                    onClick={(e) => { e.stopPropagation(); if (!busy) onPick(i, true); }}
                  >⚡+10</span>
                </>
              )}
            </span>
          </motion.button>
        );
      })}
    </div>
  );
}

function ConfirmModal({ prompt, onAnswer }) {
  return (
    <div className="overlay">
      <motion.div className="modal" initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
        <h3>A tug on the thread</h3>
        <p>{prompt}</p>
        <div className="btnrow">
          <button className="btn primary" onClick={() => onAnswer(true)}>↻ Spend it</button>
          <button className="btn" onClick={() => onAnswer(false)}>Let fate stand</button>
        </div>
      </motion.div>
    </div>
  );
}

function AllocateModal({ state, onDone, onError }) {
  const [alloc, setAlloc] = useState(Object.fromEntries(ABILITIES.map((a) => [a, 0])));
  const [saving, setSaving] = useState(false);
  const spent = Object.values(alloc).reduce((a, b) => a + b, 0);
  const left = state.attr_points - spent;

  const bump = (a, d) => setAlloc((x) => ({ ...x, [a]: Math.max(0, x[a] + d) }));

  const save = async () => {
    setSaving(true);
    try {
      await onDone(alloc);
    } catch (e) { onError(String(e.message || e)); setSaving(false); }
  };

  return (
    <div className="overlay">
      <motion.div className="modal" initial={{ scale: 0.92, opacity: 0 }} animate={{ scale: 1, opacity: 1 }}>
        <h3>Level up — shape yourself</h3>
        <p>Spend your attribute points. They are yours to keep forever.</p>
        <div className="pts-left">{left} point{left === 1 ? "" : "s"} left</div>
        {ABILITIES.map((a) => {
          const st = state.stats[a];
          const capped = st.base + alloc[a] >= state.stat_cap;
          return (
            <div className="alloc-row" key={a}>
              <span className="a-name">{a.toUpperCase()}</span>
              <span className="a-val">{st.base}{alloc[a] > 0 && <b> +{alloc[a]}</b>}</span>
              <span className="a-btns">
                <button disabled={alloc[a] === 0} onClick={() => bump(a, -1)}>−</button>
                <button disabled={left === 0 || capped} onClick={() => bump(a, 1)}>+</button>
              </span>
            </div>
          );
        })}
        <div className="btnrow">
          <button className="btn primary" disabled={spent === 0 || saving} onClick={save}>
            {left > 0 ? `Confirm (${left} unspent)` : "Confirm"}
          </button>
        </div>
      </motion.div>
    </div>
  );
}

export default function Game({ heroId, onExit, onError }) {
  const [state, setState] = useState(null);
  const [events, setEvents] = useState([]);
  const [choices, setChoices] = useState([]);
  const [busy, setBusy] = useState(true);
  const [confirmPrompt, setConfirmPrompt] = useState(null);
  const [allocating, setAllocating] = useState(false);
  const [text, setText] = useState("");
  const sockRef = useRef(null);
  const seenIds = useRef(new Set());
  const startedRef = useRef(false);

  const pushEvents = useCallback((evs) => {
    setEvents((old) => {
      const fresh = evs.filter((e) => e.id == null || !seenIds.current.has(e.id));
      fresh.forEach((e) => e.id != null && seenIds.current.add(e.id));
      return fresh.length ? [...old, ...fresh] : old;
    });
  }, []);

  useEffect(() => {
    let dead = false;
    api.log(heroId).then((r) => !dead && pushEvents(r.events)).catch(() => {});
    const sock = gameSocket(heroId, (msg) => {
      if (dead) return;
      if (msg.type === "event") pushEvents([msg]);
      else if (msg.type === "state") setState(msg.state);
      else if (msg.type === "choices") setChoices(msg.choices);
      else if (msg.type === "busy") setBusy(true);
      else if (msg.type === "idle") setBusy(false);
      else if (msg.type === "confirm") setConfirmPrompt(msg.prompt);
      else if (msg.type === "levelup") setAllocating(true);
      else if (msg.type === "error") { onError(msg.message); setBusy(false); }
      else if (msg.type === "hello" && !startedRef.current) {
        startedRef.current = true;
        sock.send({ type: "start" });
      }
    }, () => !dead && setBusy(false));
    sockRef.current = sock;
    return () => { dead = true; sock.close(); };
  }, [heroId, pushEvents, onError]);

  const pick = (i, power) => sockRef.current?.send({ type: "choice", index: i, power });
  const say = (e) => {
    e.preventDefault();
    const t = text.trim();
    if (!t || busy) return;
    setText("");
    sockRef.current?.send({ type: "say", text: t });
  };
  const useSkill = (i) => sockRef.current?.send({ type: "skill", index: i });
  const answer = (v) => { setConfirmPrompt(null); sockRef.current?.send({ type: "confirm", answer: v }); };

  const equip = async (id) => {
    try { setState(await api.equip(heroId, id)); }
    catch (e) { onError(String(e.message || e)); }
  };
  const forget = async (id, name) => {
    if (!window.confirm(`Forget ${name}? The slot frees up, the knowledge is gone.`)) return;
    try { setState(await api.forget(heroId, id)); }
    catch (e) { onError(String(e.message || e)); }
  };
  const toggleLang = async () => {
    try { setState(await api.setLang(heroId, state.lang === "canto" ? "en" : "canto")); }
    catch (e) { onError(String(e.message || e)); }
  };
  const allocate = async (alloc) => {
    setState(await api.allocate(heroId, alloc));
    setAllocating(false);
  };

  if (!state) {
    return (
      <div className="app">
        <div className="lobby"><h1>Fateweaver</h1><p className="strap">taking up the thread</p></div>
      </div>
    );
  }

  return (
    <>
      <div className="topbar">
        <span className="wordmark"><span className="die">⚅</span>Fateweaver</span>
        <span className="who">{state.name} · lvl {state.level}</span>
        <span className="spacer" />
        <span className="tokens">
          <span className="tok">⚡ <b>{state.power_rolls}</b></span>
          <span className="tok arc">↻ <b>{state.rerolls}</b></span>
          <span className="tok">◈ <b>{state.gold}</b></span>
        </span>
        <button className="linkish" onClick={onExit}>⟵ heroes</button>
      </div>

      <div className="game">
        <div className="stage">
          <Feed events={events} heroName={state.name} busy={busy} />
          <div className="actiondock">
            <AnimatePresence>{!busy && <ChoiceCards choices={choices} busy={busy} onPick={pick} />}</AnimatePresence>
            <form className="sayrow" onSubmit={say}>
              <input value={text} onChange={(e) => setText(e.target.value)}
                placeholder={busy ? "the Fateweaver is narrating…" : "or do anything — type your own action"}
                disabled={busy} />
              <button className="btn primary" disabled={busy || !text.trim()}>Act</button>
            </form>
          </div>
        </div>
        <Sidebar state={state} busy={busy} onEquip={equip}
          onUseSkill={useSkill} onForget={forget} onLang={toggleLang} />
      </div>

      {confirmPrompt && <ConfirmModal prompt={confirmPrompt} onAnswer={answer} />}
      {allocating && state.attr_points > 0 && (
        <AllocateModal state={state} onDone={allocate} onError={onError} />
      )}
    </>
  );
}
