/**
 * Browser check for the History screen.
 *
 * Seeds two dated visits through the API (paste-to-parse, so it does not depend on a
 * cloud OCR key), then verifies the year view, dose change, conditions, lab section,
 * and the dossier download — failing on any console error.
 */
import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";

const UI = process.env.UI_BASE ?? "http://127.0.0.1:5173";
const API = process.env.API_BASE ?? "http://127.0.0.1:8010";
const ROOT = path.resolve(process.cwd(), "..");
const RX = path.join(
  ROOT,
  "backend-py/data/uploads/prescriptions/464aaec7-8009-474c-b0d5-17e1487a7634/d58fc68cfa08b76b49adb6c8aa6e2df9b9fb4733aa5097a4aa601a6d7e7b81d6-sample-rx.png",
);
const HAND = path.join(
  ROOT,
  "backend-py/data/uploads/prescriptions/8bae7104-2d41-496f-827e-827fdcc59ab0/3d544fb8170a84c92737f268f97e83ad65409da7996c168006282208757d11dc-WhatsApp_Image_2026-10-20_at_11.41.32_PM.jpeg",
);

const results = [];
const ok = (condition, name, detail = "") => {
  results.push([condition, name]);
  console.log(`${condition ? "PASS" : "FAIL"}  ${name}${!condition && detail ? `  [${detail}]` : ""}`);
};

const phone = "9" + Math.floor(Math.random() * 1e9).toString().padStart(9, "0");
const register = await fetch(`${API}/api/auth/register`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "History Check",
    phone,
    password: "correct-horse-battery",
    role: "caregiver",
  }),
});
const auth = await register.json();
const headers = {
  Authorization: `Bearer ${auth.access_token}`,
  "Content-Type": "application/json",
};

const household = await (
  await fetch(`${API}/api/households`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      household_name: "History Home",
      patient_display_name: "Amma",
      consent_recorded: true,
    }),
  })
).json();
const member = household.patient.household_member_id;
const patientId = household.patient.patient_id;

async function seedVisit(date, line, filePath, mime, filename) {
  const form = new FormData();
  form.append("file", new Blob([fs.readFileSync(filePath)], { type: mime }), filename);
  form.append("prescribed_by", "Dr Rao");
  form.append("prescribed_on", `${date}T00:00:00Z`);
  const uploadResponse = await fetch(
    `${API}/api/prescriptions/upload?household_member_id=${member}`,
    {
      method: "POST",
      headers: { Authorization: `Bearer ${auth.access_token}` },
      body: form,
    },
  );
  if (!uploadResponse.ok) {
    throw new Error(`upload ${date} failed: ${uploadResponse.status} ${await uploadResponse.text()}`);
  }
  const upload = await uploadResponse.json();

  await fetch(`${API}/api/prescriptions/${upload.id}/parse-text`, {
    method: "POST",
    headers,
    body: JSON.stringify({ text: line }),
  });
  const fetched = await (
    await fetch(`${API}/api/prescriptions/${upload.id}`, {
      headers: { Authorization: `Bearer ${auth.access_token}` },
    })
  ).json();
  const verifyResponse = await fetch(`${API}/api/prescriptions/${upload.id}/verify`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      items: (fetched.items ?? []).map((item) => ({
        item_id: item.id,
        medication_name: item.medication_name,
        dosage: item.dosage,
        frequency: item.frequency,
      })),
    }),
  });
  if (!verifyResponse.ok) {
    throw new Error(`verify ${date} failed: ${verifyResponse.status} ${await verifyResponse.text()}`);
  }
  console.log(`seeded ${date}: ${(fetched.items ?? []).length} item(s)`);
}

await seedVisit("2023-05-10", "Tab Sotret NF 10mg OD", RX, "image/png", "rx-2023.png");
await seedVisit(
  "2025-01-15",
  "Tab Sotret NF 20mg OD",
  HAND,
  "image/jpeg",
  "rx-2025.jpg",
);

await fetch(`${API}/api/patients/${patientId}/conditions`, {
  method: "POST",
  headers,
  body: JSON.stringify({ name: "Acne vulgaris", onset_date: "2023-05-10T00:00:00Z" }),
});

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
await context.addInitScript(
  ({ access, refresh, patient }) => {
    sessionStorage.setItem("taalmel.access", access);
    sessionStorage.setItem("taalmel.refresh", refresh);
    sessionStorage.setItem("taalmel.member", JSON.stringify(patient));
  },
  {
    access: auth.access_token,
    refresh: auth.refresh_token,
    patient: household.patient,
  },
);

const page = await context.newPage();
const errors = [];
page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
page.on("pageerror", (error) => errors.push(String(error)));

await page.goto(`${UI}/app/history`, { waitUntil: "networkidle" });
await page.getByRole("heading", { name: "History" }).waitFor({ timeout: 20000 }).catch(() => {});
ok(await page.getByRole("heading", { name: "History" }).isVisible().catch(() => false), "history screen renders");

const body = await page.locator("body").innerText();
ok(/Medicines by year/i.test(body), "medicine section present");
ok(/2023/.test(body) && /2025/.test(body), "both years listed", body.slice(0, 200));
ok(/10mg/.test(body) && /20mg/.test(body), "doses listed");
ok(/Dose changes/i.test(body), "dose change section present");
ok(/10mg\s*→\s*20mg/.test(body), "dose change row shows 10mg to 20mg");
ok(/Lab comparison/i.test(body), "lab section present");
ok(/Acne vulgaris/i.test(body), "condition listed");

const [download] = await Promise.all([
  page.waitForEvent("download", { timeout: 30000 }),
  page.getByRole("button", { name: /Download full record/i }).click(),
]);
ok((await download.suggestedFilename()).endsWith(".pdf"), "dossier download starts");

ok(errors.length === 0, "no console errors", errors.join(" | "));

await browser.close();
const passed = results.filter(([condition]) => condition).length;
console.log(`\n${passed}/${results.length} history checks passed`);
process.exit(passed === results.length ? 0 : 1);
