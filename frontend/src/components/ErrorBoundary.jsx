import { Component } from "react";

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }
  componentDidCatch(error, info) {
    console.error("✗ ErrorBoundary capturó un error:", error, info);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: "24px", fontFamily: "monospace", color: "#f87171", background: "#0a0a0a", minHeight: "100vh" }}>
          <h1 style={{ fontSize: "18px", marginBottom: "12px" }}>⚠️ Algo se rompió en la interfaz</h1>
          <p style={{ fontSize: "13px", color: "#9ca3af", marginBottom: "16px" }}>
            El panel falló al renderizar. Los datos pueden estar incompletos. Recarga la página.
          </p>
          <pre style={{ fontSize: "11px", color: "#6b7280", whiteSpace: "pre-wrap" }}>
            {String(this.state.error)}
          </pre>
          <button
            onClick={() => window.location.reload()}
            style={{ marginTop: "16px", padding: "8px 16px", background: "#1f2937", color: "#e5e7eb", border: "1px solid #374151", borderRadius: "8px", cursor: "pointer", fontFamily: "monospace" }}
          >
            Recargar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
