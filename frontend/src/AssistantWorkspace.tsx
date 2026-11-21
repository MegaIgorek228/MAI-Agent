import { type ChangeEvent, type FormEvent, useEffect, useRef, useState } from "react";

import { type ChatMessage, type ChatSession, documentFileUrl } from "./api";
import { Icon } from "./Icon";
import "./assistant.css";

type AssistantWorkspaceProps = {
  token: string;
  sessionId: number | null;
  sessions: ChatSession[];
  messages: ChatMessage[];
  input: string;
  pending: boolean;
  historyLoading: boolean;
  attachment: { name: string; previewUrl: string } | null;
  onInputChange: (value: string) => void;
  onOpenSession: (id: number) => void;
  onStartSession: () => void;
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

const messageTimeFormat = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit"
});

function formatDate(date: string | undefined, formatter: Intl.DateTimeFormat) {
  if (!date) return "";
  const parsed = new Date(date);
  return Number.isNaN(parsed.getTime()) ? "" : formatter.format(parsed);
}

function MessageText({ content }: { content: string }) {
  return content.split(/(https?:\/\/[^\s<>{}\[\]"']+)/g).map((part, index) => {
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
  token,
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
  onRefreshHistory,
  onSend,
  onAttach,
  onRemoveAttachment
}: AssistantWorkspaceProps) {
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const log = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const waitingForReply = pending && messages.at(-1)?.role === "user";

  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [sessionId, messages, waitingForReply]);

  return (
    <section className="assistant-workspace" aria-labelledby="assistant-title">
      <h1 id="assistant-title">Чат с помощником</h1>
      <div className="assistant-layout">
        <aside className="assistant-history" aria-label="История диалогов">
          <div className="assistant-history-mobile">
            <button
              aria-controls="assistant-history-content"
              aria-expanded={mobileHistoryOpen}
              className="assistant-history-toggle"
              onClick={() => setMobileHistoryOpen((open) => !open)}
              type="button"
            >
              <Icon name="clock" />
              История диалогов
              <Icon name="chevron-down" />
            </button>
            <button
              aria-label="Начать диалог"
              className="assistant-icon-button"
              disabled={pending}
              onClick={() => {
                onStartSession();
                setMobileHistoryOpen(false);
              }}
              title="Начать диалог"
              type="button"
            ><Icon name="plus" /></button>
          </div>

          <div
            className={mobileHistoryOpen ? "assistant-history-content is-open" : "assistant-history-content"}
            id="assistant-history-content"
            aria-busy={historyLoading}
          >
            <div className="assistant-history-heading">
              <h2>История диалогов</h2>
              <button
                aria-label="Обновить список диалогов"
                className="assistant-icon-button"
                disabled={historyLoading || pending}
                onClick={onRefreshHistory}
                title="Обновить список диалогов"
                type="button"
              ><Icon name="refresh" /></button>
            </div>
            <button
              className="assistant-new-chat"
              disabled={pending}
              onClick={() => {
                onStartSession();
                setMobileHistoryOpen(false);
              }}
              type="button"
            ><Icon name="plus" /> Начать диалог</button>

            {!sessions.length && (
              <p className="assistant-history-empty" role={historyLoading ? "status" : undefined}>
                {historyLoading ? "Загружаем историю…" : "Начатые диалоги появятся здесь."}
              </p>
            )}
            {!!sessions.length && (
              <ul className="assistant-session-list">
                {sessions.map((session) => {
                  const date = formatDate(session.created_at, sessionDateFormat);
                  return (
                    <li key={session.id}>
                      <button
                        aria-current={session.id === sessionId ? "true" : undefined}
                        className="assistant-session"
                        disabled={pending}
                        onClick={() => {
                          onOpenSession(session.id);
                          setMobileHistoryOpen(false);
                        }}
                        type="button"
                      >
                        <span className="assistant-session-icon">
                          <Icon name={session.channel === "telegram" ? "telegram" : "chat"} />
                        </span>
                        <span>
                          <strong>Диалог №{session.id}</strong>
                          <small>
                            {session.channel === "telegram" ? "Telegram" : "Веб"}
                            {date && <><span aria-hidden="true"> · </span><time dateTime={session.created_at}>{date}</time></>}
                          </small>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </aside>

        <div className="assistant-panel">
          <header className="assistant-panel-header">
            <span className="assistant-avatar assistant-avatar-header"><Icon name="spark" /></span>
            <div>
              <h2>Помощник МАИ</h2>
              <p>{sessionId ? `Диалог №${sessionId}` : "Новый диалог"}</p>
            </div>
          </header>

          {messages.length > 0 ? (
            <div ref={log} className="assistant-log" role="log" aria-label="Сообщения диалога" tabIndex={0}>
              {messages.map((message, index) => {
                const isUser = message.role === "user";
                const time = formatDate(message.created_at, messageTimeFormat);
                return (
                  <article className={isUser ? "assistant-message from-user" : "assistant-message"} key={index}>
                    <span className="assistant-avatar" aria-hidden="true"><Icon name={isUser ? "user" : "spark"} /></span>
                    <div className="assistant-message-content">
                      <header>
                        <strong>{isUser ? "Вы" : "Помощник МАИ"}</strong>
                        {time && <time dateTime={message.created_at}>{time}</time>}
                      </header>
                      <div className="assistant-bubble">
                        {message.image_document_id && (
                          <img
                            alt={message.image_filename || "Прикреплённое изображение"}
                            className="assistant-message-image"
                            loading="lazy"
                            src={documentFileUrl(token, message.image_document_id)}
                          />
                        )}
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
          ) : (
            <div className="assistant-welcome">
              <div className="assistant-welcome-copy">
                <span className="assistant-welcome-mark"><Icon name="spark" /></span>
                <h2>Чем помочь?</h2>
                <p>Задайте вопрос о поступлении в МАИ.</p>
              </div>
              <div className="assistant-suggestions" aria-label="Примеры вопросов">
                {suggestions.map(({ icon, text }) => (
                  <button
                    className="assistant-suggestion"
                    disabled={pending}
                    key={text}
                    onClick={() => {
                      onInputChange(text);
                      composer.current?.focus();
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
          )}

          <div className="assistant-composer-area">
            <form className="assistant-composer" onSubmit={onSend}>
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
                <button
                  aria-label="Отправить"
                  className="assistant-send"
                  disabled={pending || (!input.trim() && !attachment)}
                  title="Отправить"
                  type="submit"
                ><Icon name="arrow-up" /></button>
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
