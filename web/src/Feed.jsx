import React, { useEffect, useRef } from "react";
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
  if (kind === "roll") {
    const r = parseRoll(content);
    const cls = r.nat === 20 ? "nat20" : r.nat === 1 ? "nat1" : "";
    return (
      <motion.div className="ev ev-roll hot" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
        <span className="knot" />
        <div className="card">
          <motion.div className={`d20 ${cls}`}
            initial={{ rotate: -160, scale: 0.4 }} animate={{ rotate: 0, scale: 1 }}
            transition={{ type: "spring", stiffness: 220, damping: 14 }}>
            {r.total ?? "?"}
          </motion.div>
          <div>
            <div className="roll-label">{r.label || "Roll"}
              {r.nat === 20 && " — NATURAL 20"}{r.nat === 1 && " — NATURAL 1"}</div>
            <div className="roll-math">{r.math}</div>
          </div>
        </div>
      </motion.div>
    );
  }
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
        {busy && (
          <div className="thinking"><span className="orb" /> the Fateweaver considers your thread…</div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
