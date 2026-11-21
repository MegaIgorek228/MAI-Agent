import { FormEvent, useEffect, useState } from "react";

import {
  Applicant,
  Application,
  ApplicationStatus,
  downloadApplicationDocument,
  getStaffApplicants,
  getStaffApplication,
  getStaffApplications,
  publishAdmissionRule,
  reviewApplication,
  reviewApplicationDocument,
  StaffApplication
} from "./api";
import { ApplicationHistory, applicationStatus, Requirements, Verification } from "./Admissions";
import { documentStatusLabel, requestErrorMessage } from "./Documents";
import { Icon } from "./Icon";
import { WorkflowEmpty, WorkflowHeader, WorkflowNotice, WorkflowStatus } from "./WorkflowUI";

const pageSize = 20;

const nextStatuses: Partial<Record<ApplicationStatus, ApplicationStatus[]>> = {
  submitted: ["under_review", "needs_changes"],
  under_review: ["needs_changes", "reviewed"]
};

export function StaffApplications({ token }: { token: string }) {
  const [mode, setMode] = useState<"applications" | "applicants" | "rules">("applications");
  const [applications, setApplications] = useState<Application[]>([]);
  const [filters, setFilters] = useState({ query: "", status: "", offset: 0 });
  const [selected, setSelected] = useState<number | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (mode !== "applications") return;
    let ignore = false;
    const search = new URLSearchParams({ limit: String(pageSize), offset: String(filters.offset) });
    if (filters.query) search.set("q", filters.query);
    if (filters.status) search.set("status", filters.status);
    setPending(true);
    setError("");
    getStaffApplications(token, search).then((items) => {
      if (!ignore) setApplications(items);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить очередь заявлений"));
    }).finally(() => {
      if (!ignore) setPending(false);
    });
    return () => { ignore = true; };
  }, [token, filters, mode]);

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setFilters({ query: String(values.get("query") ?? "").trim(), status: String(values.get("status") ?? ""), offset: 0 });
    setSelected(null);
  };

  const onUpdate = (application: Application) => {
    setApplications((current) => current.map((item) => item.id === application.id ? application : item));
  };

  return (
    <div className="workflow">
      <WorkflowHeader title="Рабочее место сотрудника" description="Проверяйте заявления и документы и публикуйте правила приёма." />
      <div className="workflow-tabs" role="group" aria-label="Раздел рабочего места">
        <button type="button" aria-pressed={mode === "applications"} onClick={() => setMode("applications")}><Icon name="folder" /> Заявления</button>
        <button type="button" aria-pressed={mode === "applicants"} onClick={() => setMode("applicants")}><Icon name="user" /> Абитуриенты</button>
        <button type="button" aria-pressed={mode === "rules"} onClick={() => setMode("rules")}><Icon name="book" /> Правила приёма</button>
      </div>
      {mode === "rules" && <AdmissionRuleEditor token={token} />}
      {mode === "applicants" && <StaffApplicantList token={token} onOpen={(applicant) => {
        setFilters({ query: applicant.email, status: "", offset: 0 });
        setSelected(null);
        setMode("applications");
      }} />}
      {mode === "applications" && (
        <>
          <section className="workflow-panel workflow-queue" aria-labelledby="queue-heading">
            <div className="workflow-panel-heading">
              <h3 id="queue-heading">Очередь заявлений</h3>
            </div>
            <form className="workflow-queue-filter" onSubmit={applyFilters}>
              <label>
                Поиск заявлений
                <input name="query" defaultValue={filters.query} placeholder="Email или направление" />
              </label>
              <label>
                Статус
                <select name="status" defaultValue={filters.status}>
                  <option value="">Все статусы</option>
                  {Object.entries(applicationStatus).filter(([value]) => value !== "draft")
                    .map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select>
              </label>
              <button type="submit" disabled={pending}><Icon name="search" /> Найти</button>
            </form>
            {pending && <p role="status" className="workflow-muted">Загрузка заявлений…</p>}
            {error && <p className="error" role="alert">{error}</p>}
            {!pending && !error && applications.length === 0 && (
              <WorkflowEmpty title="Заявлений по этим условиям нет" description="Измените параметры поиска, чтобы увидеть другие заявления." icon="search" />
            )}
            {applications.length > 0 && (
              <ul className="workflow-list workflow-queue-list">
                {applications.map((item) => (
                  <li key={item.id}>
                    <button className="workflow-queue-row" type="button" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>
                      <span className="workflow-mark"><Icon name="file" /></span>
                      <span className="workflow-row-main">
                        <span>№{item.id} · {item.program}</span>
                        <small>{item.campaign_year} · {item.admission_basis}</small>
                      </span>
                      <WorkflowStatus status={item.status}>{applicationStatus[item.status]}</WorkflowStatus>
                      <Icon name="chevron-right" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {(filters.offset > 0 || applications.length === pageSize) && (
              <div className="workflow-actions">
                <button className="workflow-secondary" type="button" disabled={pending || filters.offset === 0} onClick={() => {
                  setSelected(null);
                  setFilters((current) => ({ ...current, offset: current.offset - pageSize }));
                }}>Предыдущая страница</button>
                <button className="workflow-secondary" type="button" disabled={pending || applications.length < pageSize} onClick={() => {
                  setSelected(null);
                  setFilters((current) => ({ ...current, offset: current.offset + pageSize }));
                }}>Следующая страница</button>
              </div>
            )}
          </section>
          {selected !== null && <StaffApplicationDetail key={selected} token={token} id={selected} onUpdate={onUpdate} />}
        </>
      )}
    </div>
  );
}

function StaffApplicantList({ token, onOpen }: { token: string; onOpen: (applicant: Applicant) => void }) {
  const [applicants, setApplicants] = useState<Applicant[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    getStaffApplicants(token).then((list) => {
      if (!ignore) setApplicants(list);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить список абитуриентов"));
    });
    return () => { ignore = true; };
  }, [token]);

  return (
    <section className="workflow-panel" aria-labelledby="applicants-heading">
      <div className="workflow-panel-heading">
        <h3 id="applicants-heading">Абитуриенты</h3>
        {Boolean(applicants?.length) && <span className="workflow-count">{applicants?.length}</span>}
      </div>
      {error ? <p role="alert" className="error">{error}</p> : !applicants ? (
        <p role="status" className="workflow-muted">Загрузка абитуриентов…</p>
      ) : applicants.length === 0 ? (
        <WorkflowEmpty title="Абитуриентов пока нет" />
      ) : (
        <ul className="workflow-list workflow-queue-list">
          {applicants.map((applicant) => (
            <li key={applicant.id}>
              <button className="workflow-queue-row" type="button" onClick={() => onOpen(applicant)}>
                <span className="workflow-mark"><Icon name="user" /></span>
                <span className="workflow-row-main">
                  <span>{applicant.email}</span>
                  {!applicant.is_active && <small>Учётная запись неактивна</small>}
                </span>
                <Icon name="chevron-right" />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function StaffApplicationDetail({ token, id, onUpdate }: {
  token: string;
  id: number;
  onUpdate: (application: Application) => void;
}) {
  const [detail, setDetail] = useState<StaffApplication | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    getStaffApplication(token, id).then((data) => {
      if (!ignore) setDetail(data);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить заявление"));
    }).finally(() => {
      if (!ignore) setPending(false);
    });
    return () => { ignore = true; };
  }, [token, id]);

  const run = async (task: () => Promise<void>) => {
    setError("");
    setPending(true);
    try {
      await task();
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось выполнить действие по заявлению"));
    } finally {
      setPending(false);
    }
  };

  const setStatus = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    return run(async () => {
      const changed = await reviewApplication(
        token,
        id,
        String(form.get("status")) as ApplicationStatus,
        String(form.get("note") ?? "").trim()
      );
      onUpdate(changed);
      setDetail(await getStaffApplication(token, id));
    });
  };

  const setDocumentStatus = (event: FormEvent<HTMLFormElement>, documentId: number) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const status = form.get("status") === "rejected" ? "rejected" : "accepted";
    return run(async () => {
      const updated = await reviewApplicationDocument(token, id, documentId, status, String(form.get("note") ?? "").trim());
      setDetail((current) => current ? {
        ...current,
        documents: current.documents.map((document) => document.id === documentId ? updated : document)
      } : current);
      setDetail(await getStaffApplication(token, id));
    });
  };

  const download = (documentId: number, filename: string) => run(async () => {
    const file = await downloadApplicationDocument(token, id, documentId);
    const url = URL.createObjectURL(file);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  if (!detail) return <p className={error ? "error" : undefined} role={error ? "alert" : "status"}>{error || "Загрузка заявления…"}</p>;

  const { application, applicant, documents, ege, requirements } = detail;
  const statuses = nextStatuses[application.status] ?? [];

  return (
    <section className="workflow-panel workflow-editor">
      <div className="workflow-panel-heading">
        <div>
          <h3>Заявление №{application.id}</h3>
          <p className="workflow-muted">{applicant.email} · {application.campaign_year} · {application.program} · {application.admission_basis}</p>
        </div>
        <WorkflowStatus status={application.status}>{applicationStatus[application.status]}</WorkflowStatus>
      </div>
      {application.review_note && <p className="notice">{application.review_note}</p>}
      {pending && <p role="status">Запрос выполняется…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <Requirements result={requirements} />
      <section className="workflow-subsection">
        <h4>Заявленные результаты ЕГЭ</h4>
        {ege.scores.length > 0
          ? <dl className="workflow-staff-scores">{ege.scores.map((score) => (
            <div key={`${score.subject}-${score.year}`}>
              <dt>{score.subject} <small>{score.year}</small></dt>
              <dd>{score.score}</dd>
            </div>
          ))}</dl>
          : <p className="workflow-muted">Баллы ещё не введены.</p>}
        <Verification verification={ege.verification} />
      </section>
      <section className="workflow-subsection">
        <h4>Документы заявления</h4>
        {documents.length === 0 && <p className="workflow-muted">К заявлению не приложены документы.</p>}
        {documents.map((document) => (
          <article className="workflow-document-review" key={document.id}>
            <div className="workflow-file-name">
              <span className="workflow-mark"><Icon name="file" /></span>
              <div>
                <h5>{document.filename}</h5>
                <small>{document.document_type ?? "Тип не указан"}</small>
              </div>
              <WorkflowStatus status={document.status}>{documentStatusLabel(document.status)}</WorkflowStatus>
            </div>
            {document.review_message && <p className="workflow-muted">{document.review_message}</p>}
            <div className="workflow-actions">
              <button className="workflow-secondary" type="button" disabled={pending} onClick={() => download(document.id, document.filename)}>Скачать файл</button>
            </div>
            {document.extracted_text && <details className="workflow-disclosure"><summary>Извлечённый текст</summary><pre>{document.extracted_text}</pre></details>}
            {application.status === "under_review" && (
              <form onSubmit={(event) => setDocumentStatus(event, document.id)}>
                <div className="form-columns">
                  <label>
                    Результат проверки
                    <select name="status" defaultValue={document.status === "rejected" ? "rejected" : "accepted"}>
                      <option value="accepted">Принять файл</option>
                      <option value="rejected">Отклонить файл</option>
                    </select>
                  </label>
                  <label>
                    Комментарий к документу
                    <input name="note" maxLength={2000} defaultValue={document.review_message ?? ""} />
                  </label>
                </div>
                <div className="workflow-actions"><button type="submit" disabled={pending}>Сохранить проверку</button></div>
              </form>
            )}
          </article>
        ))}
      </section>
      {statuses.length > 0 && (
        <form onSubmit={setStatus} key={application.status} className="workflow-subsection">
          <div className="form-columns">
            <label>
              Новый статус заявления
              <select name="status">
                {statuses.map((status) => <option value={status} key={status}>{applicationStatus[status]}</option>)}
              </select>
            </label>
            <label>
              Комментарий к заявлению
              <input name="note" maxLength={2000} defaultValue={application.review_note ?? ""} />
            </label>
          </div>
          <div className="workflow-actions"><button type="submit" disabled={pending}>Сохранить статус</button></div>
        </form>
      )}
      {detail.history.length > 0 && (
        <details className="workflow-disclosure"><summary>История заявления</summary><ApplicationHistory events={detail.history} /></details>
      )}
    </section>
  );
}

function AdmissionRuleEditor({ token }: { token: string }) {
  const [documents, setDocuments] = useState<number[]>([]);
  const [subjects, setSubjects] = useState<number[]>([]);
  const [nextKey, setNextKey] = useState(1);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const publish = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const field = (name: string) => String(form.get(name) ?? "").trim();
    setError("");
    setMessage("");
    setPending(true);
    try {
      const entries = subjects.map((key) => [field(`subject-${key}`), Number(field(`minimum-${key}`))] as const);
      const normalizedSubjects = entries.map(([subject]) => subject.toLowerCase().replace(/\s+/g, " "));
      if (new Set(normalizedSubjects).size !== entries.length) throw new Error("Каждый предмет указывается один раз.");
      const rule = await publishAdmissionRule(token, {
        campaign_year: Number(field("year")),
        program: field("program"),
        admission_basis: field("basis"),
        source_url: field("source") || null,
        document_requirements: documents.map((key) => ({
          document_type: field(`type-${key}`),
          title: field(`title-${key}`)
        })),
        subject_minima: Object.fromEntries(entries)
      });
      setMessage(`Опубликована редакция №${rule.revision} для направления «${rule.program}».`);
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось опубликовать правила"));
    } finally {
      setPending(false);
    }
  };

  return (
    <section className="workflow-panel workflow-editor">
      <div className="workflow-panel-heading"><h3>Новая редакция правил приёма</h3></div>
      <form onSubmit={publish}>
        <fieldset disabled={pending}>
          <legend>Область применения</legend>
          <div className="form-columns">
            <label>Год приёма <input type="number" name="year" min={2000} max={2100} defaultValue={new Date().getFullYear()} required /></label>
            <label>Направление <input name="program" maxLength={255} required /></label>
            <label>Основание поступления <input name="basis" maxLength={100} required /></label>
          </div>
          <label>URL источника <input type="url" name="source" placeholder="https://priem.mai.ru/…" /></label>
        </fieldset>
        <fieldset disabled={pending}>
          <legend>Обязательные документы</legend>
          {documents.map((key) => (
            <div className="form-columns" key={key}>
              <label>Тип документа <input name={`type-${key}`} maxLength={100} required /></label>
              <label>Название <input name={`title-${key}`} maxLength={255} required /></label>
              <button className="workflow-secondary" type="button" onClick={() => setDocuments((current) => current.filter((item) => item !== key))}>Удалить</button>
            </div>
          ))}
          <div className="workflow-actions"><button className="workflow-secondary" type="button" onClick={() => {
            setDocuments((current) => [...current, nextKey]);
            setNextKey((current) => current + 1);
          }}>Добавить документ</button></div>
        </fieldset>
        <fieldset disabled={pending}>
          <legend>Минимальные баллы</legend>
          {subjects.map((key) => (
            <div className="form-columns" key={key}>
              <label>Предмет <input name={`subject-${key}`} maxLength={100} required /></label>
              <label>Балл <input type="number" name={`minimum-${key}`} min={0} max={100} required /></label>
              <button className="workflow-secondary" type="button" onClick={() => setSubjects((current) => current.filter((item) => item !== key))}>Удалить</button>
            </div>
          ))}
          <div className="workflow-actions"><button className="workflow-secondary" type="button" onClick={() => {
            setSubjects((current) => [...current, nextKey]);
            setNextKey((current) => current + 1);
          }}>Добавить предмет</button></div>
        </fieldset>
        <div className="workflow-actions"><button type="submit" disabled={pending}>Опубликовать редакцию</button></div>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <WorkflowNotice variant="success"><p>{message}</p></WorkflowNotice>}
    </section>
  );
}
