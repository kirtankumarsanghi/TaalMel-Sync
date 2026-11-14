/**
 * Verify the newly added UI: PDF/QR export, tapering, and photo attach.
 *
 * Fails on any console error and asserts on visible content, not just that a request
 * returned 200.
 */
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = "http://127.0.0.1:5173";
const OUT = "screens";
fs.mkdirSync(OUT, { recursive: true });

const phone = "9" + Math.floor(Math.random() * 1e9).toString().padStart(9, "0");
const errors = [];
let exitCode = 0;

function pass(label) {
  console.log("PASS  " + label);
}
function fail(label, detail) {
  console.log("FAIL  " + label + (detail ? "  [" + detail + "]" : ""));
  exitCode = 1;
}

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("console", (m) => {
  if (m.type() === "error") errors.push(m.text());
});
page.on("pageerror", (e) => errors.push(String(e)));

// Sign up and onboard
await page.goto(BASE + "/signup", { waitUntil: "networkidle" });
await page.getByPlaceholder("Asha Sharma").fill("UI Check");
await page.getByPlaceholder("9876543210").fill(phone);
await page.getByPlaceholder("At least 8 characters").fill("correct-horse-battery");
await page.getByRole("button", { name: "Create account" }).click();
await page.waitForURL("**/app", { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1200);
await page.getByPlaceholder("Amma").fill("Amma");
await page.getByRole("button", { name: "Create household" }).click();
await page.waitForTimeout(2500);

// Upload the sample prescription so there is a medicine to work with
await page.getByRole("link", { name: "Medicines" }).click();
await page.waitForTimeout(1200);
await page.locator('input[type="file"]').first().setInputFiles("scripts/sample-rx.png");
await page.waitForTimeout(6000);

const verifyVisible = await page.getByText("What the prescription says").isVisible().catch(() => false);
verifyVisible ? pass("prescription verification panel appears") : fail("verification panel missing");

if (verifyVisible) {
  await page.screenshot({ path: `${OUT}/30-verify-panel.png`, fullPage: true });
  await page.getByRole("button", { name: "Confirm and add" }).click();
  await page.waitForTimeout(2500);
}

const medicineCards = await page.locator('button:has-text("mg")').count();
medicineCards > 0 ? pass(`${medicineCards} medicine row(s) rendered`) : fail("no medicine rows");

// Open the evidence drawer for the first medicine
await page.locator("ul li button").first().click();
await page.waitForTimeout(1500);
await page.screenshot({ path: `${OUT}/31-medicine-drawer.png`, fullPage: true });

const taperVisible = await page.getByText("Tapering plan").isVisible().catch(() => false);
taperVisible ? pass("tapering section present") : fail("tapering section missing");

// Save a taper
const taperInput = page.getByPlaceholder("20mg x7d, 10mg x7d, 5mg x7d");
if (await taperInput.isVisible().catch(() => false)) {
  await taperInput.fill("20mg x7d, 10mg x7d, 5mg x7d");
  await page.getByRole("button", { name: "Save" }).click();
  await page.waitForTimeout(2000);
  const saved = await page.getByText("Step 1:").isVisible().catch(() => false);
  saved ? pass("taper schedule saved and rendered") : fail("taper schedule not rendered");
  await page.screenshot({ path: `${OUT}/32-taper-saved.png`, fullPage: true });
}

const photoVisible = await page.getByText("Photo of the strip").isVisible().catch(() => false);
photoVisible ? pass("photo section present") : fail("photo section missing");

await page.keyboard.press("Escape");
await page.locator("body").click({ position: { x: 10, y: 10 } }).catch(() => {});
await page.waitForTimeout(600);

// Doctor export: QR + download buttons
await page.getByRole("link", { name: "Doctor export" }).click();
await page.waitForTimeout(2000);
await page.screenshot({ path: `${OUT}/33-export-before.png`, fullPage: true });

await page.getByRole("button", { name: "Create link" }).click();
await page.waitForTimeout(3000);

const qrVisible = await page.locator('img[alt="QR code for the doctor link"]').isVisible().catch(() => false);
qrVisible ? pass("QR code rendered") : fail("QR code missing");

const qrBytes = qrVisible
  ? await page.locator('img[alt="QR code for the doctor link"]').evaluate((img) => (img.src || "").length)
  : 0;
qrBytes > 500 ? pass(`QR image has real data (${qrBytes} chars)`) : fail("QR image looks empty", String(qrBytes));

const pdfButton = await page.getByRole("button", { name: "Download PDF" }).isVisible().catch(() => false);
pdfButton ? pass("PDF download button present") : fail("PDF button missing");

await page.screenshot({ path: `${OUT}/34-export-with-qr.png`, fullPage: true });

await browser.close();

if (errors.length) {
  console.log("\nCONSOLE ERRORS:");
  for (const error of [...new Set(errors)]) console.log("  - " + error);
  exitCode = 1;
} else {
  console.log("\nno console errors");
}

console.log(exitCode ? "\nNEW UI CHECK FAILED" : "\nNEW UI CHECK PASSED");
process.exitCode = exitCode;
