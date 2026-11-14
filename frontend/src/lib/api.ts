/**
 * API client for the Taalmel Sync backend.
 *
 * Token handling: the access token lives in memory and is mirrored to
 * sessionStorage so a refresh does not log the caregiver out. It is deliberately
 * NOT in localStorage: this app holds family medical records, and a token that
 * survives every tab and browser restart is a bigger exposure than the convenience
 * is worth.
 */

const BASE = import.meta.env.VITE_API_BASE ?? "";

const ACCESS_KEY = "taalmel.access";
const REFRESH_KEY = "taalmel.refresh";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getAccessToken(): string | null {
  return sessionStorage.getItem(ACCESS_KEY);
}

export function getRefreshToken(): string | null {
  return sessionStorage.getItem(REFRESH_KEY);
}

export function setTokens(access: string, refresh?: string | null): void {
  sessionStorage.setItem(ACCESS_KEY, access);
  if (refresh) sessionStorage.setItem(REFRESH_KEY, refresh);
}

export function clearTokens(): void {
  sessionStorage.removeItem(ACCESS_KEY);
  sessionStorage.removeItem(REFRESH_KEY);
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  form?: FormData;
  auth?: boolean;
  idempotencyKey?: string;
  signal?: AbortSignal;
  // Evidence writes are safe to queue: the server dedupes them by idempotency key.
  offlineQueue?: boolean;
};

type QueuedWrite = {
  path: string;
  method: "POST";
  body: unknown;
  idempotencyKey: string;
};

const OFFLINE_KEY = "taalmel.outbox";

function readOutbox(): QueuedWrite[] {
  try {
    return JSON.parse(localStorage.getItem(OFFLINE_KEY) || "[]") as QueuedWrite[];
  } catch {
    return [];
  }
}

function writeOutbox(items: QueuedWrite[]): void {
  localStorage.setItem(OFFLINE_KEY, JSON.stringify(items));
}

export function queuedWriteCount(): number {
  return readOutbox().length;
}

export function clearOutbox(): void {
  localStorage.removeItem(OFFLINE_KEY);
}

function enqueueWrite(path: string, body: unknown, key?: string): void {
  const items = readOutbox();
  items.push({
    path,
    method: "POST",
    body,
    idempotencyKey: key || crypto.randomUUID(),
  });
  writeOutbox(items);
}

export async function flushOutbox(): Promise<number> {
  const items = readOutbox();
  if (items.length === 0) return 0;
  const remaining: QueuedWrite[] = [];
  let sent = 0;
  for (const item of items) {
    try {
      await request(item.path, {
        method: item.method,
        body: item.body,
        idempotencyKey: item.idempotencyKey,
      });
      sent += 1;
    } catch {
      remaining.push(item);
    }
  }
  writeOutbox(remaining);
  return sent;
}

async function parseError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.error === "string") return data.error;
    if (typeof data?.detail === "string") return data.detail;
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) return String(data.detail[0].msg);
  } catch {
    /* fall through */
  }
  return `Request failed (${response.status})`;
}

let refreshInFlight: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  const refresh = getRefreshToken();
  if (!refresh) return false;

  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const response = await fetch(`${BASE}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!response.ok) return false;
      const data = await response.json();
      setTokens(data.access_token, data.refresh_token);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const {
    method = "GET",
    body,
    form,
    auth = true,
    idempotencyKey,
    signal,
    offlineQueue = false,
  } = options;

  if (offlineQueue && typeof navigator !== "undefined" && !navigator.onLine) {
    enqueueWrite(path, body, idempotencyKey);
    return { id: "queued", queued: true } as T;
  }

  const headers: Record<string, string> = {};
  if (form === undefined && body !== undefined) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  const token = getAccessToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    });
  } catch (err) {
    if (offlineQueue) {
      enqueueWrite(path, body, idempotencyKey);
      return { id: "queued", queued: true } as T;
    }
    throw err;
  }

  // An expired access token is normal; refresh once and retry.
  if (response.status === 401 && auth && getRefreshToken()) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      const retryHeaders = { ...headers, Authorization: `Bearer ${getAccessToken()}` };
      try {
        response = await fetch(`${BASE}${path}`, {
          method,
          headers: retryHeaders,
          body: form ?? (body !== undefined ? JSON.stringify(body) : undefined),
          signal,
        });
      } catch (err) {
        if (offlineQueue) {
          enqueueWrite(path, body, idempotencyKey);
          return { id: "queued", queued: true } as T;
        }
        throw err;
      }
    } else {
      clearTokens();
    }
  }

  if (!response.ok) {
    throw new ApiError(await parseError(response), response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

// ── Types shared by the screens ──────────────────────────────────────

export type User = { id: string; role: string; name: string; phone: string | null };

export type Tokens = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  user: User;
};

export type Patient = {
  patient_id: string;
  household_member_id: string;
  household_id: string;
  display_name: string;
  relationship: string | null;
};

export type CreatedHousehold = {
  household: { id: string; name: string };
  patient: Patient;
};

export type DimensionState = {
  status: string;
  last_verified: string | null;
  age_days: number | null;
  stale: boolean;
  source_event_id: string | null;
  details: Record<string, unknown>;
};

export type MedicationState = {
  medication_id: string;
  prescribed: DimensionState;
  available: DimensionState;
  reported_taking: DimensionState;
  confirmed_status: DimensionState;
  current_dose: string | null;
  dose_history: { dose: string; changed_at: string; event_id: string }[];
  event_count: number;
};

export type Medication = {
  id: string;
  household_member_id: string;
  name_raw: string;
  name_generic: string | null;
  name_brand: string | null;
  strength: string | null;
  dosage_form: string | null;
  frequency: string | null;
  normalization_status: string;
  normalization_method: string | null;
  normalization_confidence: number | null;
  identity_confirmed: boolean;
};

export type Summary = {
  medicines_total: number;
  confirmed: number;
  needs_checking: number;
  open_cases: number;
  near_expiry: number;
  expired: number;
};

export type CaseRow = {
  id: string;
  medication_id: string;
  medication_name: string | null;
  issue: string | null;
  trigger_event_id: string | null;
  status: string;
  action_taken: string | null;
  reason_code: string | null;
  opened_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
};

export type Explanation = {
  what: string;
  why: string;
  source: string;
  status: string;
  action: string;
  reason_recorded: string | null;
  taalmel_does_not: string;
};

export type NotificationRow = {
  id: string;
  title: string;
  body: string;
  rule: string | null;
  is_read: boolean;
  created_at: string;
};

export type Prescription = {
  id: string;
  household_member_id: string;
  original_filename: string;
  prescribed_by?: string | null;
  prescribed_on?: string | null;
  ocr_status: string;
  ocr_error: string | null;
  ocr_raw_text?: string | null;
  verified: boolean;
  items: {
    id: string;
    medication_name: string;
    dosage: string | null;
    frequency: string | null;
    instructions: string | null;
    confidence: number;
    verified: boolean;
  }[];
};

export type TodayItem = {
  medication_id: string;
  name: string;
  dose: string | null;
  confirmed_status: string;
  reported_taking: string;
  instruction: string | null;
  plain_explanation: string | null;
  explanation_source: string | null;
};

export type SafetyResult = {
  normalized_names: string[];
  pairs: { a: string; b: string; result: string; detail: string | null; source: string | null }[];
  uncovered: string[];
  disclaimer: string;
};

export type RefillItem = {
  medication_id: string;
  name: string;
  dose: string | null;
  reason: string;
  basis: string;
};

export type QuestionRow = {
  id: string;
  medication_id: string | null;
  question_text: string;
  raised_by: string;
  status: string;
  created_at: string;
  discussed_at: string | null;
  note: string;
};

// ── Endpoint helpers ─────────────────────────────────────────────────

export const api = {
  register: (
    name: string,
    phone: string,
    password: string,
    role = "caregiver",
    email?: string,
  ) =>
    request<Tokens>("/api/auth/register", {
      method: "POST",
      auth: false,
      body: { name, phone, password, role, email: email || null },
    }),

  login: (phone: string, password: string) =>
    request<Tokens>("/api/auth/login", {
      method: "POST",
      auth: false,
      body: { phone, password },
    }),

  logout: () => request<void>("/api/auth/logout", { method: "POST" }),

  me: () => request<User>("/api/auth/me"),

  createHousehold: (
    household_name: string,
    patient_display_name: string,
    consent_recorded = false,
  ) =>
    request<CreatedHousehold>("/api/households", {
      method: "POST",
      body: { household_name, patient_display_name, consent_recorded },
    }),

  getPatient: (patientId: string) => request<Patient>(`/api/patients/${patientId}`),

  prescriptionsForPatient: (patientId: string) =>
    request<Prescription[]>(`/api/patients/${patientId}/prescriptions`),

  getPrescription: (prescriptionId: string) =>
    request<Prescription>(`/api/prescriptions/${prescriptionId}`),

  summary: (memberId: string) => request<Summary>(`/api/households/${memberId}/summary`),

  medications: (memberId: string) =>
    request<Medication[]>(`/api/medications?household_member_id=${encodeURIComponent(memberId)}`),

  today: (memberId: string) => request<TodayItem[]>(`/api/households/${memberId}/today`),

  openCases: (memberId: string) => request<CaseRow[]>(`/api/households/${memberId}/open-cases`),

  notifications: () => request<NotificationRow[]>("/api/notifications"),

  markNotificationRead: (id: string) =>
    request<NotificationRow>(`/api/notifications/${id}/read`, { method: "POST" }),

  medicationsForMember: (memberId: string) =>
    request<Medication[]>(`/api/medications/needs-review?household_member_id=${memberId}`),

  medicationState: (medicationId: string) =>
    request<MedicationState>(`/api/medications/${medicationId}/state`),

  report: (medicationId: string, taking: boolean, reason?: string, note?: string) =>
    request<{ id: string }>(`/api/medications/${medicationId}/report`, {
      method: "POST",
      body: { taking, reason: reason ?? null, note: note ?? null },
      offlineQueue: true,
    }),

  availability: (
    medicationId: string,
    present: boolean,
    quantityNote?: string | null,
    expiryDate?: string | null,
  ) =>
    request<{ id: string }>(`/api/medications/${medicationId}/availability`, {
      method: "POST",
      body: {
        present,
        quantity_note: quantityNote ?? null,
        expiry_date: expiryDate ?? null,
      },
      offlineQueue: true,
    }),

  detect: (medicationId: string) =>
    request<CaseRow[]>(`/api/medications/${medicationId}/detect`, { method: "POST" }),

  explainCase: (caseId: string) => request<Explanation>(`/api/cases/${caseId}/explain`),

  recordReason: (caseId: string, reason: string, note?: string) =>
    request<{
      case: CaseRow;
      action: string;
      action_description: string;
      closes_case: boolean;
      resources: { name: string; description: string; url: string }[] | null;
    }>(`/api/cases/${caseId}/reason`, {
      method: "POST",
      body: { reason, note: note ?? null },
    }),

  resolveCase: (caseId: string, outcome: string, resolutionNote?: string) =>
    request<CaseRow>(`/api/cases/${caseId}/resolve`, {
      method: "POST",
      body: { outcome, resolution_note: resolutionNote ?? null },
    }),

  doctorExport: (memberId: string) =>
    request<Record<string, unknown>>(`/api/households/${memberId}/doctor-export`),

  doctorLink: (memberId: string) =>
    request<{ token: string; url_path: string; expires_at: string }>(
      `/api/households/${memberId}/doctor-link`,
      { method: "POST" },
    ),

  doctorLinkQr: (memberId: string, baseUrl: string) =>
    request<{ url: string; token: string; expires_at: string; qr_png_base64: string }>(
      `/api/households/${memberId}/doctor-link/qr?base_url=${encodeURIComponent(baseUrl)}`,
      { method: "POST" },
    ),

  // The browser cannot send an Authorization header on a plain download, so the export
  // is fetched with the token and opened as a blob.
  downloadExport: async (memberId: string, format: "pdf" | "html"): Promise<Blob> => {
    const token = getAccessToken();
    const response = await fetch(
      `${BASE}/api/households/${memberId}/doctor-export?format=${format}`,
      { headers: token ? { Authorization: `Bearer ${token}` } : {} },
    );
    if (!response.ok) throw new ApiError(await parseError(response), response.status);
    return response.blob();
  },

  languages: () =>
    request<{ code: string; name: string; native: string }[]>("/api/i18n/languages", {
      auth: false,
    }),

  catalogue: (language: string) =>
    request<{ language: string; strings: Record<string, string>; coverage: { translated: number; total: number } }>(
      `/api/i18n/${language}`,
      { auth: false },
    ),

  voiceReport: (memberId: string, audio: Blob, language?: string) => {
    const form = new FormData();
    form.append("audio", audio, "report.wav");
    const query = language ? `?language=${encodeURIComponent(language)}` : "";
    return request<{
      recorded: boolean;
      medication_id: string | null;
      medication_name: string | null;
      taking: boolean | null;
      transcript: string;
      clarification: string | null;
    }>(`/api/households/${memberId}/voice-report${query}`, { method: "POST", form });
  },

  voiceReportText: (memberId: string, transcript: string, language?: string) => {
    const form = new FormData();
    form.append("transcript", transcript);
    const query = language ? `?language=${encodeURIComponent(language)}` : "";
    return request<{
      recorded: boolean;
      medication_id: string | null;
      medication_name: string | null;
      taking: boolean | null;
      transcript: string;
      clarification: string | null;
    }>(`/api/households/${memberId}/voice-report${query}`, { method: "POST", form });
  },

  prescriptionDetails: (
    prescriptionId: string,
    prescribed_by: string | null,
    prescribed_on: string | null,
  ) =>
    request<Prescription>(`/api/prescriptions/${prescriptionId}`, {
      method: "PATCH",
      body: { prescribed_by, prescribed_on },
    }),

  addPrescriptionItem: (
    prescriptionId: string,
    item: { medication_name: string; dosage?: string | null; frequency?: string | null; instructions?: string | null },
  ) =>
    request<Prescription["items"][number]>(`/api/prescriptions/${prescriptionId}/items`, {
      method: "POST",
      body: item,
    }),

  parsePrescriptionText: (prescriptionId: string, text: string) =>
    request<Prescription["items"]>(`/api/prescriptions/${prescriptionId}/parse-text`, {
      method: "POST",
      body: { text },
    }),

  labReports: (patientId: string) =>
    request<
      {
        id: string;
        original_filename: string;
        ocr_status: string;
        captured_on: string | null;
        lab_name: string | null;
        values: { test_name: string; value: string; unit: string | null; reference_range_raw: string | null }[];
      }[]
    >(`/api/patients/${patientId}/lab-reports`),

  uploadLabReport: (patientId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Record<string, unknown>>(`/api/patients/${patientId}/lab-reports/upload`, {
      method: "POST",
      form,
    });
  },

  wellnessTimeline: (patientId: string) =>
    request<
      { date: string; kind: string; title: string; detail: string | null; source: string | null }[]
    >(`/api/patients/${patientId}/wellness-timeline`),

  symptomReport: (patientId: string, symptom_text: string, severity: string) =>
    request<{ id: string; symptom_text: string; severity: string; care_action: string }>(
      `/api/patients/${patientId}/symptoms`,
      { method: "POST", body: { symptom_text, severity } },
    ),

  refillOrder: (memberId: string) =>
    request<{
      id: string;
      provider: string;
      provider_order_id: string | null;
      status: string;
      detail: string | null;
      items: { name: string; dose: string | null; reason: string }[];
      created_at: string;
    }>(`/api/households/${memberId}/refill-orders`, { method: "POST" }),

  doctorRedeem: (token: string) =>
    request<{ household_member_id: string; name: string; granted_at: string; expires_at: string | null }>(
      "/api/doctor/redeem",
      { method: "POST", body: { token } },
    ),

  doctorPatients: () =>
    request<{ household_member_id: string; name: string; granted_at: string; expires_at: string | null }[]>(
      "/api/doctor/patients",
    ),

  doctorPatientExport: (memberId: string) =>
    request<Record<string, unknown>>(`/api/doctor/patients/${memberId}/export`),

  taper: (medicationId: string, day?: number) =>
    request<{
      medication_id: string;
      medicine: string;
      schedule: { step: number; dose: string; duration_days: number }[];
      current_step: number | null;
      expected_dose: string | null;
      reported_dose: string | null;
      finding: string;
      detail: string;
    }>(`/api/medications/${medicationId}/taper${day !== undefined ? `?day=${day}` : ""}`),

  setTaper: (medicationId: string, scheduleText: string) =>
    request<{
      schedule: { step: number; dose: string; duration_days: number }[];
      finding: string;
      detail: string;
    }>(`/api/medications/${medicationId}/taper`, {
      method: "POST",
      body: { schedule_text: scheduleText },
    }),

  photoVerify: (medicationId: string, photo: File) => {
    const form = new FormData();
    form.append("photo", photo);
    return request<{
      id: string;
      outcome: string;
      detail: string | null;
      confidence: number | null;
      created_at: string;
    }>(`/api/medications/${medicationId}/photo-verify`, { method: "POST", form });
  },

  safetyCheck: (memberId: string) =>
    request<SafetyResult>(`/api/households/${memberId}/safety-check`),

  refillList: (memberId: string) => request<RefillItem[]>(`/api/households/${memberId}/refill-list`),

  questions: (memberId: string) =>
    request<QuestionRow[]>(`/api/households/${memberId}/questions`),

  addQuestion: (memberId: string, question_text: string) =>
    request<QuestionRow>(`/api/households/${memberId}/questions`, {
      method: "POST",
      body: { question_text },
    }),

  uploadPrescription: (memberId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<Prescription>(
      `/api/prescriptions/upload?household_member_id=${encodeURIComponent(memberId)}`,
      { method: "POST", form },
    );
  },

  uploadDocument: (memberId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{
      document_id: string;
      document_type: "PRESCRIPTION" | "LAB_REPORT" | "DISCHARGE_SUMMARY" | "INVOICE" | "OTHER";
      ocr_status: string;
      prescription_id: string | null;
      lab_report_id: string | null;
      item_count: number;
      value_count: number;
      message: string;
      raw_text_preview: string;
    }>(`/api/documents/upload?household_member_id=${encodeURIComponent(memberId)}`, {
      method: "POST",
      form,
    });
  },

  documentAsPrescription: (documentId: string) =>
    request<{ prescription_id: string }>(`/api/documents/${documentId}/as-prescription`, {
      method: "POST",
    }),

  documents: (patientId: string) =>
    request<
      {
        id: string;
        document_type: string;
        original_filename: string;
        ocr_status: string;
        ocr_error: string | null;
        captured_on: string | null;
        created_at: string;
        raw_text_preview: string;
      }[]
    >(`/api/patients/${patientId}/documents`),

  verifyPrescription: (
    prescriptionId: string,
    items: { item_id: string; medication_name: string; dosage?: string | null; frequency?: string | null }[],
  ) =>
    request<{ prescription_id: string; medication_results: unknown[] }>(
      `/api/prescriptions/${prescriptionId}/verify`,
      { method: "POST", body: { items } },
    ),
};
