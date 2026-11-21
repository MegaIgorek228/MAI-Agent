import { useEffect, useState } from "react";

import { applicationStatus } from "./Admissions";
import { getApplications } from "./api";
import type { Application, DocumentItem, User } from "./api";
import { requestErrorMessage } from "./Documents";
import { Icon } from "./Icon";
import { WorkflowStatus } from "./WorkflowUI";
import "./cockpit.css";

const competitionListsUrl = "https://priem.mai.ru/rating/";

type CockpitProps = {
  token: string;
  user: User;
  documents: DocumentItem[];
  onOpenApplications?: () => void;
  onOpenStaff?: () => void;
};

type ApplicationSummaryState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; applications: Application[] };

function ApplicationSummary({ token, onOpen }: { token: string; onOpen?: () => void }) {
  const [summary, setSummary] = useState<ApplicationSummaryState>({ status: "loading" });

  useEffect(() => {
    let ignore = false;

    getApplications(token).then((applications) => {
      if (!ignore) setSummary({ status: "ready", applications });
    }).catch((error: unknown) => {
      if (!ignore) setSummary({ status: "error", message: requestErrorMessage(error, "Не удалось загрузить заявления") });
    });

    return () => { ignore = true; };
  }, [token]);

  return (
    <section className="cockpit-panel" aria-labelledby="cockpit-applications">
      <div className="cockpit-panel__heading">
        <Icon name="folder" />
        <h2 id="cockpit-applications">Последние заявления</h2>
      </div>
      {summary.status === "loading" && <p role="status">Загрузка заявлений…</p>}
      {summary.status === "error" && <p className="error" role="alert">{summary.message}</p>}
      {summary.status === "ready" && (
        summary.applications.length === 0 ? <p>Заявлений пока нет.</p> : (
          <ul className="cockpit-applications">
            {summary.applications.slice(0, 3).map((application) => (
              <li key={application.id}>
                <div>
                  <strong>{application.program}</strong>
                  <small>{application.campaign_year} · {application.admission_basis}</small>
                </div>
                <WorkflowStatus status={application.status}>{applicationStatus[application.status]}</WorkflowStatus>
              </li>
            ))}
          </ul>
        )
      )}
      {onOpen && (
        <button type="button" className="button-link cockpit-action" onClick={onOpen}>
          К заявлениям <Icon name="arrow-right" />
        </button>
      )}
    </section>
  );
}

export function Cockpit({ token, user, documents, onOpenApplications, onOpenStaff }: CockpitProps) {
  const applicant = user.role === "applicant";
  const staff = user.role === "admissions_staff" || user.role === "administrator";

  return (
    <section className="cockpit" aria-labelledby="cockpit-title">
      <header className="cockpit-heading">
        <h1 id="cockpit-title">Кабина пилотов</h1>
        {user.role !== "student" && documents.length > 0 && (
          <div className="cockpit-file-count">
            <Icon name="file" />
            <span>Загружено файлов</span>
            <strong>{documents.length}</strong>
          </div>
        )}
      </header>
      {applicant && (
        <div className="cockpit-overview">
          <ApplicationSummary key={token} token={token} onOpen={onOpenApplications} />
          <section className="cockpit-panel" aria-labelledby="cockpit-rank">
            <div className="cockpit-panel__heading">
              <Icon name="graduation" />
              <h2 id="cockpit-rank">Место в конкурсном списке</h2>
            </div>
            <p>Данные о позиции в кабинете недоступны. Проверьте своё место по конкурсной группе на сайте МАИ.</p>
            <a className="cockpit-action" href={competitionListsUrl} target="_blank" rel="noreferrer">
              Конкурсные списки МАИ <Icon name="external" />
            </a>
          </section>
        </div>
      )}
      {staff && onOpenStaff && (
        <button type="button" className="button-link cockpit-action" onClick={onOpenStaff}>
          К проверке заявлений <Icon name="arrow-right" />
        </button>
      )}
    </section>
  );
}
