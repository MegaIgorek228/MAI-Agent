import { FormEvent, useEffect, useState } from "react";

import {
  analyzeDocument,
  DocumentCompleteness,
  DocumentItem,
  getAdmissionRules,
  getDocumentCompleteness,
  updateDocumentType,
  uploadDocument
} from "./api";
import { Icon } from "./Icon";
import { WorkflowEmpty, WorkflowHeader, WorkflowNotice, WorkflowStatus } from "./WorkflowUI";

const documentStatus: Record<string, string> = {
  pending: "Ждёт проверки",
  uploaded: "Загружен",
  extracted: "Текст извлечён",
  analyzed: "Проанализирован",
  needs_manual_review: "Требуется ручная проверка",
  accepted: "Принят",
  rejected: "Отклонён",
  changes_requested: "Запрошено исправление"
};

const commonDocumentTypes: { value: string; label: string }[] = [
  { value: "passport", label: "Паспорт" },
  { value: "education", label: "Документ об образовании (аттестат)" },
  { value: "Диплом", label: "Диплом" },
  { value: "СНИЛС", label: "СНИЛС" },
  { value: "Заявление", label: "Заявление" },
  { value: "Согласие на зачисление", label: "Согласие на зачисление" }
];

// Russian display names for the machine codes the backend uses when a
// published rule with a matching title is not loaded.
const documentTypeLabels: Record<string, string> = {
  passport: "Паспорт",
  education: "Документ об образовании",
  evidence: "Документ-подтверждение"
};

export function documentTypeLabel(type: string | null | undefined, titles?: Record<string, string>) {
  if (!type) return "Тип не указан";
  const known = titles?.[type] ?? documentTypeLabels[type.toLowerCase()];
  return known ?? type;
}

export function documentStatusLabel(status: string) {
  return documentStatus[status] ?? status;
}

export function requestErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function CompletenessResult({ result }: { result: DocumentCompleteness }) {
  const groups = [
    { title: "Не хватает", files: result.missing_documents },
    { title: "Ожидают проверки", files: result.pending_documents ?? [] }
  ];

  return (
    <WorkflowNotice variant={result.status === "complete" ? "success" : "info"}>
      <p>{result.message}</p>
      {groups.map(({ title, files }) => files.length > 0 && (
        <div key={title}>
          <strong>{title}</strong>
          <ul>{files.map(({ document_type, title: documentTitle }) => (
            <li key={document_type}>{documentTitle}</li>
          ))}</ul>
        </div>
      ))}
    </WorkflowNotice>
  );
}

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} Б`;
  const [value, unit] = bytes < 1024 * 1024
    ? [bytes / 1024, "КБ"]
    : [bytes / (1024 * 1024), "МБ"];
  return `${new Intl.NumberFormat("ru", { maximumFractionDigits: 1 }).format(value)} ${unit}`;
}

function DocumentAnalysis({ content }: { content: string }) {
  let result: Record<string, unknown>;

  try {
    result = JSON.parse(content);
  } catch {
    return <pre>{content}</pre>;
  }
  if (!result || typeof result.is_readable !== "boolean") return <pre>{content}</pre>;
  const type = typeof result.document_type === "string" ? result.document_type : "";
  const fields = result.extracted_fields && typeof result.extracted_fields === "object"
    ? Object.entries(result.extracted_fields)
    : [];
  const issues = Array.isArray(result.issues)
    ? result.issues.filter((issue): issue is string => typeof issue === "string")
    : [];
  return (
    <div className="workflow-analysis">
      <dl>
        <div><dt>Тип по результатам анализа</dt><dd>{type || "Не определён"}</dd></div>
        <div><dt>Читаемость</dt><dd>{result.is_readable ? "Текст читается" : "Текст не удалось прочитать"}</dd></div>
        {fields.map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{typeof value === "string" ? value : value == null ? "—" : JSON.stringify(value)}</dd>
          </div>
        ))}
      </dl>
      {issues.length > 0 && (
        <div>
          <strong>Замечания</strong>
          <ul>{issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>
        </div>
      )}
    </div>
  );
}

type DocumentsProps = {
  token: string;
  documents: DocumentItem[];
  replaceDocument: (document: DocumentItem) => void;
};

export function Documents({ token, documents, replaceDocument }: DocumentsProps) {
  const [completeness, setCompleteness] = useState<DocumentCompleteness | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [pickedFile, setPickedFile] = useState<File | null>(null);
  const [showTypes, setShowTypes] = useState<Record<number, boolean>>({});
  const [configuredTypes, setConfiguredTypes] = useState<{ value: string; label: string }[]>([]);

  useEffect(() => {
    let ignore = false;
    getAdmissionRules(token).then((rules) => {
      if (!ignore) setConfiguredTypes(rules.flatMap((rule) =>
        rule.document_requirements.map(({ document_type, title }) => ({
          value: document_type,
          label: title || document_type
        }))
      ));
    }).catch(() => {
      if (!ignore) setConfiguredTypes([]);
    });
    return () => { ignore = true; };
  }, [token]);

  // The select shows the Russian titles but submits the machine codes, so a
  // choice like «Паспорт» is stored as the code the published rule expects.
  // Rules win over the common list; first occurrence wins (Map keeps the LAST
  // entry for a duplicate key, so build the map with explicit first-wins).
  const typeTitles: Record<string, string> = Object.fromEntries(configuredTypes.map((item) => [item.value, item.label]));
  const typeOptionMap = new Map<string, { value: string; label: string }>();
  for (const item of [...configuredTypes, ...commonDocumentTypes,
    ...documents.flatMap((doc) => doc.document_type
      ? [{ value: doc.document_type, label: typeTitles[doc.document_type] ?? doc.document_type }]
      : [])]) {
    if (!typeOptionMap.has(item.value)) typeOptionMap.set(item.value, item);
  }
  const documentTypeOptions = [...typeOptionMap.values()];

  const run = async (task: () => Promise<void>) => {
    setError("");
    setPending(true);
    try {
      await task();
    } catch (requestError) {
      setError(requestErrorMessage(requestError, "Не удалось выполнить действие с документами"));
    } finally {
      setPending(false);
    }
  };

  const upload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const file = values.get("file");
    if (!(file instanceof File) || !file.name) return;
    await run(async () => {
      const document = await uploadDocument(token, file, String(values.get("document_type") ?? "").trim());
      replaceDocument(document);
      setCompleteness(null);
      form.reset();
      setPickedFile(null);
    });
  };

  const updateType = async (event: FormEvent<HTMLFormElement>, document: DocumentItem) => {
    event.preventDefault();
    const value = String(new FormData(event.currentTarget).get("document_type") ?? "").trim();
    await run(async () => {
      replaceDocument(await updateDocumentType(token, document.id, value || null));
      setCompleteness(null);
      setShowTypes((current) => ({ ...current, [document.id]: false }));
    });
  };

  const analyze = (document: DocumentItem) => run(async () => {
    const result = await analyzeDocument(token, document.id);
    replaceDocument({
      ...document,
      status: "analyzed",
      analysis_json: JSON.stringify(result.analysis, null, 2),
      analysis_error: null
    });
    setCompleteness(null);
  });

  return (
    <div className="workflow">
      <WorkflowHeader title="Документы" description="Загрузите файлы для заявления и проверьте комплект по профилю." />
      {error && <p className="error" role="alert">{error}</p>}
      <div className="workflow-documents-grid">
        <section className="workflow-panel workflow-upload-panel" aria-labelledby="upload-heading">
          <div className="workflow-panel-heading">
            <h3 id="upload-heading">Новый документ</h3>
          </div>
          <form onSubmit={upload}>
            <label>
              Тип документа
              <select name="document_type" required disabled={pending}>
                {documentTypeOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label className="workflow-dropzone">
              <span className="workflow-mark"><Icon name="upload" /></span>
              <span className="workflow-dropzone-copy">
                <strong>{pickedFile ? pickedFile.name : "Выберите файл или перетащите его сюда"}</strong>
                <small>{pickedFile ? fileSize(pickedFile.size) : "PDF, DOCX, изображения и текстовые файлы"}</small>
              </span>
              <input
                name="file"
                type="file"
                aria-label="Файл"
                required
                disabled={pending}
                onChange={(event) => setPickedFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <div className="workflow-actions">
              <button type="submit" disabled={pending}>Загрузить документ</button>
              {pending && <small role="status">Выполняется запрос…</small>}
            </div>
          </form>
        </section>

        <aside className="workflow-panel workflow-checklist-panel" aria-labelledby="checklist-heading">
          <div className="workflow-panel-heading">
            <span className="workflow-mark"><Icon name="check" /></span>
            <h3 id="checklist-heading">Проверка комплекта</h3>
          </div>
          <p>Сверьте загруженные документы с требованиями к направлению, указанному в профиле.</p>
          <button className="workflow-secondary" type="button" disabled={pending} onClick={() => run(async () => {
            setCompleteness(await getDocumentCompleteness(token));
          })}>Проверить комплект по профилю</button>
          {completeness && <CompletenessResult result={completeness} />}
        </aside>
      </div>

      <section className="workflow-panel workflow-file-list" aria-labelledby="files-heading">
        <div className="workflow-panel-heading">
          <h3 id="files-heading">Мои файлы</h3>
          {documents.length > 0 && <span className="workflow-count">{documents.length}</span>}
        </div>
        {documents.length === 0 ? (
          <WorkflowEmpty title="Документы ещё не загружены" description="Добавьте первый файл, чтобы приложить его к заявлению." icon="file" />
        ) : (
          <ul className="workflow-list">
            {documents.map((document) => (
              <li key={document.id} className="workflow-file">
                <div className="workflow-file-row">
                  <div className="workflow-file-name">
                    <span className="workflow-mark"><Icon name="file" /></span>
                    <div>
                      <h4>{document.filename}</h4>
                      <small>{documentTypeLabel(document.document_type, typeTitles)} · {fileSize(document.size_bytes)}</small>
                    </div>
                  </div>
                  <WorkflowStatus status={document.status}>{documentStatusLabel(document.status)}</WorkflowStatus>
                  <div className="workflow-actions">
                    <button className="workflow-secondary" type="button" disabled={pending} onClick={() => {
                      setShowTypes((current) => ({ ...current, [document.id]: !current[document.id] }));
                    }}>{showTypes[document.id] ? "Отменить" : "Изменить тип"}</button>
                    {document.extracted_text && document.status !== "accepted" && document.status !== "rejected" && (
                      <button className="workflow-secondary" type="button" disabled={pending} onClick={() => analyze(document)}>
                        <Icon name="spark" /> Запустить анализ
                      </button>
                    )}
                  </div>
                </div>
                {document.review_message && <p className="workflow-muted">{document.review_message}</p>}
                {document.analysis_error && <p className="error">{document.analysis_error}</p>}
                {showTypes[document.id] && (
                  <form className="workflow-inline-form" onSubmit={(event) => updateType(event, document)}>
                    <label>
                      Тип документа
                      <select name="document_type" defaultValue={document.document_type ?? ""} disabled={pending}>
                        <option value="">Без типа</option>
                        {documentTypeOptions.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
                      </select>
                    </label>
                    <button type="submit" disabled={pending}>Сохранить тип</button>
                  </form>
                )}
                {document.analysis_json && (
                  <details className="workflow-disclosure">
                    <summary>Результат анализа</summary>
                    <DocumentAnalysis content={document.analysis_json} />
                  </details>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
