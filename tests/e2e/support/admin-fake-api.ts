// A contract-faithful, stateful fake of the Admin API (docs/contracts/admin-api.md) for the mocked
// Playwright specs, installed with page.route on /api/v1/**. It is NOT backend evidence: the lead runs
// one local trial against the real API at CP6. Files are not parsed beyond the multipart title; the
// ZIP content is ignored and a fixed preview is returned.
import { randomUUID } from "node:crypto";
import type { Page, Route } from "@playwright/test";

const DEPARTMENTS = [
  {
    id: "00000000-0000-4000-8000-000000000002",
    slug: "finance",
    name: "Finance",
  },
  {
    id: "00000000-0000-4000-8000-000000000003",
    slug: "engineering",
    name: "Engineering",
  },
];
const [FIN, ENG] = DEPARTMENTS as [
  (typeof DEPARTMENTS)[0],
  (typeof DEPARTMENTS)[0],
];

type Status = "queued" | "processing" | "ready" | "failed";

interface Doc {
  document_id: string;
  revision_id: string;
  status: Status;
  phase: string | null;
  failure_code: string | null;
  failure_message: string | null;
  delivery_state: string | null;
  can_retry: boolean;
  can_replace: boolean;
  title: string;
  filename: string;
  owner_department: (typeof DEPARTMENTS)[0];
  allowed_departments: (typeof DEPARTMENTS)[0][];
  page_count: number | null;
  size_bytes: number;
  created_at: string;
  updated_at: string;
  /** Titles containing "scan" fail extraction until the file is replaced. */
  failsExtraction: boolean;
}

const CSRF = "csrf-admin-e2e";

export class AdminFakeApi {
  readonly docs: Doc[] = [];
  readonly calls: string[] = [];
  readonly confirmKeys: string[] = [];
  readonly createKeys: string[] = [];

  async install(page: Page): Promise<void> {
    await page.route("**/api/v1/**", (route) => this.handle(route));
  }

  private json(route: Route, status: number, body: unknown) {
    return route.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  }

  private error(route: Route, status: number, code: string) {
    return this.json(route, status, {
      error: { code, message: code, request_id: "req_e2eadmin" },
    });
  }

  private view(doc: Doc) {
    const { failsExtraction: _hidden, ...out } = doc;
    return out;
  }

  private setState(doc: Doc, status: Status) {
    doc.status = status;
    doc.updated_at = new Date().toISOString();
    doc.phase = null;
    doc.failure_code = null;
    doc.failure_message = null;
    doc.can_retry = false;
    doc.can_replace = false;
    doc.delivery_state = status === "ready" ? "done" : status;
    if (status === "ready") doc.page_count = 3;
    if (status === "failed") {
      doc.failure_code = "NO_EXTRACTABLE_TEXT";
      doc.failure_message = "No readable text";
      doc.delivery_state = "failed";
      doc.can_retry = true;
      doc.can_replace = true;
    }
  }

  private newDoc(title: string, owner: string, allowed: string[]): Doc {
    const find = (id: string) => DEPARTMENTS.find((d) => d.id === id) ?? FIN;
    const doc: Doc = {
      document_id: randomUUID(),
      revision_id: randomUUID(),
      status: "queued",
      phase: null,
      failure_code: null,
      failure_message: null,
      delivery_state: "queued",
      can_retry: false,
      can_replace: false,
      title,
      filename: "upload.pdf",
      owner_department: find(owner),
      allowed_departments: allowed.map(find),
      page_count: null,
      size_bytes: 2048,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      failsExtraction: /scan/i.test(title),
    };
    this.docs.unshift(doc);
    return doc;
  }

  /** The status stream: one body with the stages and an `end`, then the document has settled. */
  private events(doc: Doc): string {
    const frame = (event: string, data: unknown) =>
      `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
    const status = () => {
      const {
        document_id,
        revision_id,
        status,
        phase,
        failure_code,
        failure_message,
        delivery_state,
        can_retry,
        can_replace,
      } = doc;
      return {
        document_id,
        revision_id,
        status,
        phase,
        failure_code,
        failure_message,
        delivery_state,
        can_retry,
        can_replace,
      };
    };
    let body = "";
    if (doc.status === "queued") {
      this.setState(doc, "processing");
      doc.phase = "extracting";
      body += frame("status", status());
      doc.phase = "embedding";
      body += frame("status", status());
      this.setState(doc, doc.failsExtraction ? "failed" : "ready");
    }
    body += frame("status", status());
    return body + frame("end", { reason: "terminal" });
  }

  private async handle(route: Route): Promise<void> {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace(/^\/api/, "");
    const key = `${request.method()} ${path}`;
    this.calls.push(key);
    const buffer = request.postDataBuffer()?.toString("latin1") ?? "";
    const field = (name: string) =>
      new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]*)`).exec(buffer)?.[1] ?? "";
    const fields = (name: string) =>
      [
        ...buffer.matchAll(
          new RegExp(`name="${name}"\\r\\n\\r\\n([^\\r]*)`, "g"),
        ),
      ].map((m) => m[1] ?? "");
    const idempotencyKey = request.headers()["idempotency-key"] ?? "";

    if (
      request.method() !== "GET" &&
      request.headers()["x-csrf-token"] !== CSRF
    ) {
      return this.error(route, 403, "CSRF_INVALID");
    }
    if (key === "GET /v1/auth/me") {
      return this.json(route, 200, {
        user_id: "33333333-3333-4333-8333-333333333333",
        kind: "admin",
        sign_in_provider: "password",
        email: "admin@example.test",
        display_name: null,
        active_department: FIN,
        csrf_token: CSRF,
        expires_at: new Date(Date.now() + 3_600_000).toISOString(),
      });
    }
    if (key === "GET /v1/departments")
      return this.json(route, 200, { departments: DEPARTMENTS });
    if (key === "GET /v1/admin/documents") {
      return this.json(route, 200, {
        items: this.docs.map((d) => this.view(d)),
        next_cursor: null,
        has_more: false,
      });
    }
    if (key === "POST /v1/admin/documents") {
      this.createKeys.push(idempotencyKey);
      const doc = this.newDoc(
        field("title"),
        field("owner_department_id"),
        fields("allowed_department_ids"),
      );
      return this.json(route, 202, this.view(doc));
    }

    const match =
      /^\/v1\/admin\/documents\/([^/]+)(\/events|\/replace|\/retry|\/access)?$/.exec(
        path,
      );
    const doc = this.docs.find((d) => d.document_id === match?.[1]);
    if (match && !doc) return this.error(route, 404, "DOCUMENT_NOT_FOUND");
    if (match && doc) {
      const [, , suffix] = match;
      if (suffix === "/events") {
        return route.fulfill({
          status: 200,
          headers: {
            "content-type": "text/event-stream",
            "cache-control": "no-store",
          },
          body: this.events(doc),
        });
      }
      if (suffix === "/replace" && request.method() === "POST") {
        if (!doc.can_replace)
          return this.error(route, 409, "DOCUMENT_NOT_REPLACEABLE");
        doc.failsExtraction = false;
        this.setState(doc, "queued");
        return this.json(route, 202, this.view(doc));
      }
      if (suffix === "/retry" && request.method() === "POST") {
        this.setState(doc, "queued");
        return this.json(route, 202, this.view(doc));
      }
      if (suffix === "/access" && request.method() === "PATCH") {
        const body = request.postDataJSON() as {
          allowed_department_ids: string[];
        };
        doc.allowed_departments = DEPARTMENTS.filter((d) =>
          body.allowed_department_ids.includes(d.id),
        );
        return this.json(route, 200, this.view(doc));
      }
      if (!suffix && request.method() === "DELETE") {
        this.docs.splice(this.docs.indexOf(doc), 1);
        return route.fulfill({ status: 204 });
      }
    }

    if (key === "POST /v1/admin/imports/preview") {
      return this.json(route, 200, {
        valid_count: 2,
        invalid_count: 1,
        entries: [
          {
            index: 0,
            file: "leave.pdf",
            valid: true,
            title: "Leave policy",
            owner_department: FIN,
            allowed_departments: [FIN, ENG],
          },
          {
            index: 1,
            file: "expenses.pdf",
            valid: true,
            title: "Expenses",
            owner_department: FIN,
            allowed_departments: [FIN],
          },
          {
            index: 2,
            file: "bad.pdf",
            valid: false,
            title: "No access",
            owner_department: FIN,
            allowed_departments: [],
            error_code: "ALLOWED_DEPARTMENTS_MISSING",
          },
        ],
      });
    }
    if (key === "POST /v1/admin/imports/confirm") {
      this.confirmKeys.push(idempotencyKey);
      // Always a partial result. The fake does not model re-sending a ZIP: the real backend scopes
      // idempotency per key, so a second confirm of the same ZIP would create the entries again.
      this.newDoc("Leave policy", FIN.id, [FIN.id, ENG.id]);
      return this.json(route, 200, {
        created_count: 1,
        rejected_count: 1,
        results: [
          {
            index: 0,
            file: "leave.pdf",
            status: "created",
            document_id: this.docs[0]?.document_id,
          },
          {
            index: 1,
            file: "expenses.pdf",
            status: "rejected",
            error_code: "UPLOAD_BACKLOG_FULL",
          },
        ],
      });
    }
    return this.error(route, 404, "NOT_FOUND");
  }
}

export async function installAdminApi(page: Page): Promise<AdminFakeApi> {
  const api = new AdminFakeApi();
  await api.install(page);
  return api;
}
