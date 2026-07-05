// Free art: game-icons.net (via react-icons/gi, CC BY 3.0) for foes,
// DiceBear "adventurer" for player avatars — both bundled, no CDN.
import React, { useMemo } from "react";
import {
  GiRat, GiGoblinHead, GiSkeleton, GiWolfHead, GiSpiderFace, GiSnake,
  GiDragonHead, GiWitchFlight, GiGhost, GiBlackKnightHelm, GiBandit,
  GiDevilMask, GiSlime, GiBearHead, GiOrcHead, GiTroll, GiMinotaur,
  GiVampireDracula, GiSpectre, GiOgre, GiMonsterGrasp,
} from "react-icons/gi";
import { createAvatar } from "@dicebear/core";
import { adventurer } from "@dicebear/collection";

// Keyword → icon, mirroring art.py's preset matching (Chinese included).
const FOE_ICONS = [
  [["rat", "mouse", "鼠"], GiRat],
  [["goblin", "哥布林"], GiGoblinHead],
  [["skeleton", "bone", "骷髏", "骨"], GiSkeleton],
  [["wolf", "dog", "hound", "狼", "犬"], GiWolfHead],
  [["spider", "蜘蛛"], GiSpiderFace],
  [["snake", "serpent", "蛇"], GiSnake],
  [["dragon", "wyrm", "drake", "龍"], GiDragonHead],
  [["witch", "hag", "sorcer", "巫"], GiWitchFlight],
  [["ghost", "spirit", "wraith", "鬼", "靈"], GiGhost],
  [["phantom", "spectre", "specter"], GiSpectre],
  [["knight", "guard", "soldier", "騎士", "衛"], GiBlackKnightHelm],
  [["bandit", "thief", "thug", "rogue", "盜", "賊"], GiBandit],
  [["demon", "devil", "fiend", "魔"], GiDevilMask],
  [["slime", "ooze", "史萊姆"], GiSlime],
  [["bear", "熊"], GiBearHead],
  [["orc", "獸人"], GiOrcHead],
  [["troll", "巨魔"], GiTroll],
  [["minotaur", "牛頭"], GiMinotaur],
  [["vampire", "吸血"], GiVampireDracula],
  [["ogre", "食人魔"], GiOgre],
];

export function FoeIcon({ name, size = 20, className = "" }) {
  const low = (name || "").toLowerCase();
  const entry = FOE_ICONS.find(([words]) => words.some((w) => low.includes(w)));
  const Icon = entry ? entry[1] : GiMonsterGrasp;
  return <Icon size={size} className={className} aria-hidden="true" />;
}

export function Avatar({ name, size = 40, className = "" }) {
  const uri = useMemo(
    () => createAvatar(adventurer, { seed: name || "hero", size: size * 2 }).toDataUri(),
    [name, size]);
  return (
    <img src={uri} width={size} height={size} alt=""
      className={`avatar ${className}`} draggable={false} />
  );
}
