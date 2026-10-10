import type { ReactNode } from "react";
import { CircleHelp } from "lucide-react";

export function HelpTip({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="help-tip">
      <summary aria-label={`Ajuda: ${label}`} title={`Ajuda: ${label}`}>
        <CircleHelp aria-hidden="true" size={15} strokeWidth={1.8} />
      </summary>
      <span className="help-tip-popover" role="tooltip">{children}</span>
    </details>
  );
}
