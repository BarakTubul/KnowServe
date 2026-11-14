# D15 experiment runbook (M3-AC25)

Status: prepared, not run. The design is plan section 12.2. Every step below needs the Owner's separate approval, and the Owner runs them with their own credentials. The runner is `tests/d15/run_d15.py`. It is not part of any image.

## What it proves

On the real path (QStash, the Cloud Run Worker, Neon) a failed delivery is retried, the cap of 4 processing attempts holds, a duplicate delivery produces one claim, and a manual retry after the cap works. The pass criteria are M3-AC25 in the plan.

## Two points to confirm before approving

1. Scenario 1 of plan 12.2 (a transient failure that succeeds on the redelivery) is not run as its own scenario. The existing test handler `fail_then_ok` fails until an operator has retried the job by hand, so it never succeeds on an automatic redelivery. The first retry of the `cycle` run shows the same thing the scenario was meant to show: a non-2xx answer, a redelivery after about 12 seconds, and the attempt counter going to 2. A handler that succeeds on the second delivery (`fail_once`) would need a new Worker image, so it is left out unless the Owner asks for it.
2. The tagged revision changes the service's template. The Worker service sends 100% of traffic to its latest revision. Deploying a no-traffic tagged revision therefore pins traffic to the current revision, and the service template then holds the test settings. Step 6 restores both. Until step 6 is done, do not run the `deploy` workflow, `terraform apply`, or `update-traffic --to-latest`: any of them could put the test flag on the serving traffic.

## Safeguards

- The runner publishes only to a URL of the form `https://d15---....run.app`. The serving URL is refused.
- The experiment jobs use the test types `noop`, `always_fail` and `fail_then_ok`. No document, revision, chunk, R2 object or OpenAI call is involved, and the runner checks that the document table counts did not change.
- At most four experiment jobs and about 16 deliveries, far under the QStash free limit.
- Stop at any unexpected result: step 7.

## Steps

Values used below: project `knowserve-m0-spike`, region `europe-west1`, service `knowserve-worker`, original `KS_WORKER_PUBLIC_URL` `https://knowserve-worker-866929656529.europe-west1.run.app`.

1. Record the starting point. Note the serving revision and its image:
   ```
   gcloud run services describe knowserve-worker --region europe-west1 --project knowserve-m0-spike --format="value(status.latestReadyRevisionName)"
   gcloud run services describe knowserve-worker --region europe-west1 --project knowserve-m0-spike --format="value(spec.template.spec.containers[0].image)"
   ```
   Confirm no real ingestion job is running, because the tagged revision shares the database.

2. Deploy the tagged revision with no traffic (approval A). Use the image from step 1. Get the tag URL from the output, or from `gcloud run services describe knowserve-worker ... --format="value(status.traffic.url)"`. It starts with `https://d15---`:
   ```
   gcloud run deploy knowserve-worker --region europe-west1 --project knowserve-m0-spike --image <IMAGE_FROM_STEP_1> --no-traffic --tag d15 --update-env-vars KS_ENABLE_SPIKE_FAILURE_HOOKS=true,KS_WORKER_PUBLIC_URL=<TAG_URL>
   ```
   Check that traffic still goes 100% to the serving revision and that `<TAG_URL>/health/ready` answers 200.

3. Load the runner's settings without printing them (approval B, PowerShell):
   ```
   $env:KS_DATABASE_URL = gcloud secrets versions access latest --secret database-url --project knowserve-m0-spike
   $env:KS_QSTASH_TOKEN = gcloud secrets versions access latest --secret qstash-token --project knowserve-m0-spike
   $env:KS_D15_TAG_URL = "<TAG_URL>"
   uv run python tests/d15/run_d15.py dry-run
   ```
   The dry run writes nothing. It checks the three values and refuses the serving URL.

4. Run the scenarios one at a time (approval C). Each needs `--i-have-the-owners-approval`:
   ```
   uv run python tests/d15/run_d15.py duplicate --i-have-the-owners-approval
   uv run python tests/d15/run_d15.py cycle --i-have-the-owners-approval
   ```
   `duplicate` takes a few minutes. `cycle` takes about 33 minutes at QStash's default delays (retries after about 12 s, 148 s and 1808 s), then publishes the manual retry. `cap` (`always_fail`, no manual retry) is optional, because `cycle` already shows the cap. Add `--retry-delay-ms 5000` to shorten a run, but then the real delays are not observed. If the terminal session ends, resume with `watch JOB_ID MESSAGE_ID`. The runner writes the job and message ids to a state file in the temporary folder.

5. Collect the Worker side of the record. The runner prints the job rows and the QStash events (time, state, HTTP status, next delivery time). The tagged revision's request log adds what the Worker answered, with times:
   ```
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=knowserve-worker AND httpRequest.requestUrl:\"/internal/jobs/run\" AND timestamp>=\"<START_TIME>\"" --project knowserve-m0-spike --format="table(timestamp,httpRequest.status,labels.\"run.googleapis.com/tag\")"
   ```
   Check that the experiment deliveries reached only the tagged URL. The serving revision must show no experiment delivery.

6. Remove the experiment and restore the service (approval D). The order matters:
   ```
   gcloud run services update-traffic knowserve-worker --region europe-west1 --project knowserve-m0-spike --remove-tags d15
   gcloud run deploy knowserve-worker --region europe-west1 --project knowserve-m0-spike --image <IMAGE_FROM_STEP_1> --no-traffic --remove-env-vars KS_ENABLE_SPIKE_FAILURE_HOOKS --update-env-vars KS_WORKER_PUBLIC_URL=https://knowserve-worker-866929656529.europe-west1.run.app
   gcloud run services update-traffic knowserve-worker --region europe-west1 --project knowserve-m0-spike --to-latest
   ```
   Then check that the live revision has no `KS_ENABLE_SPIKE_FAILURE_HOOKS` and the original public URL, that `/health/ready` answers 200, and that `terraform plan` (read only) shows no change on the Worker. Delete the old tagged revision with `gcloud run revisions delete`. The experiment job rows keep the correlation id prefix `d15-`. Keep them as evidence, or delete them with the Owner's approval.

7. Stop at any unexpected result. Remove the tag (first command of step 6), cancel pending messages with `uv run python tests/d15/run_d15.py cancel MESSAGE_ID ...`, then finish step 6.

## Record

Put the run output into the handoff under M3-AC25: the delivery list for each message (time, HTTP status, retry count), the job rows after each step, the final states, and the confirmation that no document data changed. The M3-AC25 pass criteria are the plan's: QStash retried after a non-2xx answer, the processing attempts stopped at 4, the final job state is consistent, a duplicate delivery produced one claim, and no document, revision, chunk or OpenAI call was involved.
