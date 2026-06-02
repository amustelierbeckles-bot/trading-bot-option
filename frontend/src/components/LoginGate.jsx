import { useEffect, useState } from "react";

const API = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

export default function LoginGate({ children }) {
  const [authed, setAuthed]   = useState(null);   // null = comprobando
  const [password, setPassword] = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(`${API}/api/auth/me`)
      .then(r => r.json())
      .then(d => { if (alive) setAuthed(!!d.authenticated); })
      .catch(() => { if (alive) setAuthed(false); });
    return () => { alive = false; };
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const r = await fetch(`${API}/api/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (r.ok) {
        setPassword("");
        setAuthed(true);
      } else {
        setError(r.status === 401 ? "Contraseña incorrecta" : "Error de autenticación");
      }
    } catch {
      setError("No se pudo conectar con el servidor");
    } finally {
      setLoading(false);
    }
  };

  if (authed === null) {
    return (
      <div style={S.wrap}>
        <span style={{ color: "#888" }}>Verificando sesión…</span>
      </div>
    );
  }

  if (authed) return children;

  return (
    <div style={S.wrap}>
      <form onSubmit={submit} style={S.card}>
        <h2 style={S.title}>Trading Bot</h2>
        <input
          type="password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          placeholder="Contraseña"
          autoFocus
          style={S.input}
        />
        {error && <div style={S.error}>{error}</div>}
        <button type="submit" disabled={loading || !password} style={S.btn}>
          {loading ? "Entrando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}

const S = {
  wrap:  { minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", background: "#000" },
  card:  { display: "flex", flexDirection: "column", gap: 14, width: 300, padding: 28, background: "#0F0F0F", border: "1px solid #333", borderRadius: 12 },
  title: { color: "#fff", margin: 0, fontSize: 20, textAlign: "center" },
  input: { padding: "12px 14px", background: "#000", border: "1px solid #333", borderRadius: 8, color: "#fff", fontSize: 15, outline: "none" },
  error: { color: "#ff5555", fontSize: 13, textAlign: "center" },
  btn:   { padding: "12px 14px", background: "#16a34a", border: "none", borderRadius: 8, color: "#fff", fontSize: 15, fontWeight: 600, cursor: "pointer" },
};
