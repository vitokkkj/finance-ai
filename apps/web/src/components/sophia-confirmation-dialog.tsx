"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";

import { BrandMark } from "@/components/brand-mark";

export type SophiaConfirmationRequest = {
  title: string;
  description: string;
  impact: string;
  confirmLabel: string;
};

export function useSophiaConfirmation() {
  const [request, setRequest] = useState<SophiaConfirmationRequest | null>(null);
  const resolveRef = useRef<((confirmed: boolean) => void) | null>(null);

  const confirm = useCallback((nextRequest: SophiaConfirmationRequest) => {
    return new Promise<boolean>((resolve) => {
      if (resolveRef.current) {
        resolve(false);
        return;
      }

      resolveRef.current = resolve;
      setRequest(nextRequest);
    });
  }, []);

  const resolve = useCallback((confirmed: boolean) => {
    const finish = resolveRef.current;
    resolveRef.current = null;
    setRequest(null);
    finish?.(confirmed);
  }, []);

  useEffect(() => {
    return () => {
      resolveRef.current?.(false);
      resolveRef.current = null;
    };
  }, []);

  return {
    confirm,
    dialog: request ? <SophiaConfirmationDialog onResolve={resolve} request={request} /> : null,
  };
}

function SophiaConfirmationDialog({
  request,
  onResolve,
}: {
  request: SophiaConfirmationRequest;
  onResolve: (confirmed: boolean) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const impactId = useId();

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;

    dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog
      aria-describedby={`${descriptionId} ${impactId}`}
      aria-labelledby={titleId}
      className="sophia-confirmation-dialog"
      onCancel={(event) => {
        event.preventDefault();
        onResolve(false);
      }}
      ref={dialogRef}
    >
      <div className="sophia-confirmation-brand">
        <span className="sophia-confirmation-brand-mark"><BrandMark size={30} /></span>
        <span><strong>SophIA</strong><small>Confirmação</small></span>
      </div>

      <h2 id={titleId}>{request.title}</h2>
      <p className="sophia-confirmation-description" id={descriptionId}>{request.description}</p>

      <div className="sophia-confirmation-impact" id={impactId}>
        <span className="sophia-confirmation-impact-icon"><AlertTriangle aria-hidden="true" size={18} /></span>
        <div><strong>O que acontece</strong><p>{request.impact}</p></div>
      </div>

      <p className="sophia-confirmation-footnote">Essa exclusão é permanente.</p>

      <div className="sophia-confirmation-actions">
        <button className="secondary-button" onClick={() => onResolve(false)} type="button">Manter registro</button>
        <button className="sophia-confirmation-delete" onClick={() => onResolve(true)} type="button">
          <Trash2 aria-hidden="true" size={16} />
          {request.confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
