import { useCallback, useEffect, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";

import {
  createChatSession,
  deleteChatSession,
  getChatMessages,
  requestErrorMessage,
  sendChatMessage
} from "./api";
import type { ChatMessage, ImagePayload, WebSession } from "./api";
import { AssistantWorkspace } from "./AssistantWorkspace";
import { ChatShell } from "./Portal";
import "./styles.css";

type Attachment = { payload: ImagePayload; name: string; previewUrl: string };

const sessionsKey = "mai-agent.web-sessions";
const activeKey = "mai-agent.active-session";

function readStoredSessions(): WebSession[] {
  try {
    const raw = window.localStorage.getItem(sessionsKey);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((item): item is { id: string; created_at: string } =>
        Boolean(item) && typeof item.id === "string" && typeof item.created_at === "string"
      )
      .map((item): WebSession => ({
        id: item.id,
        source: "web",
        created_at: item.created_at,
        updated_at: item.created_at
      }));
  } catch {
    return [];
  }
}

function storeSessions(sessions: WebSession[], activeId: string | null) {
  try {
    window.localStorage.setItem(sessionsKey, JSON.stringify(sessions));
    if (activeId) window.localStorage.setItem(activeKey, activeId);
    else window.localStorage.removeItem(activeKey);
  } catch {
    // Storage is optional: the page keeps its in-memory session list.
  }
}

export function App() {
  const [sessions, setSessions] = useState<WebSession[]>(readStoredSessions);
  const [activeId, setActiveId] = useState<string | null>(() => {
    const stored = readStoredSessions();
    try {
      const active = window.localStorage.getItem(activeKey);
      return active && stored.some((session) => session.id === active)
        ? active
        : stored[0]?.id ?? null;
    } catch {
      return stored[0]?.id ?? null;
    }
  });
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [attachment, setAttachment] = useState<Attachment | null>(null);

  const persistSessions = useCallback((next: WebSession[], nextActive: string | null) => {
    setSessions(next);
    setActiveId(nextActive);
    storeSessions(next, nextActive);
  }, []);

  const loadHistory = useCallback(async (id: string) => {
    setHistoryLoading(true);
    setError("");
    try {
      setMessages(await getChatMessages(id));
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось восстановить историю диалога"));
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  // Restore the active dialog, or create the first one.
  useEffect(() => {
    if (activeId) {
      void loadHistory(activeId);
      return;
    }
    let ignore = false;
    setHistoryLoading(true);
    createChatSession()
      .then((session) => {
        if (ignore) return;
        persistSessions([session], session.id);
        setMessages([]);
      })
      .catch((requestError: unknown) => {
        if (!ignore) {
          setError(requestErrorMessage(requestError, "Не удалось создать диалог"));
          setHistoryLoading(false);
        }
      });
    return () => { ignore = true; };
  }, [activeId, loadHistory, persistSessions]);

  useEffect(() => {
    if (!attachment) return;
    return () => URL.revokeObjectURL(attachment.previewUrl);
  }, [attachment]);

  const startSession = async () => {
    if (pending) return;
    setError("");
    setPending(true);
    try {
      const session = await createChatSession();
      persistSessions([session, ...sessions], session.id);
      setMessages([]);
      setInput("");
      setAttachment(null);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось начать новый диалог"));
    } finally {
      setPending(false);
    }
  };

  const openSession = async (id: string) => {
    if (pending || id === activeId) return;
    setActiveId(id);
    storeSessions(sessions, id);
    setMessages([]);
    setInput("");
    setAttachment(null);
    await loadHistory(id);
  };

  const removeSession = async (id: string) => {
    if (pending) return;
    try {
      await deleteChatSession(id);
    } catch {
      // The local list is authoritative for the UI; drop the entry regardless.
    }
    const next = sessions.filter((session) => session.id !== id);
    const nextActive = activeId === id ? (next[0]?.id ?? null) : activeId;
    persistSessions(next, nextActive);
    if (activeId === id) setMessages([]);
  };

  const sendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || (!input.trim() && !attachment)) return;
    const content = input.trim() || "Проанализируй прикреплённое изображение.";
    setError("");
    setPending(true);
    const previous = messages;
    try {
      if (!activeId) throw new Error("Диалог ещё не готов");
      setMessages([...previous, { role: "user", content }]);
      const reply = await sendChatMessage(activeId, content, attachment?.payload);
      setMessages((current) => [...current, reply]);
      setInput("");
      setAttachment(null);
      persistSessions(
        sessions.map((session) =>
          session.id === activeId ? { ...session, updated_at: new Date().toISOString() } : session
        ),
        activeId
      );
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось отправить сообщение"));
      setMessages(previous);
    } finally {
      setPending(false);
    }
  };

  const attachImage = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || pending) return;
    setError("");
    try {
      const data = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const result = String(reader.result ?? "");
          const base64 = result.slice(result.indexOf(",") + 1);
          if (base64) resolve(base64);
          else reject(new Error("Пустой файл"));
        };
        reader.onerror = () => reject(new Error("Не удалось прочитать файл"));
        reader.readAsDataURL(file);
      });
      setAttachment({
        payload: { data, mime_type: file.type || "image/png" },
        name: file.name,
        previewUrl: URL.createObjectURL(file)
      });
    } catch {
      setError("Не удалось подготовить изображение");
    }
  };

  return (
    <ChatShell>
      {error && <p className="error global-error" role="alert">{error}</p>}
      <AssistantWorkspace
        sessionId={activeId}
        sessions={sessions}
        messages={messages}
        input={input}
        pending={pending}
        historyLoading={historyLoading}
        attachment={attachment ? { name: attachment.name, previewUrl: attachment.previewUrl } : null}
        onInputChange={setInput}
        onOpenSession={openSession}
        onStartSession={startSession}
        onDeleteSession={removeSession}
        onRefreshHistory={() => { if (activeId) void loadHistory(activeId); }}
        onSend={sendMessage}
        onAttach={attachImage}
        onRemoveAttachment={() => setAttachment(null)}
      />
    </ChatShell>
  );
}
