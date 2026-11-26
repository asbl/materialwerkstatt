import { Component } from "react";

export default class FeatureBoundary extends Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <div className="deck-error" role="alert">
      <p>Das Zusatzwerkzeug konnte nicht geladen werden. Bitte zuerst speichern und die Folienansicht neu laden.</p>
      <button onClick={this.props.close}>Schließen</button>
    </div>;
  }
}
