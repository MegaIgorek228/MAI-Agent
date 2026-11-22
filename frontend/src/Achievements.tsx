import { FormEvent, useEffect, useState } from "react";

import {
  AchievementCategory,
  AchievementItem,
  AchievementLevel,
  Application,
  DocumentItem,
  createAchievement,
  getAchievements,
  getApplications,
  getDocuments,
  submitAchievement,
  updateAchievement,
  uploadDocument
} from "./api";
import { requestErrorMessage } from "./Documents";
import { Icon } from "./Icon";
import { WorkflowEmpty, WorkflowHeader, WorkflowNotice, WorkflowStatus } from "./WorkflowUI";

export const achievementCategory: Record<AchievementCategory, string> = {
  olympiad: "Олимпиада",
  sport: "Спортивное достижение",
  gto: "Готовность к труду и обороне (ГТО)",
  volunteering: "Волонтёрство",
  creative: "Творческое достижение",
  other: "Другое"
};

export const achievementLevel: Record<AchievementLevel, string> = {
  school: "Школьный",
  municipal: "Муниципальный",
  regional: "Региональный",
  national: "Всероссийский",
  international: "Международный"
};

export const achievementStatus: Record<AchievementItem["status"], string> = {
  draft: "Черновик",
  pending: "На проверке",
  confirmed: "Подтверждено",
  rejected: "Отклонено",
  needs_revision: "Требует исправления"
};

const statusTone: Record<AchievementItem["status"], string> = {
  draft: "uploaded",
  pending: "submitted",
  confirmed: "reviewed",
  rejected: "rejected",
  needs_revision: "needs_changes"
};

type FormState = {
  category: AchievementCategory;
  title: string;
  level: AchievementLevel | "";
  achieved_on: string;
  organization: string;
  description: string;
  applicationId: string;
  documentId: string;
  documentName: string;
};

const emptyForm: FormState = {
  category: "olympiad",
  title: "",
  level: "",
  achieved_on: "",
  organization: "",
  description: "",
  applicationId: "",
  documentId: "",
  documentName: ""
};

const formFromItem = (item: AchievementItem): FormState => ({
  category: item.category,
  title: item.title,
  level: item.level ?? "",
  achieved_on: item.achieved_on,
  organization: item.organization ?? "",
  description: item.description ?? "",
  applicationId: item.application_id ? String(item.application_id) : "",
  documentId: item.document?.id ? String(item.document.id) : "",
  documentName: item.document?.filename ?? ""
});

const dateLabel = (value: string | null) =>
  value ? new Date(value).toLocaleDateString("ru-RU") : "—";

export function Achievements({ token }: { token: string }) {
  const [items, setItems] = useState<AchievementItem[] | null>(null);
  const [applications, setApplications] = useState<Application[]>([]);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [form, setForm] = useState<FormState | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    getAchievements(token).then((list) => {
      if (!ignore) setItems(list);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить достижения"));
    });
    getApplications(token).then((list) => {
      if (!ignore) setApplications(list);
    }).catch(() => undefined);
    getDocuments(token).then((list) => {
      if (!ignore) setDocuments(list.filter((document) => document.document_type === "evidence"));
    }).catch(() => undefined);
    return () => { ignore = true; };
  }, [token]);

  const refresh = () => {
    getAchievements(token).then(setItems).catch((requestError) => {
      setError(requestErrorMessage(requestError, "Не удалось обновить достижения"));
    });
  };

  const openCreate = () => {
    setEditingId(null);
    setForm(emptyForm);
    setMessage("");
    setError("");
  };

  const openEdit = (item: AchievementItem) => {
    if (item.status !== "draft" && item.status !== "rejected" && item.status !== "needs_revision") return;
    setEditingId(item.id);
    setForm(formFromItem(item));
    setMessage("");
    setError("");
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!form || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    const values = {
      category: form.category,
      title: form.title.trim(),
      level: form.level || null,
      achieved_on: form.achieved_on,
      organization: form.organization.trim() || null,
      description: form.description.trim() || null,
      application_id: form.applicationId ? Number(form.applicationId) : null,
      document_id: form.documentId ? Number(form.documentId) : null
    };
    try {
      if (editingId === null) {
        const created = await createAchievement(token, values);
        setItems((current) => (current ?? []).concat(created));
        setMessage("Достижение сохранено в черновик. Проверьте сведения и отправьте его на проверку.");
      } else {
        const updated = await updateAchievement(token, editingId, values);
        setItems((current) => (current ?? []).map((item) => item.id === updated.id ? updated : item));
        setMessage("Сведения о достижении обновлены.");
      }
      setForm(null);
      setEditingId(null);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось сохранить достижение"));
    } finally {
      setBusy(false);
    }
  };

  const sendToReview = async (id: number) => {
    if (busy) return;
    if (!window.confirm("Отправить достижение на проверку сотруднику приёмной комиссии? После отправки его нельзя изменить до решения сотрудника.")) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await submitAchievement(token, id);
      setItems((current) => (current ?? []).map((item) => item.id === updated.id ? updated : item));
      setMessage("Достижение отправлено на проверку.");
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось отправить достижение"));
    } finally {
      setBusy(false);
    }
  };

  const attachFile = async (file: File) => {
    if (!form || uploading) return;
    setUploading(true);
    setError("");
    try {
      const uploaded = await uploadDocument(token, file, "evidence");
      setDocuments((current) => [uploaded, ...current]);
      setForm((current) => current && { ...current, documentId: String(uploaded.id), documentName: uploaded.filename });
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось загрузить документ"));
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="workflow">
      <WorkflowHeader level={1} title="Индивидуальные достижения"
        description="Олимпиады, спорт, ГТО, волонтёрство и творческие достижения. Подтверждённые сотрудником достижения учитываются при поступлении по правилам приёма.">
        <button type="button" onClick={openCreate} disabled={form !== null}><Icon name="plus" /> Добавить достижение</button>
      </WorkflowHeader>

      {message && <WorkflowNotice variant="success"><p>{message}</p></WorkflowNotice>}
      {error && <p className="error" role="alert">{error}</p>}

      {form && (
        <section className="workflow-panel workflow-editor" aria-labelledby="achievement-form-heading">
          <div className="workflow-panel-heading">
            <h3 id="achievement-form-heading">{editingId === null ? "Новое достижение" : `Изменить достижение №${editingId}`}</h3>
          </div>
          <form className="workflow-achievement-form" onSubmit={submit} onChange={() => setForm((current) => current && { ...current })}>
            <div className="form-columns">
              <label>
                Категория
                <select value={form.category} onChange={(event) => setForm((current) => current && { ...current, category: event.target.value as AchievementCategory })}>
                  {Object.entries(achievementCategory).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label>
                Название
                <input value={form.title} maxLength={255} placeholder="Например: Победитель городской олимпиады по физике"
                  onChange={(event) => setForm((current) => current && { ...current, title: event.target.value })} required />
              </label>
              <label>
                Уровень
                <select value={form.level} onChange={(event) => setForm((current) => current && { ...current, level: event.target.value as AchievementLevel | "" })}>
                  <option value="">Не указан</option>
                  {Object.entries(achievementLevel).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <label>
                Дата получения
                <input type="date" value={form.achieved_on} max={new Date().toISOString().slice(0, 10)}
                  onChange={(event) => setForm((current) => current && { ...current, achieved_on: event.target.value })} required />
              </label>
            </div>
            <div className="form-columns">
              <label>
                Организация
                <input value={form.organization} maxLength={255} placeholder="Школа, вуз, федерация и т. д."
                  onChange={(event) => setForm((current) => current && { ...current, organization: event.target.value })} />
              </label>
              <label>
                Связанное заявление
                <select value={form.applicationId} onChange={(event) => setForm((current) => current && { ...current, applicationId: event.target.value })}>
                  <option value="">Не привязано к заявлению</option>
                  {applications.map((application) => (
                    <option key={application.id} value={application.id}>
                      №{application.id} · {application.campaign_year} · {application.program}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label>
              Описание
              <textarea value={form.description} rows={3} maxLength={2000}
                placeholder="Сведения о достижении: место, состав команды, значимость и т. д."
                onChange={(event) => setForm((current) => current && { ...current, description: event.target.value })} />
            </label>
            <div>
              <h4>Подтверждающий документ</h4>
              <div className="form-columns">
                <label>
                  Документ из загруженных
                  <select value={form.documentId} onChange={(event) => setForm((current) => current && {
                    ...current,
                    documentId: event.target.value,
                    documentName: documents.find((document) => String(document.id) === event.target.value)?.filename ?? ""
                  })}>
                    <option value="">Без документа (нужен для отправки на проверку)</option>
                    {documents.map((document) => <option key={document.id} value={document.id}>{document.filename}</option>)}
                  </select>
                </label>
                <label>
                  Или загрузить файл
                  <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp,.doc,.docx" disabled={uploading}
                    onChange={(event) => { const file = event.target.files?.[0]; if (file) void attachFile(file); event.target.value = ""; }} />
                </label>
              </div>
              {form.documentName && <p className="workflow-muted">Прикреплён файл: {form.documentName}</p>}
              {uploading && <p role="status" className="workflow-muted">Загружаем файл…</p>}
            </div>
            <div className="workflow-actions">
              <button type="submit" disabled={busy}>{busy ? "Сохраняем…" : (editingId === null ? "Сохранить черновик" : "Сохранить изменения")}</button>
              <button className="workflow-secondary" type="button" disabled={busy} onClick={() => { setForm(null); setEditingId(null); }}>Отмена</button>
            </div>
          </form>
        </section>
      )}

      <section className="workflow-panel" aria-labelledby="achievement-list-heading">
        <div className="workflow-panel-heading">
          <h3 id="achievement-list-heading">Мои достижения</h3>
          {items && items.length > 0 && <span className="workflow-count">{items.length}</span>}
        </div>
        {items === null && <p role="status" className="workflow-muted">Загрузка достижений…</p>}
        {items !== null && items.length === 0 && (
          <WorkflowEmpty icon="file" title="Достижений пока нет"
            description="Добавьте первое достижение: заполните сведения, прикрепите подтверждающий документ и отправьте на проверку." />
        )}
        {items !== null && items.length > 0 && (
          <ul className="workflow-achievement-list">
            {items.map((item) => (
              <li key={item.id} className="workflow-achievement-card">
                <div className="workflow-achievement-card__head">
                  <span>№{item.id} · {item.title}</span>
                  <WorkflowStatus status={statusTone[item.status]}>{achievementStatus[item.status]}</WorkflowStatus>
                </div>
                <div className="workflow-achievement-card__meta">
                  <span>{achievementCategory[item.category]}</span>
                  {item.level && <span>{achievementLevel[item.level]}</span>}
                  <span>Получено: {dateLabel(item.achieved_on)}</span>
                  {item.organization && <span>{item.organization}</span>}
                  {item.application_id && <span>Заявление №{item.application_id}</span>}
                  {item.document && <span><Icon name="file" /> {item.document.filename}</span>}
                </div>
                {item.description && <p className="workflow-muted">{item.description}</p>}
                {(item.status === "confirmed" || item.status === "rejected" || item.status === "needs_revision") && (
                  <div className="workflow-achievement-card__comment">
                    <strong>Комментарий сотрудника</strong>
                    <p>{item.review_comment || "Без комментария"}</p>
                    <small>Решение от {dateLabel(item.reviewed_at)}</small>
                  </div>
                )}
                <div className="workflow-actions">
                  {(item.status === "draft" || item.status === "rejected" || item.status === "needs_revision") && (
                    <>
                      <button className="workflow-secondary" type="button" disabled={busy} onClick={() => openEdit(item)}>
                        Изменить
                      </button>
                      <button type="button" disabled={busy || !item.document} title={!item.document ? "Сначала приложите подтверждающий документ" : undefined}
                        onClick={() => sendToReview(item.id)}>
                        {item.status === "draft" ? "Отправить на проверку" : "Повторно подать на проверку"}
                      </button>
                    </>
                  )}
                  {item.status === "pending" && <span className="workflow-muted">Ожидаем решение сотрудника приёмной комиссии.</span>}
                  {item.status === "confirmed" && <span className="workflow-muted">Достижение подтверждено и учитывается по правилам приёма.</span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
