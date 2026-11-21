const apiRequest = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? "Ошибка запроса");
  }
  return response.json() as Promise<T>;
};

export type User = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type Profile = {
  id: number;
  user_id: number;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  target_program: string | null;
  admission_basis: string | null;
  updated_at: string;
};

export type DocumentItem = {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  document_type: string | null;
  status: string;
  extracted_text: string | null;
  review_message: string | null;
  created_at: string;
};

export type ChatMessage = {
  role: string;
  content: string;
  created_at?: string;
  image_document_id?: number | null;
  image_filename?: string | null;
};

export type TelegramPairingCode = {
  code: string;
  expires_at: string;
};

export const register = (email: string, password: string) =>
  apiRequest<User>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });

export const login = (email: string, password: string) =>
  apiRequest<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });

export const getCurrentUser = (token: string) =>
  apiRequest<User>("/users/me", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getProfile = (token: string) =>
  apiRequest<Profile>("/applicant/profile", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const updateProfile = (token: string, profile: Partial<Profile>) =>
  apiRequest<Profile>("/applicant/profile", {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(profile)
  });

export const getDocuments = (token: string) =>
  apiRequest<DocumentItem[]>("/applicant/documents", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const uploadDocument = (token: string, file: File, documentType: string) => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_type", documentType);
  return apiRequest<DocumentItem>("/applicant/documents", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData
  });
};

export const getStaffApplicants = (token: string) =>
  apiRequest<Array<{ id: number; email: string; is_active: boolean }>>("/applicant/staff/applicants", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const createChatSession = (token: string) =>
  apiRequest<{ id: number; channel: string; hermes_session_id: string }>("/chat/sessions", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ channel: "web" })
  });

export const sendChatMessage = (
  token: string,
  sessionId: number,
  content: string,
  imageDocumentId?: number
) =>
  apiRequest<ChatMessage>(`/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      content,
      image_document_id: imageDocumentId ?? null
    })
  });

export const getChatMessages = (token: string, sessionId: number) =>
  apiRequest<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`, {
    headers: { Authorization: `Bearer ${token}` }
  });

/** URL for loading an attached image in chat history. Uses the
 * `access_token` query parameter because plain `<img>` tags cannot set
 * custom headers. */
export const documentFileUrl = (token: string, documentId: number) =>
  `/applicant/documents/${documentId}/file?access_token=${encodeURIComponent(token)}`;

export const createTelegramPairingCode = (token: string) =>
  apiRequest<TelegramPairingCode>("/auth/telegram/pairing-code", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  });
