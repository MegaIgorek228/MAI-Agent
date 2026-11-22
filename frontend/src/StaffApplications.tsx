import { FormEvent, useEffect, useState } from "react";

import {
  Application,
  ApplicationStatus,
  AchievementCategory,
  AchievementItem,
  StaffAchievementCard,
  StaffApplicantCard,
  StaffApplicantRow,
  StaffApplication,
  StaffDashboardData,
  downloadAchievementDocument,
  downloadApplicationDocument,
  getStaffAchievementCard,
  getStaffAchievements,
  getStaffApplicantCard,
  getStaffApplicants,
  getStaffApplication,
  getStaffApplications,
  getStaffDashboard,
  publishAdmissionRule,
  reviewAchievement,
  reviewApplication,
  reviewApplicationDocument
} from "./api";
import { achievementCategory, achievementLevel, achievementStatus } from "./Achievements";
import { ApplicationHistory, applicationStatus, Requirements, Verification } from "./Admissions";
import { documentStatusLabel, documentTypeLabel, requestErrorMessage } from "./Documents";
import { Icon } from "./Icon";
import { WorkflowEmpty, WorkflowHeader, WorkflowNotice, WorkflowStatus } from "./WorkflowUI";

const pageSize = 20;

const nextStatuses: Partial<Record<ApplicationStatus, ApplicationStatus[]>> = {
  submitted: ["under_review", "needs_changes"],
  under_review: ["needs_changes", "reviewed"]
};

const achievementTone: Record<AchievementItem["status"], string> = {
  draft: "uploaded",
  pending: "submitted",
  confirmed: "reviewed",
  rejected: "rejected",
  needs_revision: "needs_changes"
};

// Human labels for feed/history actions (not statuses).
const feedAction: Record<string, string> = {
  created: "создано",
  updated: "изменено",
  submitted: "отправлено на проверку",
  resubmitted: "повторно отправлено на проверку",
  reviewed: "проверено",
  needs_changes: "требуются изменения",
  confirmed: "подтверждено",
  rejected: "отклонено",
  needs_revision: "запрошено исправление"
};

const dateLabel = (value: string) =>
  new Date(value).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });

type StaffMode = "dashboard" | "applications" | "applicants" | "achievements" | "rules";

export function StaffApplications({ token }: { token: string }) {
  const [mode, setMode] = useState<StaffMode>("dashboard");
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

  const openApplicantApplications = (email: string) => {
    setFilters({ query: email, status: "", offset: 0 });
    setSelected(null);
    setMode("applications");
  };

  const switchTo = (target: StaffMode) => {
    setMode(target);
    window.scrollTo({ top: 0, behavior: "instant" });
  };

  return (
    <div className="workflow">
      <WorkflowHeader level={1} title="Рабочее место сотрудника"
        description="Сводка по приёмной кампании, проверка заявлений, документов и индивидуальных достижений." />
      <div className="workflow-tabs" role="group" aria-label="Раздел рабочего места">
        <button type="button" aria-pressed={mode === "dashboard"} onClick={() => switchTo("dashboard")}><Icon name="grid" /> Обзор</button>
        <button type="button" aria-pressed={mode === "applications"} onClick={() => switchTo("applications")}><Icon name="folder" /> Заявления</button>
        <button type="button" aria-pressed={mode === "applicants"} onClick={() => switchTo("applicants")}><Icon name="user" /> Абитуриенты</button>
        <button type="button" aria-pressed={mode === "achievements"} onClick={() => switchTo("achievements")}><Icon name="badge" /> Достижения</button>
        <button type="button" aria-pressed={mode === "rules"} onClick={() => switchTo("rules")}><Icon name="book" /> Правила приёма</button>
      </div>
      {mode === "dashboard" && <StaffDashboard token={token} onNavigate={switchTo} />}
      {mode === "rules" && <AdmissionRuleEditor token={token} />}
      {mode === "applicants" && <StaffApplicantList token={token} onOpenApplication={openApplicantApplications} />}
      {mode === "achievements" && <StaffAchievementsQueue token={token} />}
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
          {selected !== null && (
            <StaffApplicationDetail key={selected} token={token} id={selected} onUpdate={(application) =>
              setApplications((current) => current.map((item) => item.id === application.id ? application : item))} />
          )}
        </>
      )}
    </div>
  );
}

function StaffDashboard({ token, onNavigate }: {
  token: string;
  onNavigate: (target: StaffMode) => void;
}) {
  const [data, setData] = useState<StaffDashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    setData(null);
    getStaffDashboard(token).then((current) => {
      if (!ignore) setData(current);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить сводку"));
    });
    return () => { ignore = true; };
  }, [token]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!data) return <p role="status" className="workflow-muted">Загружаем сводку по приёмной кампании…</p>;

  const stats: Array<{ label: string; value: number; target: StaffMode; attention: boolean }> = [
    { label: "Всего абитуриентов", value: data.applicants_total, target: "applicants", attention: false },
    { label: "Заявлений в работе", value: data.applications_in_work, target: "applications", attention: false },
    { label: "Заявления ждут проверки", value: data.applications_awaiting_review, target: "applications", attention: data.applications_awaiting_review > 0 },
    { label: "Документы ждут проверки", value: data.documents_awaiting_review, target: "applications", attention: data.documents_awaiting_review > 0 },
    { label: "Достижения ждут проверки", value: data.achievements_awaiting_review, target: "achievements", attention: data.achievements_awaiting_review > 0 }
  ];

  return (
    <>
      <section className="workflow-panel" aria-labelledby="dashboard-heading">
        <div className="workflow-panel-heading">
          <h3 id="dashboard-heading">Сводка</h3>
        </div>
        <div className="workflow-stats">
          {stats.map((stat) => (
            <div key={stat.label} className={stat.attention ? "workflow-stat workflow-stat--attention" : "workflow-stat"}>
              <span className="workflow-stat__value">{stat.value}</span>
              <span className="workflow-stat__label">{stat.label}</span>
              <button type="button" className="workflow-stat__action" onClick={() => onNavigate(stat.target)}>
                Перейти <Icon name="chevron-right" />
              </button>
            </div>
          ))}
        </div>
      </section>
      <section className="workflow-panel" aria-labelledby="activity-heading">
        <div className="workflow-panel-heading">
          <h3 id="activity-heading">Последние действия</h3>
        </div>
        {data.recent_activity.length === 0
          ? <WorkflowEmpty icon="inbox" title="Активности пока нет" description="Здесь появятся новые заявления, документы и достижения." />
          : (
            <ol className="workflow-activity">
              {data.recent_activity.map((entry) => (
                <li key={`${entry.source}-${entry.reference_id}-${entry.created_at}`} className="workflow-activity-item">
                  <time dateTime={entry.created_at}>{dateLabel(entry.created_at)}</time>
                  <div>
                    {entry.source === "application"
                      ? <>Заявление №{entry.reference_id}: <strong>{feedAction[entry.action] ?? entry.action}</strong></>
                      : <>Достижение №{entry.reference_id}: <strong>{feedAction[entry.action] ?? entry.action}</strong></>}
                    {entry.note && <small>{entry.note}</small>}
                  </div>
                </li>
              ))}
            </ol>
          )}
      </section>
    </>
  );
}

function StaffApplicantList({ token, onOpenApplication }: {
  token: string;
  onOpenApplication: (email: string) => void;
}) {
  const [rows, setRows] = useState<StaffApplicantRow[] | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    setRows(null);
    getStaffApplicants(token, query).then((list) => {
      if (!ignore) setRows(list);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить список абитуриентов"));
    });
    return () => { ignore = true; };
  }, [token, query]);

  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setSelected(null);
    setQuery(String(values.get("query") ?? "").trim());
  };

  return (
    <>
      <section className="workflow-panel" aria-labelledby="applicants-heading">
        <div className="workflow-panel-heading">
          <h3 id="applicants-heading">Абитуриенты</h3>
          {rows && rows.length > 0 && <span className="workflow-count">{rows.length}</span>}
        </div>
        <form className="workflow-queue-filter" onSubmit={applySearch}>
          <label>
            Поиск
            <input name="query" defaultValue={query} placeholder="ФИО или email" />
          </label>
          <button type="submit"><Icon name="search" /> Найти</button>
        </form>
        {error ? <p role="alert" className="error">{error}</p> : rows === null ? (
          <p role="status" className="workflow-muted">Загрузка абитуриентов…</p>
        ) : rows.length === 0 ? (
          <WorkflowEmpty title="Абитуриентов по этим условиям нет" description="Измените параметры поиска или дождитесь новых регистраций." />
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table className="workflow-data-table">
              <thead>
                <tr>
                  <th>ФИО</th>
                  <th>Идентификатор</th>
                  <th>Заявление</th>
                  <th>Статус</th>
                  <th>Документы</th>
                  <th>Проверка документов</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const latest = row.applications.length > 0
                    ? row.applications.reduce((best, item) => item.updated_at > best.updated_at ? item : best)
                    : null;
                  const documentsTotal = row.applications.reduce((sum, item) => sum + item.document_count, 0);
                  const documentsPending = row.applications.reduce((sum, item) => sum + item.documents_pending, 0);
                  return (
                    <tr key={row.id}>
                      <td>
                        <button type="button" className="workflow-stat__action" aria-pressed={selected === row.id} onClick={() => setSelected(selected === row.id ? null : row.id)}>
                          {row.last_name && row.first_name ? `${row.last_name} ${row.first_name}` : row.email}
                        </button>
                      </td>
                      <td>№{row.id}</td>
                      <td>{latest
                        ? <>№{latest.id} · {latest.campaign_year}{row.applications.length > 1 ? ` · ещё ${row.applications.length - 1}` : ""}</>
                        : <span className="workflow-muted">нет заявления</span>}</td>
                      <td>{latest
                        ? <WorkflowStatus status={latest.status}>{applicationStatus[latest.status as ApplicationStatus] ?? latest.status}</WorkflowStatus>
                        : <span className="workflow-muted">—</span>}</td>
                      <td>{documentsTotal}</td>
                      <td>{!latest
                        ? <span className="workflow-muted">—</span>
                        : documentsPending > 0
                          ? <WorkflowStatus status="warning">{documentsPending} ждут проверки</WorkflowStatus>
                          : documentsTotal > 0
                            ? <WorkflowStatus status="reviewed">Проверены</WorkflowStatus>
                            : <span className="workflow-muted">Не приложены</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {selected !== null && <StaffApplicantCardView key={selected} token={token} applicantId={selected} onOpenApplication={onOpenApplication} />}
    </>
  );
}

function StaffApplicantCardView({ token, applicantId, onOpenApplication }: {
  token: string;
  applicantId: number;
  onOpenApplication: (email: string) => void;
}) {
  const [card, setCard] = useState<StaffApplicantCard | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    setCard(null);
    getStaffApplicantCard(token, applicantId).then((data) => {
      if (!ignore) setCard(data);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить карточку абитуриента"));
    });
    return () => { ignore = true; };
  }, [token, applicantId]);

  if (error) return <p className="error" role="alert">{error}</p>;
  if (!card) return <p role="status" className="workflow-muted">Загружаем карточку абитуриента…</p>;

  const { profile, applications, ege, achievements, history } = card;

  return (
    <section className="workflow-panel workflow-editor" aria-label="Карточка абитуриента">
      <div className="workflow-panel-heading">
        <div>
          <h3>Абитуриент №{profile.id}</h3>
          <p className="workflow-muted">
            {[profile.last_name, profile.first_name].filter(Boolean).join(" ") || profile.email}
            {!profile.is_active && " · учётная запись неактивна"}
          </p>
        </div>
      </div>
      <section className="workflow-subsection">
        <h4>Личные данные и поступление</h4>
        <dl className="workflow-staff-scores">
          <div><dt>Email</dt><dd>{profile.email}</dd></div>
          {profile.phone && <div><dt>Телефон</dt><dd>{profile.phone}</dd></div>}
          {profile.target_program && <div><dt>Направление</dt><dd>{profile.target_program}</dd></div>}
          {profile.admission_basis && <div><dt>Основание</dt><dd>{profile.admission_basis}</dd></div>}
        </dl>
      </section>
      <section className="workflow-subsection">
        <h4>Заявления</h4>
        {applications.length === 0 && <p className="workflow-muted">Заявлений пока нет.</p>}
        {applications.map((application) => (
          <div key={application.id} className="workflow-document-review">
            <div className="workflow-file-name">
              <span className="workflow-mark"><Icon name="file" /></span>
              <div>
                <h5>№{application.id} · {application.program}</h5>
                <small>{application.campaign_year} · {application.admission_basis} · документов: {application.document_count}
                  {application.documents_pending > 0 ? ` (ждут проверки: ${application.documents_pending})` : ""}</small>
              </div>
              <WorkflowStatus status={application.status}>{applicationStatus[application.status as ApplicationStatus] ?? application.status}</WorkflowStatus>
            </div>
            <div className="workflow-actions">
              <button className="workflow-secondary" type="button" onClick={() => onOpenApplication(profile.email)}>
                Открыть заявление <Icon name="chevron-right" />
              </button>
            </div>
          </div>
        ))}
      </section>
      {ege.length > 0 && (
        <section className="workflow-subsection">
          <h4>Результаты ЕГЭ</h4>
          {ege.map((entry) => (
            <div key={entry.application_id} className="workflow-document-review">
              <div className="workflow-file-name">
                <div>
                  <h5>Заявление №{entry.application_id}</h5>
                  <small>{entry.synthetic_candidate_id ? `Тестовый реестр: ${entry.synthetic_candidate_id}` : "Синтетическая сверка ещё не выполнялась"}</small>
                </div>
              </div>
              {entry.scores.length > 0
                ? <dl className="workflow-staff-scores">{entry.scores.map((score) => (
                  <div key={`${score.subject}-${score.year}`}>
                    <dt>{score.subject} <small>{score.year}</small></dt>
                    <dd>{score.score}</dd>
                  </div>
                ))}</dl>
                : <p className="workflow-muted">Баллы ещё не введены.</p>}
              {entry.verification && (
                <WorkflowNotice variant={entry.verification.status === "match" ? "success" : "info"}>
                  <p>{verificationLabel(entry.verification.status, entry.verification.missing_subjects, entry.verification.mismatched_subjects)}</p>
                </WorkflowNotice>
              )}
            </div>
          ))}
        </section>
      )}
      <section className="workflow-subsection">
        <h4>Индивидуальные достижения</h4>
        {achievements.length === 0 && <p className="workflow-muted">Достижения не заявлены.</p>}
        {achievements.map((item) => (
          <div key={item.id} className="workflow-achievement-card">
            <div className="workflow-achievement-card__head">
              <span>№{item.id} · {item.title}</span>
              <WorkflowStatus status={achievementTone[item.status]}>{achievementStatus[item.status]}</WorkflowStatus>
            </div>
            <div className="workflow-achievement-card__meta">
              <span>{achievementCategory[item.category]}</span>
              {item.level && <span>{achievementLevel[item.level]}</span>}
              {item.organization && <span>{item.organization}</span>}
            </div>
          </div>
        ))}
      </section>
      {history.length > 0 && (
        <section className="workflow-subsection">
          <h4>История проверок и изменений</h4>
          <ol className="workflow-activity">
            {history.map((entry) => (
              <li key={`${entry.source}-${entry.reference_id}-${entry.created_at}`} className="workflow-activity-item">
                <time dateTime={entry.created_at}>{dateLabel(entry.created_at)}</time>
                <div>
                  {entry.source === "application"
                    ? <>Заявление №{entry.reference_id}: <strong>{feedAction[entry.action] ?? entry.action}</strong></>
                    : <>Достижение №{entry.reference_id}: <strong>{feedAction[entry.action] ?? entry.action}</strong></>}
                  {entry.note && <small>{entry.note}</small>}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </section>
  );
}

function verificationLabel(status: string, missing: string[], mismatched: string[]) {
  switch (status) {
    case "match": return "Синтетическая сверка: баллы совпадают с тестовым реестром.";
    case "mismatch": return `Синтетическая сверка: различия по предметам ${mismatched.join(", ") || "—"}.`;
    case "not_found": return "Синтетическая сверка: запись в тестовом реестре не найдена.";
    case "incomplete": return `Синтетическая сверка: не хватает предметов ${missing.join(", ") || "—"}.`;
    default: return `Синтетическая сверка: ${status}.`;
  }
}

function StaffAchievementsQueue({ token }: { token: string }) {
  const [filters, setFilters] = useState({ status: "pending", category: "", q: "" });
  const [items, setItems] = useState<AchievementItem[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    setItems(null);
    getStaffAchievements(token, filters).then((list) => {
      if (!ignore) setItems(list);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить очередь достижений"));
    });
    return () => { ignore = true; };
  }, [token, filters]);

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    setSelected(null);
    setFilters({
      status: String(values.get("status") ?? "pending"),
      category: String(values.get("category") ?? ""),
      q: String(values.get("q") ?? "").trim()
    });
  };

  return (
    <>
      <section className="workflow-panel workflow-queue" aria-labelledby="achievements-heading">
        <div className="workflow-panel-heading">
          <h3 id="achievements-heading">Проверка индивидуальных достижений</h3>
          {items && items.length > 0 && <span className="workflow-count">{items.length}</span>}
        </div>
        <form className="workflow-queue-filter" onSubmit={applyFilters}>
          <label>
            Статус
            <select name="status" defaultValue={filters.status}>
              <option value="pending">На проверке</option>
              <option value="">Все статусы</option>
              <option value="draft">Черновик</option>
              <option value="needs_revision">Требует исправления</option>
              <option value="rejected">Отклонено</option>
              <option value="confirmed">Подтверждено</option>
            </select>
          </label>
          <label>
            Категория
            <select name="category" defaultValue={filters.category}>
              <option value="">Все категории</option>
              {(Object.keys(achievementCategory) as AchievementCategory[]).map((value) => (
                <option key={value} value={value}>{achievementCategory[value]}</option>
              ))}
            </select>
          </label>
          <label>
            Поиск
            <input name="q" defaultValue={filters.q} placeholder="Название или абитуриент" />
          </label>
          <button type="submit"><Icon name="search" /> Найти</button>
        </form>
        {error && <p className="error" role="alert">{error}</p>}
        {items === null && <p role="status" className="workflow-muted">Загружаем очередь достижений…</p>}
        {items !== null && items.length === 0 && (
          <WorkflowEmpty icon="file" title="Достигновений по этим условиям нет"
            description="Измените параметры поиска или дождитесь новых подач." />
        )}
        {items !== null && items.length > 0 && (
          <ul className="workflow-list workflow-queue-list">
            {items.map((item) => (
              <li key={item.id}>
                <button className="workflow-queue-row" type="button" aria-pressed={selected === item.id} onClick={() => setSelected(item.id)}>
                  <span className="workflow-mark"><Icon name="badge" /></span>
                  <span className="workflow-row-main">
                    <span>№{item.id} · {item.title}</span>
                    <small>{achievementCategory[item.category]}{item.level ? ` · ${achievementLevel[item.level]}` : ""}</small>
                  </span>
                  <WorkflowStatus status={achievementTone[item.status]}>{achievementStatus[item.status]}</WorkflowStatus>
                  <Icon name="chevron-right" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
      {selected !== null && <StaffAchievementDetail key={selected} token={token} id={selected} />}
    </>
  );
}

function StaffAchievementDetail({ token, id }: { token: string; id: number }) {
  const [card, setCard] = useState<StaffAchievementCard | null>(null);
  const [comment, setComment] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let ignore = false;
    setCard(null);
    getStaffAchievementCard(token, id).then((data) => {
      if (!ignore) setCard(data);
    }).catch((requestError) => {
      if (!ignore) setError(requestErrorMessage(requestError, "Не удалось загрузить карточку достижения"));
    });
    return () => { ignore = true; };
  }, [token, id]);

  const run = async (task: () => Promise<void>) => {
    setError("");
    setPending(true);
    try {
      await task();
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось выполнить действие"));
    } finally {
      setPending(false);
    }
  };

  const decide = (action: "confirmed" | "rejected" | "needs_revision") => {
    if (action !== "confirmed" && !comment.trim()) {
      setError("Для отклонения или запроса исправления комментарий обязателен.");
      return;
    }
    const phrases: Record<typeof action, string> = {
      confirmed: "Подтвердить достижение?",
      rejected: "Отклонить достижение? Абитуриент увидит ваш комментарий.",
      needs_revision: "Запросить исправление? Абитуриент сможет исправить сведения и повторно подать достижение."
    };
    if (!window.confirm(phrases[action])) return;
    return run(async () => {
      const updated = await reviewAchievement(token, id, action, comment.trim());
      setCard(updated);
      setComment("");
    });
  };

  const download = () => run(async () => {
    const blob = await downloadAchievementDocument(token, id);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = card?.document?.filename ?? "evidence";
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  });

  if (error && !card) return <p className="error" role="alert">{error}</p>;
  if (!card) return <p role="status" className="workflow-muted">Загружаем карточку достижения…</p>;

  return (
    <section className="workflow-panel workflow-editor" aria-label={`Достижение ${card.id}`}>
      <div className="workflow-panel-heading">
        <div>
          <h3>Достижение №{card.id} · {card.title}</h3>
          <p className="workflow-muted">
            {[card.applicant.last_name, card.applicant.first_name].filter(Boolean).join(" ") || card.applicant.email}
            {` · ${card.applicant.email}`}
          </p>
        </div>
        <WorkflowStatus status={achievementTone[card.status]}>{achievementStatus[card.status]}</WorkflowStatus>
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <dl className="workflow-staff-scores">
        <div><dt>Категория</dt><dd>{achievementCategory[card.category]}</dd></div>
        {card.level && <div><dt>Уровень</dt><dd>{achievementLevel[card.level]}</dd></div>}
        <div><dt>Дата получения</dt><dd>{new Date(card.achieved_on).toLocaleDateString("ru-RU")}</dd></div>
        {card.organization && <div><dt>Организация</dt><dd>{card.organization}</dd></div>}
        {card.application_id && <div><dt>Заявление</dt><dd>№{card.application_id}</dd></div>}
        {card.submitted_at && <div><dt>Подано на проверку</dt><dd>{dateLabel(card.submitted_at)}</dd></div>}
      </dl>
      {card.description && <p className="workflow-muted">{card.description}</p>}
      {card.document ? (
        <div className="workflow-actions">
          <span className="workflow-mark"><Icon name="file" /></span>
          <span>{card.document.filename}</span>
          <button className="workflow-secondary" type="button" disabled={pending} onClick={download}>Скачать файл</button>
        </div>
      ) : <p className="workflow-muted">Подтверждающий документ не приложен.</p>}

      {card.status === "pending" ? (
        <section className="workflow-subsection">
          <h4>Решение сотрудника</h4>
          <label>
            Комментарий (обязателен для отклонения и запроса исправления)
            <textarea value={comment} rows={3} maxLength={2000} placeholder="Комментарий виден абитуриенту"
              onChange={(event) => setComment(event.target.value)} />
          </label>
          <div className="workflow-actions">
            <button type="button" disabled={pending} onClick={() => decide("confirmed")}><Icon name="check" /> Подтвердить</button>
            <button className="workflow-secondary" type="button" disabled={pending} onClick={() => decide("needs_revision")}>Запросить исправление</button>
            <button className="workflow-secondary" type="button" disabled={pending} onClick={() => decide("rejected")}>Отклонить</button>
          </div>
        </section>
      ) : (
        card.review_comment && (
          <WorkflowNotice variant={card.status === "confirmed" ? "success" : "info"}>
            <strong>Решение от {card.reviewed_at ? dateLabel(card.reviewed_at) : "—"}</strong>
            <p>{card.review_comment}</p>
          </WorkflowNotice>
        )
      )}

      <details className="workflow-disclosure">
        <summary>История решений</summary>
        {card.history.length === 0
          ? <p className="workflow-muted">Решений ещё не было.</p>
          : (
            <ol className="workflow-timeline">
              {card.history.map((entry) => (
                <li key={entry.id}>
                  <span className="workflow-timeline-dot" />
                  <div>
                    <strong>{decisionLabel(entry.action)}</strong>
                    <time dateTime={entry.created_at}>{dateLabel(entry.created_at)}</time>
                    {entry.comment && <p>{entry.comment}</p>}
                  </div>
                </li>
              ))}
            </ol>
          )}
      </details>
    </section>
  );
}

function decisionLabel(action: string) {
  switch (action) {
    case "created": return "Создано";
    case "updated": return "Изменено";
    case "submitted": return "Отправлено на проверку";
    case "resubmitted": return "Повторно отправлено на проверку";
    case "confirmed": return "Подтверждено";
    case "rejected": return "Отклонено";
    case "needs_revision": return "Запрошено исправление";
    default: return action;
  }
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
  const typeTitles: Record<string, string> = Object.fromEntries(
    (requirements.rules?.document_requirements ?? []).map((item) => [item.document_type, item.title] as const)
  );

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
                <small>{documentTypeLabel(document.document_type, typeTitles)}</small>
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
