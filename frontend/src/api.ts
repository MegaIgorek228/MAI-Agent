// Минимальное API MAI Agent: только сессии агента. Без токенов и JWT.

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const apiFetch = async (path: string, init?: RequestInit): Promise<Response> => {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers
    });
  } catch {
    throw new ApiError("Backend недоступен. Попробуйте позже.", 0);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail: unknown = body.detail;
    if (typeof detail === "string") throw new ApiError(detail, response.status);
    if (Array.isArray(detail)) {
      const errors = detail.flatMap((item) => {
        if (!item || typeof item.msg !== "string") return [];
        const field = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        return [field ? `${field}: ${item.msg}` : item.msg];
      });
      if (errors.length) throw new ApiError(errors.join(". "), response.status);
    }
    throw new ApiError(`Ошибка запроса (HTTP ${response.status})`, response.status);
  }
  return response;
};

const apiRequest = async <T>(path: string, init?: RequestInit): Promise<T> =>
  (await apiFetch(path, init)).json() as Promise<T>;

export type WebSession = {
  id: string;
  source: string;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

export type ImagePayload = {
  data: string;
  mime_type: string;
};

export const createChatSession = (): Promise<WebSession> =>
  apiRequest<WebSession>("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({})
  });

export const getChatMessages = (id: string): Promise<ChatMessage[]> =>
  apiRequest<ChatMessage[]>(`/chat/sessions/${id}/messages`);

export const sendChatMessage = (
  id: string,
  content: string,
  image?: ImagePayload
): Promise<ChatMessage> =>
  apiRequest<ChatMessage>(`/chat/sessions/${id}/messages`, {
    method: "POST",
    body: JSON.stringify({ content, image })
  });

export const deleteChatSession = (id: string): Promise<void> =>
  apiRequest<void>(`/chat/sessions/${id}`, { method: "DELETE" });

export function requestErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return fallback;
}
