import type { HTMLAttributes, ReactNode } from 'react';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  header?: ReactNode;
  padded?: boolean;
}

export function Card({
  header,
  padded = true,
  className = '',
  children,
  ...props
}: CardProps) {
  return (
    <div
      className={[
        'bg-surface border border-border rounded-lg',
        'overflow-hidden',
        className,
      ].join(' ')}
      {...props}
    >
      {header && (
        <div className="px-4 py-3 border-b border-border bg-surface-raised/50">
          {typeof header === 'string' ? (
            <h3 className="text-sm font-semibold text-text">{header}</h3>
          ) : (
            header
          )}
        </div>
      )}
      <div className={padded ? 'p-4' : ''}>{children}</div>
    </div>
  );
}
