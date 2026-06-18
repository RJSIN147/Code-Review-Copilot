import type { ReactNode } from 'react';

interface EmptyStateProps {
  icon?: ReactNode;
  title: string;
  message?: string;
  action?: ReactNode;
}

export function EmptyState({ icon, title, message, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
      {icon && (
        <div className="mb-4 text-text-dim" aria-hidden="true">
          {icon}
        </div>
      )}
      <h3 className="text-base font-semibold text-text-muted mb-1">
        {title}
      </h3>
      {message && (
        <p className="text-sm text-text-dim max-w-sm mb-4">{message}</p>
      )}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
