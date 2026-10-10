export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        "X-SophIA-Request": "1",
        ...init?.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError("Não foi possível conectar à aplicação. Confira se o ambiente está ativo.", 0);
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
