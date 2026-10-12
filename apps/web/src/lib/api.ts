export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function financialIdempotency(path: string, init?: RequestInit): Promise<{
  key: string;
  storageKey: string;
} | null> {
  if (typeof window === "undefined" || (init?.method ?? "GET").toUpperCase() !== "POST") {
    return null;
  }
  const isFinancialCreate =
    path === "/api/transactions" ||
    path === "/api/transfers" ||
    path === "/api/card-purchases" ||
    /^\/api\/invoices\/[^/]+\/payments$/.test(path);
  const body = init?.body;
  if (!isFinancialCreate || typeof body !== "string") return null;

  const source = new TextEncoder().encode(`${path}\n${body}`);
  const digest = await window.crypto.subtle.digest("SHA-256", source);
  const fingerprint = Array.from(new Uint8Array(digest), (value) =>
    value.toString(16).padStart(2, "0"),
  ).join("");
  const storageKey = `sophia:idempotency:${fingerprint}`;
  let key = window.sessionStorage.getItem(storageKey);
  if (key === null) {
    key = window.crypto.randomUUID();
    window.sessionStorage.setItem(storageKey, key);
  }
  return { key, storageKey };
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const idempotency = await financialIdempotency(path, init);
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-SophIA-Request": "1",
        ...(idempotency ? { "Idempotency-Key": idempotency.key } : {}),
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Não foi possível conectar à aplicação. Confira se o ambiente está ativo.", 0);
  }

  if (response.ok && idempotency !== null) {
    window.sessionStorage.removeItem(idempotency.storageKey);
  }

  if (!response.ok) {
    let message = "Não foi possível concluir a solicitação.";
    try {
      const body: unknown = await response.json();
      if (
        typeof body === "object" &&
        body !== null &&
        "detail" in body &&
        typeof body.detail === "string"
      ) {
        message = body.detail;
      }
    } catch {
      // Respostas sem JSON mantêm a mensagem genérica.
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
