# Job Board CI/CD -- Step-by-Step Guide

This guide walks through deploying the full CI/CD stack, observing both ECS deployment
strategies in action, and tearing down all resources.

---

## S0 -- Prerequisites

1. AWS CLI: `aws sts get-caller-identity` must return your account ID.
2. Docker installed and running.
3. Python 3.11+ with pip: `python3 --version`.
4. Fork this repository to your GitHub account.
5. Set a shell variable for convenience:
   ```bash
   export ENV=jobboard-cicd   # matches the EnvironmentName CFN parameter default
   ```

---

## S1 -- Create a CodeStar Connection to GitHub

CodePipeline uses a CodeStar Connection to pull source from GitHub. This requires
a one-time manual authorization step in the console because it opens an OAuth flow.

1. Open: AWS console > Developer Tools > Settings > Connections
2. Click **Create connection**, choose **GitHub**, name it `jobboard-github`.
3. Click **Connect to GitHub** -- authorize the AWS Connector for GitHub app.
4. Once status shows **Available**, copy the Connection ARN.
5. Save it:
   ```bash
   export CONNECTION_ARN=arn:aws:codestar-connections:us-east-1:123456789:connection/...
   ```

The ARN will be passed as a CloudFormation parameter. Do not put it in version control.

---

## S2 -- Deploy the CloudFormation stack

```bash
aws cloudformation create-stack \
  --stack-name "$ENV" \
  --template-body file://cfn/template.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=GitHubConnectionArn,ParameterValue="$CONNECTION_ARN" \
    ParameterKey=GitHubOwner,ParameterValue="<your-github-username>" \
    ParameterKey=GitHubRepo,ParameterValue="jobboard-cicd-codepipeline-fargate"
```

If the template is above the 51 KB direct-upload limit, stage to S3 first:
```bash
aws s3 cp cfn/template.yaml "s3://your-staging-bucket/template.yaml"
aws cloudformation create-stack \
  --stack-name "$ENV" \
  --template-url "https://s3.amazonaws.com/your-staging-bucket/template.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters ...
```

Wait for CREATE_COMPLETE:
```bash
aws cloudformation wait stack-create-complete --stack-name "$ENV"
aws cloudformation describe-stacks --stack-name "$ENV" \
  --query 'Stacks[0].Outputs' --output table
```

Note the `ALBDnsName` output. Set it:
```bash
export ALB=$(aws cloudformation describe-stacks --stack-name "$ENV" \
  --query 'Stacks[0].Outputs[?OutputKey==`ALBDnsName`].OutputValue' \
  --output text)
```

At this point the ECS services are running a placeholder image (Python's built-in
HTTP server) which passes ALB health checks but does not serve the real API.
The first pipeline run (S4) replaces it with the Flask app.

---

## S3 -- Publish the shared library to CodeArtifact

The `jobboard_common` Python package is used by both services as a pip dependency.
It lives in this repo under `app/lib/jobboard_common/` and must be published to
CodeArtifact before CodeBuild can install it during Docker builds.

```bash
./scripts/publish-common-lib.sh "$ENV" jobboard-internal
```

Verify it appears:
```bash
aws codeartifact list-package-versions \
  --domain "$ENV" --repository jobboard-internal \
  --package jobboard-common --format pypi \
  --output table
```

---

## S4 -- Trigger the first pipeline run

Push any trivial commit to the `main` branch of your fork to trigger the pipeline:
```bash
echo "# trigger" >> README.md
git commit -am "chore: trigger first pipeline run"
git push
```

Watch all three stages turn green in the console:
```
AWS Console > Developer Tools > CodePipeline > jobboard-cicd-pipeline
```

Or poll from the CLI:
```bash
aws codepipeline get-pipeline-state --name "${ENV}-pipeline" \
  --query 'stageStates[*].{stage:stageName,status:latestExecution.status}' \
  --output table
```

The Build stage takes 3-6 minutes. The Deploy stage completes when both deployment
actions (blue/green and rolling) finish.

---

## S5 -- Smoke test the API

Once the first pipeline run completes, the ECS services are running the real Flask app.

```bash
# Create a job
JOB=$(curl -sf -X POST "http://$ALB/jobs" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Site Reliability Engineer","company":"Acme Corp","description":"Own production reliability."}')
echo $JOB | python3 -m json.tool

# Extract job_id and list jobs
JOB_ID=$(echo $JOB | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
curl -s "http://$ALB/jobs" | python3 -m json.tool

# Submit an application
curl -sf -X POST "http://$ALB/applications" \
  -H 'Content-Type: application/json' \
  -d "{\"job_id\":\"$JOB_ID\",\"applicant_name\":\"Alice Smith\",\"applicant_email\":\"alice@example.com\",\"resume_summary\":\"5 yrs SRE.\"}" \
  | python3 -m json.tool

# List applications for that job
curl -s "http://$ALB/applications?job_id=$JOB_ID" | python3 -m json.tool
```

---

## S6 -- Demo: ECS blue/green deployment

This is the main teaching moment. Make a visible change to `jobs-api`, push, then
watch CodeDeploy shift traffic from the blue task set to the green task set at 10%
per minute -- all without dropping a single request.

1. Edit `app/services/jobs/app.py` -- change the `index()` response message:
   ```python
   return jsonify({"service": "jobs-api", "status": "ok", "version": "v2"}), 200
   ```

2. Commit and push:
   ```bash
   git commit -am "feat(jobs): add version field to index response"
   git push
   ```

3. Open the CodeDeploy deployment in the console:
   ```
   AWS Console > Developer Tools > CodeDeploy > Applications > jobboard-cicd-jobs
                > Deployment Groups > jobboard-cicd-jobs-bluegreen > Deployments
   ```

4. Watch the **Traffic shifting** tab. Every minute CodeDeploy shifts 10% more traffic
   to the green target group. At 100%, CodeDeploy terminates the blue task set after
   a 5-minute wait.

5. During the shift, curl the index endpoint repeatedly to see responses from both
   the old (blue) and new (green) task set:
   ```bash
   for i in $(seq 1 20); do curl -s "http://$ALB/" | python3 -m json.tool; sleep 5; done
   ```

---

## S7 -- Demo: automatic rollback

Introduce a startup crash in `jobs-api` to see CodeDeploy detect the failure via the
CloudWatch alarm and roll back automatically.

1. Edit `app/services/jobs/app.py` -- add a crash at startup (outside any route):
   ```python
   raise RuntimeError("intentional startup crash for rollback demo")
   ```

2. Commit and push:
   ```bash
   git commit -am "demo: intentional crash for rollback demo"
   git push
   ```

3. The Build stage succeeds (the crash is runtime, not compile-time). When CodeDeploy
   tries to shift traffic to the green task set, the tasks crash on startup, the ALB
   returns 5XX responses, and the `jobboard-cicd-alb-5xx` CloudWatch alarm fires.

4. Watch CodeDeploy roll back automatically in the console. The blue task set is kept
   as-is and takes over full traffic again.

5. After observing the rollback, fix the crash, commit, and push again:
   ```bash
   git commit -am "fix(jobs): remove intentional crash"
   git push
   ```

---

## S8 -- Demo: ECS rolling update (contrast)

Change `applications-api` and observe the different (rolling) update behavior.

1. Edit `app/services/applications/app.py` -- change the `index()` response:
   ```python
   return jsonify({"service": "applications-api", "status": "ok", "version": "v2"}), 200
   ```

2. Commit and push:
   ```bash
   git commit -am "feat(applications): add version field to index response"
   git push
   ```

3. Watch the ECS service update in the console:
   ```
   AWS Console > ECS > Clusters > jobboard-cicd > Services > jobboard-cicd-applications-api
                     > Deployments
   ```

   You will see ECS replace the running task with the new task definition revision
   directly -- no traffic-shifting UI, no target group swap. This is the rolling update
   strategy. Compare it to the blue/green experience from S6.

---

## S9 -- Inspect CodeArtifact

Show that CodeArtifact is actually serving packages during builds.

```bash
# List all packages cached in the jobboard-internal repo (includes PyPI upstream)
aws codeartifact list-packages \
  --domain "$ENV" --repository jobboard-internal \
  --output table

# Show versions of the private package you published in S3
aws codeartifact list-package-versions \
  --domain "$ENV" --repository jobboard-internal \
  --package jobboard-common --format pypi \
  --output table

# Authenticate pip locally and do a dry-run install to show the repo works
aws codeartifact login --tool pip --domain "$ENV" --repository jobboard-internal
pip install --dry-run jobboard-common==1.0.0
```

The first build may show popular packages (flask, boto3, gunicorn) cached in the
upstream proxy repo. Subsequent builds use the cached versions, reducing build time
and isolation from PyPI outages.

---

## S10 -- Inspect ECR image tagging

```bash
# List all tags in the jobs-api repo
aws ecr list-images \
  --repository-name "${ENV}/jobs-api" \
  --query 'imageIds[*].imageTag' \
  --output table

# The full git SHA tag makes every image traceable back to a commit
```

Each image is tagged with the full `CODEBUILD_RESOLVED_SOURCE_VERSION` (git SHA), not
just `latest`. This means you can always identify which commit produced which image and
roll back to any previous SHA.

---

## S11 -- Teardown

Run these steps in order to avoid dependency errors.

```bash
# 1. Empty the S3 artifact bucket (required before stack deletion)
BUCKET="${ENV}-artifacts-$(aws sts get-caller-identity --query Account --output text)"
aws s3 rm "s3://$BUCKET" --recursive

# 2. Force-delete both ECR repos (images must be removed first)
aws ecr delete-repository --repository-name "${ENV}/jobs-api" --force
aws ecr delete-repository --repository-name "${ENV}/applications-api" --force

# 3. Delete the CloudFormation stack
aws cloudformation delete-stack --stack-name "$ENV"
aws cloudformation wait stack-delete-complete --stack-name "$ENV"
echo "Stack deleted."

# 4. Delete the CodeArtifact domain (stack deletion removes the repo; domain may persist)
aws codeartifact delete-domain --domain "$ENV" 2>/dev/null || true

# 5. Delete the CodeStar Connection (created manually in S1, not in CFN)
aws codestar-connections delete-connection --connection-arn "$CONNECTION_ARN"

echo "Teardown complete. Verify: no stacks, no ECR repos, no NAT gateway charges."
```

---

## Appendix -- Optional HTTPS with ACM and Route 53

To expose the job board over HTTPS at a custom domain, add these resources after the
core stack is running:

1. Request an ACM certificate in the same region as the ALB:
   ```bash
   CERT_ARN=$(aws acm request-certificate \
     --domain-name api.yourdomain.com \
     --validation-method DNS \
     --query CertificateArn --output text)
   ```
   Add the CNAME record to Route 53 to complete DNS validation.

2. Add an HTTPS listener to the ALB (port 443) referencing the certificate ARN.

3. Update the Jobs and Applications listener rules to attach to the new HTTPS listener.

4. Optionally add an HTTP->HTTPS redirect as the port 80 default action.

This pattern mirrors the logistics-prod project for full production hardening.
