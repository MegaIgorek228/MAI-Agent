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

const documentStatus: Record<string, string> = {
  uploaded: "Загружен",
  extracted: "Текст извлечён",
  analyzed: "Проанализирован",
  needs_manual_review: "Требуется ручная проверка",
  accepted: "Принят",
  rejected: "Отклонён"
};

const commonDocumentTypes = ["Паспорт", "Аттестат", "Диплом", "СНИЛС", "Заявление", "Согласие на зачисление"];

export function documentStatusLabel(status: string) {
  return documentStatus[status] ?? status;
}

export function requestErrorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export function CompletenessResult({ result }: { result: DocumentCompleteness }) {
  return (
    <div className="notice">
      <p>{result.message}</p>
      {result.missing_documents.length > 0 && (
        <p>Не хватает: {result.missing_documents.map(({ title }) => title).join(", ")}.</p>
      )}
      {Boolean(result.pending_documents?.length) && (
        <p>Ожидают проверки: {result.pending_documents?.map(({ title }) => title).join(", ")}.</p>
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
  const [showTypes, setShowTypes] = useState<Record<number, boolean>>({});
  const [configuredTypes, setConfiguredTypes] = useState<string[]>([]);

  useEffect(() => {
    let ignore = false;
    getAdmissionRules(token).then((rules) => {
      if (!ignore) setConfiguredTypes(rules.flatMap((rule) => rule.document_requirements.map(({ document_type }) => document_type)));
    }).catch(() => {
      if (!ignore) setConfiguredTypes([]);
    });
    return () => { ignore = true; };
  }, [token]);

  const documentTypes = [...new Set([
    ...configuredTypes,
    ...commonDocumentTypes,
    ...documents.flatMap((item) => item.document_type ? [item.document_type] : [])
  ])];

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
    <div className="view-stack">
      <h2>Документы</h2>
      <form onSubmit={upload}>
        <label>
          Тип документа
          <input name="document_type" list="document-types" placeholder="Например, паспорт" maxLength={100} required disabled={pending} />
        </label>
        <datalist id="document-types">
          {documentTypes.map((value) => <option key={value} value={value} />)}
        </datalist>
        <label>
          Файл
          <input name="file" type="file" required disabled={pending} />
        </label>
        <div className="actions">
          <button type="submit" disabled={pending}>Загрузить документ</button>
          <button type="button" disabled={pending} onClick={() => run(async () => {
            setCompleteness(await getDocumentCompleteness(token));
          })}>Проверить комплект по профилю</button>
        </div>
      </form>

      {pending && <p role="status">Запрос выполняется…</p>}
      {error && <p className="error" role="alert">{error}</p>}
      {completeness && <CompletenessResult result={completeness} />}
      {documents.length === 0 && <p>Документы ещё не загружены.</p>}

      {documents.map((document) => {
        return (
          <section key={document.id} className="record">
            <h3>{document.filename}</h3>
            <p>{document.document_type ?? "Тип не указан"} · {documentStatusLabel(document.status)}</p>
            {document.review_message && <p>{document.review_message}</p>}
            {document.analysis_error && <p className="error">{document.analysis_error}</p>}
            <div className="actions">
              <button type="button" disabled={pending} onClick={() => {
                setShowTypes((current) => ({ ...current, [document.id]: !current[document.id] }));
              }}>{showTypes[document.id] ? "Отменить" : "Изменить тип"}</button>
              {document.extracted_text && document.status !== "accepted" && document.status !== "rejected" && (
                <button type="button" disabled={pending} onClick={() => analyze(document)}>Запустить анализ</button>
              )}
            </div>
            {showTypes[document.id] && (
              <form onSubmit={(event) => updateType(event, document)}>
                <label>
                  Тип документа
                  <input name="document_type" defaultValue={document.document_type ?? ""} list="document-types" maxLength={100} disabled={pending} />
                </label>
                <button type="submit" disabled={pending}>Сохранить тип</button>
              </form>
            )}
            {document.analysis_json && (
              <details><summary>Результат анализа</summary><pre>{document.analysis_json}</pre></details>
            )}
          </section>
        );
      })}
    </div>
  );
}
