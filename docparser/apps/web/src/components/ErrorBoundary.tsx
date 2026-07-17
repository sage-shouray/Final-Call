import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';

interface Props  { children: ReactNode; fallback?: ReactNode; }
interface State  { error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[ErrorBoundary]', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="flex min-h-[400px] flex-col items-center justify-center gap-4 p-8 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-danger-50 dark:bg-danger-950">
            <AlertTriangle className="h-7 w-7 text-danger-600 dark:text-danger-400" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-neutral-800 dark:text-neutral-100">Something went wrong</h2>
            <p className="mt-1 max-w-sm text-sm text-neutral-400 dark:text-neutral-500">
              An unexpected error occurred. Refreshing the page usually fixes it.
            </p>
            {import.meta.env.DEV && (
              <pre className="mt-3 max-w-lg overflow-auto rounded-lg bg-neutral-100 p-3 text-left text-xs text-neutral-600 dark:bg-neutral-800 dark:text-neutral-400">
                {this.state.error.message}
              </pre>
            )}
          </div>
          <button
            type="button"
            onClick={() => window.location.reload()}
            className="inline-flex items-center gap-2 rounded-lg bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 transition-colors"
          >
            Refresh page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
