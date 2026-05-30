# Teaching Guide -- Job Board CI/CD Pipeline

Instructor-facing reference. Students follow `guide.md`. This file covers setup,
timing, talking points, console paths, demo gotchas, and recovery procedures.

---

## What this project teaches

The three demos each isolate one capability of the pipeline:

| Demo | Section | Core concept |
|---|---|---|
| Blue/green deployment | S17 | Controlled traffic shift with zero downtime |
| Automatic rollback | S18 | Alarm-triggered CodeDeploy rollback; CloudWatch metric latency |
| Rolling update contrast | S19 | ECS default deployment vs blue/green -- trade-offs are visible |

Supporting sections reinforce secondary concepts:
- S20 (CodeArtifact): private package registry as a first-class artifact store
- S21 (ECR image tagging): git SHA immutability and audit trail

---

## Pre-session setup

Allow **30-45 minutes** before class for setup and verification. Do not attempt to
set up during the session -- CodeStar Connection requires an interactive GitHub OAuth
that cannot be automated.

### Step 1 -- Deploy the stack (10-15 min)

Complete S0 and S1 manually (fork, CodeStar Connection OAuth). Then use the CFN
shortcut from Appendix A:

```bash
export ENV=jobboard-cicd
export CONNECTION_ARN=arn:aws:codeconnections:us-east-1:ACCOUNT:connection/...

aws cloudformation create-stack \
  --stack-name "$ENV" \
  --template-body file://cfn/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=GitHubConnectionArn,ParameterValue="$CONNECTION_ARN" \
    ParameterKey=GitHubOwner,ParameterValue="<your-github-username>" \
    ParameterKey=GitHubRepo,ParameterValue="jobboard-cicd-codepipeline-fargate"

aws cloudformation wait stack-create-complete --stack-name "$ENV"
```

Save the ALB DNS name from the stack outputs:
```bash
export ALB=$(aws cloudformation describe-stacks --stack-name "$ENV" \
  --query 'Stacks[0].Outputs[?OutputKey==`ALBDnsName`].OutputValue' --output text)
```

### Step 2 -- Publish the shared library (2 min)

```bash
./scripts/publish-common-lib.sh jobboard-cicd jobboard-internal
```

Verify:
```bash
aws codeartifact list-package-versions \
  --domain jobboard-cicd --repository jobboard-internal \
  --package jobboard-common --format pypi --output table
```

### Step 3 -- Run the first pipeline (5-8 min)

Push a trivial commit and manually trigger:
```bash
git commit --allow-empty -m "chore: trigger initial pipeline run"
git push
aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
```

Wait for all three stages to go green. The first run replaces the placeholder
`python:3.12-slim http.server` images with the real Flask services.

### Step 4 -- Smoke test (2 min)

```bash
JOB=$(curl -sf -X POST "http://$ALB/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"SRE","company":"Acme Corp","description":"Own production."}')
echo $JOB | python3 -m json.tool

JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

curl -sf -X POST "http://$ALB/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB_ID\",\"applicant_name\":\"Alice\",\"applicant_email\":\"alice@example.com\",\"resume_summary\":\"5 yrs SRE.\"}" \
  | python3 -m json.tool
```

Both calls should return 201 with valid JSON.

### Step 5 -- Pre-flight checklist

Run all of these before students arrive:

```
[ ] Both ECS services: running=1/desired=1
    ECS > Clusters > jobboard-cicd > Services

[ ] CloudWatch alarm: OK state
    CloudWatch > Alarms > jobboard-cicd-alb-5xx

[ ] GET /jobs returns 200 with no X-Version header (clean v1 state)
    curl -si "http://$ALB/jobs" | grep -E 'HTTP|X-Version'

[ ] app/services/jobs/app.py has no RuntimeError line (clean state)
    grep -n "RuntimeError" app/services/jobs/app.py  # should return nothing

[ ] CodePipeline shows last execution as Succeeded
    aws codepipeline get-pipeline-state --name jobboard-cicd-pipeline \
      --query 'stageStates[*].[stageName,latestExecution.status]' --output table
```

---

## Session flow and timing

Total classroom time: **50-60 minutes** (not counting setup).

| Block | Content | Time |
|---|---|---|
| Orientation | Architecture walk, pipeline overview | 10 min |
| S17 | Blue/green demo (live) | 15-20 min |
| S18 | Rollback demo (live) + reset | 20-25 min |
| S19 | Rolling update contrast | 5 min |
| S20-21 | CodeArtifact + ECR inspection | 5 min |
| Teardown discussion | Cost, cleanup, appendices | 5 min |

The S18 reset (fix commit + clean pipeline run + 5-min alarm cooldown) is the
longest single wait. Pre-fill the fix commit in a terminal tab before S18 so you
can push in seconds after the rollback completes.

---

## Orientation -- talking points (10 min)

Open `architecture.drawio` on the projector. Walk the diagram left-to-right, top
to bottom:

**Top half -- the delivery pipeline:**
1. "A developer pushes to GitHub main. CodeStar Connection forwards the webhook to
   CodePipeline -- that is the trigger."
2. "CodeBuild runs buildspec.yml. It authenticates to CodeArtifact to pip-install
   our shared library, builds both Docker images, pushes them to ECR tagged with
   the git SHA. It then renders the task definition and appspec files as artifacts."
3. "Two Deploy actions run in parallel. jobs-api goes through CodeDeploy blue/green.
   applications-api uses ECS rolling update. Same commit, same pipeline run, two
   different deployment strategies -- that contrast is the whole point."

**Bottom half -- the runtime:**
4. "The ALB routes /jobs/* to the jobs target group, /applications/* to the
   applications target group. Both services read from DynamoDB. The services never
   touch the internet -- ECR image pulls and CloudWatch logs go through VPC endpoints."
5. "The CloudWatch alarm on the left is the safety net. If it fires during a
   CodeDeploy shift, CodeDeploy rolls traffic back automatically -- no human in the loop."

**Key question to ask students:** "What is the difference between CodeDeploy stopping
a deployment versus ECS stopping a deployment?"
Answer: CodeDeploy has a separate rollback mechanism that shifts traffic back to the
original task set. ECS rolling update just stops the new task -- it does not revert
traffic because there is no traffic-shifting concept in rolling.

---

## S17 -- Blue/green demo (15-20 min)

### What this demo teaches

Students see that "zero-downtime deployment" is not magic -- it is two live task sets,
a weighted listener rule, and a controlled shift window. The shift is slow enough
(20%/min, 5 steps) to observe in real time.

### Setup (in advance or live)

Edit `app/services/jobs/app.py`, add `X-Version` header to `list_jobs()`:

```python
@app.route("/jobs", methods=["GET"])
def list_jobs():
    resp = jsonify(scan_items(JOBS_TABLE))
    resp.headers["X-Version"] = "v2"
    return resp, 200
```

Commit and push, then manually trigger:
```bash
git commit -am "feat(jobs): add X-Version header"
git push
aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
```

### Console path during the shift

```
CodeDeploy > Applications > jobboard-cicd-jobs
  > Deployment Groups > jobboard-cicd-jobs-bluegreen
  > Deployments > (latest) > Traffic shifting tab
```

The Traffic shifting tab is the clearest visual. It shows the current weight split
and each shift step with a timestamp.

### What to watch for

- Build stage takes 4-6 min (Docker build + push). Wait until the Deploy stage starts.
- Traffic shifting begins when the green task set passes health checks. You will see
  the split move: 80/20 -> 60/40 -> 40/60 -> 20/80 -> 0/100.
- Each step is 1 minute.
- After 100% green, CodeDeploy waits 5 minutes then terminates the blue task set.

### ALB weight monitor (run in a separate terminal)

```bash
LISTENER=$(aws elbv2 describe-listeners \
  --load-balancer-arn $(aws elbv2 describe-load-balancers \
    --names jobboard-cicd-alb \
    --query 'LoadBalancers[0].LoadBalancerArn' --output text) \
  --query 'Listeners[0].ListenerArn' --output text)

for i in $(seq 1 10); do
  echo -n "[$(date +%H:%M:%S)] "
  aws elbv2 describe-rules --listener-arn $LISTENER --output json | python3 -c "
import sys,json; data=json.load(sys.stdin)
for rule in data['Rules']:
    if rule.get('Priority')=='10':
        for tg in rule['Actions'][0]['ForwardConfig']['TargetGroups']:
            n='blue' if 'blue' in tg['TargetGroupArn'] else 'green'
            print(f'{n}={tg[\"Weight\"]}', end=' ')
        break
print()
"
  sleep 60
done
```

### Verify the shift is complete

```bash
# Should return X-Version: v2 header (green task set serving)
curl -si "http://$ALB/jobs" | grep X-Version
```

### Talking points during the shift

- "Notice /jobs is still returning 200 the entire time. No traffic is dropped."
- "The ALB is doing weighted forwarding between two live target groups. The app did
  not restart -- two independent task sets exist simultaneously during the shift."
- "What would happen if the new task set was unhealthy? The CloudWatch alarm would
  fire, CodeDeploy would roll back to blue. We demo that next."
- After 100%: "CodeDeploy holds the blue task set alive for 5 minutes after full
  cutover. That is the rollback window -- if something wrong surfaces in production
  after the shift, CodeDeploy can still snap back."

### Gotcha -- ALB index route

The ALB default action (a fixed-response 200) intercepts `GET /` before the
`/jobs*` rule. Calling `curl http://$ALB/` returns 200 from the ALB itself, not
the Flask app. This confuses students. Use `/jobs` not `/` as the health probe.

---

## S18 -- Rollback demo (20-25 min, including reset)

### What this demo teaches

Automatic rollback wired to a CloudWatch alarm. Students see the alarm as an active
infrastructure contract, not just an alert. CodeDeploy observing the alarm is a
service-level SLO enforcer.

### Critical distinction -- route-level vs startup crash

**This is the most common demo failure mode.** If you raise RuntimeError at module
level (outside a function), the container crashes at startup. ECS keeps it in a
crash loop. CodeDeploy never shifts traffic to the broken task set because it never
passes health checks. The ALB never sees 5XX. The alarm never fires.

CodeDeploy eventually times out and reports DEPLOYMENT_FAILURE -- that is a different
(less interesting) rollback mechanism and misses the alarm story entirely.

**Always raise inside `list_jobs()`, not at module level.**

### Setup (right after S17 completes)

Edit `app/services/jobs/app.py` -- raise inside the route handler:

```python
@app.route("/jobs", methods=["GET"])
def list_jobs():
    raise RuntimeError("simulated database connection failure")
    return jsonify(scan_items(JOBS_TABLE)), 200
```

Commit and push:
```bash
git commit -am "demo: intentional 500 on GET /jobs for rollback demo"
git push
aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
```

### Start the load loop immediately

The load loop must be running before CodeDeploy starts shifting traffic. If you
start it too late, CodeDeploy may complete the shift to green before any requests
hit the broken handler. The alarm only fires if it actually sees 5XX responses.

```bash
# Open a dedicated terminal. Keep this running for the entire demo.
while true; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://$ALB/jobs")
  echo "[$(date +%H:%M:%S)] GET /jobs -> $STATUS"
  sleep 3
done
```

### Console paths to open (side by side on projector)

```
Left panel:
  CloudWatch > Alarms > jobboard-cicd-alb-5xx

Right panel:
  CodeDeploy > Applications > jobboard-cicd-jobs
    > Deployment Groups > jobboard-cicd-jobs-bluegreen
    > Deployments > (latest) > Traffic shifting tab
```

### What to watch for

1. Build stage succeeds (the RuntimeError is inside a function, not at import time).
2. CodeDeploy starts the shift. Load loop shows 200 (hitting blue task set still).
3. At 20% to green, some requests start returning 500 (load loop shows 500).
4. CloudWatch alarm transitions to ALARM within 1-2 minutes of first 500.
5. CodeDeploy stops the shift and rolls traffic back to 100% blue.
6. Load loop returns to 200 immediately.

### After rollback -- reset procedure (5-min wait required)

ALB 5XX metrics have a ~3-minute processing delay in CloudWatch. If you reset the
alarm immediately and start the fix deployment, CloudWatch evaluates the still-pending
historical data bucket and can re-fire the alarm within 60 seconds -- stopping the
recovery deployment too. This looks like the fix failed.

**Wait 5 minutes from the last 500 response, then:**

```bash
# Step 1 -- reset the alarm
aws cloudwatch set-alarm-state \
  --alarm-name jobboard-cicd-alb-5xx \
  --state-value OK \
  --state-reason "Manual reset before fix deployment"

# Step 2 -- fix the bug
# Edit app/services/jobs/app.py: remove the raise RuntimeError line
# list_jobs() should return:
#   return jsonify(scan_items(JOBS_TABLE)), 200

# Step 3 -- push the fix (NO load loop during recovery)
git commit -am "fix(jobs): remove intentional 500 from list_jobs"
git push
aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
```

Do not run the load loop during the fix deployment. Let it complete cleanly.

### Verify clean state after fix

```bash
curl -s "http://$ALB/jobs" | python3 -m json.tool
aws cloudwatch describe-alarms \
  --alarm-names jobboard-cicd-alb-5xx \
  --query 'MetricAlarms[0].StateValue' --output text  # should be OK
```

### Talking points during the demo

- While the load loop shows 200: "CodeDeploy is running tasks in green but the
  listener still forwards 80% to blue. The broken handler exists but is not yet
  reachable from the public internet."
- When the first 500 appears: "There it is -- green just received a request and
  returned a 500. That goes into the ALB 5XX metric bucket."
- When the alarm fires: "The alarm crossed the threshold. CodeDeploy is watching
  that alarm -- it will stop the shift and snap back to blue immediately."
- After rollback: "Notice we did not click anything. No PagerDuty, no human in the
  loop. The infrastructure enforced its own SLO."
- During the 5-min wait: "Why are we waiting? CloudWatch ALB metrics are near-real-
  time but not instant. There is a 2-3 minute processing delay. If we reset the alarm
  too early, a CloudWatch evaluation triggered by still-pending historical data can
  re-fire the alarm and kill the fix deployment. We are waiting for the pipeline to
  clear the observation window."

---

## S19 -- Rolling update contrast (5 min)

### What this demo teaches

The difference between ECS rolling update and CodeDeploy blue/green is architectural,
not just visual. Rolling update is faster and simpler but has no rollback wire.

### Setup

Edit `app/services/applications/app.py`:

```python
return jsonify({"service": "applications-api", "status": "ok", "version": "v2"}), 200
```

```bash
git commit -am "feat(applications): add version to index response"
git push
aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
```

### Console path

```
ECS > Clusters > jobboard-cicd
  > Services > jobboard-cicd-applications-api-svc
  > Deployments tab
```

### What to watch for

ECS shows two deployment rows briefly: the old revision at desiredCount=0/runningCount=1
while the new revision is at desiredCount=1/runningCount=0. Within 2-3 minutes the old
task is deregistered and drained, and the new one is running. No Traffic shifting tab,
no target group swap visible anywhere.

### Talking points

- "Where is the Traffic shifting tab? There is none. ECS replaces the task directly --
  there is no green task set, no rollback window, no alarm wire."
- "When would you choose rolling over blue/green? For stateless services that are
  tolerant of brief restarts. For a job board API that is read-heavy and has no
  long-lived connections, rolling is probably fine. For a payment service that must
  never serve a bad transaction, blue/green with a rollback alarm is the right choice."
- "Both strategies ran in the same pipeline run. That is intentional -- it shows that
  the pipeline does not impose one strategy. Each service chooses its own."

---

## S20 -- CodeArtifact (5 min)

Run these commands on the projector:

```bash
# Show the private package
aws codeartifact list-package-versions \
  --domain jobboard-cicd --repository jobboard-internal \
  --package jobboard-common --format pypi --output table

# Show the upstream cache after a few builds (flask, boto3 appear here)
aws codeartifact list-packages \
  --domain jobboard-cicd --repository jobboard-internal --output table
```

**Talking point:** "CodeArtifact is doing two things. It hosts our private wheel
`jobboard-common`, which both services install during Docker build. It also caches
public PyPI. After 3-4 pipeline runs, all the transitive dependencies are cached.
The build no longer reaches the public internet for packages -- faster and isolated
from upstream outages."

---

## S21 -- ECR image tagging (2 min)

```bash
aws ecr list-images \
  --repository-name "jobboard-cicd/jobs-api" \
  --query 'imageIds[*].imageTag' --output table
```

**Talking point:** "Every image is tagged with the full git SHA from
CODEBUILD_RESOLVED_SOURCE_VERSION. `latest` is a convenience alias -- it moves with
every build. The SHA tag is immutable. If the S18 rollback had not caught the bug,
we could revert by redeploying the previous SHA tag. That is why git SHA tagging
matters in production."

---

## Teardown (end of session)

Do not leave the stack running. The NAT gateway alone costs ~$1.10/day.

```bash
# 1. Empty S3 artifact bucket
BUCKET="jobboard-cicd-artifacts-$(aws sts get-caller-identity --query Account --output text)"
aws s3 rm "s3://$BUCKET" --recursive

# 2. Force-delete both ECR repos
aws ecr delete-repository --repository-name "jobboard-cicd/jobs-api" --force
aws ecr delete-repository --repository-name "jobboard-cicd/applications-api" --force

# 3. Delete the CFN stack
aws cloudformation delete-stack --stack-name jobboard-cicd
aws cloudformation wait stack-delete-complete --stack-name jobboard-cicd

# 4. Delete CodeArtifact domain (may persist after stack delete)
aws codeartifact delete-domain --domain jobboard-cicd 2>/dev/null || true

# 5. Delete the CodeStar Connection
aws codeconnections delete-connection --connection-arn "$CONNECTION_ARN"
```

---

## Common problems and recovery

### Pipeline does not trigger on push

GitHub webhooks through CodeStar Connections are unreliable in demo environments.
Always use manual trigger:
```bash
aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
```

### CodeBuild fails: "unable to pull jobboard-common"

The shared library was not published or the CodeArtifact token expired. Re-run:
```bash
./scripts/publish-common-lib.sh jobboard-cicd jobboard-internal
```

### CodeDeploy fails: "deployment group has no target group"

The blue/green service was recreated and lost its TG assignment. Recreate the CodeDeploy
deployment group (S14) pointing at the new service and target groups.

### S18 alarm never fires (rollback demo fails)

Likely cause: RuntimeError is at module level, not inside list_jobs(). The container
is in a crash loop. Check:
```bash
aws ecs describe-services --cluster jobboard-cicd \
  --services jobboard-cicd-jobs-api-svc \
  --query 'services[0].events[0:5]' --output table
```

If you see "task stopped" events repeatedly, that is the crash loop. Edit app.py so
the raise is inside the list_jobs() function body and re-push.

### S18 alarm fires again during the fix deployment

You reset the alarm too soon. The CloudWatch ALB metric pipeline has a ~3-min delay.
Wait 5 minutes from the last 500 response. Then reset the alarm and push the fix.
Verify the alarm is in OK state before triggering the pipeline:
```bash
aws cloudwatch describe-alarms \
  --alarm-names jobboard-cicd-alb-5xx \
  --query 'MetricAlarms[0].StateValue' --output text
```

### ECS service stuck in DRAINING

An in-progress CodeDeploy deployment locked the task set. Check for an active
deployment and either let it finish or stop it:
```bash
aws deploy list-deployments \
  --application-name jobboard-cicd-jobs \
  --deployment-group-name jobboard-cicd-jobs-bluegreen \
  --include-only-statuses InProgress
```

### Both services show 0 running tasks after CFN stack create

The placeholder task definition uses a public ECR image. The VPC endpoints are for
your private ECR repos, not public.ecr.aws. The placeholder image pulls via NAT --
if the NAT GW is not yet healthy, the pull fails. Wait 2-3 minutes and check again:
```bash
aws ecs describe-services --cluster jobboard-cicd \
  --services jobboard-cicd-jobs-api-svc jobboard-cicd-applications-api-svc \
  --query 'services[*].[serviceName,runningCount,desiredCount]' --output table
```

---

## Pre-demo state checklist (quick reference)

Run this block before every demo section to confirm clean state:

```bash
# Services healthy
aws ecs describe-services --cluster jobboard-cicd \
  --services jobboard-cicd-jobs-api-svc jobboard-cicd-applications-api-svc \
  --query 'services[*].[serviceName,runningCount,desiredCount]' --output table

# Alarm OK
aws cloudwatch describe-alarms --alarm-names jobboard-cicd-alb-5xx \
  --query 'MetricAlarms[0].StateValue' --output text

# API healthy
curl -si "http://$ALB/jobs" | head -2

# No RuntimeError in app.py (required before S17 and after S18 reset)
grep -n "RuntimeError" app/services/jobs/app.py && echo "FOUND -- clean up before demo" || echo "clean"
```

All should show: running=desired, OK, HTTP/1.1 200, clean.

---

## Windows students -- publish-common-lib.py

Students on Windows cannot run `publish-common-lib.sh`. Use the Python equivalent
instead -- it does exactly the same thing and runs on Windows, macOS, and Linux.

**Requirements:** Python 3.11+, AWS CLI, git. No Docker, no bash.

```
python scripts/publish-common-lib.py
# or with explicit domain/repo:
python scripts/publish-common-lib.py jobboard-cicd jobboard-internal
```

The script:
1. Creates a temp venv, installs `build` and `twine` into it
2. Builds the wheel from `app/lib/jobboard_common/`
3. Runs `aws codeartifact login --tool twine` to get a scoped upload token
4. Uploads the wheel with `twine upload --repository codeartifact`
5. Prints a table of the published versions as confirmation

**How to verify it worked:**

```bash
# Option 1 -- CLI (works on all platforms)
aws codeartifact list-package-versions \
  --domain jobboard-cicd \
  --repository jobboard-internal \
  --package jobboard-common \
  --format pypi \
  --output table
# Expected: one row, version=1.0.0, status=Published

# Option 2 -- console
# CodeArtifact > Repositories > jobboard-internal > jobboard-common
# Shows version, upload timestamp, and available files (.whl)

# Option 3 -- authenticate pip locally and dry-run install
aws codeartifact login --tool pip --domain jobboard-cicd --repository jobboard-internal
pip install --dry-run jobboard-common==1.0.0
# Expected: "Would install jobboard-common-1.0.0"
```

---

## Is the app functional? Using it as a real job board

Yes -- the app is fully functional. Both services perform real CRUD operations
against DynamoDB. Students can use it as an actual job board during and after demos.

### Jobs API -- full reference

```bash
export ALB=<your-alb-dns-name>

# Create a job posting
curl -sf -X POST "http://$ALB/jobs" \
  -H 'Content-Type: application/json' \
  -d '{
    "title": "Backend Engineer",
    "company": "Acme Corp",
    "description": "Build APIs at scale."
  }' | python3 -m json.tool
# Returns: { "job_id": "...", "title": "...", "status": "open", "created_at": "..." }

# List all jobs
curl -s "http://$ALB/jobs" | python3 -m json.tool

# Get a specific job (replace JOB_ID)
curl -s "http://$ALB/jobs/JOB_ID" | python3 -m json.tool

# Update a job
curl -sf -X PUT "http://$ALB/jobs/JOB_ID" \
  -H 'Content-Type: application/json' \
  -d '{"status": "closed"}' | python3 -m json.tool

# Delete a job
curl -sf -X DELETE "http://$ALB/jobs/JOB_ID"
# Returns: HTTP 204 No Content
```

### Applications API -- full reference

```bash
# Apply to a job (JOB_ID must exist in DynamoDB first)
curl -sf -X POST "http://$ALB/applications" \
  -H 'Content-Type: application/json' \
  -d "{
    \"job_id\": \"JOB_ID\",
    \"applicant_name\": \"Alice Smith\",
    \"applicant_email\": \"alice@example.com\",
    \"resume_summary\": \"5 years SRE experience, AWS certified.\"
  }" | python3 -m json.tool
# Returns: { "application_id": "...", "status": "submitted", "applied_at": "..." }

# List all applications for a specific job
curl -s "http://$ALB/applications?job_id=JOB_ID" | python3 -m json.tool

# List ALL applications (no filter)
curl -s "http://$ALB/applications" | python3 -m json.tool

# Get a specific application
curl -s "http://$ALB/applications/APPLICATION_ID" | python3 -m json.tool
```

### End-to-end flow students can run themselves

```bash
# 1. Post two jobs
JOB1=$(curl -sf -X POST "http://$ALB/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"SRE","company":"Acme","description":"Own prod."}')
JOB2=$(curl -sf -X POST "http://$ALB/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Data Engineer","company":"Acme","description":"Build pipelines."}')

JOB1_ID=$(echo $JOB1 | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
JOB2_ID=$(echo $JOB2 | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")

# 2. Apply to the first job twice
curl -sf -X POST "http://$ALB/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB1_ID\",\"applicant_name\":\"Alice\",\"applicant_email\":\"alice@example.com\",\"resume_summary\":\"5 yrs SRE.\"}" \
  | python3 -m json.tool

curl -sf -X POST "http://$ALB/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB1_ID\",\"applicant_name\":\"Bob\",\"applicant_email\":\"bob@example.com\",\"resume_summary\":\"3 yrs SRE.\"}" \
  | python3 -m json.tool

# 3. See both applicants for the SRE role
curl -s "http://$ALB/applications?job_id=$JOB1_ID" | python3 -m json.tool

# 4. List all jobs -- both appear
curl -s "http://$ALB/jobs" | python3 -m json.tool
```

### The point of a functional app (not just a stub)

The app is real so students can see the pipeline's output is a working service --
not just a "hello world" that prints text. The teaching value of each demo is
reinforced when students can observe the impact on live data:

- **S17:** After the shift to green, the X-Version header changes but the jobs data
  is still there -- DynamoDB is shared between both task sets.
- **S18:** When the rollback fires, the `GET /jobs` that was returning 500 immediately
  starts returning the real job list again -- the data was never affected.
- **S19:** After the rolling update, `GET /applications?job_id=...` still returns
  the same applications -- task replacement did not affect persistence.

The separation of compute (ECS tasks) from state (DynamoDB) is something students
can verify themselves with curl, making the "stateless containers" principle concrete.
