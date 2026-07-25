import { useState } from "react";
import "./App.css";

const MY_PLAYER_ID = "18ed6f43-0f27-4a76-9e2d-9c47932c1367";

interface MapResult {
  map: string;
  win_probability: number;
}

interface PredictResponse {
  my_team: string;
  maps: MapResult[];
}

const MAP_DISPLAY: Record<string, string> = {
  de_mirage: "Mirage",
  de_dust2: "Dust2",
  de_ancient: "Ancient",
  de_inferno: "Inferno",
  de_anubis: "Anubis",
  de_nuke: "Nuke",
  de_cache: "Cache",
  de_overpass: "Overpass",
};

function App() {
  const [matchId, setMatchId] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PredictResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [crossedOut, setCrossedOut] = useState<Set<string>>(new Set());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setResult(null);
    setError(null);
    setCrossedOut(new Set());

    try {
      const res = await fetch("http://localhost:8000/predict", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ match_id: matchId.trim(), my_player_id: MY_PLAYER_ID }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail ?? "Request failed");
      }

      setResult(await res.json());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  const toggleCrossed = (map: string) => {
    setCrossedOut((prev) => {
      const next = new Set(prev);
      if (next.has(map)) next.delete(map);
      else next.add(map);
      return next;
    });
  };

  const activeMaps = result?.maps.filter((m) => !crossedOut.has(m.map)) ?? [];
  const best = activeMaps[0];
  const worst = activeMaps[activeMaps.length - 1];

  return (
    <div className="container">
      <h1>Map Selector</h1>
      <p className="subtitle">Paste your FACEIT match ID to get map win probabilities</p>

      <form onSubmit={handleSubmit} className="form">
        <input
          type="text"
          placeholder="Match ID (e.g. 1-abc123...)"
          value={matchId}
          onChange={(e) => setMatchId(e.target.value)}
          disabled={loading}
        />
        <button type="submit" disabled={loading || !matchId.trim()}>
          {loading ? "Analysing..." : "Predict"}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="results">
          <div className="recommendations">
            <div className="rec pick">
              <span className="rec-label">PICK</span>
              <span className="rec-map">{best ? (MAP_DISPLAY[best.map] ?? best.map) : "—"}</span>
              <span className="rec-prob">{best ? `${(best.win_probability * 100).toFixed(1)}%` : ""}</span>
            </div>
            <div className="rec ban">
              <span className="rec-label">BAN FIRST</span>
              <span className="rec-map">{worst ? (MAP_DISPLAY[worst.map] ?? worst.map) : "—"}</span>
              <span className="rec-prob">{worst ? `${(worst.win_probability * 100).toFixed(1)}%` : ""}</span>
            </div>
          </div>

          <div className="map-list">
            {result.maps.map((m) => {
              const pct = m.win_probability * 100;
              const banned = crossedOut.has(m.map);
              return (
                <div key={m.map} className={`map-row${banned ? " crossed" : ""}`}>
                  <span className="map-name">{MAP_DISPLAY[m.map] ?? m.map}</span>
                  <div className="bar-track">
                    <div className="bar-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="map-pct">{pct.toFixed(1)}%</span>
                  <button
                    className={`cross-btn${banned ? " undo" : ""}`}
                    onClick={() => toggleCrossed(m.map)}
                    title={banned ? "Restore map" : "Ban map"}
                  >
                    {banned ? "↩" : "✕"}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
