# M0 hosting comparison: same-origin routing without Cloud Run Domain Mapping

Status: DOCUMENTED research only. Nothing here was measured or deployed. No recommendation is made (the Owner decides). Retrieved = 2026-10-30 for every row (pages were fetched with WebFetch/curl and read as text in this session; Cloudflare/Google pages show their own "last updated" dates, not recorded here). UNKNOWN = not found on an official page in this session. INFERENCE = reasoning by this report, not documented. Context: `spike-report.md` finding F1 (Cloud Run domain mappings are preview), OPEN-04, OPEN-10. Options: (A) Firebase Hosting + Cloud Run rewrite; (B) Cloudflare Pages + Cloud Run; (LB) Cloud Run behind a Global external Application Load Balancer (reference only).

Abbreviations of sources: FB-CR = https://firebase.google.com/docs/hosting/cloud-run ; FB-CACHE = https://firebase.google.com/docs/hosting/manage-cache ; FB-CFG = https://firebase.google.com/docs/hosting/full-config ; FB-QUOTA = https://firebase.google.com/docs/hosting/usage-quotas-pricing ; FB-PRICE = https://firebase.google.com/pricing ; CF-WLIM = https://developers.cloudflare.com/workers/platform/limits/ ; CF-PFP = https://developers.cloudflare.com/pages/functions/pricing/ ; CF-RT = https://developers.cloudflare.com/pages/functions/routing/ ; CF-PLIM = https://developers.cloudflare.com/pages/platform/limits/ ; CR-ING = https://docs.cloud.google.com/run/docs/securing/ingress ; CR-HTTPS = https://docs.cloud.google.com/run/docs/triggering/https-request ; CR-TO = https://docs.cloud.google.com/run/docs/configuring/request-timeout ; CR-BILL = https://docs.cloud.google.com/run/docs/configuring/billing-settings.

## A. Firebase Hosting + Cloud Run

| # | Fact | Source |
|---|---|---|
| A1.1 | Rewrite to Cloud Run: after deploy "Your container is now reachable via ... PROJECT_ID.web.app/ and PROJECT_ID.firebaseapp.com/ (Firebase subdomains) ... Any connected custom domains". So default domains serve rewrites without a custom domain | FB-CR |
| A1.2 | Plan: the page says a Cloud Billing account must be associated with the project "to use or try out Cloud Run"; linking billing to a Spark project upgrades it to Blaze. Spark-only (no billing) use of Cloud Run rewrites is not offered on this page | FB-CR (paraphrase of the WebFetch summary; exact sentence not re-quoted) |
| A1.3 | Regions: "Rewrites to Cloud Run from Hosting are supported in the following regions:" followed by a list of 37 regions (asia-east1 ... us-west4, includes us-central1, us-east1, us-west1, europe-west1, europe-west4, asia-northeast1). Best performance when colocated in us-west1, us-central1, us-east1, europe-west1, asia-east1 | FB-CR |
| A1.4 | Unauthenticated: the deploy step says "Respond Y to allow unauthenticated invocations". Whether Hosting can call a private (IAM-protected) service is NOT stated on the page | FB-CR; private-call support UNKNOWN |
| A1.5 | Cloud Run docs list Firebase Hosting among services that use the default run.app URL, so "Disabling the default run.app URL prevents these services ... from working as expected" | CR-ING (section "Disable the default URL") |
| A1.6 | rewrite config shape: `"run": {"serviceId": "...", "region": "..." (optional, default us-central1), "pinTag": true}`; first matching rewrite rule wins; rewrites come after redirects and exact static matches | FB-CR, FB-CFG |
| A2.1 | Cookies: "When using Firebase Hosting together with Cloud Functions or Cloud Run, cookies are generally stripped from incoming requests. This is necessary to allow for efficient CDN cache behavior. Only the specially-named __session cookie is permitted to pass through to the execution of your app." | FB-CACHE |
| A2.2 | "When present, the __session cookie is automatically made a part of the cache key" | FB-CACHE |
| A2.3 | Vary: Hosting "adds Cookie and Authorization to the Vary header by default" for dynamic content (example response header: `vary: X-My-Custom-Header, x-fh-requested-host, accept-encoding, cookie, authorization`) | FB-CACHE |
| A2.4 | Caching: dynamic responses "do not cache on the CDN by default"; "By default, Firebase Hosting sets Cache-Control to private for dynamic content" | FB-CACHE |
| A2.5 | Set-Cookie on responses: not mentioned on the retrieved page. Pass-through behavior UNKNOWN | FB-CACHE; UNKNOWN |
| A3.1 | "Firebase Hosting is subject to a 60-second request timeout. If your app requires more than 60 seconds to run, you'll receive an HTTPS status code 504 (request timeout)." | FB-CR |
| A3.2 | SSE/streaming behavior, response buffering, request/response size limits, HTTP versions toward Cloud Run, WebSocket support for rewrites, allowed methods: not stated on FB-CR, FB-CFG (first 100k chars read; tail 17,980 chars of FB-CFG not read) or FB-CACHE | UNKNOWN |
| A4.1 | Hosting pricing table: Spark storage 10 GB; data transfer 360 MB/day; Blaze: no-cost up to 10 GB storage then $0.026/GB; data transfer no-cost up to 360 MB/day then $0.15/GB; custom domain and SSL included; multiple sites per project included | FB-PRICE |
| A4.2 | The usage page states instead "no cost up to 10 GB/month" data transfer ($0.15/GB beyond on Blaze); on Spark past the limit "we offer a short grace period but then your sites will be disabled ... until the start of the next month". FB-PRICE (360 MB/day) and FB-QUOTA (10 GB/month) disagree: CONFLICT inside official sources | FB-QUOTA vs FB-PRICE |
| A4.3 | Max single file 2 GB; Spark at 10 GB storage cannot deploy new content | FB-QUOTA |
| A4.4 | Extra cost of proxying to Cloud Run on the Hosting side: no separate charge listed on FB-PRICE/FB-QUOTA (Hosting data transfer applies; cache misses and hits both count). Cloud Run is billed per its own pricing (see C4). Budget alerts "do not cap your usage" | FB-QUOTA, FB-PRICE |
| A5.1 | Deploy with firebase-tools (`firebase deploy --only hosting`; `firebase init hosting:github` creates the Actions setup) | FB-CR, https://firebase.google.com/docs/hosting/github-integration |
| A5.2 | GitHub integration page: CLI creates a service account and "Encrypts that service account's JSON key and uploads it ... as a GitHub secret". WIF not mentioned on that page | github-integration page |
| A5.3 | CLI in CI: "We recommend that you authenticate using Application Default Credentials"; `FIREBASE_TOKEN` is "less secure ... no longer recommended". How ADC is obtained from GitHub OIDC is not on that page (WIF-to-CLI: UNKNOWN) | https://firebase.google.com/docs/cli |
| A5.4 | Terraform: google-beta (latest 8.9.0, published 2026-10-27) has `google_firebase_hosting_site`, `_version`, `_release`, `_channel`, `_custom_domain`. Site and version docs carry the warning "This resource is in beta, and should be used with the terraform-provider-google-beta provider". Version example includes `rewrites { run { service_id, region } }` and header configs. Version doc: "Static files are not supported at the moment" (file upload is not Terraform) | https://raw.githubusercontent.com/hashicorp/terraform-provider-google/main/website/docs/r/firebase_hosting_version.html.markdown , .../firebase_hosting_site.html.markdown , https://registry.terraform.io/v1/providers/hashicorp/google-beta |
| A5.5 | Manual steps documented: link billing (Blaze) and create Firebase project/site; static file deploy through firebase-tools | FB-CR, A5.4 |
| A6.1 | Client IP / X-Forwarded-For / Origin / Host as seen by Cloud Run: not documented on the pages read. `x-fh-requested-host` appears in the Vary example (FB-CACHE), meaning the requested host is carried in a header (what Cloud Run sees as Host: UNKNOWN) | FB-CACHE; UNKNOWN |
| A6.2 | Response headers: `firebase.json` `hosting.headers` array (source glob + key/value); example shows Access-Control-Allow-Origin and Cache-Control. Whether they apply to Cloud Run rewrite responses: UNKNOWN (not stated in the part read) | FB-CFG |
| A6.3 | Direct run.app URL: with default ingress the service is reachable from the internet; ingress "internal" excludes internet and does not list Firebase Hosting among allowed sources; "internal-and-cloud-load-balancing" allows only external Application Load Balancer. Default URL can be disabled, but that breaks Firebase Hosting (A1.5) | CR-ING |

## B. Cloudflare Pages + Cloud Run

| # | Fact | Source |
|---|---|---|
| B1.1 | `_redirects` proxying (status 200): "Proxying will only support relative URLs on your site." and "You cannot proxy external domains." External destinations work only for redirects (3xx), not 200 proxy | https://developers.cloudflare.com/pages/configuration/redirects/ |
| B1.2 | `_redirects` limits: 2,000 static + 100 dynamic redirects, 1,000 characters per rule | same |
| B2.1 | Pages Functions requests are billed as Workers requests; Free quota is shared: "100,000 daily request usage", resets midnight UTC. Static asset requests are free and unlimited, but once Functions exist "all requests by default will invoke your Function" unless `_routes.json` excludes static routes | CF-PFP, CF-RT |
| B2.2 | `_routes.json`: at least one include rule; max 100 include/exclude rules combined; 100 characters per rule | CF-RT |
| B2.3 | Free-plan Worker limits: CPU time 10 ms per HTTP request; 50 subrequests per invocation; request body 100 MB (Free Cloudflare plan domain); six simultaneous connections per invocation can wait for response headers | CF-WLIM |
| B2.4 | CPU waiting on I/O: "Time spent waiting on fetch(), KV, or database calls is excluded from CPU time" (page text, paraphrase of table) | CF-WLIM |
| B2.5 | Wall-clock: no limit for HTTP requests while the client stays connected; no enforced response body size limit; a Worker still streaming a response stays active | CF-WLIM |
| B2.6 | Over Free quota: Workers page says exceeding returns Error 1027, with routes failing open or closed. Pages: Settings > Runtime > "Fail open / closed": open serves static assets, closed returns an error page. Limit removable by upgrading to Workers Standard | CF-WLIM, CF-RT |
| B2.7 | Streaming pass-through for Pages Functions proxying an external origin: no Pages-specific page found. A WebSearch summary of Workers docs says a Response built from a stream body is streamed to the client as chunks arrive; I did not open that page in full (secondary, treat as unverified) | WebSearch over developers.cloudflare.com; Pages-specific SSE behavior UNKNOWN |
| B3.1 | Origin Rules are available on the Free plan (availability table: Free = Yes for the first listed row) | https://developers.cloudflare.com/rules/origin-rules/ |
| B3.2 | Host header override "rewrite[s] the HTTP Host header"; an override "will also update the Server Name Indication (SNI) value ... to the same value". Separate SNI override is possible; SNI/DNS override values must be "a valid hostname on the same Cloudflare account" | https://developers.cloudflare.com/rules/origin-rules/features/ |
| B3.3 | Cloudflare says a cloud provider endpoint such as GCP Cloud Run used as an origin may answer 404/400 if the Host header does not match a configured domain; the Origin Rule rewrite is the documented fix (from a WebSearch summary of the Cloudflare for SaaS custom-origin page; page not opened in full) | https://developers.cloudflare.com/cloudflare-for-platforms/cloudflare-for-saas/start/advanced-settings/custom-origin/ |
| B3.4 | Google's statement of Cloud Run host/SNI requirements for run.app origins: not found in official Google docs in this session | UNKNOWN |
| B3.5 | A proxied `api.<domain>` needs a domain in a Cloudflare zone | INFERENCE (not verified; this option depends on owning a domain, the thing the question tries to avoid) |
| B4.1 | Set-Cookie through Pages Functions: not documented on a Pages page. Workers `Headers` doc says Set-Cookie is the exception to comma-concatenation and needs `getAll`/special handling because cookies contain commas | https://developers.cloudflare.com/workers/runtime-apis/headers/ ; pass-through behavior for Pages proxies UNKNOWN |
| B4.2 | `*.pages.dev`: project gets `<project>.pages.dev`; previews get `<hash>.<project>.pages.dev`. Usable as the single origin without buying a domain: a Pages Function on `/api/*` would run on pages.dev | https://developers.cloudflare.com/pages/configuration/preview-deployments/ ; the same-origin use is INFERENCE |
| B5.1 | Pages Free: 500 builds/month, 1 concurrent build, 20,000 files/site, 100 custom domains/project, 100 projects/account; static requests unlimited | CF-PLIM, CF-PFP |
| B5.2 | Paid tiers: Pro 5,000 builds/month, Business 20,000. Functions paid path = Workers Standard (price: UNKNOWN, not retrieved here) | CF-PLIM, CF-RT |
| B6.1 | Deploy: `wrangler pages deploy <dir>` (direct upload); a `functions` folder is compiled only via Wrangler, not drag and drop; `_worker.js` works in both | https://developers.cloudflare.com/pages/get-started/direct-upload/ |
| B6.2 | CI auth documented: `CLOUDFLARE_API_TOKEN` and account ID secrets (Workers GitHub Actions page). GitHub OIDC for Cloudflare: not mentioned on that page (UNKNOWN whether supported) | https://developers.cloudflare.com/workers/ci-cd/external-cicd/github-actions/ |
| B6.3 | Token scopes for Pages: the Terraform doc lists accepted permissions "Pages Read, Pages Write" for `cloudflare_pages_project` | https://raw.githubusercontent.com/cloudflare/terraform-provider-cloudflare/main/docs/resources/pages_project.md |
| B6.4 | Terraform cloudflare provider 5.28.1 (2026-10-20): resources `pages_project` (build_config, deployment_configs incl. compatibility_date) and `pages_domain`; no pages deployment/functions resource in the docs listing (deployments happen via wrangler) | registry.terraform.io/v1/providers/cloudflare/cloudflare ; github.com/cloudflare/terraform-provider-cloudflare/docs/resources listing |
| B7.1 | Forwarded headers (proxied zone): CF-Connecting-IP = client IP; "If there was no existing X-Forwarded-For header ... X-Forwarded-For has an identical value to CF-Connecting-IP"; otherwise Cloudflare appends the connecting proxy IP | https://developers.cloudflare.com/fundamentals/reference/http-headers/ |
| B7.2 | For Worker subrequests to a non-Cloudflare zone, "the Worker script controls the client IP headers: both CF-Connecting-IP and x-real-ip can be altered by the Worker. If the subrequest forwards the original request's headers unchanged, both headers reflect the client's IP address." What Cloud Run (Google Frontend) then exposes in X-Forwarded-For: UNKNOWN | same |
| B7.3 | `_headers`: "Custom headers defined in the _headers file are not applied to responses generated by Pages Functions"; headers must be set in the Function. Max 2,000 characters per header | https://developers.cloudflare.com/pages/configuration/headers/ , CF-PLIM |
| B7.4 | Cloud Run URL stays reachable directly unless ingress is restricted or the default URL is disabled; Cloudflare is not in Cloud Run's ingress allowlist (internal / internal-and-cloud-load-balancing). Using IAM invoker with a token needs Function-side code | CR-ING; the last sentence is INFERENCE |

## C. Cross-cutting

### C1 Public Suffix List

Command: `curl -s https://publicsuffix.org/list/public_suffix_list.dat -o psl.dat` then `grep -nxF "<domain>" psl.dat` and `grep -n "run\.app" psl.dat` (retrieved 2026-10-30; the file's private section begins at line 11247).

| Domain | Result |
|---|---|
| run.app | no exact `run.app` line. Entries found: `*.run.app` (line 13981) and `*.mtls.run.app` (13982): wildcard, so `<name>.run.app` is itself a public suffix |
| web.app | present, line 13983 |
| firebaseapp.com | present, line 13701 |
| pages.dev | present, line 12763 |
| workers.dev | present, line 12765 |

INFERENCE: because all five are public suffixes, `x.web.app` and `y.pages.dev` (and each `*.run.app` service) are different sites, so a page on one default domain calling an API on another default domain is cross-site: SameSite=Lax cookies would not be sent on its fetch/XHR calls, and the browser may treat those cookies as third-party; same-origin routing avoids this.

### C2 Cloud Run (CR-TO, CR-HTTPS, CR-BILL, spike-report.md 2.1)

| # | Fact | Source |
|---|---|---|
| C2.1 | Timeout default 5 min (300 s), extendable to 60 min (3600 s); on timeout Cloud Run closes the connection and returns HTTP 504; the container may keep processing | CR-TO |
| C2.2 | "Cloud Run supports streaming HTTP responses. No configuration is required ... The server has to respond with a Transfer-Encoding: chunked response header." SSE is not named on that page. HTTP/2 is downgraded to HTTP/1 toward the container by default | CR-HTTPS |
| C2.3 | Request-based billing (default): instances "only charged when they process requests, when they start, and when they shut down"; "CPU is only allocated during request processing", so CPU is allocated while a streaming request is active (reading of that sentence) | CR-BILL |
| C2.4 | Idle connection behavior and SSE proxy buffering: not found on the pages read (a connection-timeouts page was fetched but not read for this fact) | UNKNOWN |

### C3 Reference: Global external Application Load Balancer (https://docs.cloud.google.com/load-balancing/pricing, retrieved via https://cloud.google.com/load-balancing/pricing)

| # | Fact |
|---|---|
| C3.1 | Global forwarding rules: first 5 rules $0.025/hour; each additional $0.01/hour. "There are no global data processing charges. Data processing is charged by the region, depending on where the traffic is processed." |
| C3.2 | Example region price (US-region table, Iowa/Oregon entries): inbound data processed $0.008/GiB, outbound $0.008/GiB (Doha shows $0.00984/GiB: regions differ) |
| C3.3 | Arithmetic only: 1 rule x $0.025/h x 730 h = $18.25/month, plus $0.008/GiB x processed GiB. Hours-per-month value 730 is this report's assumption (the page example uses its own month length); NEG/serverless backend, Cloud Armor and certificate costs not computed (UNKNOWN) |
| C3.4 | Cloud Run ingress "internal-and-cloud-load-balancing" allows the external Application Load Balancer and refuses direct run.app internet requests (CR-ING) |

### C4 Cloud Run free tier (reused from spike-report.md 1.1, 1.3, 1.6; source https://cloud.google.com/run/pricing)

180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million requests free per month (request-based billing); 1 GB/GiB North America egress free; per-unit prices beyond the free tier are UNKNOWN in spike-report.md and were not re-retrieved here. Proxy path adds one Cloud Run request per proxied call in options A and B; Hosting/Functions add no Cloud Run charge (INFERENCE).

## Side-by-side

| Criterion | A: Firebase Hosting rewrite | B: Cloudflare Pages (Function proxy or `_redirects`) | LB reference |
|---|---|---|---|
| Same-origin routing without Domain Mapping | Documented: default web.app/firebaseapp.com serve Cloud Run rewrites (A1.1); needs billing/Blaze (A1.2) and public (unauthenticated) service in the documented flow (A1.4) | `_redirects` cannot proxy external hosts (B1.1). Pages Function can fetch an upstream (INFERENCE from Workers fetch; no Pages page confirms). Works on `*.pages.dev` (B4.2). Origin Rule route needs a Cloudflare zone (B3.5) | Needs a domain and LB; Cloud Run ingress can be locked to LB (C3.4) |
| Auth/cookies/SSE | Only `__session` reaches Cloud Run; other cookies stripped (A2.1); 60 s timeout (A3.1); SSE/Set-Cookie behavior UNKNOWN | Cookie/Set-Cookie through Function UNKNOWN (B4.1); no wall-clock cap while client connected (B2.5); streaming through a Pages Function UNKNOWN (B2.7); 10 ms CPU cap excludes upstream wait (B2.4) | Not researched for cookies/SSE: UNKNOWN. Cloud Run limits apply (C2) |
| Free-tier limits and cost | Hosting 10 GB storage; data transfer 360 MB/day or 10 GB/month (conflicting pages, A4.2); Blaze billing account required; Cloud Run free tier (C4) | 100,000 Function requests/day shared; static free/unlimited; 500 builds/month (B2.1, B5.1); Cloud Run free tier | Arithmetic: $18.25/month for one rule + $0.008/GiB (C3.3); above the $0-5 budget by arithmetic |
| Deployment and security | firebase-tools; ADC recommended in CI, WIF path not shown on pages read (A5.3); Terraform: sites/versions/releases are beta provider only, files not covered (A5.4); direct run.app stays reachable unless default URL disabled, and disabling breaks Hosting (A1.5); client-IP forwarding UNKNOWN | wrangler pages deploy; API token auth documented, OIDC not mentioned (B6.2); Terraform covers project/domain, not deployments (B6.4); `_headers` not applied to Function responses (B7.3); CF-Connecting-IP / X-Forwarded-For documented (B7.1); direct run.app stays reachable | LB + Cloud Run ingress restriction closes the run.app path (C3.4); more resources to manage (INFERENCE) |

## Facts that conflict with the current plan or contracts

Contracts were not re-read line by line for this table; items are flagged against the approved topology stated in the task (host-only cookies, session-bound CSRF + Origin check, SSE over fetch POST, rate limiting).

1. Firebase strips every cookie except `__session` before the request reaches Cloud Run (A2.1). The opaque session cookie (and any CSRF cookie) would need to be named `__session`, or the plan changes. Also forces `Cache-Control: private` handling (A2.4).
2. Firebase 60-second timeout (A3.1) is below Cloud Run's 300 s default and could cut long SSE chat streams (504) unless streams finish within 60 s.
3. `_redirects` cannot proxy to Cloud Run (B1.1); B needs a Function (counts toward 100,000/day; chat + API calls all consume it, B2.1).
4. Cloud Run `run.app` is a public suffix (C1): any plan relying on cross-site cookies between `*.pages.dev`/`*.web.app` and `*.run.app` is cross-site; this is the reason same-origin routing is needed.
5. Client IP for rate limiting: Cloud Run sees whatever the proxy sends (A6.1 UNKNOWN; B7.2: a Pages Function controls the IP headers). The rate-limit key design must be validated per option.
6. Origin check: the Origin header seen by the API would be the Hosting/Pages origin; Host seen by Cloud Run differs (Firebase `x-fh-requested-host`, A6.1; Cloudflare Host override, B3.2). Host/Origin allowlists need verification.
7. Spike-report says the Terraform grants allUsers invoker; Firebase's documented flow also requires unauthenticated access (A1.4), so direct run.app access cannot be closed without disabling the default URL, which breaks Hosting (A1.5).
8. Firebase pages disagree on free data transfer (360 MB/day vs 10 GB/month, A4.2).

## What only a deployed spike can measure

1. Whether SSE events are delivered incrementally (no buffering) through Firebase rewrite and through a Pages Function, and through Cloud Run.
2. Real stream cut-off: Firebase 60 s versus Pages Function behavior for 30 to 300 s streams; idle-connection timeouts.
3. Set-Cookie and Cookie pass-through (names other than `__session`, SameSite/Secure/HttpOnly attributes preserved) in both options.
4. Which client-IP, Host, Origin, X-Forwarded-* values the API actually receives.
5. Whether Firebase can invoke a private Cloud Run service and whether the Firebase CLI can authenticate in GitHub Actions via OIDC/WIF.
6. Whether `_headers`/`firebase.json` headers (CSP) reach Cloud Run rewrite or Function responses.
7. Cold-start latency added by each path, and actual Function request counts per chat session against the 100,000/day quota.
8. POST/large-body handling (upload sizes) through each proxy.
