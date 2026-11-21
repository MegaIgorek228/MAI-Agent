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
  saveApplication,
  saveExamScores,
  submitApplication,
  verifyExamScores
} from "./api";
import { CompletenessResult, documentStatusLabel, requestErrorMessage } from "./Documents";

export const applicationStatus: Record<ApplicationStatus, string> = {
  draft: "Черновик",
  submitted: "Отправлено",
  under_review: "На проверке",
  needs_changes: "Требуются изменения",
  reviewed: "Проверено"
};

export function ApplicationHistory({ events }: { events: ApplicationEvent[] }) {
  return (
    <ol>
      {events.map((event) => (
        <li key={event.id}>
          {applicationStatus[event.status]} · <time dateTime={event.created_at}>
            {new Date(event.created_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}
          </time>
          {event.note && <p>{event.note}</p>}
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
    <div className="view-stack">
      <CompletenessResult result={result.documents} />
      {result.rules && (
        <p>
          Редакция правил №{result.rules.revision}.
          {result.rules.source_url && <> <a href={result.rules.source_url}>Источник правил</a>.</>}
        </p>
      )}
      <p>{requirementResult[result.ege.status] ?? result.ege.status}</p>
      {result.ege.missing_subjects.length > 0 && <p>Нужны результаты по предметам {result.ege.missing_subjects.join(", ")}.</p>}
      {result.ege.below_minimum.map(({ subject, score, minimum }) => (
        <p key={subject}>{subject} · {score} баллов при минимуме {minimum}.</p>
      ))}
    </div>
  );
}

export function Verification({ verification }: { verification: ExamScores["verification"] }) {
  if (!verification) return null;
  return (
    <div className="notice">
      <p><strong>Синтетическая сверка.</strong> {verificationResult[verification.status] ?? verification.status}</p>
      {verification.missing_subjects.length > 0 && (
        <p>В тестовом реестре не найдены предметы {verification.missing_subjects.join(", ")}.</p>
      )}
      {verification.mismatched_subjects.length > 0 && (
        <p>Баллы различаются по предметам {verification.mismatched_subjects.join(", ")}.</p>
      )}
    </div>
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
    <div className="view-stack">
      <h2>Заявления</h2>
      {pending && <p role="status">Загрузка заявлений…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      <div className="actions">
        <button type="button" onClick={() => setSelection("new")}>Новое заявление</button>
      </div>
      {applications.length > 0 && (
        <label>
          Ваши заявления
          <select value={typeof selection === "number" ? selection : ""} onChange={(event) => setSelection(Number(event.target.value))}>
            <option value="" disabled>Выберите заявление</option>
            {applications.map((item) => (
              <option key={item.id} value={item.id}>
                №{item.id} · {item.program} · {applicationStatus[item.status]}
              </option>
            ))}
          </select>
        </label>
      )}
      {selection === "new" && <ApplicationEditor key="new" token={token} profile={profile} documents={documents} rules={rules} onSaved={onSaved} />}
      {active && <ApplicationEditor key={active.id} token={token} application={active} profile={profile} documents={documents} rules={rules} onSaved={onSaved} />}
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
    <section className="record view-stack">
      <h3>{application ? `Заявление №${application.id}` : "Новое заявление"}</h3>
      {application && <p><strong>{applicationStatus[application.status]}</strong></p>}
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
          {displayDocuments.length === 0 && <p>Загрузите файлы в разделе «Документы».</p>}
          {displayDocuments.map((document) => (
            <label className="check-row" key={document.id}>
              <input type="checkbox" checked={documentIds.includes(document.id)} onChange={(event) => {
                const checked = event.target.checked;
                setDocumentIds((current) => checked ? [...current, document.id] : current.filter((id) => id !== document.id));
              }} />
              <span>
                {document.filename} · {document.document_type ?? "Тип не указан"} · {documentStatusLabel(document.status)}
                {document.review_message && <small>{document.review_message}</small>}
              </span>
            </label>
          ))}
        </fieldset>
        <div className="actions">
          {canEdit && <button type="submit" disabled={pending || !dirty}>Сохранить заявление</button>}
          {applicationId !== undefined && (
            <>
              <button type="button" disabled={pending || dirty} onClick={inspectRules}>Проверить требования</button>
              <button type="button" disabled={pending} onClick={showHistory}>История заявления</button>
              {canEdit && <button type="button" disabled={pending || dirty || scoresDirty} onClick={submit}>Отправить на проверку</button>}
            </>
          )}
        </div>
      </form>
      {error && <p role="alert" className="error">{error}</p>}
      {message && <p role="status">{message}</p>}
      {requirements && <Requirements result={requirements} />}
      {history && <ApplicationHistory events={history} />}
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

  return (
    <div className="view-stack">
      <h3>Заявленные результаты ЕГЭ</h3>
      {scores.length === 0 && !pending && <p>Баллы ещё не введены.</p>}
      <form onSubmit={save}>
        {scores.map((row) => (
          <fieldset className="form-columns" key={row.key} disabled={!canEdit || pending}>
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
            {canEdit && <button type="button" onClick={() => change(() => setScores((current) => current.filter(({ key }) => key !== row.key)))}>Удалить строку</button>}
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
            <p>Укажите этот идентификатор только для синтетической сверки.</p>
          </>
        )}
        <div className="actions">
          {canEdit && (
            <>
              <button type="button" disabled={pending} onClick={() => change(() => {
                setScores((current) => [...current, { key: keyCounter, subject: "", year: defaultYear, score: "" }]);
                setKeyCounter((current) => current + 1);
              })}>Добавить предмет</button>
              <button type="submit" disabled={pending || !dirty}>Сохранить баллы</button>
            </>
          )}
          <button type="button" disabled={pending || dirty || !syntheticId || !scores.length} onClick={verify}>Сверить с тестовым реестром</button>
        </div>
      </form>
      {pending && <p role="status">Загрузка результатов…</p>}
      {error && <p role="alert" className="error">{error}</p>}
      {message && <p role="status">{message}</p>}
      <Verification verification={verification} />
    </div>
  );
}
