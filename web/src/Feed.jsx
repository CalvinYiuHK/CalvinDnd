import React, { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import { motion } from "framer-motion";
import { FoeIcon } from "./icons.jsx";

// "label: d20+5: [14] +5 = 19" → { label, math, nat, total }
function parseRoll(content) {
  const m = content.match(/^(.*?):\s*([-+]?\d*d\d.*)$/s);
  const label = m ? m[1] : "";
  const math = m ? m[2] : content;
  const natM = math.match(/\[(\d+)(?:,\s*\d+)*\]/);
  const totM = math.match(/=\s*(-?\d+)\s*$/);
  const d20 = /(^|\s|:)d20/.test(math) || /1d20/.test(math);
  return {
    label, math,
    nat: d20 && natM ? parseInt(natM[1], 10) : null,
    total: totM ? parseInt(totM[1], 10) : null,
  };
}

function boldHero(text, heroName) {
  if (!heroName) return text;
  const esc = heroName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`(?<![\\w*])${esc}(?![\\w*])`, "g"), `**${heroName}**`);
}

// The d20 tumbles through random faces before settling on the real total,
// then flashes gold on a natural 20 / shakes on a natural 1.
function RollCard({ content }) {
  const r = parseRoll(content);
  const [face, setFace] = useState(r.total == null ? null : "?");
  const [settled, setSettled] = useState(r.total == null);
  useEffect(() => {
    if (r.total == null) return;
    let ticks = 0;
    const iv = setInterval(() => {
      ticks += 1;
      if (ticks >= 8) {
        clearInterval(iv);
        setFace(r.total);
        setSettled(true);
      } else {
        setFace(1 + Math.floor(Math.random() * 20));
      }
    }, 70);
    return () => clearInterval(iv);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const cls = settled ? (r.nat === 20 ? "nat20" : r.nat === 1 ? "nat1" : "") : "tumbling";
  return (
    <motion.div className="ev ev-roll hot" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <span className="knot" />
      <div className="card">
        <motion.div className={`d20 ${cls}`}
          initial={{ rotate: -160, scale: 0.4 }} animate={{ rotate: 0, scale: 1 }}
          transition={{ type: "spring", stiffness: 220, damping: 14 }}>
          {face ?? "?"}
        </motion.div>
        <div>
          <div className="roll-label">{r.label || "Roll"}
            {settled && r.nat === 20 && " — NATURAL 20"}
            {settled && r.nat === 1 && " — NATURAL 1"}</div>
          <div className="roll-math">{settled ? r.math : "the die tumbles…"}</div>
        </div>
      </div>
    </motion.div>
  );
}

// Busy indicator with an elapsed-time counter so long GM turns never look hung.
function Thinking() {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const iv = setInterval(() => setSecs((s) => s + 1), 1000);
    return () => clearInterval(iv);
  }, []);
  return (
    <div className="thinking">
      <span className="orb" />
      {secs >= 20
        ? "the Fateweaver weighs a heavy thread… (still narrating)"
        : "the Fateweaver considers your thread…"}
      {secs >= 5 && <span className="think-secs"> {secs}s</span>}
    </div>
  );
}

function Event({ ev, heroName }) {
  const { kind, content } = ev;

  if (kind === "gm") {
    return (
      <div className="ev ev-gm"><span className="knot" />
        <Markdown>{boldHero(content, heroName)}</Markdown>
      </div>
    );
  }
  if (kind === "player") {
    if (content.startsWith("[")) return null;
    // Engine-built prompts carry the mechanics; show only the chosen action.
    const chose = content.match(/^I (?:choose|use my skill):?\s*"([^"]+)"/);
    return <div className="ev ev-player">{chose ? chose[1] : content}</div>;
  }
  if (kind === "roll") return <RollCard content={content} />;
  if (kind === "damage") {
    const out = content.startsWith("dealt");
    return (
      <motion.div className={`ev ev-damage ${out ? "outgoing" : ""}`}
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <span className="knot" />
        <div className="card"><div className="dmg-line">
          {out ? "⚔ " : "🩸 "}
          <b>{content}</b>
        </div></div>
      </motion.div>
    );
  }
  if (kind === "levelup") {
    return (
      <motion.div className="ev ev-levelup hot" initial={{ opacity: 0, scale: 0.9 }} animate={{ opacity: 1, scale: 1 }}>
        <span className="knot" />
        <div className="card">✦ {content} ✦</div>
      </motion.div>
    );
  }
  if (kind === "reward") {
    return (
      <div className="ev ev-reward"><span className="knot" />
        <div className="card">🎁 {content}</div>
      </div>
    );
  }
  if (kind === "enemy") {
    const foe = (content.match(/^(.+?) appears/) || [])[1];
    return (
      <div className="ev ev-enemy hot"><span className="knot" />
        <div className="card">
          {foe && <FoeIcon name={foe} size={22} className="ev-foe-icon" />}
          {content}
        </div>
      </div>
    );
  }
  if (kind === "equip") {
    const rarity = (content.match(/^(normal|uncommon|rare|epic|legendary)/i) || [])[1];
    return (
      <div className="ev"><span className="knot" />
        <div className={`card ${rarity ? `rarity-${rarity.toLowerCase()}` : ""}`}>💎 {content}</div>
      </div>
    );
  }
  if (kind === "skill") {
    return (
      <div className="ev"><span className="knot" />
        <div className="card">📖 {content}</div>
      </div>
    );
  }
  if (kind === "sheet" || kind === "inventory") {
    return <div className="ev ev-ledger"><span className="k">{kind === "sheet" ? "📜" : "🎒"}</span> {content}</div>;
  }
  return null;
}

export default function Feed({ events, heroName, busy }) {
  const endRef = useRef(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length, busy]);

  return (
    <div className="feed">
      <div className="feed-inner">
        {events.map((ev) => <Event key={ev.id ?? `${ev.kind}-${ev.content}`} ev={ev} heroName={heroName} />)}
        {busy && <Thinking />}
        <div ref={endRef} />
      </div>
    </div>
  );
}
