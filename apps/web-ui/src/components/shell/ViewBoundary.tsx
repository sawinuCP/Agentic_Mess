import { Component, type ReactNode } from "react";

export default class ViewBoundary extends Component<
  { children: ReactNode; name: string }, { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <section className="pad" role="alert">
      <h2>{this.props.name} could not be displayed</h2>
      <p>Your workspace state has not been cleared. Retry this view.</p>
      <button className="button" onClick={() => this.setState({ failed: false })}>Retry view</button>
    </section>;
  }
}
