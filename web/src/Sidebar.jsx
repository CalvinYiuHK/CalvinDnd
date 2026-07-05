import React, { useEffect, useMemo, useState } from "react";
import { AnsiUp } from "ansi_up";
import { Avatar, FoeIcon } from "./icons.jsx";

const ABILITIES = ["str", "dex", "con", "int", "wis", "cha"];
const ansi = new AnsiUp();

function HpBar({ hp, max, cls = "hp" }) {
  const pct = Math.max(0, Math.min(100, Math.round((100 * hp) / Math.max(1, max))));
  return (
    <div className={`bar ${cls} ${pct <= 30 ? "low" : ""}`}>
      <div style={{ width: `${pct}%` }} />
    </div>
  );
}

function HeroTab({ state, onLang }) {
  const s = state;
  return (
    <>
      <div className="sb-head">
        <Avatar name={s.name} size={56} />
        <div>
          <div className="sb-name">{s.name}</div>
          <div className="sb-sub">
            level {s.level} {s.race !== "—" ? `${s.race} ` : ""}{s.class}
          </div>
        </div>
      </div>
      <div className="barlabel"><span>HP</span><b>{s.hp}/{s.max_hp}</b></div>
      <HpBar hp={s.hp} max={s.max_hp} />
      <div className="barlabel"><span>XP → level {s.level + 1}</span><b>{s.xp}/{s.xp_next}</b></div>
      <HpBar hp={s.xp} max={s.xp_next} cls="xp" />

      <div className="statgrid">
        {ABILITIES.map((a) => {
          const st = s.stats[a];
          return (
            <div className="statbox" key={a}>
              <span className="s-a">{a.toUpperCase()}</span>
              <span className="s-v">{st.score}</span>
              {st.gear !== 0 && <span className="s-g">{st.gear > 0 ? `+${st.gear}` : st.gear} gear</span>}
              <span className="s-m">{st.mod >= 0 ? `+${st.mod}` : st.mod}</span>
            </div>
          );
        })}
      </div>

      <div className="kv"><span>Gold</span><b>{s.gold}</b></div>
      <div className="kv"><span>Armor</span><b>{s.armor}</b></div>
      <div className="kv"><span>Proficiency</span><b>+{s.proficiency}</b></div>
      <div className="kv"><span>⚡ power / ↻ rerolls</span><b>{s.power_rolls} / {s.rerolls}</b></div>
      <div className="kv"><span>Language</span>
        <button className="linkish" onClick={onLang}>
          {s.lang === "canto" ? "廣東話 → English" : "English → 廣東話"}
        </button>
      </div>

      <div className="rowlabel" style={{ marginTop: 22 }}>Pack</div>
      <ul className="invlist">
        {s.inventory.length === 0 && <li>(empty)</li>}
        {s.inventory.map((i) => <li key={i.item}><b>{i.item}</b> ×{i.qty}</li>)}
      </ul>
    </>
  );
}

function GearTab({ state, onEquip }) {
  if (state.equipment.length === 0) return <div className="empty">No equipment yet — the story will provide.</div>;
  return (
    <>
      {state.equipment.map((e) => (
        <div className={`gear-item ${e.equipped ? "on" : ""}`} key={e.id}>
          <span className={`g-name rarity-${e.rarity}`}>{e.name}</span>
          <span className="g-slot">{e.rarity} {e.slot}</span>
          {Object.keys(e.bonuses).length > 0 && (
            <div className="g-bon">
              {Object.entries(e.bonuses).map(([k, v]) => `${k.toUpperCase()}${v > 0 ? "+" : ""}${v}`).join("  ")}
            </div>
          )}
          {e.abilities.map((a, i) => <div className="g-ab" key={i}>{a}</div>)}
          {e.equipped
            ? <div className="g-on" style={{ marginTop: 8 }}>◈ equipped</div>
            : <button className="g-btn" onClick={() => onEquip(e.id)}>Equip</button>}
        </div>
      ))}
    </>
  );
}

function SkillsTab({ state, busy, onUse, onForget }) {
  return (
    <>
      <div className="slotcount">slots {state.skills.length}/{state.max_skill_slots}</div>
      {state.skills.length === 0 && <div className="empty">No skills learned yet — trainers, tomes, and milestones await.</div>}
      {state.skills.map((sk, i) => (
        <div className="skill-item" key={sk.id}>
          <span className="sk-name">{sk.name}</span>
          <span className="sk-dice">
            {sk.dice}{sk.mod ? (sk.mod > 0 ? `+${sk.mod}` : sk.mod) : ""} ({sk.attrs.map((a) => a.toUpperCase()).join("+")})
          </span>
          {sk.descr && <div className="sk-descr">{sk.descr}</div>}
          <div className="sk-row">
            <button className="sk-use" disabled={busy} onClick={() => onUse(i)}>Use as action</button>
            <button className="sk-forget" onClick={() => onForget(sk.id, sk.name)}>forget</button>
          </div>
        </div>
      ))}
    </>
  );
}

function FoesTab({ state }) {
  const foes = state.enemies;
  if (foes.length === 0) return <div className="empty">No foes in sight. Enjoy it while it lasts.</div>;
  return (
    <>
      {foes.map((f) => (
        <div className={`foe ${f.defeated ? "dead" : ""}`} key={f.id}>
          <span className="f-head">
            <FoeIcon name={f.name} icon={f.icon} size={22} className="f-icon" />
            <span className="f-name">{f.name}</span>
            <span className="f-lvl">{f.level != null ? `lvl ${f.level}` : "lvl ???"}{f.defeated ? " · ✝ defeated" : ""}</span>
          </span>
          {f.art ? (
            <div className="f-art" dangerouslySetInnerHTML={{ __html: ansi.ansi_to_html(f.art) }} />
          ) : (
            <div className="f-art f-portrait"><FoeIcon name={f.name} icon={f.icon} size={84} /></div>
          )}
          <div className="f-hp">
            <span>HP</span>
            <span>{f.hp != null ? `${f.hp}/${f.max_hp}` : `${f.hp_pct}%`}</span>
          </div>
          <HpBar hp={f.hp_pct} max={100} />
          {f.tier === "full" && (
            <>
              <div className="f-attrs">
                {ABILITIES.map((a) => `${a.toUpperCase()} ${f.attrs[a]}`).join("  ")} · armor {f.armor}
              </div>
              {f.gear?.length > 0 && <div className="f-line"><b>Gear:</b> {f.gear.join("; ")}</div>}
              {f.skills?.length > 0 && <div className="f-line"><b>Skills:</b> {f.skills.join("; ")}</div>}
            </>
          )}
          {f.tier === "partial" && (
            <>
              <div className="f-attrs">
                {Object.entries(f.attrs).map(([a, v]) => `${a.toUpperCase()} ${v}`).join("  ")} — the rest is unclear
              </div>
              {f.gear?.length > 0 && <div className="f-line"><b>Carries:</b> {f.gear.join(", ")}</div>}
            </>
          )}
          {f.tier === "vague" && (
            <div className="f-vague">You sense only overwhelming {f.hint?.toUpperCase()} — study it or grow stronger.</div>
          )}
          {f.tier === "silhouette" && (
            <div className="f-vague">A shape far beyond you. Run, talk, or pray.</div>
          )}
        </div>
      ))}
    </>
  );
}

export default function Sidebar({ state, busy, onEquip, onUseSkill, onForget, onLang }) {
  const [tab, setTab] = useState("hero");
  const liveFoes = useMemo(
    () => state.enemies.filter((e) => !e.defeated).length,
    [state.enemies]);

  useEffect(() => {
    if (liveFoes > 0) setTab("foes");
  }, [liveFoes]);

  return (
    <div className="sidebar">
      <div className="tabs">
        {["hero", "gear", "skills", "foes"].map((t) => (
          <button key={t} className={`tab ${tab === t ? "sel" : ""} ${t === "foes" && liveFoes ? "alert" : ""}`}
            onClick={() => setTab(t)}>
            {t === "foes" && liveFoes ? `⚔ foes (${liveFoes})` : t}
          </button>
        ))}
      </div>
      <div className="tabbody">
        {tab === "hero" && <HeroTab state={state} onLang={onLang} />}
        {tab === "gear" && <GearTab state={state} onEquip={onEquip} />}
        {tab === "skills" && <SkillsTab state={state} busy={busy} onUse={onUseSkill} onForget={onForget} />}
        {tab === "foes" && <FoesTab state={state} />}
      </div>
    </div>
  );
}
