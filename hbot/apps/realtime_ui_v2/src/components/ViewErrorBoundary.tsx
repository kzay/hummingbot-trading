import { Component, type ErrorInfo, type ReactNode } from "react";

interface ViewErrorBoundaryProps {
  label: string;
  children: ReactNode;
}

interface ViewErrorBoundaryState {
  hasError: boolean;
  message: string;
  stack: string;
}

export class ViewErrorBoundary extends Component<ViewErrorBoundaryProps, ViewErrorBoundaryState> {
  override state: ViewErrorBoundaryState = {
    hasError: false,
    message: "",
    stack: "",
  };

  static getDerivedStateFromError(error: Error): ViewErrorBoundaryState {
    return {
      hasError: true,
      message: error.message || "Unexpected render failure",
      stack: error.stack ?? "",
    };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error(`[ui] ${this.props.label} view failed`, error, errorInfo);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, message: "", stack: "" });
  };

  override render(): ReactNode {
    if (this.state.hasError) {
      return (
        <section className="panel panel-span-12 error-boundary-panel" role="alert">
          <h2>{this.props.label} unavailable</h2>
          <p>The active view hit a rendering error. Reconnect or switch views to recover.</p>
          <pre className="error-boundary-copy">{this.state.stack || this.state.message}</pre>
          <button type="button" className="secondary" onClick={this.handleRetry}>Retry</button>
        </section>
      );
    }
    return this.props.children;
  }
}
