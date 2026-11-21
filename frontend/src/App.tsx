import { useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import {
  ApiError,
  createChatSession,
  createTelegramPairingCode,
  getChatMessages,
  getCurrentUser,
  getDocuments,
  getProfile,
  listChatSessions,
  login,
  register,
  sendChatMessage,
  updateProfile,
  uploadDocument,
} from "./api";
import type { ChatMessage, ChatSession, DocumentItem, Profile, User } from "./api";
import { ApplicantApplications } from "./Admissions";
import { AssistantWorkspace } from "./AssistantWorkspace";
import { Cockpit } from "./Cockpit";
import { Documents, requestErrorMessage } from "./Documents";
import { AuthScreen, HomePage, ProfilePage, Workspace, isStaff } from "./Portal";
import type { AuthMode, View } from "./Portal";
import { StaffApplications } from "./StaffApplications";
import "./styles.css";

type ChatAttachment = { documentId: number; name: string; previewUrl: string };

const sessionKey = "mai-agent.session";
const viewHashes: Record<View, string> = {
  home: "#map",
  profile: "#seat",
  documents: "#cockpit",
  applications: "#applications",
  staff: "#staff",
  agent: "#cabin",
};

function readView(): View {
  const route = (Object.keys(viewHashes) as View[]).find((view) => viewHashes[view] === window.location.hash);
  return route ?? "home";
}

function canOpenView(user: User, view: View) {
  if (view === "staff") return isStaff(user);
  if (view === "applications") return user.role === "applicant";
  if (view === "documents") return user.role !== "student";
  return true;
}

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

export function App() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      if (mode === "register") await register(email, password);
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
    setToken(null);
    setUser(null);
    setError("");
    setRestoreError("");
    window.history.replaceState(null, "", viewHashes.home);
  };

  if (token && user) return <SessionWorkspace key={token} token={token} user={user} onLogout={logout} />;

  if (token) {
    return (
      <main className="session-restore" aria-busy={!restoreError}>
        <h1>{restoreError ? "Не удалось открыть кабинет" : "Открываем кабинет"}</h1>
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
    onEmailChange={setEmail} onPasswordChange={setPassword} onSubmit={submit} onModeChange={() => {
      setError("");
      setMode((current) => current === "login" ? "register" : "login");
    }} />;
}

function SessionWorkspace({ token, user, onLogout }: { token: string; user: User; onLogout: () => void }) {
  const [requestedView, setRequestedView] = useState(readView);
  const view = canOpenView(user, requestedView) ? requestedView : "home";
  const [error, setError] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [chatSessionId, setChatSessionId] = useState<number | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatAttachment, setChatAttachment] = useState<ChatAttachment | null>(null);
  const [telegramPairingCode, setTelegramPairingCode] = useState("");
  const [telegramPairingLoading, setTelegramPairingLoading] = useState(false);
  const [profilePending, setProfilePending] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);

  useEffect(() => {
    const restoreView = () => {
      setError("");
      setRequestedView(readView());
    };
    window.addEventListener("popstate", restoreView);
    window.addEventListener("hashchange", restoreView);
    return () => {
      window.removeEventListener("popstate", restoreView);
      window.removeEventListener("hashchange", restoreView);
    };
  }, []);

  useEffect(() => {
    if (requestedView !== view) {
      window.history.replaceState(null, "", viewHashes[view]);
      setRequestedView(view);
    }
  }, [requestedView, view]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [view]);

  useEffect(() => {
    let ignore = false;
    const reportError = (requestError: unknown) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить данные кабинета"));
    };
    getProfile(token).then((currentProfile) => {
      if (!ignore) setProfile(currentProfile);
    }).catch(reportError);
    if (user.role !== "student") {
      getDocuments(token).then((currentDocuments) => {
        if (!ignore) setDocuments((current) => {
          const changedIds = new Set(current.map((document) => document.id));
          return [...current, ...currentDocuments.filter((document) => !changedIds.has(document.id))];
        });
      }).catch(reportError);
    }
    return () => { ignore = true; };
  }, [token, user.role]);

  useEffect(() => {
    if (!chatAttachment) return;
    return () => URL.revokeObjectURL(chatAttachment.previewUrl);
  }, [chatAttachment]);

  useEffect(() => {
    if (!token || view !== "agent") return;
    let ignore = false;
    setHistoryLoading(true);
    listChatSessions(token).then((sessions) => {
      if (!ignore) setChatSessions(sessions);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось открыть историю диалогов"));
    }).finally(() => {
      if (!ignore) setHistoryLoading(false);
    });
    return () => { ignore = true; };
  }, [token, view, historyRefresh]);

  const replaceDocument = (replacement: DocumentItem) => {
    setDocuments((current) => current.some((item) => item.id === replacement.id)
      ? current.map((item) => item.id === replacement.id ? replacement : item)
      : [replacement, ...current]);
  };

  const saveProfile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    setProfileSaved(false);
    setProfilePending(true);
    try {
      const updated = await updateProfile(token, {
        first_name: String(form.get("first_name") || ""),
        last_name: String(form.get("last_name") || ""),
        phone: String(form.get("phone") || ""),
        target_program: String(form.get("target_program") || ""),
        admission_basis: String(form.get("admission_basis") || ""),
      });
      setProfile(updated);
      setProfileSaved(true);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось сохранить профиль"));
    } finally {
      setProfilePending(false);
    }
  };

  const showView = (next: View) => {
    if (!canOpenView(user, next)) return;
    if (window.location.hash !== viewHashes[next]) {
      window.history.pushState(null, "", viewHashes[next]);
    }
    setError("");
    setRequestedView(next);
  };

  const clearComposer = () => {
    setChatInput("");
    setChatAttachment(null);
  };

  const openChat = async (id: number) => {
    if (chatLoading || id === chatSessionId) return;
    setError("");
    setChatLoading(true);
    try {
      const messages = await getChatMessages(token, id);
      setChatSessionId(id);
      setChatMessages(messages);
      clearComposer();
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось восстановить диалог"));
    } finally {
      setChatLoading(false);
    }
  };

  const createAndRememberChat = async () => {
    const session = await createChatSession(token);
    setChatSessionId(session.id);
    setChatSessions((current) => [
      { id: session.id, channel: session.channel, created_at: new Date().toISOString() },
      ...current.filter(({ id }) => id !== session.id),
    ]);
    setHistoryRefresh((value) => value + 1);
    return session.id;
  };

  const startChat = async () => {
    if (chatLoading) return;
    setError("");
    setChatLoading(true);
    try {
      await createAndRememberChat();
      setChatMessages([]);
      clearComposer();
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось начать диалог"));
    } finally {
      setChatLoading(false);
    }
  };

  const createTelegramPairing = async () => {
    setError("");
    setTelegramPairingLoading(true);
    try {
      const pairing = await createTelegramPairingCode(token);
      setTelegramPairingCode(pairing.code);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось создать код"));
    } finally {
      setTelegramPairingLoading(false);
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
      clearComposer();
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
      replaceDocument(uploaded);
      setChatAttachment({ documentId: uploaded.id, name: file.name, previewUrl: URL.createObjectURL(file) });
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось загрузить изображение"));
    } finally {
      setChatLoading(false);
      event.target.value = "";
    }
  };

  return (
    <Workspace user={user} profile={profile} view={view} error={error} onNavigate={showView} onLogout={onLogout}>
      {view === "home" && <HomePage pairingCode={telegramPairingCode} pairingPending={telegramPairingLoading}
        onPair={createTelegramPairing} />}
      {view === "profile" && <ProfilePage user={user} profile={profile} pending={profilePending} saved={profileSaved}
        onSave={saveProfile} onChange={() => setProfileSaved(false)} />}
      {view === "documents" && user.role !== "student" && (
        <>
          <Cockpit token={token} user={user} documents={documents}
            onOpenApplications={() => showView("applications")} onOpenStaff={() => showView("staff")} />
          <Documents token={token} documents={documents} replaceDocument={replaceDocument} />
        </>
      )}
      {view === "applications" && user.role === "applicant" && (
        <ApplicantApplications key={token} token={token} documents={documents} profile={profile} />
      )}
      {view === "staff" && isStaff(user) && <StaffApplications key={token} token={token} />}
      {view === "agent" && <AssistantWorkspace token={token} sessionId={chatSessionId}
        sessions={chatSessions} messages={chatMessages} input={chatInput} pending={chatLoading}
        historyLoading={historyLoading} attachment={chatAttachment}
        onInputChange={setChatInput} onOpenSession={openChat} onStartSession={startChat}
        onRefreshHistory={() => {
          setError("");
          setHistoryRefresh((value) => value + 1);
        }}
        onSend={sendMessage} onAttach={attachChatImage} onRemoveAttachment={() => setChatAttachment(null)} />}
    </Workspace>
  );
}
