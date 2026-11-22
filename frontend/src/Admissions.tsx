import { FormEvent, useEffect, useState } from "react";

import {
  AdmissionRule,
  Application,
  ApplicationEvent,
  ApplicationRequirements,
  ApplicationStatus,
  DocumentItem,
  ExamScores,
  getAdmissionRules,
  getApplicationDocuments,
  getApplicationEvents,
  getApplicationRequirements,
  getApplications,
  getExamScores,
  Profile,
  refreshExamScores,
  saveApplication,
  saveExamScores,
  submitApplication,
  verifyExamScores
} from "./api";
import { CompletenessResult, documentStatusLabel, documentTypeLabel, requestErrorMessage } from "./Documents";
import { Icon } from "./Icon";
import { WorkflowEmpty, WorkflowHeader, WorkflowNotice, WorkflowStatus } from "./WorkflowUI";

export const applicationStatus: Record<ApplicationStatus, string> = {
  draft: "Черновик",
  submitted: "Отправлено",
  under_review: "На проверке",
  needs_changes: "Требуются изменения",
  reviewed: "Проверено"
};

export function ApplicationHistory({ events }: { events: ApplicationEvent[] }) {
  if (events.length === 0) return <p className="workflow-muted">Изменений статуса пока нет.</p>;
  const eventLabel = (status: string) =>
    (applicationStatus as Record<string, string>)[status]
    ?? (status === "document_reviewed" ? "Решение по документу" : status);
  return (
    <ol className="workflow-timeline">
      {events.map((event) => (
        <li key={event.id}>
          <span className="workflow-timeline-dot" />
          <div>
            <strong>{eventLabel(event.status)}</strong>
            <time dateTime={event.created_at}>
              {new Date(event.created_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}
            </time>
            {event.note && <p>{event.note}</p>}
          </div>
        </li>
      ))}
    </ol>
  );
}

const requirementResult: Record<string, string> = {
  needs_admission_requirements: "Для заявления ещё нет правил проверки предметов и баллов.",
  not_required: "Для выбранных условий требования к результатам ЕГЭ не заданы.",
  incomplete: "Для проверки не хватает результатов по обязательным предметам.",
  below_minimum: "Часть результатов ниже установленного минимума.",
  meets_minimum: "Введённые баллы удовлетворяют минимальным требованиям."
};

const verificationResult: Record<string, string> = {
  match: "Введённые баллы совпали с тестовой записью.",
  mismatch: "Введённые баллы отличаются от тестовой записи.",
  not_found: "Запись в тестовом реестре не найдена.",
  incomplete: "Для синтетической сверки не хватает данных."
};

export function Requirements({ result }: { result: ApplicationRequirements }) {
  return (
    <div className="workflow-requirements">
      <div>
        <h4>Комплект документов</h4>
        <CompletenessResult result={result.documents} />
      </div>
      <div>
        <h4>Предметы и минимальные баллы</h4>
        <WorkflowNotice variant={result.ege.status === "meets_minimum" ? "success" : "info"}>
          <p>{requirementResult[result.ege.status] ?? result.ege.status}</p>
          {result.ege.missing_subjects.length > 0 && <p>Нужны результаты по предметам {result.ege.missing_subjects.join(", ")}.</p>}
          {result.ege.below_minimum.length > 0 && (
            <ul>{result.ege.below_minimum.map(({ subject, score, minimum }) => (
              <li key={subject}>{subject} · {score} баллов при минимуме {minimum}.</li>
            ))}</ul>
          )}
        </WorkflowNotice>
      </div>
      {result.rules && (
        <p className="workflow-muted workflow-rule-reference">
          Редакция правил №{result.rules.revision}
          {result.rules.source_url && <> · <a href={result.rules.source_url}>Источник правил</a></>}
        </p>
      )}
    </div>
  );
}

export function Verification({ verification }: { verification: ExamScores["verification"] }) {
  if (!verification) return null;
  return (
    <WorkflowNotice variant={verification.status === "match" ? "success" : "info"}>
      <strong>Синтетическая сверка</strong>
      <p>{verificationResult[verification.status] ?? verification.status}</p>
      {verification.missing_subjects.length > 0 && (
        <p>В тестовом реестре не найдены предметы {verification.missing_subjects.join(", ")}.</p>
      )}
      {verification.mismatched_subjects.length > 0 && (
        <p>Баллы различаются по предметам {verification.mismatched_subjects.join(", ")}.</p>
      )}
    </WorkflowNotice>
  );
}

export function ApplicantApplications({ token, documents, profile }: {
  token: string;
  documents: DocumentItem[];
  profile: Profile | null;
}) {
  const [applications, setApplications] = useState<Application[]>([]);
  const [rules, setRules] = useState<AdmissionRule[]>([]);
  const [selection, setSelection] = useState<number | "new" | null>(null);
  const [pending, setPending] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    Promise.allSettled([getApplications(token), getAdmissionRules(token)]).then(([list, admissionRules]) => {
      if (ignore) return;
      if (list.status === "fulfilled") setApplications(list.value);
      if (admissionRules.status === "fulfilled") setRules(admissionRules.value);
      if (list.status === "rejected") {
        setError(requestErrorMessage(list.reason, "Не удалось загрузить заявления"));
      } else if (admissionRules.status === "rejected") {
        setError(requestErrorMessage(admissionRules.reason, "Не удалось загрузить правила приёма"));
      }
      setPending(false);
    });
    return () => { ignore = true; };
  }, [token]);

  const active = applications.find(({ id }) => id === selection);

  const onSaved = (application: Application) => {
    setApplications((current) => current.some(({ id }) => id === application.id)
      ? current.map((item) => item.id === application.id ? application : item)
      : [application, ...current]);
    setSelection(application.id);
  };

  return (
    <div className="workflow">
      <WorkflowHeader level={1} title="Заявления" description="Создавайте заявления, прикладывайте документы и следите за проверкой.">
        <button type="button" onClick={() => setSelection("new")}><Icon name="plus" /> Новое заявление</button>
      </WorkflowHeader>
      {error && <p role="alert" className="error">{error}</p>}
      {pending && <p role="status" className="workflow-muted">Загрузка заявлений…</p>}
      <div className={`workflow-application-grid${applications.length ? " workflow-application-grid--split" : ""}`}>
        {applications.length > 0 && (
          <aside className="workflow-panel workflow-application-index">
            <div className="workflow-panel-heading">
              <span className="workflow-mark"><Icon name="folder" /></span>
              <h3>Мои заявления</h3>
              <span className="workflow-count">{applications.length}</span>
            </div>
            <label>
              <span className="workflow-visually-hidden">Ваши заявления</span>
              <select value={typeof selection === "number" ? selection : ""} onChange={(event) => setSelection(Number(event.target.value))}>
                <option value="" disabled>Выберите заявление</option>
                {applications.map((item) => (
                  <option key={item.id} value={item.id}>
                    №{item.id} · {item.program} · {applicationStatus[item.status]}
                  </option>
                ))}
              </select>
            </label>
            {active && (
              <div className="workflow-index-summary">
                <strong>{active.program}</strong>
                <small>{active.campaign_year} · {active.admission_basis}</small>
                <WorkflowStatus status={active.status}>{applicationStatus[active.status]}</WorkflowStatus>
              </div>
            )}
          </aside>
        )}
        <div className="workflow-application-details">
          {selection === "new" && <ApplicationEditor key="new" token={token} profile={profile} documents={documents} rules={rules} onSaved={onSaved} />}
          {active && <ApplicationEditor key={active.id} token={token} application={active} profile={profile} documents={documents} rules={rules} onSaved={onSaved} />}
          {!active && selection !== "new" && !pending && !error && (
            <section className="workflow-panel">
              {applications.length ? (
                <WorkflowEmpty title="Выберите заявление" description="Откройте его, чтобы увидеть документы, баллы и текущий статус." icon="folder" />
              ) : (
                <WorkflowEmpty title="У вас пока нет заявлений" description="Создайте заявление, чтобы выбрать направление и приложить документы." icon="folder" />
              )}
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

type ApplicationEditorProps = {
  token: string;
  documents: DocumentItem[];
  profile: Profile | null;
  application?: Application;
  rules: AdmissionRule[];
  onSaved: (value: Application) => void;
};

function ApplicationEditor({ token, documents, profile, application, rules, onSaved }: ApplicationEditorProps) {
  const canEdit = !application || application.status === "draft" || application.status === "needs_changes";
  const [program, setProgram] = useState(application?.program ?? profile?.target_program ?? "");
  const [basis, setBasis] = useState(application?.admission_basis ?? profile?.admission_basis ?? "");
  const [year, setYear] = useState(application?.campaign_year ?? new Date().getFullYear());
  const [documentIds, setDocumentIds] = useState(application?.document_ids ?? []);
  const [requirements, setRequirements] = useState<ApplicationRequirements | null>(null);
  const [history, setHistory] = useState<ApplicationEvent[] | null>(null);
  const [attachedDocuments, setAttachedDocuments] = useState<DocumentItem[]>([]);
  const [pending, setPending] = useState(false);
  const [dirty, setDirty] = useState(!application);
  const [scoresDirty, setScoresDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const applicationId = application?.id;
  const typeTitles: Record<string, string> = Object.fromEntries(
    rules.flatMap((rule) => rule.document_requirements.map((item) => [item.document_type, item.title] as const))
  );
  const attachedById = new Map(attachedDocuments.map((item) => [item.id, item]));
  const displayDocuments = canEdit
    ? documents.map((item) => attachedById.get(item.id) ?? item)
    : attachedDocuments;

  useEffect(() => {
    if (applicationId === undefined) return;
    let ignore = false;
    getApplicationDocuments(token, applicationId).then((files) => {
      if (!ignore) setAttachedDocuments(files);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить документы заявления"));
    });
    return () => { ignore = true; };
  }, [token, applicationId, application?.updated_at]);

  const run = async (task: () => Promise<void>) => {
    setError("");
    setMessage("");
    setPending(true);
    try {
      await task();
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось обработать заявление"));
    } finally {
      setPending(false);
    }
  };

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    return run(async () => {
      const saved = await saveApplication(token, { campaign_year: year, program: program.trim(), admission_basis: basis.trim(), document_ids: documentIds }, applicationId);
      onSaved(saved);
      setDirty(false);
      setRequirements(null);
      setMessage("Заявление сохранено.");
    });
  };

  const submit = () => {
    if (applicationId === undefined) return;
    return run(async () => {
      onSaved(await submitApplication(token, applicationId));
      setRequirements(null);
      setHistory(null);
      setMessage("Заявление отправлено на проверку.");
    });
  };

  const inspectRules = () => {
    if (applicationId === undefined) return;
    return run(async () => setRequirements(await getApplicationRequirements(token, applicationId)));
  };

  const showHistory = () => {
    if (applicationId === undefined) return;
    return run(async () => setHistory(await getApplicationEvents(token, applicationId)));
  };

  return (
    <section className="workflow-panel workflow-editor">
      <div className="workflow-panel-heading">
        <h3>{application ? `Заявление №${application.id}` : "Новое заявление"}</h3>
        {application && <WorkflowStatus status={application.status}>{applicationStatus[application.status]}</WorkflowStatus>}
      </div>
      {application?.review_note && <p className="notice">{application.review_note}</p>}
      <form onSubmit={save} onChange={() => { setDirty(true); setRequirements(null); setMessage(""); }}>
        <fieldset disabled={!canEdit || pending}>
          <legend>Данные заявления</legend>
          {rules.length > 0 && (
            <label>
              Выбрать направление из опубликованных правил
              <select value="" onChange={(event) => {
                const rule = rules.find(({ id }) => id === Number(event.target.value));
                if (!rule) return;
                setProgram(rule.program);
                setBasis(rule.admission_basis);
                setYear(rule.campaign_year);
              }}>
                <option value="">Выберите направление</option>
                {rules.map((rule) => (
                  <option key={rule.id} value={rule.id}>{rule.campaign_year} · {rule.program} · {rule.admission_basis}</option>
                ))}
              </select>
            </label>
          )}
          <div className="form-columns">
            <label>
              Год приёма
              <input type="number" min={2000} max={2100} value={year} onChange={(event) => setYear(event.target.valueAsNumber || 0)} required />
            </label>
            <label>
              Направление
              <input value={program} maxLength={255} onChange={(event) => setProgram(event.target.value)} required />
            </label>
            <label>
              Основание поступления
              <input value={basis} maxLength={100} onChange={(event) => setBasis(event.target.value)} required />
            </label>
          </div>
        </fieldset>
        <fieldset disabled={!canEdit || pending}>
          <legend>Документы заявления</legend>
          {displayDocuments.length === 0 && <p className="workflow-muted">Загрузите файлы в разделе «Документы».</p>}
          {displayDocuments.map((document) => (
            <label className="check-row workflow-check-row" key={document.id}>
              <input type="checkbox" checked={documentIds.includes(document.id)} onChange={(event) => {
                const checked = event.target.checked;
                setDocumentIds((current) => checked ? [...current, document.id] : current.filter((id) => id !== document.id));
              }} />
              <span className="workflow-check-text">
                <strong>{document.filename}</strong>
                <small>{documentTypeLabel(document.document_type, typeTitles)}</small>
                {document.review_message && <small>{document.review_message}</small>}
              </span>
              <WorkflowStatus status={document.status}>{documentStatusLabel(document.status)}</WorkflowStatus>
            </label>
          ))}
        </fieldset>
        <div className="workflow-actions workflow-editor-actions">
          {canEdit && <button className={applicationId !== undefined ? "workflow-secondary" : undefined} type="submit" disabled={pending || !dirty}>Сохранить заявление</button>}
          {applicationId !== undefined && (
            <>
              <button className="workflow-secondary" type="button" disabled={pending || dirty} onClick={inspectRules}>Проверить требования</button>
              <button className="workflow-secondary" type="button" disabled={pending} onClick={showHistory}><Icon name="clock" /> История заявления</button>
              {canEdit && <button type="button" disabled={pending || dirty || scoresDirty} onClick={submit}>Отправить на проверку</button>}
            </>
          )}
        </div>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
      {message && <WorkflowNotice variant="success"><p>{message}</p></WorkflowNotice>}
      {requirements && <Requirements result={requirements} />}
      {history && <section className="workflow-history"><h4>История заявления</h4><ApplicationHistory events={history} /></section>}
      {applicationId !== undefined && (
        <ExamScoreEditor
          token={token}
          applicationId={applicationId}
          defaultYear={application?.campaign_year ?? year}
          canEdit={canEdit}
          onDirty={setScoresDirty}
          onSaved={() => setRequirements(null)}
        />
      )}
    </section>
  );
}

type ScoreRow = { key: number; subject: string; year: number | ""; score: number | "" };

function ExamScoreEditor({ token, applicationId, defaultYear, canEdit, onDirty, onSaved }: {
  token: string;
  applicationId: number;
  defaultYear: number;
  canEdit: boolean;
  onDirty: (value: boolean) => void;
  onSaved: () => void;
}) {
  const [scores, setScores] = useState<ScoreRow[]>([]);
  const [keyCounter, setKeyCounter] = useState(1);
  const [syntheticId, setSyntheticId] = useState("");
  const [verification, setVerification] = useState<ExamScores["verification"]>(null);
  const [pending, setPending] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  function showScores(result: ExamScores) {
    setScores(result.scores.map((score, index) => ({ ...score, key: index + 1 })));
    setKeyCounter(result.scores.length + 1);
    setSyntheticId(result.synthetic_candidate_id ?? "");
    setVerification(result.verification);
    setDirty(false);
    onDirty(false);
  }

  useEffect(() => {
    let ignore = false;
    getExamScores(token, applicationId).then((result) => {
      if (!ignore) showScores(result);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить результаты ЕГЭ"));
    }).finally(() => {
      if (!ignore) setPending(false);
    });
    return () => { ignore = true; };
  }, [token, applicationId]);

  const change = (changeRow: () => void) => {
    changeRow();
    setDirty(true);
    onDirty(true);
    setVerification(null);
    setMessage("");
  };

  const update = (key: number, values: Partial<ScoreRow>) => {
    change(() => setScores((current) => current.map((row) => row.key === key ? { ...row, ...values } : row)));
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPending(true);
    setError("");
    setMessage("");
    try {
      const payload = scores.map(({ subject, year, score }) => {
        if (!subject.trim() || year === "" || score === "") throw new Error("Заполните предмет, год и балл каждой строки.");
        return { subject: subject.trim(), year, score };
      });
      showScores(await saveExamScores(token, applicationId, payload, syntheticId.trim() || null));
      onSaved();
      setMessage("Результаты сохранены.");
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось сохранить результаты"));
    } finally {
      setPending(false);
    }
  };

  const verify = async () => {
    setPending(true);
    setError("");
    setMessage("");
    try {
      showScores(await verifyExamScores(token, applicationId));
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось выполнить синтетическую сверку"));
    } finally {
      setPending(false);
    }
  };

  const refresh = async () => {
    setPending(true);
    setError("");
    setMessage("");
    try {
      showScores(await refreshExamScores(token, applicationId, syntheticId.trim().toUpperCase()));
      setMessage("Баллы обновлены из тестового реестра.");
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось обновить результаты из реестра"));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="workflow-scores">
      <div className="workflow-panel-heading"><h3>Заявленные результаты ЕГЭ</h3></div>
      {scores.length === 0 && !pending && <p>Баллы ещё не введены.</p>}
      <form onSubmit={save}>
        {scores.map((row) => (
          <fieldset className="form-columns workflow-score-row" key={row.key} disabled={!canEdit || pending}>
            <legend>Результат</legend>
            <label>
              Предмет
              <input value={row.subject} maxLength={100} required onChange={(event) => update(row.key, { subject: event.target.value })} />
            </label>
            <label>
              Год
              <input type="number" min={2000} max={2100} value={row.year} required onChange={(event) => update(row.key, { year: event.target.valueAsNumber || "" })} />
            </label>
            <label>
              Балл
              <input type="number" min={0} max={100} value={row.score} required onChange={(event) => update(row.key, { score: event.target.value === "" ? "" : event.target.valueAsNumber })} />
            </label>
            {canEdit && <button className="workflow-secondary" type="button" onClick={() => change(() => setScores((current) => current.filter(({ key }) => key !== row.key)))}>Удалить строку</button>}
          </fieldset>
        ))}
        {canEdit && (
          <>
            <label>
              Идентификатор из тестового реестра
              <input
                value={syntheticId}
                maxLength={48}
                pattern="SYN-[A-Z0-9\-]{1,44}"
                placeholder="SYN-123"
                disabled={pending}
                onChange={(event) => change(() => setSyntheticId(event.target.value.toUpperCase()))}
              />
            </label>
            <p className="workflow-muted">Этот идентификатор используется только для синтетической сверки.</p>
          </>
        )}
        <div className="workflow-actions">
          {canEdit && (
            <>
              <button className="workflow-secondary" type="button" disabled={pending} onClick={() => change(() => {
                setScores((current) => [...current, { key: keyCounter, subject: "", year: defaultYear, score: "" }]);
                setKeyCounter((current) => current + 1);
              })}>Добавить предмет</button>
              <button type="submit" disabled={pending || !dirty}>Сохранить баллы</button>
            </>
          )}
          <button className="workflow-secondary" type="button" disabled={pending || dirty || !syntheticId || !scores.length} onClick={verify}>Сверить с тестовым реестром</button>
          {canEdit && (
            <button className="workflow-secondary" type="button" disabled={pending || dirty || !syntheticId} onClick={refresh}>Обновить баллы из тестового реестра</button>
          )}
        </div>
      </form>
      {pending && <p role="status">Загрузка результатов…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {message && <WorkflowNotice variant="success"><p>{message}</p></WorkflowNotice>}
      <Verification verification={verification} />
    </div>
  );
}
