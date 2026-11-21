import { useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import {
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
import { Documents, requestErrorMessage } from "./Documents";
import { AuthScreen, HomePage, ProfilePage, Workspace, isStaff } from "./Portal";
import type { AuthMode, View } from "./Portal";
import { StaffApplications } from "./StaffApplications";
import "./styles.css";

type ChatAttachment = { documentId: number; name: string; previewUrl: string };

export function App() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [authPending, setAuthPending] = useState(false);
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
  const [chatAttachment, setChatAttachment] = useState<ChatAttachment | null>(null);
  const [telegramPairingCode, setTelegramPairingCode] = useState("");
  const [telegramPairingLoading, setTelegramPairingLoading] = useState(false);
  const [profilePending, setProfilePending] = useState(false);
  const [profileSaved, setProfileSaved] = useState(false);

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

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (authPending) return;
    setError("");
    setAuthPending(true);

    try {
      if (mode === "register") await register(email, password);
      const response = await login(email, password);
      const currentUser = await getCurrentUser(response.access_token);
      setProfile(null);
      setDocuments([]);
      setView("home");
      setToken(response.access_token);
      setUser(currentUser);
      setProfile(await getProfile(response.access_token));
      if (currentUser.role !== "student") {
        setDocuments(await getDocuments(response.access_token));
      }
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось войти в кабинет"));
    } finally {
      setAuthPending(false);
    }
  };

  if (!token || !user) {
    return <AuthScreen mode={mode} email={email} password={password} error={error} pending={authPending}
      onEmailChange={setEmail} onPasswordChange={setPassword} onSubmit={submit} onModeChange={() => {
        setError("");
        setMode((current) => current === "login" ? "register" : "login");
      }} />;
  }

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
    setError("");
    setView(next);
    window.scrollTo({ top: 0, behavior: "instant" });
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
    <Workspace user={user} profile={profile} view={view} error={error} onNavigate={showView} onLogout={() => {
      setToken(null);
      setUser(null);
      setChatSessions([]);
      setHistoryLoading(false);
    }}>
      {view === "home" && <HomePage user={user} profile={profile} documents={documents}
        pairingCode={telegramPairingCode} pairingPending={telegramPairingLoading}
        onPair={createTelegramPairing} onNavigate={showView} />}
      {view === "profile" && <ProfilePage user={user} profile={profile} pending={profilePending} saved={profileSaved}
        onSave={saveProfile} onChange={() => setProfileSaved(false)} />}
      {view === "documents" && user.role !== "student" && (
        <Documents token={token} documents={documents} replaceDocument={replaceDocument} />
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
