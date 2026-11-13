// CP6 local real-API trial of the M3 Admin frontend. Run: pnpm --filter @knowserve/frontend e2e:trial
//
// This is NOT a copy of admin.mocked.spec.ts. It checks the real wiring only: the Vite /api proxy,
// session and CSRF cookies, multipart upload with an Idempotency-Key, the status stream (SSE) through
// the proxy, and status badges produced by the real API, Worker and queue stand-in.
//
// Needs the lead's harness (API :8000, Worker :8001, QStash stand-in :8090, Vite :5199, Firebase Auth
// Emulator :9099) and an existing Admin account in the emulator:
//   E2E_ADMIN_EMAIL, E2E_ADMIN_PASSWORD   (required)
//   E2E_BASE_URL                           (optional; default http://localhost:5199, set by the config)
//   E2E_FIREBASE_AUTH_EMULATOR_URL         (optional; default http://localhost:9099, used by Vite)
// Departments are the seeded ones (migration 0002): Finance (finance) and Engineering (engineering).
import { expect, test, type Locator, type Page } from "@playwright/test";

const PROCESSING_TIMEOUT_MS = 60_000;
const STAMP = Date.now().toString(36);
const OWNER = "Finance";
const OTHER = "Engineering";

// --- Fixture builders (no dependencies) ------------------------------------------------------------

function pdfBytes(pages: { text?: string; image?: boolean }[]): Buffer {
  // Objects: 1 catalog, 2 pages, 3 font, 4 image, then (page, content) pairs.
  const objects: string[] = [];
  const kids: string[] = [];
  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>";
  objects[4] =
    "<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /ASCIIHexDecode /Length 26 >>\nstream\nFF000000FF000000FFFFFF00>\nendstream";
  pages.forEach((page, index) => {
    const pageId = 5 + index * 2;
    const contentId = pageId + 1;
    const body = page.image
      ? "q 200 0 0 200 72 500 cm /Im1 Do Q"
      : `BT /F1 12 Tf 72 720 Td 14 TL ${(page.text ?? "")
          .match(/.{1,70}(\s|$)/g)
          ?.map((line) => `(${line.trim().replace(/[()\\]/g, "")}) Tj T*`)
          .join(" ")} ET`;
    objects[pageId] =
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents ${contentId} 0 R /Resources << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> >>`;
    objects[contentId] =
      `<< /Length ${body.length} >>\nstream\n${body}\nendstream`;
    kids.push(`${pageId} 0 R`);
  });
  objects[2] = `<< /Type /Pages /Kids [${kids.join(" ")}] /Count ${pages.length} >>`;

  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  for (let id = 1; id < objects.length; id += 1) {
    offsets[id] = out.length;
    out += `${id} 0 obj\n${objects[id]}\nendobj\n`;
  }
  const xref = out.length;
  out += `xref\n0 ${objects.length}\n0000000000 65535 f \n`;
  for (let id = 1; id < objects.length; id += 1) {
    out += `${String(offsets[id]).padStart(10, "0")} 00000 n \n`;
  }
  out += `trailer\n<< /Size ${objects.length} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(out, "latin1");
}

const SENTENCE =
  "The quarterly expense policy explains how employees submit receipts, who approves travel, and when reimbursements are paid. ";

function textPdf(topic: string): Buffer {
  return pdfBytes([
    { text: `${topic}. ${SENTENCE.repeat(3)}` },
    { text: `${topic}, page two. ${SENTENCE.repeat(3)}` },
  ]);
}

const imageOnlyPdf = (): Buffer => pdfBytes([{ image: true }, { image: true }]);

const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(data: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of data)
    crc = (CRC_TABLE[(crc ^ byte) & 0xff] as number) ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

/** A ZIP with stored (uncompressed) entries. */
function zipBytes(entries: Record<string, Buffer>): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const [name, data] of Object.entries(entries)) {
    const nameBytes = Buffer.from(name, "utf8");
    const crc = crc32(data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4); // version needed
    local.writeUInt16LE(0x0800, 6); // UTF-8 names
    local.writeUInt16LE(0, 8); // stored
    local.writeUInt16LE(0, 10); // time
    local.writeUInt16LE(0x21, 12); // 1980-01-01
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(nameBytes.length, 26);
    locals.push(local, nameBytes, data);

    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4); // version made by
    central.writeUInt16LE(20, 6); // version needed
    central.writeUInt16LE(0x0800, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0x21, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(nameBytes.length, 28);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, nameBytes);
    offset += 30 + nameBytes.length + data.length;
  }
  const centralBytes = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(Object.keys(entries).length, 8);
  end.writeUInt16LE(Object.keys(entries).length, 10);
  end.writeUInt32LE(centralBytes.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, centralBytes, end]);
}

// --- Page helpers -------------------------------------------------------------------------------

function adminCredentials() {
  const email = process.env["E2E_ADMIN_EMAIL"];
  const password = process.env["E2E_ADMIN_PASSWORD"];
  if (!email || !password) {
    throw new Error(
      "Set E2E_ADMIN_EMAIL and E2E_ADMIN_PASSWORD (the Admin account in the Firebase Emulator).",
    );
  }
  return { email, password };
}

const pdfFile = (name: string, buffer: Buffer) => ({
  name,
  mimeType: "application/pdf",
  buffer,
});

function rowFor(page: Page, title: string): Locator {
  return page.getByTestId("admin-document").filter({ hasText: title });
}

/** Records every status badge a row shows, in the page itself, so a reload would lose it. */
async function trackBadges(page: Page) {
  await page.evaluate(() => {
    const seen: string[] = [];
    (window as unknown as { __badges: string[] }).__badges = seen;
    const scan = () => {
      for (const row of document.querySelectorAll(
        '[data-testid="admin-document"]',
      )) {
        const title = row.querySelector("span.font-medium")?.textContent ?? "";
        const badge = row.querySelector('[data-testid^="status-badge-"]');
        const kind = badge
          ?.getAttribute("data-testid")
          ?.replace("status-badge-", "");
        if (kind && !seen.includes(`${title}|${kind}`))
          seen.push(`${title}|${kind}`);
      }
    };
    new MutationObserver(scan).observe(document.body, {
      subtree: true,
      childList: true,
      characterData: true,
    });
    scan();
  });
}

const badgesSeen = (page: Page) =>
  page.evaluate(
    () => (window as unknown as { __badges?: string[] }).__badges ?? [],
  );

async function uploadViaForm(
  page: Page,
  title: string,
  file: ReturnType<typeof pdfFile>,
) {
  await page.getByRole("button", { name: "Upload a document" }).click();
  const form = page.getByTestId("upload-form");
  await form.getByLabel("PDF file").setInputFiles(file);
  await form.getByLabel("Title").fill(title);
  await form.getByLabel("Owner department").selectOption({ label: OWNER });
  // Choosing the owner pre-selects it; the other department is an explicit choice.
  await expect(form.getByLabel(OWNER, { exact: true })).toBeChecked();
  await form.getByLabel(OTHER, { exact: true }).check();
  await form.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(form.getByTestId("upload-success")).toBeVisible();
  await page.getByRole("button", { name: "Upload a document" }).click(); // close the panel
}

// --- The trial ----------------------------------------------------------------------------------

test("CP6 trial: Admin sign-in, upload, failure and replace, ZIP import, access and delete", async ({
  page,
}) => {
  test.setTimeout(12 * 60_000);
  const { email, password } = adminCredentials();
  const streams: { url: string; status: number; type: string }[] = [];
  page.on("response", (response) => {
    if (/\/api\/v1\/admin\/documents\/[^/]+\/events/.test(response.url())) {
      streams.push({
        url: response.url(),
        status: response.status(),
        type: response.headers()["content-type"] ?? "",
      });
    }
  });
  const unexpected: string[] = [];
  page.on("response", (response) => {
    if (
      response.url().includes("/api/v1/") &&
      [401, 403].includes(response.status())
    ) {
      unexpected.push(
        `${response.status()} ${response.request().method()} ${response.url()}`,
      );
    }
  });

  await test.step("sign in as the Admin through the emulator-backed login screen", async () => {
    await page.goto("/login");
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByTestId("dashboard-page")).toBeVisible();
    await expect(page.getByTestId("admin-link")).toBeVisible(); // identity.kind === 'admin' from the real API
  });

  await page.goto("/admin/documents");
  await expect(page.getByTestId("admin-documents-page")).toBeVisible();
  await expect(page.getByText("Loading documents...")).toBeHidden();
  await trackBadges(page);

  const leaveTitle = `Trial text policy ${STAMP}`;
  await test.step("upload a text PDF and follow it to Ready through the live stream", async () => {
    await uploadViaForm(
      page,
      leaveTitle,
      pdfFile("trial-text.pdf", textPdf("Expense policy")),
    );
    const row = rowFor(page, leaveTitle);
    await expect(row).toBeVisible();
    await expect(row.getByTestId("status-badge-ready")).toBeVisible({
      timeout: PROCESSING_TIMEOUT_MS,
    });
    await expect(row.getByTestId("allowed-departments")).toContainText(OWNER);
    await expect(row.getByTestId("allowed-departments")).toContainText(OTHER);

    // At least one status change reached the page over SSE, with no reload in between.
    const seen = await badgesSeen(page);
    expect(seen).toContain(`${leaveTitle}|ready`);
    expect(
      seen.filter((s) => s.startsWith(`${leaveTitle}|`)).length,
    ).toBeGreaterThanOrEqual(2);
    expect(streams.length).toBeGreaterThan(0);
    expect(streams[0]).toMatchObject({ status: 200 });
    expect(streams[0]?.type).toContain("text/event-stream");
  });

  const scanTitle = `Trial scanned ${STAMP}`;
  await test.step("an image-only PDF fails with the catalog message and offers Replace file first", async () => {
    await uploadViaForm(
      page,
      scanTitle,
      pdfFile("trial-scan.pdf", imageOnlyPdf()),
    );
    const row = rowFor(page, scanTitle);
    await expect(row.getByTestId("status-badge-failed")).toBeVisible({
      timeout: PROCESSING_TIMEOUT_MS,
    });
    await expect(row.getByTestId("failure-reason")).toContainText(
      "No readable text was found",
    );
    await expect(row.getByRole("button").first()).toHaveText("Replace file");
  });

  await test.step("replace the failed document with a text PDF and reach Ready", async () => {
    const row = rowFor(page, scanTitle);
    await row.getByRole("button", { name: "Replace file" }).click();
    const dialog = page.getByRole("dialog", { name: "Replace file" });
    await expect(dialog.getByTestId("replace-notice")).toContainText(
      "unavailable to users",
    );
    await dialog
      .getByLabel("New PDF file")
      .setInputFiles(pdfFile("trial-fixed.pdf", textPdf("Replacement text")));
    await dialog.getByRole("button", { name: "Replace file" }).click();
    await expect(dialog).toBeHidden();
    await expect(row.getByTestId("status-badge-ready")).toBeVisible({
      timeout: PROCESSING_TIMEOUT_MS,
    });
  });

  const zipA = `Trial ZIP leave ${STAMP}`;
  const zipB = `Trial ZIP expenses ${STAMP}`;
  const zipBad = `Trial ZIP bad ${STAMP}`;
  await test.step("ZIP preview names the invalid entry and has no default access", async () => {
    const manifest = {
      version: 1,
      documents: [
        {
          file: "leave.pdf",
          title: zipA,
          owner_department: "finance",
          allowed_departments: ["finance", "engineering"],
        },
        {
          file: "expenses.pdf",
          title: zipB,
          owner_department: "finance",
          allowed_departments: ["finance"],
        },
        {
          file: "bad.pdf",
          title: zipBad,
          owner_department: "finance",
          allowed_departments: ["no-such-department"],
        },
      ],
    };
    const archive = zipBytes({
      "manifest.json": Buffer.from(JSON.stringify(manifest)),
      "leave.pdf": textPdf("ZIP leave"),
      "expenses.pdf": textPdf("ZIP expenses"),
      "bad.pdf": textPdf("ZIP bad"),
    });
    await page.getByRole("button", { name: "Import a ZIP" }).click();
    const panel = page.getByTestId("import-panel");
    await panel
      .getByLabel("ZIP file")
      .setInputFiles({
        name: "trial.zip",
        mimeType: "application/zip",
        buffer: archive,
      });
    await panel.getByRole("button", { name: "Preview" }).click();

    const preview = panel.getByTestId("import-preview");
    await expect(preview.getByTestId("import-entry-valid")).toHaveCount(2);
    const invalid = preview.getByTestId("import-entry-invalid");
    await expect(invalid).toHaveCount(1);
    await expect(invalid).toContainText("bad.pdf");
    await expect(invalid.getByTestId("import-entry-problem")).toContainText(
      "does not exist",
    ); // UNKNOWN_DEPARTMENT
    await expect(invalid.getByTestId("import-entry-problem")).toContainText(
      "no-such-department",
    );
    await expect(invalid.getByTestId("import-entry-allowed")).toHaveCount(0); // nothing is inferred
    await expect(rowFor(page, zipA)).toHaveCount(0); // preview creates nothing

    await preview
      .getByRole("button", { name: "Import 2 valid documents" })
      .click();
    await expect(
      panel
        .getByTestId("import-results")
        .getByText("2 created, 0 not imported."),
    ).toBeVisible();
    await panel.getByRole("button", { name: "Close" }).click();

    for (const title of [zipA, zipB]) {
      await expect(
        rowFor(page, title).getByTestId("status-badge-ready"),
      ).toBeVisible({
        timeout: PROCESSING_TIMEOUT_MS,
      });
    }
    await expect(rowFor(page, zipBad)).toHaveCount(0);
  });

  await test.step("change access of one document", async () => {
    const row = rowFor(page, zipA);
    await row.getByRole("button", { name: "Edit access" }).click();
    const dialog = page.getByRole("dialog", { name: "Edit access" });
    await expect(dialog.getByLabel(OTHER, { exact: true })).toBeChecked();
    await dialog.getByLabel(OTHER, { exact: true }).uncheck();
    await dialog.getByRole("button", { name: "Save" }).click();
    await expect(dialog).toBeHidden();
    await expect(row.getByTestId("allowed-departments")).not.toContainText(
      OTHER,
    );
    await expect(row.getByTestId("allowed-departments")).toContainText(OWNER);
  });

  await test.step("soft-delete another document and see it gone, also after a reload", async () => {
    await rowFor(page, zipB).getByRole("button", { name: "Delete" }).click();
    const dialog = page.getByRole("dialog", { name: "Delete document" });
    await dialog.getByRole("button", { name: "Delete", exact: true }).click();
    await expect(dialog).toBeHidden();
    await expect(rowFor(page, zipB)).toHaveCount(0);
    await page.reload();
    await expect(rowFor(page, zipA)).toBeVisible();
    await expect(rowFor(page, zipB)).toHaveCount(0);
    await expect(rowFor(page, leaveTitle)).toBeVisible();
  });

  // Cookies, CSRF and CORS worked end to end: no authorization failure came back from the real API.
  expect(unexpected).toEqual([]);
});
