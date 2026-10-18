import { Component, type ErrorInfo, type ReactNode } from 'react'

/** Catches a render crash in one screen so the rail and the other screens keep working. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('screen crashed', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="card">
        <div className="error"><strong>This screen hit an unexpected problem.</strong><br /><small>{this.state.error.message}</small></div>
        <p className="muted">Try again, or switch to another screen.</p>
        <button onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    )
  }
}
