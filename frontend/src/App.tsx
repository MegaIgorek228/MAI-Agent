import { useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import {
  ApiError,
  createChatSession,
  getChatMessages,
  getCurrentUser,
  listChatSessions,
  login,
  register,
  sendChatMessage,
  uploadDocument,
} from "./api";
import type { ChatMessage, ChatSession, User } from "./api";
import { AssistantWorkspace } from "./AssistantWorkspace";
import { requestErrorMessage } from "./Documents";
import { AuthScreen, Workspace } from "./Portal";
import type { AuthMode, RegisterType } from "./Portal";
import "./styles.css";

type ChatAttachment = { documentId: number; name: string; previewUrl: string };

const sessionKey = "mai-agent.session";
const chatSessionKey = "mai-agent.chat-session";

function readSessionToken(): string | null {
  try {
    return window.sessionStorage.getItem(sessionKey);
  } catch {
    return null;
  }
}

function storeSessionToken(token: string | null) {
  try {
    if (token) window.sessionStorage.setItem(sessionKey, token);
    else window.sessionStorage.removeItem(sessionKey);
  } catch {
    // The active page can still use its in-memory session if storage is blocked.
  }
}

function readChatSessionId(): number | null {
  try {
    const raw = window.sessionStorage.getItem(chatSessionKey);
    return raw ? Number(raw) : null;
  } catch {
    return null;
  }
}

function storeChatSessionId(id: number | null) {
  try {
    if (id !== null) window.sessionStorage.setItem(chatSessionKey, String(id));
    else window.sessionStorage.removeItem(chatSessionKey);
  } catch {
    // storage is optional
  }
}

export function App() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [registerType, setRegisterType] = useState<RegisterType>("applicant");
  const [inviteCode, setInviteCode] = useState("");
  const [authPending, setAuthPending] = useState(false);
  const [token, setToken] = useState(readSessionToken);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [restoreError, setRestoreError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);

  useEffect(() => {
    if (!token) return;
    let ignore = false;

    getCurrentUser(token).then((currentUser) => {
      if (!ignore) setUser(currentUser);
    }).catch((requestError: unknown) => {
      if (ignore) return;
      if (requestError instanceof ApiError && (requestError.status === 401 || requestError.status === 403)) {
        storeSessionToken(null);
        setToken(null);
        setError("Сеанс завершился. Войдите снова.");
      } else {
        setRestoreError(requestErrorMessage(requestError, "Не удалось восстановить сеанс"));
      }
    });

    return () => { ignore = true; };
  }, [token, restoreAttempt]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (authPending) return;
    setError("");
    setAuthPending(true);

    try {
      if (mode === "register") {
        await register(email, password, registerType === "staff" ? inviteCode : undefined);
        setInviteCode("");
      }
      const response = await login(email, password);
      storeSessionToken(response.access_token);
      setPassword("");
      setToken(response.access_token);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось войти в кабинет"));
    } finally {
      setAuthPending(false);
    }
  };

  const logout = () => {
    storeSessionToken(null);
    storeChatSessionId(null);
    setToken(null);
    setUser(null);
    setError("");
    setRestoreError("");
  };

  if (token && user) return <SessionWorkspace key={token} token={token} user={user} onLogout={logout} />;

  if (token) {
    return (
      <main className="session-restore" aria-busy={!restoreError}>
        <h1>{restoreError ? "Не удалось открыть MAI Agent" : "Открываем MAI Agent"}</h1>
        {restoreError ? (
          <>
            <p className="error" role="alert">{restoreError}</p>
            <div className="actions">
              <button type="button" onClick={() => {
                setRestoreError("");
                setRestoreAttempt((attempt) => attempt + 1);
              }}>Повторить</button>
              <button type="button" className="button-secondary" onClick={logout}>Выйти</button>
            </div>
          </>
        ) : <p role="status">Загружаем данные учётной записи…</p>}
      </main>
    );
  }

  return <AuthScreen mode={mode} email={email} password={password} error={error} pending={authPending}
    registerType={registerType} inviteCode={inviteCode}
    onEmailChange={setEmail} onPasswordChange={setPassword}
    onRegisterTypeChange={setRegisterType} onInviteCodeChange={setInviteCode}
    onSubmit={submit} onModeChange={() => {
      setError("");
      setInviteCode("");
      setMode((current) => current === "login" ? "register" : "login");
    }} />;
}

function SessionWorkspace({ token, user, onLogout }: { token: string; user: User; onLogout: () => void }) {
  const [error, setError] = useState("");
  const [chatSessionId, setChatSessionId] = useState<number | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatAttachment, setChatAttachment] = useState<ChatAttachment | null>(null);

  useEffect(() => {
    if (!chatAttachment) return;
    return () => URL.revokeObjectURL(chatAttachment.previewUrl);
  }, [chatAttachment]);

  // Load the dialog history and restore the last active dialog for this browser tab.
  useEffect(() => {
    let ignore = false;
    setHistoryLoading(true);
    (async () => {
      try {
        const sessions = await listChatSessions(token);
        if (ignore) return;
        setChatSessions(sessions);
        const stored = readChatSessionId();
        const preferred = sessions.find((session) => session.id === stored) ?? sessions[0];
        const id = preferred?.id ?? null;
        setChatSessionId(id);
        if (id === null) {
          setChatMessages([]);
          return;
        }
        storeChatSessionId(id);
        setChatMessages(await getChatMessages(token, id));
      } catch (requestError) {
        if (!ignore) setError(requestErrorMessage(requestError, "Не удалось открыть историю диалогов"));
      } finally {
        if (!ignore) setHistoryLoading(false);
      }
    })();
    return () => { ignore = true; };
  }, [token, historyRefresh]);

  const createAndRememberChat = async () => {
    const session = await createChatSession(token);
    setChatSessionId(session.id);
    storeChatSessionId(session.id);
    setChatSessions((current) => [
      { id: session.id, channel: session.channel, created_at: new Date().toISOString() },
      ...current.filter(({ id }) => id !== session.id),
    ]);
    setHistoryRefresh((value) => value + 1);
    return session.id;
  };

  const openChat = async (id: number) => {
    if (chatLoading || id === chatSessionId) return;
    setError("");
    setChatLoading(true);
    try {
      const messages = await getChatMessages(token, id);
      setChatSessionId(id);
      storeChatSessionId(id);
      setChatMessages(messages);
      setChatInput("");
      setChatAttachment(null);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось восстановить диалог"));
    } finally {
      setChatLoading(false);
    }
  };

  const startChat = async () => {
    if (chatLoading) return;
    setError("");
    setChatLoading(true);
    try {
      await createAndRememberChat();
      setChatMessages([]);
      setChatInput("");
      setChatAttachment(null);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось начать диалог"));
    } finally {
      setChatLoading(false);
    }
  };

  const sendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (chatLoading || (!chatInput.trim() && !chatAttachment)) return;
    const content = chatInput.trim() || "Проанализируй прикреплённое изображение.";
    const previousMessages = chatMessages;
    let sessionId = chatSessionId;
    setError("");
    setChatLoading(true);

    try {
      sessionId = sessionId ?? await createAndRememberChat();
      setChatMessages([...previousMessages, {
        role: "user",
        content,
        image_document_id: chatAttachment?.documentId ?? null,
        image_filename: chatAttachment?.name ?? null,
      }]);
      const response = await sendChatMessage(token, sessionId, content, chatAttachment?.documentId);
      setChatMessages((current) => [...current, response]);
      setChatInput("");
      setChatAttachment(null);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось отправить сообщение"));
      if (sessionId !== null) {
        setChatMessages(await getChatMessages(token, sessionId).catch(() => previousMessages));
      }
    } finally {
      setChatLoading(false);
    }
  };

  const attachChatImage = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || chatLoading) return;
    setError("");
    setChatLoading(true);
    try {
      const uploaded = await uploadDocument(token, file, "image");
      setChatAttachment({ documentId: uploaded.id, name: file.name, previewUrl: URL.createObjectURL(file) });
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось загрузить изображение"));
    } finally {
      setChatLoading(false);
      event.target.value = "";
    }
  };

  return (
    <Workspace chatOnly user={user} profile={null} view="agent" error={error}
      onNavigate={() => {}} onLogout={onLogout}>
      <AssistantWorkspace token={token} sessionId={chatSessionId}
        sessions={chatSessions} messages={chatMessages} input={chatInput} pending={chatLoading}
        historyLoading={historyLoading} attachment={chatAttachment}
        onInputChange={setChatInput} onOpenSession={openChat} onStartSession={startChat}
        onRefreshHistory={() => {
          setError("");
          setHistoryRefresh((value) => value + 1);
        }}
        onSend={sendMessage} onAttach={attachChatImage} onRemoveAttachment={() => setChatAttachment(null)} />
    </Workspace>
  );
}
