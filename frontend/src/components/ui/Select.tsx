import type { SelectHTMLAttributes } from 'react';

interface OptionDef {
  value: string;
  label: string;
  disabled?: boolean;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  label: string;
  options: (OptionDef | string)[];
  error?: string;
  hint?: string;
}

function normalizeOption(opt: OptionDef | string): OptionDef {
  return typeof opt === 'string' ? { value: opt, label: opt } : opt;
}

export function Select({
  label,
  options,
  error,
  hint,
  id,
  className = '',
  children,
  ...props
}: SelectProps) {
  const selectId = id ?? label.toLowerCase().replace(/\s+/g, '-');
  const hasError = !!error;
  const normalized = options.map(normalizeOption);

  return (
    <div className="flex flex-col gap-1.5">
      <label
        htmlFor={selectId}
        className="text-sm font-medium text-text-muted"
      >
        {label}
      </label>
      <select
        id={selectId}
        className={[
          'w-full bg-surface text-text text-sm font-mono',
          'border border-border rounded-md',
          'px-3 py-2 pr-8',
          'appearance-none',
          'transition-colors duration-150',
          'focus:outline-none focus:ring-2 focus:ring-accent focus:border-accent',
          'cursor-pointer',
          hasError
            ? 'border-danger focus:ring-danger focus:border-danger'
            : '',
          className,
        ].join(' ')}
        aria-invalid={hasError || undefined}
        aria-describedby={hasError ? `${selectId}-error` : undefined}
        {...props}
      >
        {children}
        {normalized.map((opt) => (
          <option
            key={opt.value}
            value={opt.value}
            disabled={opt.disabled}
          >
            {opt.label}
          </option>
        ))}
      </select>
      {hasError && (
        <p id={`${selectId}-error`} className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
      {!hasError && hint && (
        <p className="text-xs text-text-dim">{hint}</p>
      )}
    </div>
  );
}
