import type { InputHTMLAttributes, ReactNode } from 'react';

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label: string;
  error?: string;
  hint?: string;
  icon?: ReactNode;
}

export function Input({
  label,
  error,
  hint,
  icon,
  id,
  className = '',
  ...props
}: InputProps) {
  const inputId = id ?? label.toLowerCase().replace(/\s+/g, '-');
  const hasError = !!error;

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={inputId}
        className="text-sm font-medium text-text-muted"
      >
        {label}
      </label>
      <div className="relative">
        {icon && (
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-text-dim">
            {icon}
          </span>
        )}
        <input
          id={inputId}
          className={[
            'w-full bg-surface text-text text-sm font-mono',
            'border border-border rounded-md',
            'px-3 py-2',
            'placeholder:text-text-dim',
            'transition-colors duration-150',
            'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent',
            icon ? 'pl-9' : '',
            hasError
              ? 'border-danger focus:ring-danger focus:border-danger'
              : '',
            className,
          ].join(' ')}
          aria-invalid={hasError || undefined}
          aria-describedby={hasError ? `${inputId}-error` : undefined}
          {...props}
        />
      </div>
      {hasError && (
        <p id={`${inputId}-error`} className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
      {!hasError && hint && (
        <p className="text-xs text-text-dim">{hint}</p>
      )}
    </div>
  );
}
