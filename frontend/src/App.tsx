import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import {
  DocumentItem,
  ChatMessage,
  ChatSession,
  createTelegramPairingCode,
  createChatSession,
  documentFileUrl,
  getChatMessages,
  getCurrentUser,
  getDocuments,
  getProfile,
  listChatSessions,
  login,
  Profile,
  register,
  updateProfile,
  uploadDocument,
  sendChatMessage,
  User
} from "./api";
import { ApplicantApplications } from "./Admissions";
import { StaffApplications } from "./StaffApplications";
import { Documents, requestErrorMessage } from "./Documents";
import "./styles.css";

type AuthMode = "login" | "register";
type View = "home" | "profile" | "documents" | "applications" | "staff" | "agent";

const sessionLabel = (session: ChatSession) => {
  const channel = session.channel === "telegram" ? "Telegram" : "Web";
  const date = new Date(session.created_at);
  const stamp = Number.isNaN(date.getTime()) ? "" : date.toLocaleString("ru-RU", {
    dateStyle: "short",
    timeStyle: "short"
  });
  return [`${channel} · Диалог №${session.id}`, stamp].filter(Boolean).join(" · ");
};

export function App() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [error, setError] = useState("");
  const [view, setView] = useState<View>("home");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [chatSessionId, setChatSessionId] = useState<number | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [telegramPairingCode, setTelegramPairingCode] = useState("");
  const [telegramPairingLoading, setTelegramPairingLoading] = useState(false);
  const [chatImageDocumentId, setChatImageDocumentId] = useState<number | null>(null);
  const [chatImageFile, setChatImageFile] = useState<File | null>(null);
  const [chatImagePreview, setChatImagePreview] = useState<string | null>(null);
  const [profilePending, setProfilePending] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);

  useEffect(() => {
    if (!chatImagePreview) return;
    return () => URL.revokeObjectURL(chatImagePreview);
  }, [chatImagePreview]);

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

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      if (mode === "register") {
        await register(email, password);
      }
      const response = await login(email, password);
      const currentUser = await getCurrentUser(response.access_token);
      setToken(response.access_token);
      setUser(currentUser);
      setProfile(await getProfile(response.access_token));
      if (currentUser.role !== "student") {
        setDocuments(await getDocuments(response.access_token));
      }
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Неизвестная ошибка");
    }
  };

  if (token && user) {
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
          admission_basis: String(form.get("admission_basis") || "")
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
      setError("");
      setView(next);
    };

    const clearComposer = () => {
      setChatInput("");
      setChatImageDocumentId(null);
      setChatImageFile(null);
      setChatImagePreview(null);
    };

    const openChat = async (event: ChangeEvent<HTMLSelectElement>) => {
      const id = Number(event.target.value);
      if (!id || id === chatSessionId) return;
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

    const startChat = async () => {
      setError("");
      setChatLoading(true);
      try {
        const session = await createChatSession(token);
        setChatSessionId(session.id);
        setChatMessages([]);
        setChatSessions((current) => [
          { id: session.id, channel: session.channel, created_at: new Date().toISOString() },
          ...current.filter(({ id }) => id !== session.id)
        ]);
        setHistoryRefresh((value) => value + 1);
        clearComposer();
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "Ошибка запуска агента");
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
        setError(requestError instanceof Error ? requestError.message : "Не удалось создать код");
      } finally {
        setTelegramPairingLoading(false);
      }
    };

    const sendMessage = async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!chatSessionId || (!chatInput.trim() && !chatImageDocumentId)) return;
      const content = chatInput.trim() || "Проанализируй прикреплённое изображение.";
      const attachedId = chatImageDocumentId;
      const attachedFile = chatImageFile;
      setError("");
      const previousMessages = chatMessages;
      setChatMessages((current) => [
        ...current,
        {
          role: "user",
          content,
          image_document_id: attachedId,
          image_filename: attachedFile?.name ?? null
        }
      ]);
      setChatLoading(true);
      try {
        const response = await sendChatMessage(token, chatSessionId, content, attachedId ?? undefined);
        setChatMessages((current) => [...current, response]);
        clearComposer();
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "Ошибка запроса к агенту");
        setChatMessages(await getChatMessages(token, chatSessionId).catch(() => previousMessages));
      } finally {
        setChatLoading(false);
      }
    };

    const attachChatImage = async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      setError("");
      setChatLoading(true);
      try {
        const uploaded = await uploadDocument(token, file, "image");
        replaceDocument(uploaded);
        setChatImageDocumentId(uploaded.id);
        setChatImageFile(file);
        setChatImagePreview(URL.createObjectURL(file));
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "Не удалось загрузить изображение");
      } finally {
        setChatLoading(false);
        event.target.value = "";
      }
    };

    return (
      <main className="container">
        <section className="card workspace-card">
          <nav className="nav">
            <button type="button" aria-pressed={view === "home"} onClick={() => showView("home")}>Главная</button>
            <button type="button" aria-pressed={view === "profile"} onClick={() => showView("profile")}>Профиль</button>
            {user.role !== "student" && (
              <button type="button" aria-pressed={view === "documents"} onClick={() => showView("documents")}>Документы</button>
            )}
            {user.role === "applicant" && (
              <button type="button" aria-pressed={view === "applications"} onClick={() => showView("applications")}>Заявления</button>
            )}
            <button type="button" aria-pressed={view === "agent"} onClick={() => showView("agent")}>Агент</button>
            {(user.role === "admissions_staff" || user.role === "administrator") && (
              <button type="button" aria-pressed={view === "staff"} onClick={() => showView("staff")}>Сотрудники</button>
            )}
          </nav>
          <h1>MAI-Agent</h1>
          {error && <p className="error" role="alert">{error}</p>}
          {view === "home" && (
            <>
              <p>Добро пожаловать, {user.email}.</p>
              <p>Роль: {user.role}</p>
              <p>Используйте навигацию для работы с профилем и документами.</p>
              <button type="button" onClick={createTelegramPairing} disabled={telegramPairingLoading}>
                {telegramPairingLoading ? "Создание..." : "Привязать Telegram"}
              </button>
              {telegramPairingCode && (
                <p>
                  Отправьте боту <strong>/pair {telegramPairingCode}</strong>.
                  Код действителен 10 минут.
                </p>
              )}
            </>
          )}
          {view === "profile" && profile && (
            <form onSubmit={saveProfile} onChange={() => setProfileSaved(false)}>
              {[
                ["first_name", "Имя"],
                ["last_name", "Фамилия"],
                ["phone", "Телефон"],
                ["target_program", "Направление подготовки"],
                ["admission_basis", "Основание поступления"]
              ].map(([name, label]) => (
                <label key={name}>
                  {label}
                  <input name={name} defaultValue={profile[name as keyof Profile] as string | null ?? ""} />
                </label>
              ))}
              <button type="submit" disabled={profilePending}>Сохранить профиль</button>
              {profileSaved && <p role="status">Профиль сохранён.</p>}
            </form>
          )}
          {view === "documents" && (
            <Documents token={token} documents={documents} replaceDocument={replaceDocument} />
          )}
          {view === "applications" && user.role === "applicant" && (
            <ApplicantApplications key={token} token={token} documents={documents} profile={profile} />
          )}
          {view === "agent" && (
            <div className="view-stack">
              <div className="actions">
                <button type="button" onClick={startChat} disabled={chatLoading}>Начать диалог</button>
                <button type="button" disabled={chatLoading || historyLoading} onClick={() => {
                  setError("");
                  setHistoryRefresh((value) => value + 1);
                }}>Обновить список диалогов</button>
              </div>
              {chatSessions.length > 0 && (
                <label>
                  История диалогов
                  <select value={chatSessionId ?? ""} onChange={openChat} disabled={chatLoading}>
                    <option value="" disabled>Выберите диалог</option>
                    {chatSessions.map((session) => <option key={session.id} value={session.id}>{sessionLabel(session)}</option>)}
                  </select>
                </label>
              )}
              {(chatLoading || historyLoading) && <p role="status">Запрос выполняется…</p>}
              {chatSessionId && (
                <>
                  <div className="chat">
                    {chatMessages.map((message, index) => (
                      <div key={`${message.role}-${index}`} className="chat-message">
                        {message.image_document_id ? (
                          <img
                            className="chat-image"
                            src={documentFileUrl(token, message.image_document_id)}
                            alt={message.image_filename ?? "Прикреплённое изображение"}
                          />
                        ) : null}
                        <p><strong>{message.role === "user" ? "Вы" : "Агент"}</strong> {message.content}</p>
                      </div>
                    ))}
                  </div>
                  <form onSubmit={sendMessage}>
                    <label className="upload">
                      Прикрепить изображение
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/gif"
                        onChange={attachChatImage}
                        disabled={chatLoading}
                      />
                    </label>
                    {chatImagePreview && (
                      <div className="chat-attachment-preview">
                        <img
                          className="chat-image"
                          src={chatImagePreview}
                          alt="Предпросмотр прикреплённого изображения"
                        />
                        <button type="button" disabled={chatLoading} onClick={() => {
                          setChatImageDocumentId(null);
                          setChatImageFile(null);
                          setChatImagePreview(null);
                        }}>Открепить изображение</button>
                      </div>
                    )}
                    <label>
                      Сообщение
                      <textarea value={chatInput} disabled={chatLoading} onChange={(event) => setChatInput(event.target.value)} />
                    </label>
                    <button type="submit" disabled={chatLoading}>Отправить</button>
                  </form>
                </>
              )}
            </div>
          )}
          {view === "staff" && (user.role === "admissions_staff" || user.role === "administrator") && (
            <StaffApplications key={token} token={token} />
          )}
          <button
            type="button"
            onClick={() => {
              setToken(null);
              setUser(null);
              setChatSessions([]);
              setHistoryLoading(false);
            }}
          >Выйти</button>
        </section>
      </main>
    );
  }

  return (
    <main className="container">
      <section className="card">
        <h1>{mode === "login" ? "Вход" : "Регистрация"}</h1>
        <form onSubmit={submit}>
          <label>
            Email
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>
            Пароль
            <input
              type="password"
              minLength={8}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit">{mode === "login" ? "Войти" : "Создать аккаунт"}</button>
        </form>
        <button type="button" className="link" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "Зарегистрироваться" : "У меня уже есть аккаунт"}
        </button>
      </section>
    </main>
  );
}
