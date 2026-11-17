import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, Camera, FileUp, Package, Send } from "lucide-react";
import { api } from "../lib/api";
import type { QuestionRow } from "../lib/api";
import { useHousehold } from "../lib/household";
import CameraCapture from "../components/CameraCapture";

type TimelineRow = {
  date: string;
  kind: string;
  title: string;
  detail: string | null;
  source: string | null;
};

type RefillItem = { medication_id: string; name: string; dose: string | null; reason: string; basis: string };

const TODAY_ISO = new Date().toISOString().slice(0, 10);

export default function Wellness() {
  const { patient } = useHousehold();
  const [timeline, setTimeline] = useState<TimelineRow[]>([]);
  const [refills, setRefills] = useState<RefillItem[]>([]);
  const [labs, setLabs] = useState<{ id: string; captured_on: string | null; values: { test_name: string; value: string; unit: string | null }[] }[]>([]);
  const [questions, setQuestions] = useState<QuestionRow[]>([]);
  const [documents, setDocuments] = useState<
    { id: string; document_type: string; original_filename: string; ocr_status: string; created_at: string }[]
  >([]);
  const [question, setQuestion] = useState("");
  const [symptom, setSymptom] = useState("");
  const [severity, setSeverity] = useState("ROUTINE");
  const [labDate, setLabDate] = useState("");
  const [showLabCamera, setShowLabCamera] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const labRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!patient) return;
    const [events, refillRows, labRows, questionRows, documentRows] = await Promise.all([
      api.wellnessTimeline(patient.patient_id),
      api.refillList(patient.household_member_id),
      api.labReports(patient.patient_id),
      api.questions(patient.household_member_id),
      api.documents(patient.patient_id),
    ]);
    setTimeline(events);
    setRefills(refillRows);
    setLabs(labRows);
    setQuestions(questionRows);
    setDocuments(documentRows);
  }, [patient]);

  useEffect(() => {
    void load().catch((err) => setMessage(err instanceof Error ? err.message : "Could not load."));
  }, [load]);

  async function uploadLab(file: File | undefined) {
    if (!patient || !file) return;
    setBusy(true);
    try {
      const result = await api.uploadDocument(patient.household_member_id, file, {
        prescribed_on: labDate ? new Date(labDate).toISOString() : null,
      });
      setMessage(result.message);
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not upload the report.");
    } finally {
      setBusy(false);
      if (labRef.current) labRef.current.value = "";
    }
  }

  async function submitSymptom() {
    if (!patient || !symptom.trim()) return;
    setBusy(true);
    try {
      const row = await api.symptomReport(patient.patient_id, symptom.trim(), severity);
      setMessage(row.care_action);
      setSymptom("");
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not record the symptom.");
    } finally {
      setBusy(false);
    }
  }

  async function submitQuestion() {
    if (!patient || !question.trim()) return;
    setBusy(true);
    try {
      await api.addQuestion(patient.household_member_id, question.trim());
      setQuestion("");
      setMessage("Saved to the Ask My Doctor list. Taalmel does not answer clinical questions.");
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not save the question.");
    } finally {
      setBusy(false);
    }
  }

  async function orderRefills() {
    if (!patient) return;
    setBusy(true);
    try {
      const order = await api.refillOrder(patient.household_member_id);
      setMessage(`Refill order ${order.id}: ${order.status}. ${order.detail ?? ""}`);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not create the refill order.");
    } finally {
      setBusy(false);
    }
  }

  if (!patient) return null;

  return (
    <div className="mx-auto max-w-[1080px] space-y-6">
      <div>
        <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Patient record</p>
        <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
          Wellness timeline
        </h1>
        <p className="mt-1 font-inter text-[12.5px] text-ink/50">
          What happened, in order. Nothing here is a diagnosis or a health score.
        </p>
      </div>

      {message && (
        <p className="rounded-lg border border-ink/10 bg-paper px-4 py-3 font-inter text-[13px] text-ink/75">
          {message}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-xl border border-ink/10 bg-paper p-4">
          <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
            <Activity className="h-4 w-4 text-ink/40" /> Timeline
          </h2>
          <ul className="mt-3 space-y-2">
            {timeline.length === 0 ? (
              <li className="font-inter text-[12.5px] text-ink/45">No events yet.</li>
            ) : (
              timeline.map((row, index) => (
                <li key={`${row.date}-${index}`} className="border-l border-ink/12 pl-3">
                  <p className="font-inter text-[12.5px] font-medium text-ink">{row.title}</p>
                  {row.detail && <p className="font-inter text-[11.5px] text-ink/55">{row.detail}</p>}
                  <p className="font-inter text-[10.5px] text-ink/35">
                    {new Date(row.date).toLocaleString()} {row.source ? `· ${row.source}` : ""}
                  </p>
                </li>
              ))
            )}
          </ul>
        </section>

        <section className="space-y-4">
          <div className="rounded-xl border border-ink/10 bg-paper p-4">
            <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
              <Send className="h-4 w-4 text-ink/40" /> Report a symptom
            </h2>
            <textarea
              value={symptom}
              onChange={(event) => setSymptom(event.target.value)}
              placeholder="Describe what you are feeling, in your own words."
              className="mt-2 min-h-20 w-full rounded-md border border-ink/15 bg-white px-3 py-2 font-inter text-[13px] text-ink outline-none"
            />
            <div className="mt-2 flex gap-2">
              <select
                value={severity}
                onChange={(event) => setSeverity(event.target.value)}
                className="h-10 rounded-md border border-ink/15 bg-white px-2 font-inter text-[12.5px]"
              >
                <option value="ROUTINE">Routine</option>
                <option value="URGENT">Urgent</option>
                <option value="EMERGENCY">Emergency</option>
              </select>
              <button
                type="button"
                disabled={busy || !symptom.trim()}
                onClick={() => void submitSymptom()}
                className="rounded-md bg-ink px-3 py-2 font-inter text-[12.5px] font-medium text-white disabled:opacity-50"
              >
                Record
              </button>
            </div>
            <p className="mt-2 font-inter text-[11px] text-ink/40">
              Taalmel records the symptom and routes you to care. It never diagnoses or names a medicine.
            </p>
          </div>

          <div className="rounded-xl border border-ink/10 bg-paper p-4">
            <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
              <FileUp className="h-4 w-4 text-ink/40" /> Lab reports
            </h2>

            <div className="mt-3">
              <label className="block">
                <span className="font-inter text-[11.5px] font-medium text-ink/60">
                  Test / Collection date
                </span>
                <div className="mt-1 flex items-center gap-1.5">
                  <input
                    type="date"
                    value={labDate}
                    max={TODAY_ISO}
                    onChange={(e) => setLabDate(e.target.value)}
                    className="h-8 rounded-md border border-ink/15 bg-white px-2.5 font-inter text-[12px] text-ink outline-none"
                  />
                  <button
                    type="button"
                    onClick={() => setLabDate(TODAY_ISO)}
                    className="h-8 rounded-md border border-ink/15 bg-white px-2 font-inter text-[11px] text-ink/65 hover:text-ink"
                  >
                    Today
                  </button>
                </div>
              </label>
              {!labDate && (
                <p className="mt-1 font-inter text-[11px] text-amber-700">
                  ⚠️ Without a collection date, test values may appear as &ldquo;undated&rdquo;.
                </p>
              )}
            </div>

            <input
              ref={labRef}
              type="file"
              accept="image/jpeg,image/png,application/pdf"
              className="hidden"
              onChange={(e) => void uploadLab(e.target.files?.[0])}
            />

            <div className="mt-2.5 flex items-center gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => setShowLabCamera(true)}
                className="flex items-center gap-1.5 rounded-md border border-ink/15 bg-white px-3 py-1.5 font-inter text-[12.5px] text-ink/75 hover:text-ink disabled:opacity-50"
              >
                <Camera className="h-3.5 w-3.5" />
                Take photo
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => labRef.current?.click()}
                className="flex items-center gap-1.5 rounded-md border border-ink/15 bg-white px-3 py-1.5 font-inter text-[12.5px] text-ink/75 hover:text-ink disabled:opacity-50"
              >
                <FileUp className="h-3.5 w-3.5" />
                Choose file
              </button>
            </div>

            {showLabCamera && (
              <CameraCapture
                title="Photograph lab report"
                onCapture={(file) => void uploadLab(file)}
                onClose={() => setShowLabCamera(false)}
              />
            )}

            <ul className="mt-3 space-y-1">
              {labs.map((lab) => (
                <li key={lab.id} className="font-inter text-[12px] text-ink/60">
                  {lab.captured_on ?? "undated"}: {lab.values.map((v) => `${v.test_name} ${v.value}${v.unit ?? ""}`).join(", ")}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-xl border border-ink/10 bg-paper p-4">
            <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
              <FileUp className="h-4 w-4 text-ink/40" /> All documents
            </h2>
            <p className="mt-1 font-inter text-[11.5px] text-ink/45">
              Prescriptions, lab reports, summaries and notes — stored with their OCR status.
            </p>
            <ul className="mt-2 space-y-1">
              {documents.length === 0 ? (
                <li className="font-inter text-[12px] text-ink/40">No documents yet.</li>
              ) : (
                documents.map((doc) => (
                  <li key={doc.id} className="font-inter text-[12px] text-ink/65">
                    <span className="font-medium text-ink">{doc.document_type.replace("_", " ")}</span>{" "}
                    · {doc.original_filename} · {doc.ocr_status}
                  </li>
                ))
              )}
            </ul>
          </div>

          <div className="rounded-xl border border-ink/10 bg-paper p-4">
            <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
              <Send className="h-4 w-4 text-ink/40" /> Ask My Doctor
            </h2>
            <p className="mt-1 font-inter text-[11.5px] text-ink/45">
              Saved for the next visit. Taalmel does not answer clinical questions.
            </p>
            <div className="mt-2 flex gap-2">
              <input
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="What should I ask the doctor?"
                className="h-10 min-w-0 flex-1 rounded-md border border-ink/15 bg-white px-3 font-inter text-[12.5px] text-ink outline-none"
              />
              <button
                type="button"
                disabled={busy || !question.trim()}
                onClick={() => void submitQuestion()}
                className="rounded-md bg-ink px-3 py-2 font-inter text-[12.5px] font-medium text-white disabled:opacity-50"
              >
                Save
              </button>
            </div>
            <ul className="mt-2 space-y-1">
              {questions.map((q) => (
                <li key={q.id} className="font-inter text-[12px] text-ink/65">
                  {q.question_text}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-xl border border-ink/10 bg-paper p-4">
            <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
              <Package className="h-4 w-4 text-ink/40" /> Refills
            </h2>
            {refills.length === 0 ? (
              <p className="mt-2 font-inter text-[12.5px] text-ink/45">Nothing is due for refill.</p>
            ) : (
              <ul className="mt-2 space-y-1">
                {refills.map((item) => (
                  <li key={item.medication_id} className="font-inter text-[12px] text-ink/65">
                    {item.name} {item.dose ?? ""} — {item.reason}
                  </li>
                ))}
              </ul>
            )}
            <button
              type="button"
              disabled={busy || refills.length === 0}
              onClick={() => void orderRefills()}
              className="mt-2 rounded-md bg-ink px-3 py-2 font-inter text-[12.5px] font-medium text-white disabled:opacity-50"
            >
              Send refill order
            </button>
            <p className="mt-1 font-inter text-[11px] text-ink/40">
              With no pharmacy credentials configured, the order is recorded locally for a pharmacist.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
