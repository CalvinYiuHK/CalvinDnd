import React, { useEffect, useState, useCallback } from "react";
import { api } from "./api.js";
import { useTheme, ThemePicker } from "./theme.jsx";
import Lobby from "./Lobby.jsx";
import Create from "./Create.jsx";
import Game from "./Game.jsx";

export default function App() {
  const [boot, setBoot] = useState(null);
  const [screen, setScreen] = useState({ name: "lobby" });
  const [err, setErr] = useState("");
  const [theme, setTheme] = useTheme();

  const refresh = useCallback(() => {
    api.bootstrap().then(setBoot).catch((e) => setErr(String(e.message || e)));
  }, []);
  useEffect(refresh, [refresh]);

  useEffect(() => {
    if (!err) return;
    const t = setTimeout(() => setErr(""), 6000);
    return () => clearTimeout(t);
  }, [err]);

  if (!boot) {
    return (
      <div className="app">
        <div className="lobby"><h1>Fateweaver</h1>
          <p className="strap">threading the loom</p>
          {err && <div className="errbar">{err}</div>}
        </div>
      </div>
    );
  }

  return (
    <div className="app">
      {screen.name === "lobby" && (
        <Lobby
          boot={boot}
          onPlay={(id) => setScreen({ name: "game", id })}
          onCreate={() => setScreen({ name: "create" })}
          onDeleted={refresh}
          onError={setErr}
        />
      )}
      {screen.name === "create" && (
        <Create
          boot={boot}
          onDone={(id) => { refresh(); setScreen({ name: "game", id }); }}
          onBack={() => setScreen({ name: "lobby" })}
          onError={setErr}
        />
      )}
      {screen.name === "game" && (
        <Game
          heroId={screen.id}
          onExit={() => { refresh(); setScreen({ name: "lobby" }); }}
          onError={setErr}
          themePicker={<ThemePicker theme={theme} setTheme={setTheme} />}
        />
      )}
      {screen.name !== "game" && (
        <div style={{ position: "fixed", top: 14, right: 18, zIndex: 40 }}>
          <ThemePicker theme={theme} setTheme={setTheme} />
        </div>
      )}
      {err && <div className="errbar">{err}</div>}
    </div>
  );
}
