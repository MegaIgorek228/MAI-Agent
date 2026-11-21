import { ChangeEvent, FormEvent, useEffect, useState } from "react";

import {
  DocumentItem,
  ChatMessage,
  createTelegramPairingCode,
  createChatSession,
  documentFileUrl,
  getChatMessages,
  getCurrentUser,
  getDocuments,
  getProfile,
  getStaffApplicants,
  login,
  Profile,
  register,
  updateProfile,
  uploadDocument,
  sendChatMessage,
  User
} from "./api";
import "./styles.css";

type AuthMode = "login" | "register";
type View = "home" | "profile" | "documents" | "staff" | "agent";

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
  const [staffApplicants, setStaffApplicants] = useState<Array<{ id: number; email: string; is_active: boolean }>>(
    []
  );
  const [chatSessionId, setChatSessionId] = useState<number | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [telegramPairingCode, setTelegramPairingCode] = useState("");
  const [telegramPairingLoading, setTelegramPairingLoading] = useState(false);
  const [chatImageDocumentId, setChatImageDocumentId] = useState<number | null>(null);
  const [chatImageFile, setChatImageFile] = useState<File | null>(null);
  const [chatImagePreview, setChatImagePreview] = useState<string | null>(null);

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
      if (currentUser.role !== "student") {
        setProfile(await getProfile(response.access_token));
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
      const updated = await updateProfile(token, {
        first_name: String(form.get("first_name") || ""),
        last_name: String(form.get("last_name") || ""),
        phone: String(form.get("phone") || ""),
        target_program: String(form.get("target_program") || ""),
        admission_basis: String(form.get("admission_basis") || "")
      });
      setProfile(updated);
    };

    const upload = async (event: ChangeEvent<HTMLInputElement>) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const uploaded = await uploadDocument(token, file, "unspecified");
      setDocuments((current) => [uploaded, ...current]);
      event.target.value = "";
    };

    const loadStaffApplicants = async () => {
      setStaffApplicants(await getStaffApplicants(token));
      setView("staff");
    };

    const startChat = async () => {
      setError("");
      setChatLoading(true);
      try {
        const session = await createChatSession(token);
        setChatSessionId(session.id);
        setChatMessages([]);
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
      if (!chatSessionId || !chatInput.trim()) return;
      const content = chatInput.trim();
      const attachedId = chatImageDocumentId;
      const attachedFile = chatImageFile;
      setChatInput("");
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
        setChatImageDocumentId(null);
        setChatImageFile(null);
        setChatImagePreview(null);
      } catch (requestError) {
        setError(requestError instanceof Error ? requestError.message : "Ошибка запроса к агенту");
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
        <section className="card">
          <nav className="nav">
            <button type="button" onClick={() => setView("home")}>Главная</button>
            <button type="button" onClick={() => setView("profile")}>Профиль</button>
            <button type="button" onClick={() => setView("documents")}>Документы</button>
            <button type="button" onClick={() => setView("agent")}>Агент</button>
            {user.role !== "applicant" && (
              <button type="button" onClick={loadStaffApplicants}>Сотрудники</button>
            )}
          </nav>
          <h1>MAI-Agent</h1>
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
            <form onSubmit={saveProfile}>
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
              <button type="submit">Сохранить профиль</button>
            </form>
          )}
          {view === "documents" && (
            <>
              <label className="upload">
                Загрузить документ
                <input type="file" onChange={upload} />
              </label>
              <ul>
                {documents.map((document) => (
                  <li key={document.id}>
                    {document.filename} — {document.status}
                    {document.review_message && <small>{document.review_message}</small>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {view === "agent" && (
            <>
              {!chatSessionId ? (
                <>
                  <p>Диалог использует Hermes Agent через ACP stdio.</p>
                  <button type="button" onClick={startChat} disabled={chatLoading}>
                    {chatLoading ? "Запуск..." : "Начать диалог"}
                  </button>
                </>
              ) : (
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
                        <p><strong>{message.role}:</strong> {message.content}</p>
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
                      <p className="chat-attachment-preview">
                        <img
                          className="chat-image"
                          src={chatImagePreview}
                          alt="Предпросмотр прикреплённого изображения"
                        />
                        <span>Изображение прикреплено.</span>
                      </p>
                    )}
                    <label>
                      Сообщение
                      <textarea value={chatInput} onChange={(event) => setChatInput(event.target.value)} />
                    </label>
                    <button type="submit" disabled={chatLoading}>Отправить</button>
                  </form>
                </>
              )}
            </>
          )}
          {view === "staff" && (
            <>
              <h2>Абитуриенты</h2>
              <ul>
                {staffApplicants.map((applicant) => <li key={applicant.id}>{applicant.email}</li>)}
              </ul>
            </>
          )}
          <button
            type="button"
            onClick={() => {
              setToken(null);
              setUser(null);
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
