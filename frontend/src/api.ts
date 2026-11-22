export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

const apiFetch = async (path: string, init?: RequestInit): Promise<Response> => {
  const headers = new Headers(init?.headers);
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail: unknown = body.detail;
    if (typeof detail === "string") throw new ApiError(detail, response.status);
    if (Array.isArray(detail)) {
      const errors = detail.flatMap((item) => {
        if (!item || typeof item.msg !== "string") return [];
        const field = Array.isArray(item.loc) ? item.loc.slice(1).join(".") : "";
        return [field ? `${field}: ${item.msg}` : item.msg];
      });
      if (errors.length) throw new ApiError(errors.join(". "), response.status);
    }
    throw new ApiError(`Ошибка запроса (HTTP ${response.status})`, response.status);
  }
  return response;
};

const apiRequest = async <T>(path: string, init?: RequestInit): Promise<T> =>
  (await apiFetch(path, init)).json() as Promise<T>;

export type User = {
  id: number;
  email: string;
  role: string;
  is_active: boolean;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type Profile = {
  id: number;
  user_id: number;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  target_program: string | null;
  admission_basis: string | null;
  updated_at: string;
};

export type DocumentItem = {
  id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  document_type: string | null;
  status: string;
  extracted_text: string | null;
  review_message: string | null;
  analysis_json?: string | null;
  analysis_error?: string | null;
  created_at: string;
};

export type ChatSession = {
  id: number;
  channel: string;
  created_at: string;
};

export type DocumentRequirement = {
  document_type: string;
  title: string;
};

export type DocumentCompleteness = {
  status: string;
  documents_received: number;
  missing_documents: DocumentRequirement[];
  pending_documents?: DocumentRequirement[];
  message: string;
};

export type Applicant = { id: number; email: string; is_active: boolean };

export type ApplicationStatus = "draft" | "submitted" | "under_review" | "needs_changes" | "reviewed";

export type ApplicationFields = {
  campaign_year: number;
  program: string;
  admission_basis: string;
  document_ids: number[];
};

export type Application = ApplicationFields & {
  id: number;
  applicant_id: number;
  status: ApplicationStatus;
  review_note: string | null;
  created_at: string;
  updated_at: string;
};

export type ApplicationEvent = {
  id: number;
  status: ApplicationStatus;
  note: string | null;
  created_at: string;
};

export type ExamScore = { subject: string; year: number; score: number };

export type ExamScores = {
  scores: ExamScore[];
  synthetic_candidate_id: string | null;
  verification: {
    status: string;
    missing_subjects: string[];
    mismatched_subjects: string[];
    verified_at: string;
  } | null;
};

export type ApplicationRequirements = {
  documents: DocumentCompleteness;
  rules: AdmissionRule | null;
  ege: {
    status: string;
    missing_subjects: string[];
    below_minimum: Array<{ subject: string; score: number; minimum: number }>;
  };
};

export type AdmissionRuleFields = {
  campaign_year: number;
  program: string;
  admission_basis: string;
  source_url: string | null;
  document_requirements: DocumentRequirement[];
  subject_minima: Record<string, number>;
};

export type AdmissionRule = AdmissionRuleFields & { id: number; revision: number };

export type StaffApplication = {
  application: Application;
  applicant: Applicant;
  documents: DocumentItem[];
  ege: ExamScores;
  requirements: ApplicationRequirements;
  history: ApplicationEvent[];
};

export type ChatMessage = {
  role: string;
  content: string;
  created_at?: string;
  image_document_id?: number | null;
  image_filename?: string | null;
};

export type TelegramPairingCode = {
  code: string;
  expires_at: string;
};

export const register = (email: string, password: string, inviteCode?: string) =>
  apiRequest<User>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, invite_code: inviteCode || null })
  });

export const login = (email: string, password: string) =>
  apiRequest<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password })
  });

export const getCurrentUser = (token: string) =>
  apiRequest<User>("/users/me", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getProfile = (token: string) =>
  apiRequest<Profile>("/applicant/profile", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const updateProfile = (token: string, profile: Partial<Profile>) =>
  apiRequest<Profile>("/applicant/profile", {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(profile)
  });

export const getDocuments = (token: string) =>
  apiRequest<DocumentItem[]>("/applicant/documents", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const uploadDocument = (token: string, file: File, documentType: string) => {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("document_type", documentType);
  return apiRequest<DocumentItem>("/applicant/documents", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData
  });
};

export const getStaffApplicants = (token: string, query: string) =>
  apiRequest<StaffApplicantRow[]>(`/applicant/staff/applicants?limit=100&${query ? `q=${encodeURIComponent(query)}` : ""}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getStaffApplicantCard = (token: string, applicantId: number) =>
  apiRequest<StaffApplicantCard>(`/applicant/staff/applicants/${applicantId}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

// --- Individual achievements ------------------------------------------------

export type AchievementCategory = "olympiad" | "sport" | "gto" | "volunteering" | "creative" | "other";
export type AchievementLevel = "school" | "municipal" | "regional" | "national" | "international";
export type AchievementStatus = "draft" | "pending" | "confirmed" | "rejected" | "needs_revision";

export type AchievementItem = {
  id: number;
  applicant_id: number;
  application_id: number | null;
  category: AchievementCategory;
  title: string;
  level: AchievementLevel | null;
  achieved_on: string;
  organization: string | null;
  description: string | null;
  status: AchievementStatus;
  document: {
    id: number;
    filename: string;
    content_type: string;
    size_bytes: number;
    created_at: string;
  } | null;
  submitted_at: string | null;
  review_comment: string | null;
  reviewed_by: number | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type AchievementReviewEntry = {
  id: number;
  action: string;
  comment: string | null;
  actor_id: number | null;
  created_at: string;
};

export type StaffAchievementCard = AchievementItem & {
  applicant: { id: number; email: string; first_name: string | null; last_name: string | null };
  history: AchievementReviewEntry[];
};

export type StaffDashboardData = {
  applicants_total: number;
  applications_in_work: number;
  applications_awaiting_review: number;
  documents_awaiting_review: number;
  achievements_awaiting_review: number;
  recent_activity: Array<{
    source: "application" | "achievement";
    reference_id: number;
    action: string;
    note: string | null;
    actor_id: number | null;
    created_at: string;
  }>;
};

export type StaffApplicantApplication = {
  id: number;
  campaign_year: number;
  program: string;
  admission_basis: string;
  status: string;
  document_count: number;
  documents_pending: number;
  updated_at: string;
};

export type StaffApplicantRow = {
  id: number;
  email: string;
  is_active: boolean;
  first_name: string | null;
  last_name: string | null;
  created_at: string;
  applications: StaffApplicantApplication[];
};

export type StaffApplicantCard = {
  profile: {
    id: number;
    email: string;
    is_active: boolean;
    first_name: string | null;
    last_name: string | null;
    phone: string | null;
    target_program: string | null;
    admission_basis: string | null;
  };
  applications: StaffApplicantApplication[];
  ege: Array<{
    application_id: number;
    synthetic_candidate_id: string | null;
    scores: Array<{ subject: string; year: number; score: number }>;
    verification: {
      status: string;
      missing_subjects: string[];
      mismatched_subjects: string[];
      verified_at: string;
    } | null;
  }>;
  achievements: AchievementItem[];
  history: Array<{
    source: "application" | "achievement";
    reference_id: number;
    action: string;
    note: string | null;
    actor_id: number | null;
    created_at: string;
  }>;
};

export const getStaffDashboard = (token: string) =>
  apiRequest<StaffDashboardData>("/applicant/staff/dashboard", {
    headers: { Authorization: `Bearer ${token}` }
  });

const achievementParams = (params: Record<string, string | number | undefined>) => {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const query = search.toString();
  return query ? `?${query}` : "";
};

export const getAchievements = (token: string) =>
  apiRequest<AchievementItem[]>("/applicant/achievements", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const createAchievement = (token: string, values: {
  category: AchievementCategory;
  title: string;
  level: AchievementLevel | null;
  achieved_on: string;
  organization: string | null;
  description: string | null;
  application_id: number | null;
  document_id: number | null;
}) =>
  apiRequest<AchievementItem>("/applicant/achievements", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(values)
  });

export const updateAchievement = (
  token: string,
  id: number,
  values: Partial<{
    category: AchievementCategory;
    title: string;
    level: AchievementLevel | null;
    achieved_on: string;
    organization: string | null;
    description: string | null;
    application_id: number | null;
    document_id: number | null;
  }>
) =>
  apiRequest<AchievementItem>(`/applicant/achievements/${id}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(values)
  });

export const submitAchievement = (token: string, id: number) =>
  apiRequest<AchievementItem>(`/applicant/achievements/${id}/submit`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  });

export const getAchievementHistory = (token: string, id: number) =>
  apiRequest<AchievementReviewEntry[]>(`/applicant/achievements/${id}/history`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getStaffAchievements = (
  token: string,
  filters: { status?: string; category?: string; q?: string; limit?: number; offset?: number }
) =>
  apiRequest<AchievementItem[]>(
    `/applicant/staff/achievements${achievementParams({ ...filters, limit: filters.limit ?? 50, offset: filters.offset ?? 0 })}`,
    { headers: { Authorization: `Bearer ${token}` } }
  );

export const getStaffAchievementCard = (token: string, id: number) =>
  apiRequest<StaffAchievementCard>(`/applicant/staff/achievements/${id}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const reviewAchievement = (
  token: string,
  id: number,
  action: "confirmed" | "rejected" | "needs_revision",
  comment: string
) =>
  apiRequest<StaffAchievementCard>(`/applicant/staff/achievements/${id}/review`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ action, comment: comment || null })
  });

export const downloadAchievementDocument = async (token: string, achievementId: number) => {
  const response = await apiFetch(`/applicant/staff/achievements/${achievementId}/document/file`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  return response.blob();
};


export const getDocumentCompleteness = (token: string) =>
  apiRequest<DocumentCompleteness>("/applicant/documents/completeness", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const updateDocumentType = (token: string, documentId: number, documentType: string | null) =>
  apiRequest<DocumentItem>(`/applicant/documents/${documentId}/type`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ document_type: documentType })
  });

export const analyzeDocument = (token: string, documentId: number) =>
  apiRequest<{ document_id: number; analysis: Record<string, unknown> }>(
    `/applicant/documents/${documentId}/analyze`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` }
    }
  );

export const listChatSessions = (token: string) =>
  apiRequest<ChatSession[]>("/chat/sessions", {
    headers: { Authorization: `Bearer ${token}` }
  });

const applicationsPath = "/applicant/applications";

export const getApplications = (token: string) =>
  apiRequest<Application[]>(applicationsPath, { headers: { Authorization: `Bearer ${token}` } });

export const saveApplication = (token: string, values: ApplicationFields, id?: number) =>
  apiRequest<Application>(id === undefined ? applicationsPath : `${applicationsPath}/${id}`, {
    method: id === undefined ? "POST" : "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(values)
  });

export const submitApplication = (token: string, id: number) =>
  apiRequest<Application>(`${applicationsPath}/${id}/submit`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  });

export const getApplicationRequirements = (token: string, id: number) =>
  apiRequest<ApplicationRequirements>(`${applicationsPath}/${id}/requirements`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getApplicationEvents = (token: string, id: number) =>
  apiRequest<ApplicationEvent[]>(`${applicationsPath}/${id}/events`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getApplicationDocuments = (token: string, id: number) =>
  apiRequest<DocumentItem[]>(`${applicationsPath}/${id}/documents`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getExamScores = (token: string, id: number) =>
  apiRequest<ExamScores>(`${applicationsPath}/${id}/ege`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const saveExamScores = (token: string, id: number, scores: ExamScore[], syntheticId: string | null) =>
  apiRequest<ExamScores>(`${applicationsPath}/${id}/ege`, {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ scores, synthetic_candidate_id: syntheticId })
  });

export const verifyExamScores = (token: string, id: number) =>
  apiRequest<ExamScores>(`${applicationsPath}/${id}/ege/verify`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  });

export const refreshExamScores = (token: string, id: number, candidateId: string) =>
  apiRequest<ExamScores>(`${applicationsPath}/${id}/ege/synthetic-confirm`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ candidate_id: candidateId })
  });

export const getAdmissionRules = (token: string) =>
  apiRequest<AdmissionRule[]>("/applicant/admission-rules", {
    headers: { Authorization: `Bearer ${token}` }
  });

export const publishAdmissionRule = (token: string, values: AdmissionRuleFields) =>
  apiRequest<AdmissionRule>("/applicant/staff/admission-rules", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(values)
  });

const staffApplicationsPath = "/applicant/staff/applications";

export const getStaffApplications = (token: string, filters: URLSearchParams) =>
  apiRequest<Application[]>(`${staffApplicationsPath}?${filters}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const getStaffApplication = (token: string, id: number) =>
  apiRequest<StaffApplication>(`${staffApplicationsPath}/${id}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

export const reviewApplication = (token: string, id: number, status: ApplicationStatus, reviewNote: string) =>
  apiRequest<Application>(`${staffApplicationsPath}/${id}/status`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status, review_note: reviewNote })
  });

export const reviewApplicationDocument = (
  token: string,
  applicationId: number,
  documentId: number,
  status: "accepted" | "rejected",
  reviewNote: string
) =>
  apiRequest<DocumentItem>(`${staffApplicationsPath}/${applicationId}/documents/${documentId}`, {
    method: "PATCH",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status, review_note: reviewNote })
  });

export const downloadApplicationDocument = async (token: string, applicationId: number, documentId: number) => {
  const response = await apiFetch(`${staffApplicationsPath}/${applicationId}/documents/${documentId}/file`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  return response.blob();
};

export const createChatSession = (token: string) =>
  apiRequest<{ id: number; channel: string; hermes_session_id: string }>("/chat/sessions", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ channel: "web" })
  });

export const sendChatMessage = (
  token: string,
  sessionId: number,
  content: string,
  imageDocumentId?: number
) =>
  apiRequest<ChatMessage>(`/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      content,
      image_document_id: imageDocumentId ?? null
    })
  });

export const getChatMessages = (token: string, sessionId: number) =>
  apiRequest<ChatMessage[]>(`/chat/sessions/${sessionId}/messages`, {
    headers: { Authorization: `Bearer ${token}` }
  });

/** URL for loading an attached image in chat history. Uses the
 * `access_token` query parameter because plain `<img>` tags cannot set
 * custom headers. */
export const documentFileUrl = (token: string, documentId: number) =>
  `/applicant/documents/${documentId}/file?access_token=${encodeURIComponent(token)}`;

export const createTelegramPairingCode = (token: string) =>
  apiRequest<TelegramPairingCode>("/auth/telegram/pairing-code", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` }
  });
