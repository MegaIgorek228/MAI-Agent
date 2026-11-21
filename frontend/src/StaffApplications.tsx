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
    <div className="view-stack">
      <h2>Рабочее место сотрудника</h2>
      <div className="actions">
        <button type="button" aria-pressed={mode === "applications"} onClick={() => setMode("applications")}>Заявления</button>
        <button type="button" aria-pressed={mode === "applicants"} onClick={() => setMode("applicants")}>Абитуриенты</button>
        <button type="button" aria-pressed={mode === "rules"} onClick={() => setMode("rules")}>Правила приёма</button>
      </div>
      {mode === "rules" && <AdmissionRuleEditor token={token} />}
      {mode === "applicants" && <StaffApplicantList token={token} onOpen={(applicant) => {
        setFilters({ query: applicant.email, status: "", offset: 0 });
        setSelected(null);
        setMode("applications");
      }} />}
      {mode === "applications" && (
        <>
          <form onSubmit={applyFilters}>
            <div className="form-columns">
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
            </div>
            <div className="actions"><button type="submit" disabled={pending}>Найти</button></div>
          </form>
          {pending && <p role="status">Загрузка заявлений…</p>}
          {error && <p className="error" role="alert">{error}</p>}
          {!pending && !error && applications.length === 0 && <p>Заявлений по этим условиям нет.</p>}
          {applications.length > 0 && (
            <ul className="application-list">
              {applications.map((item) => (
                <li key={item.id}>
                  <button type="button" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>
                    №{item.id} · {item.program} · {applicationStatus[item.status]}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {(filters.offset > 0 || applications.length === pageSize) && (
            <div className="actions">
              <button type="button" disabled={pending || filters.offset === 0} onClick={() => {
                setSelected(null);
                setFilters((current) => ({ ...current, offset: current.offset - pageSize }));
              }}>Предыдущая страница</button>
              <button type="button" disabled={pending || applications.length < pageSize} onClick={() => {
                setSelected(null);
                setFilters((current) => ({ ...current, offset: current.offset + pageSize }));
              }}>Следующая страница</button>
            </div>
          )}
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

  if (error) return <p role="alert" className="error">{error}</p>;
  if (!applicants) return <p role="status">Загрузка абитуриентов…</p>;
  if (applicants.length === 0) return <p>Абитуриентов пока нет.</p>;
  return (
    <ul className="application-list">
      {applicants.map((applicant) => (
        <li key={applicant.id}>
          <button type="button" onClick={() => onOpen(applicant)}>{applicant.email}</button>
          {!applicant.is_active && <small>Учётная запись неактивна.</small>}
        </li>
      ))}
    </ul>
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
    <section className="record view-stack">
      <h3>Заявление №{application.id}</h3>
      <p>{applicant.email} · {application.campaign_year} · {application.program} · {application.admission_basis}</p>
      <p><strong>{applicationStatus[application.status]}</strong></p>
      {application.review_note && <p className="notice">{application.review_note}</p>}
      {pending && <p role="status">Запрос выполняется…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <Requirements result={requirements} />
      <h3>Заявленные результаты ЕГЭ</h3>
      {ege.scores.length > 0
        ? <ul>{ege.scores.map((score) => <li key={`${score.subject}-${score.year}`}>{score.subject} · {score.year} · {score.score}</li>)}</ul>
        : <p>Баллы ещё не введены.</p>}
      <Verification verification={ege.verification} />
      <h3>Документы заявления</h3>
      {documents.length === 0 && <p>К заявлению не приложены документы.</p>}
      {documents.map((document) => (
        <article className="record view-stack" key={document.id}>
          <h4>{document.filename}</h4>
          <p>{document.document_type ?? "Тип не указан"} · {documentStatusLabel(document.status)}</p>
          {document.review_message && <p>{document.review_message}</p>}
          <div className="actions">
            <button type="button" disabled={pending} onClick={() => download(document.id, document.filename)}>Скачать файл</button>
          </div>
          {document.extracted_text && <details><summary>Извлечённый текст</summary><pre>{document.extracted_text}</pre></details>}
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
              <div className="actions"><button type="submit" disabled={pending}>Сохранить проверку</button></div>
            </form>
          )}
        </article>
      ))}
      {statuses.length > 0 && (
        <form onSubmit={setStatus} key={application.status}>
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
          <div className="actions"><button type="submit" disabled={pending}>Сохранить статус</button></div>
        </form>
      )}
      {detail.history.length > 0 && (
        <details><summary>История заявления</summary><ApplicationHistory events={detail.history} /></details>
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
    <section className="record view-stack">
      <h3>Новая редакция правил приёма</h3>
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
              <button type="button" onClick={() => setDocuments((current) => current.filter((item) => item !== key))}>Удалить</button>
            </div>
          ))}
          <div className="actions"><button type="button" onClick={() => {
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
              <button type="button" onClick={() => setSubjects((current) => current.filter((item) => item !== key))}>Удалить</button>
            </div>
          ))}
          <div className="actions"><button type="button" onClick={() => {
            setSubjects((current) => [...current, nextKey]);
            setNextKey((current) => current + 1);
          }}>Добавить предмет</button></div>
        </fieldset>
        <div className="actions"><button type="submit" disabled={pending}>Опубликовать редакцию</button></div>
      </form>
      {error && <p className="error" role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
