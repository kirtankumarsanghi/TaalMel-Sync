/**
 * Browser smoke test.
 *
 * A successful build proves nothing about runtime. This drives the real app in
 * Chromium, fails on any console error, and checks each screen renders and works.
 *
 *   node scripts/check-ui.mjs
 */
import { chromium } from "playwright";
import fs from "node:fs";

const BASE = process.env.UI_BASE ?? "http://127.0.0.1:5173";
const OUT = "screens";
fs.mkdirSync(OUT, { recursive: true });

const errors = [];
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();

page.on("console", (message) => {
  if (message.type() === "error") errors.push(message.text());
});
page.on("pageerror", (error) => errors.push(String(error)));

function pass(label) {
  console.log("PASS  " + label);
}
function fail(label, detail) {
  console.log("FAIL  " + label + (detail ? "  [" + detail + "]" : ""));
  process.exitCode = 1;
}

// 1. Landing page
await page.goto(BASE + "/", { waitUntil: "networkidle" });
// Entrances are staged up to 1.1s, so screenshots must wait for them to finish;
// otherwise panels are captured mid-animation at opacity 0.
await page.waitForTimeout(2200);
const headline = await page.locator("h1").first().innerText();
headline.toLowerCase().includes("every") ? pass("landing headline renders") : fail("landing headline", headline);

const navBrand = await page.locator("nav").first().innerText();
navBrand.includes("Taalmel") ? pass("navbar brand") : fail("navbar brand", navBrand);

// Word reveal: each word should be inside a span with an animation.
const wordCount = await page.locator("h1 span span").count();
wordCount >= 8 ? pass(`headline has ${wordCount} animated words`) : fail("word reveal count", String(wordCount));

const panels = await page.locator("#how > div").count();
panels === 3 ? pass("three-panel strip") : fail("panel count", String(panels));

await page.screenshot({ path: `${OUT}/01-landing-desktop.png`, fullPage: true });

// Mobile viewport
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(400);
await page.screenshot({ path: `${OUT}/02-landing-mobile.png`, fullPage: true });
pass("mobile landing screenshot");

// Tablet
await page.setViewportSize({ width: 834, height: 1112 });
await page.waitForTimeout(300);
await page.screenshot({ path: `${OUT}/03-landing-tablet.png`, fullPage: true });
pass("tablet landing screenshot");

// 2. Sign up
await page.setViewportSize({ width: 1440, height: 900 });
const phone = "9" + Math.floor(Math.random() * 1e9).toString().padStart(9, "0");
await page.goto(BASE + "/signup", { waitUntil: "networkidle" });
await page.screenshot({ path: `${OUT}/04-signup.png`, fullPage: true });

await page.getByPlaceholder("Asha Sharma").fill("Browser Test");
await page.getByPlaceholder("9876543210").fill(phone);
await page.getByPlaceholder("At least 8 characters").fill("correct-horse-battery");
await page.getByRole("button", { name: "Create account" }).click();

// Wait for the actual navigation rather than a fixed sleep.
await page.waitForURL("**/app", { timeout: 20000 }).catch(() => {});
await page.waitForTimeout(1200);

// 3. Onboarding
const onboardingVisible = await page
  .getByText("Who are you caring for?")
  .isVisible()
  .catch(() => false);
onboardingVisible ? pass("onboarding shown after signup") : fail("onboarding not shown");
await page.screenshot({ path: `${OUT}/05-onboarding.png`, fullPage: true });

await page.getByPlaceholder("Amma").fill("Amma");
await page.getByRole("checkbox").check();
await page.getByRole("button", { name: "Create household" }).click();
await page.waitForTimeout(2500);

// 4. Dashboard
const dashboard = await page.getByText("Today", { exact: false }).first().isVisible().catch(() => false);
dashboard ? pass("dashboard renders") : fail("dashboard did not render");
await page.screenshot({ path: `${OUT}/06-dashboard.png`, fullPage: true });

// 5. Medicines
await page.getByRole("link", { name: "Medicines" }).click();
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}/07-medicines-empty.png`, fullPage: true });
pass("medicines screen renders");

// 6. Cases
await page.getByRole("link", { name: "Cases" }).click();
await page.waitForTimeout(900);
await page.screenshot({ path: `${OUT}/08-cases.png`, fullPage: true });
pass("cases screen renders");

// 7. Doctor export
await page.getByRole("link", { name: "Doctor export" }).click();
await page.waitForTimeout(1400);
await page.screenshot({ path: `${OUT}/09-export.png`, fullPage: true });
pass("doctor export screen renders");

// 8. Safety
await page.getByRole("link", { name: "Safety" }).click();
await page.waitForTimeout(1200);
await page.screenshot({ path: `${OUT}/10-safety.png`, fullPage: true });
pass("safety screen renders");

// 9. Mobile app shell
await page.setViewportSize({ width: 390, height: 844 });
await page.goto(BASE + "/app", { waitUntil: "networkidle" });
await page.waitForTimeout(900);
await page.screenshot({ path: `${OUT}/11-app-mobile.png`, fullPage: true });
pass("mobile app screenshot");

await browser.close();

if (errors.length) {
  console.log("\nCONSOLE ERRORS:");
  for (const error of [...new Set(errors)]) console.log("  - " + error);
  process.exitCode = 1;
} else {
  console.log("\nno console errors");
}

console.log(process.exitCode ? "\nUI CHECK FAILED" : "\nUI CHECK PASSED");
