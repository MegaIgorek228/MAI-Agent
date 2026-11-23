import { type ChangeEvent, type FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";

import { type ChatMessage, type WebSession } from "./api";
import { Icon } from "./Icon";
import "./assistant.css";

type AssistantWorkspaceProps = {
  sessionId: string | null;
  sessions: WebSession[];
  messages: ChatMessage[];
  input: string;
  pending: boolean;
  historyLoading: boolean;
  attachment: { name: string; previewUrl: string } | null;
  onInputChange: (value: string) => void;
  onOpenSession: (id: string) => void;
  onStartSession: () => void;
  onDeleteSession: (id: string) => void;
  onRefreshHistory: () => void;
  onSend: (event: FormEvent<HTMLFormElement>) => void;
  onAttach: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemoveAttachment: () => void;
};

const suggestions = [
  { icon: "file", text: "Какие документы нужны для поступления?" },
  { icon: "clock", text: "Когда подают документы в МАИ?" },
  { icon: "grid", text: "Какие направления подготовки есть в МАИ?" },
  { icon: "book", text: "Где посмотреть прошлогодние проходные баллы?" }
] as const;

const sessionDateFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit"
});

function formatDate(date: string | undefined, formatter: Intl.DateTimeFormat) {
  if (!date) return "";
  const parsed = new Date(date);
  return Number.isNaN(parsed.getTime()) ? "" : formatter.format(parsed);
}

function MessageText({ content }: { content: string }) {
  return content.split(/(https?:\/\/[^\s<>\[\]\"']+)/g).map((part, index) => {
    if (index % 2 === 0) return part;
    const url = part.replace(/[.,!?;:)]+$/, "");
    return (
      <span key={index}>
        <a href={url} rel="noreferrer" target="_blank">{url}</a>
        {part.slice(url.length)}
      </span>
    );
  });
}

export function AssistantWorkspace({
  sessionId,
  sessions,
  messages,
  input,
  pending,
  historyLoading,
  attachment,
  onInputChange,
  onOpenSession,
  onStartSession,
  onDeleteSession,
  onRefreshHistory,
  onSend,
  onAttach,
  onRemoveAttachment
}: AssistantWorkspaceProps) {
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const historyToggle = useRef<HTMLButtonElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const followTail = useRef(true);
  const previousSession = useRef(sessionId);
  const hasMessages = messages.length > 0;
  const waitingForReply = pending && messages.at(-1)?.role === "user";

  const scrollToTail = () => {
    if (log.current && followTail.current) log.current.scrollTop = log.current.scrollHeight;
  };

  useLayoutEffect(() => {
    if (!hasMessages || previousSession.current !== sessionId || waitingForReply) followTail.current = true;
    previousSession.current = sessionId;
    scrollToTail();
  }, [sessionId, hasMessages, messages, waitingForReply]);

  useEffect(() => {
    if (!log.current) return;
    const observer = new ResizeObserver(scrollToTail);
    observer.observe(log.current);
    return () => observer.disconnect();
  }, [hasMessages]);

  const closeHistory = () => {
    setMobileHistoryOpen(false);
    historyToggle.current?.focus({ preventScroll: true });
  };

  return (
    <section className="assistant-workspace" aria-labelledby="assistant-title">
      <aside className="assistant-history" aria-label="История диалогов" onKeyDown={(event) => {
        if (mobileHistoryOpen && event.key === "Escape") closeHistory();
      }}>
        <div className="assistant-history-toolbar">
          <button
            aria-controls="assistant-history-content"
            aria-expanded={mobileHistoryOpen}
            className="assistant-history-toggle"
            onClick={() => setMobileHistoryOpen((open) => !open)}
            ref={historyToggle}
            type="button"
          >
            <Icon name="panel-left" /> История диалогов <Icon name="chevron-down" />
          </button>
          <button
            className="assistant-new-chat"
            disabled={pending}
            onClick={() => {
              onStartSession();
              setMobileHistoryOpen(false);
            }}
            type="button"
          ><Icon name="plus" /> Начать диалог</button>
        </div>

        <div
          className={mobileHistoryOpen ? "assistant-history-content is-open" : "assistant-history-content"}
          id="assistant-history-content"
          aria-busy={historyLoading}
        >
          <div className="assistant-history-heading">
            <h2>История диалогов</h2>
            <button
              aria-label="Обновить историю диалога"
              className="assistant-icon-button"
              disabled={historyLoading || pending}
              onClick={onRefreshHistory}
              title="Обновить историю диалога"
              type="button"
            ><Icon name="refresh" /></button>
          </div>
          {!sessions.length && (
            <p className="assistant-history-empty" role={historyLoading ? "status" : undefined}>
              {historyLoading ? "Загружаем историю…" : "Начатые диалоги появятся здесь."}
            </p>
          )}
          {!!sessions.length && (
            <ul className="assistant-session-list">
              {sessions.map((session) => {
                const date = formatDate(session.created_at, sessionDateFormat);
                const isActive = session.id === sessionId;
                return (
                  <li key={session.id} className="assistant-session-row">
                    <button
                      aria-current={isActive ? "true" : undefined}
                      className="assistant-session"
                      disabled={pending}
                      onClick={() => {
                        onOpenSession(session.id);
                        if (mobileHistoryOpen) closeHistory();
                      }}
                      type="button"
                    >
                      <Icon name="chat" />
                      <span>
                        <strong>Диалог</strong>
                        <small>
                          Веб
                          {date && <><span aria-hidden="true"> · </span><time dateTime={session.created_at}>{date}</time></>}
                        </small>
                      </span>
                    </button>
                    <button
                      aria-label="Удалить диалог"
                      className="assistant-icon-button assistant-session-delete"
                      disabled={pending}
                      onClick={() => onDeleteSession(session.id)}
                      title="Удалить диалог"
                      type="button"
                    ><Icon name="x" /></button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      <div className="assistant-panel">
        <header className="assistant-panel-header">
          <div className="assistant-column">
            <h1 id="assistant-title">Чат с помощником</h1>
            {sessionId && <p>Сессия {sessionId.slice(0, 8)}</p>}
          </div>
        </header>

        {hasMessages ? (
          <div
            ref={log}
            className="assistant-log"
            role="log"
            aria-label="Сообщения диалога"
            onScroll={({ currentTarget }) => {
              followTail.current = currentTarget.scrollHeight - currentTarget.scrollTop - currentTarget.clientHeight < 80;
            }}
            tabIndex={0}
          >
            <div className="assistant-column assistant-thread">
              {messages.map((message, index) => {
                const isUser = message.role === "user";
                return (
                  <article className={isUser ? "assistant-message from-user" : "assistant-message"} key={index}>
                    <div className="assistant-message-content">
                      <header>
                        <strong>{isUser ? "Вы" : "Помощник МАИ"}</strong>
                      </header>
                      <div className="assistant-bubble">
                        <p><MessageText content={message.content} /></p>
                      </div>
                    </div>
                  </article>
                );
              })}
              {waitingForReply && (
                <p className="assistant-thinking" role="status">
                  <span className="assistant-thinking-mark" aria-hidden="true" />
                  Помощник готовит ответ…
                </p>
              )}
            </div>
          </div>
        ) : (
          <div className="assistant-welcome">
            <div className="assistant-column assistant-welcome-content">
              <h2>Чем помочь?</h2>
              <p>Задайте вопрос о поступлении в МАИ.</p>
              <div className="assistant-suggestions" aria-label="Примеры вопросов">
                {suggestions.map(({ icon, text }) => (
                  <button
                    className="assistant-suggestion"
                    disabled={pending}
                    key={text}
                    onClick={() => {
                      onInputChange(text);
                      composer.current?.focus({ preventScroll: true });
                    }}
                    type="button"
                  >
                    <Icon name={icon} />
                    <span>{text}</span>
                    <Icon name="arrow-right" />
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="assistant-composer-area">
          <div className="assistant-column">
            <form className="assistant-composer" onSubmit={(event) => {
              followTail.current = true;
              onSend(event);
            }}>
              {attachment && (
                <div className="assistant-attachment">
                  <img alt="" src={attachment.previewUrl} />
                  <span>{attachment.name}</span>
                  <button
                    aria-label="Открепить изображение"
                    className="assistant-icon-button"
                    disabled={pending}
                    onClick={onRemoveAttachment}
                    title="Открепить изображение"
                    type="button"
                  ><Icon name="x" /></button>
                </div>
              )}
              <label className="assistant-sr-only" htmlFor="assistant-message">Сообщение</label>
              <textarea
                aria-describedby="assistant-composer-hint"
                disabled={pending}
                id="assistant-message"
                onChange={(event) => onInputChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault();
                    if (input.trim() || attachment) event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Напишите сообщение…"
                ref={composer}
                rows={2}
                value={input}
              />
              <div className="assistant-composer-row">
                <label className="assistant-attach" title="Прикрепить изображение">
                  <Icon name="paperclip" />
                  <span className="assistant-sr-only">Прикрепить изображение</span>
                  <input
                    accept="image/jpeg,image/png,image/webp,image/gif"
                    className="assistant-sr-only"
                    disabled={pending}
                    onChange={onAttach}
                    type="file"
                  />
                </label>
                <button
                  aria-label="Отправить"
                  className="assistant-send"
                  disabled={pending || (!input.trim() && !attachment)}
                  title="Отправить"
                  type="submit"
                ><Icon name="arrow-up" /> <span>Отправить</span></button>
              </div>
            </form>
            {pending && !waitingForReply && <p className="assistant-composer-status" role="status">Выполняем запрос…</p>}
            <p id="assistant-composer-hint" className="assistant-composer-hint">
              Enter — отправить <span aria-hidden="true">·</span> Shift + Enter — новая строка
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
