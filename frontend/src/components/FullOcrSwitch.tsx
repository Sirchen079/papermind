import { useId } from 'react';

export function FullOcrSwitch({ checked, disabled, onChange, description }: {
  checked: boolean; disabled: boolean; onChange: (checked: boolean) => void; description: string;
}) {
  const descriptionId = useId();
  return <label className={`flex items-start gap-3 rounded-lg border border-[var(--border)] p-3 ${disabled ? 'cursor-not-allowed opacity-60' : 'cursor-pointer'}`}>
    <input type="checkbox" role="switch" aria-label="全部页面使用 OCR" aria-describedby={descriptionId}
      className="peer sr-only" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />
    <span aria-hidden="true" className="relative mt-0.5 h-5 w-9 shrink-0 rounded-full border border-[var(--border)] bg-[var(--surface-2)] transition-colors peer-checked:bg-[var(--accent)] peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-[var(--accent)] after:absolute after:left-0.5 after:top-0.5 after:h-3.5 after:w-3.5 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-4" />
    <span><span className="block text-sm font-medium">全部页面使用 OCR</span>
      <span id={descriptionId} className="mt-1 block text-xs text-muted">{description}</span>
    </span>
  </label>;
}
