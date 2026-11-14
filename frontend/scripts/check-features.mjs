/**
 * End-to-end feature smoke test in a real browser.
 *
 * Covers the patient journey, not just page rendering: upload -> verify -> evidence ->
 * conflict -> reason -> resolve -> export -> wellness.
 */
import { chromium } from "playwright";
import path from "node:path";
import fs from "node:fs";

const BASE = process.env.UI_BASE ?? "http://127.0.0.1:5173";
const ROOT = path.resolve(process.cwd(), "..");
const SAMPLE_RX = path.join(
  ROOT,
  "backend-py/data/uploads/prescriptions/464aaec7-8009-474c-b0d5-17e1487a7634/d58fc68cfa08b76b49adb6c8aa6e2df9b9fb4733aa5097a4aa601a6d7e7b81d6-sample-rx.png",
);
const REPORT = path.join(
  ROOT,
  "backend-py/data/uploads/prescriptions/c8b3e33c-fb78-4f70-8490-4385c900a6f2/927d3ce3d676577f629d3163d53597cb5fa48eac840517cd5af7492b3a77f004-Kirtan_report.pdf",
);
const OUT = "screens/features";
fs.mkdirSync(OUT, { recursive: true });

const errors = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push(String(e)));

const results = [];
function pass(name) { results.push(["PASS", name]); console.log("PASS  " + name); }
function fail(name, detail) { results.push(["FAIL", name]); console.log("FAIL  " + name + (detail ? `  [${detail}]` : "")); }
function ok(condition, name, detail = "") { condition ? pass(name) : fail(name, detail); }

// 1. Signup -> consent -> onboarding
const phone = "9" + Math.floor(Math.random() * 1e9).toString().padStart(9, "0");
await page.goto(BASE + "/signup", { waitUntil: "networkidle" });
await page.getByPlaceholder("Asha Sharma").fill("Feature Test");
await page.getByPlaceholder("9876543210").fill(phone);
await page.getByPlaceholder("At least 8 characters").fill("correct-horse-battery");
await page.getByRole("button", { name: "Create account" }).click();
await page.waitForURL("**/app", { timeout: 20000 }).catch(() => {});
await page.getByText("Who are you caring for?").waitFor({ timeout: 15000 }).catch(() => {});
ok(await page.getByText("Who are you caring for?").isVisible().catch(() => false), "onboarding visible");
await page.getByPlaceholder("Amma").fill("Amma");
await page.getByRole("checkbox").check();
await page.getByRole("button", { name: "Create household" }).click();
await page.waitForTimeout(1500);
ok(await page.getByText("Needs a decision").isVisible().catch(() => false), "dashboard renders");

// 2. Upload a printed prescription
await page.getByRole("link", { name: "Medicines" }).click();
await page.waitForTimeout(800);
await page.locator('input[type="file"]').first().setInputFiles(SAMPLE_RX);
await page.getByText("What the prescription says").waitFor({ timeout: 90000 });
const itemValues = await page.locator("input").evaluateAll((els) => els.map((el) => el.value));
ok(itemValues.some((v) => /Ecosprin|Omez/i.test(v)), "OCR returned medicine lines", itemValues.join(" | "));
await page.getByRole("button", { name: "Confirm and add" }).click();
await page.waitForTimeout(1500);
const medsText = await page.locator("body").innerText();
ok(/Aspirin|Omeprazole/.test(medsText), "verified medicines appear", medsText.slice(0, 300));

// 3. Evidence -> conflict
await page.getByText("Aspirin", { exact: false }).first().click();
await page.getByText("Report taking or stopping").click();
await page.getByRole("button", { name: "No, stopped" }).click();
await page.waitForTimeout(1400);
// The drawer closes after saving; reopen the medicine for the physical check.
await page.getByText("Aspirin", { exact: false }).first().click();
await page.getByText("Record what is actually in the cabinet").click();
await page.getByRole("button", { name: "It is here" }).click();
await page.waitForTimeout(1500);

// 4. Cases -> reason -> resolve
await page.getByRole("link", { name: "Cases" }).click();
await page.waitForTimeout(1200);
const caseList = await page.locator("body").innerText();
ok(/discrepancy|Prescription|Patient|stopped|stock/i.test(caseList), "case opened after evidence", caseList.slice(0, 300));
const caseLink = page.locator("a[href*='/app/cases/']").first();
if (await caseLink.count()) {
  await caseLink.click();
  await page.waitForTimeout(800);
  ok(/Why did this happen?/.test(await page.locator("body").innerText()), "case detail shows reason controls");
  await page.getByRole("button", { name: "Ran out of stock" }).click();
  await page.waitForTimeout(800);
  await page.getByRole("button", { name: "Resolved" }).click();
  await page.getByRole("button", { name: "Record outcome" }).click();
  await page.waitForTimeout(1000);
  ok(/This case is closed/.test(await page.locator("body").innerText()), "case resolves");
} else {
  fail("no case link found");
}

// 5. Doctor export + QR
await page.getByRole("link", { name: "Doctor export" }).click();
await page.waitForTimeout(1200);
await page.getByRole("button", { name: "Create link" }).click();
await page.waitForTimeout(1500);
ok(/doctor-export/.test(await page.locator("body").innerText()), "doctor link issued");
ok(await page.locator('img[alt="QR code for the doctor link"]').isVisible().catch(() => false), "QR image renders");

// 6. Safety
await page.getByRole("link", { name: "Safety" }).click();
await page.waitForTimeout(800);
ok(/not covered|curated/i.test(await page.locator("body").innerText()), "safety page renders");

// 7. Wellness + lab report
await page.getByRole("link", { name: "Wellness" }).click();
await page.waitForTimeout(800);
ok(/Wellness timeline/.test(await page.locator("body").innerText()), "wellness page renders");
await page.locator('input[type="file"]').first().setInputFiles(REPORT);
await page.waitForTimeout(4000);
const wellnessText = await page.locator("body").innerText();
ok(/LAB REPORT/i.test(wellnessText), "lab report appears in documents", wellnessText.slice(0, 400));

// 8. Language + accessibility toggles
await page.locator("select").first().selectOption("hi");
await page.waitForTimeout(1200);
ok(/आज|दवाइयाँ/.test(await page.locator("body").innerText()), "Hindi interface applies");
await page.getByRole("button", { name: "Large text" }).click();
ok(await page.locator("html.taalmel-large-text").count() === 1, "large-text mode applies");
await page.getByRole("button", { name: "High contrast" }).click();
ok(await page.locator("html.taalmel-high-contrast").count() === 1, "high-contrast mode applies");

await page.screenshot({ path: `${OUT}/final.png`, fullPage: true });
ok(errors.length === 0, "no console errors", errors.join(" | "));

await browser.close();
const failures = results.filter(([status]) => status === "FAIL");
console.log(`\n${results.length - failures.length}/${results.length} checks passed`);
if (failures.length) process.exitCode = 1;
