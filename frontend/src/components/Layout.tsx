import type { ReactNode } from 'react';

interface LayoutProps {
  children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
  return (
    <div className="flex min-h-screen flex-col font-sans">
      {/* Header */}
      <header className="sticky top-0 z-10 border-b border-border bg-bg/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div>
            <h1 className="text-lg font-bold text-text tracking-tight">
              Code Review Copilot
            </h1>
            <p className="text-xs text-text-dim font-mono">
              AI-powered PR analysis console
            </p>
          </div>
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 mx-auto w-full max-w-6xl px-6 py-8">
        {children}
      </main>

      {/* Footer */}
      <footer className="border-t border-border bg-surface/50">
        <div className="mx-auto max-w-6xl px-6 py-4">
          <p className="text-xs text-text-dim font-mono text-center">
            Code Review Copilot &mdash; FastAPI Test Console
          </p>
        </div>
      </footer>
    </div>
  );
}
