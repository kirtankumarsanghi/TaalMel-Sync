/**
 * Populated-state screenshots: creates real data through the API, then captures
 * the screens with content, which is what actually needs design review.
 */
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://127.0.0.1:5173";
const OUT = "screens";
fs.mkdirSync(OUT, { recursive: true });

const phone = "9" + Math.floor(Math.random() * 1e9).toString().padStart(9, "0");

// Seed via the API (same origin through the Vite proxy).
const api = async (path, options = {}) => {
  const response = await fetch(BASE + path, options);
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!response.ok) throw new Error(`${path} -> ${response.status} ${text.slice(0, 200)}`);
  return data;
};

const tokens = await api("/api/auth/register", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    name: "Asha Sharma",
    phone,
    password: "correct-horse-battery",
    role: "caregiver",
  }),
});
const auth = { Authorization: `Bearer ${tokens.access_token}` };

const created = await api("/api/households", {
  method: "POST",
  headers: { ...auth, "Content-Type": "application/json" },
  body: JSON.stringify({
    household_name: "Sharma family",
    patient_display_name: "Amma",
    relationship: "mother",
    consent_recorded: true,
  }),
});
const member = created.patient.household_member_id;

// Verify two medicines directly so the UI has records without OCR.
for (const name of ["Metformin 500mg", "Amlodipine 5mg"]) {
  const form = new FormData();
  form.append("file", new Blob([new TextEncoder().encode("seed-" + name)], { type: "image/png" }), "seed.png");
  // Bypass OCR: create through the API's own prescription flow is heavy, so use the
  // medications endpoint via a stubbed prescription instead.
}

// Upload the real sample prescription so OCR finds medicines.
const form = new FormData();
form.append("file", new Blob([fs.readFileSync("scripts/sample-rx.png")], { type: "image/png" }), "rx.png");
const prescription = await api(`/api/prescriptions/upload?household_member_id=${member}`, {
  method: "POST",
  headers: auth,
  body: form,
}).catch((error) => {
  console.log("upload failed:", error.message.slice(0, 160));
  return null;
});

if (prescription?.items?.length) {
  await api(`/api/prescriptions/${prescription.id}/verify`, {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json" },
    body: JSON.stringify({
      items: prescription.items.map((item) => ({
        item_id: item.id,
        medication_name: item.medication_name,
        dosage: item.dosage,
        frequency: item.frequency,
      })),
    }),
  });
}

const meds = await api(`/api/medications?household_member_id=${member}`, { headers: auth });
console.log("medications seeded:", meds.length);

if (meds.length) {
  const first = meds[0].id;
  await api(`/api/medications/${first}/report`, {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json" },
    body: JSON.stringify({ taking: false }),
  });
  await api(`/api/medications/${first}/availability`, {
    method: "POST",
    headers: { ...auth, "Content-Type": "application/json" },
    body: JSON.stringify({ present: true, quantity_note: "low" }),
  });
  await api(`/api/medications/${first}/detect`, { method: "POST", headers: auth });
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

// Sign in through the UI so the app has a real session.
await page.goto(BASE + "/signin", { waitUntil: "networkidle" });
await page.getByPlaceholder("9876543210").fill(phone);
await page.getByPlaceholder("At least 1 characters").fill("correct-horse-battery").catch(async () => {
  await page.locator('input[type="password"]').fill("correct-horse-battery");
});
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForURL("**/app", { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(2000);

// The household context needs the member; select it by creating? It is stored only in
// sessionStorage, so the app will show onboarding unless we set it explicitly.
await page.evaluate((patient) => {
  sessionStorage.setItem("taalmel.member", JSON.stringify(patient));
}, created.patient);
await page.goto(BASE + "/app", { waitUntil: "networkidle" });
await page.waitForTimeout(2200);

await page.screenshot({ path: `${OUT}/20-dashboard-populated.png`, fullPage: true });
console.log("captured dashboard");

await page.getByRole("link", { name: "Medicines" }).click();
await page.waitForTimeout(1600);
await page.screenshot({ path: `${OUT}/21-medicines-populated.png`, fullPage: true });
console.log("captured medicines");

await page.getByRole("link", { name: "Cases" }).click();
await page.waitForTimeout(1400);
await page.screenshot({ path: `${OUT}/22-cases-populated.png`, fullPage: true });
console.log("captured cases");

const caseLinks = page.locator('a[href^="/app/cases/"]');
if (await caseLinks.count()) {
  await caseLinks.first().click();
  await page.waitForTimeout(1600);
  await page.screenshot({ path: `${OUT}/23-case-detail.png`, fullPage: true });
  console.log("captured case detail");
}

await browser.close();
console.log("DONE");
