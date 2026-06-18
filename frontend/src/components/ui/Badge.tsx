import type { HTMLAttributes, ReactNode } from 'react';

type BadgeVariant =
  | 'pending'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'critical'
  | 'high'
  | 'medium'
  | 'low';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant: BadgeVariant;
  children: ReactNode;
}

const variantClasses: Record<BadgeVariant, string> = {
  pending:
    'bg-surface-raised text-text-muted border-border',
  processing:
    'bg-info/10 text-info border-info/30',
  completed:
    'bg-success/10 text-success border-success/30',
  failed:
    'bg-danger/10 text-danger border-danger/30',
  cancelled:
    'bg-surface-raised text-text-dim border-border',
  critical:
    'bg-severity-critical/10 text-severity-critical border-severity-critical/30',
  high:
    'bg-severity-high/10 text-severity-high border-severity-high/30',
  medium:
    'bg-severity-medium/10 text-severity-medium border-severity-medium/30',
  low:
    'bg-severity-low/10 text-severity-low border-severity-low/30',
};

export function Badge({ variant, className = '', children, ...props }: BadgeProps) {
  return (
    <span
      className={[
        'inline-flex items-center gap-1',
        'text-xs font-mono font-medium',
        'px-2 py-0.5 rounded-sm',
        'border',
        variantClasses[variant],
        className,
      ].join(' ')}
      {...props}
    >
      {children}
    </span>
  );
}
