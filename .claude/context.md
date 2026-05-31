<!-- Updated by Claude. Last write: 2026-05-31. Overwrite in place -- preserve section headings. -->

# jobboard-cicd-codepipeline-fargate -- Session Context

## Purpose

CI/CD portfolio project. Demonstrates the full AWS-managed pipeline stack:
GitHub -> CodeStar Connection -> CodePipeline -> CodeBuild -> CodeArtifact
-> ECR -> CodeDeploy ECS blue/green + ECS rolling update -> ECS Fargate + DynamoDB.

Domain: job board (jobs-api + applications-api). The pipeline -- not the app -- is the
teaching artifact.

## Stack

- CodePipeline: 3-stage pipeline (Source / Build / Deploy) triggered on push to main
- CodeBuild: ARM64, privileged mode, buildspec.yml; authenticates pip to CodeArtifact,
  builds both Docker images, pushes to ECR, renders taskdef.json + imagedefinitions.json
- CodeArtifact: domain + jobboard-internal repo (pypi upstream proxy + jobboard-common wheel)
- ECR: two repos (jobs-api, applications-api); images tagged with git SHA
- CodeDeploy: ECS blue/green for jobs-api (CodeDeployDefault.ECSLinear10PercentEvery1Minutes);
  auto-rollback on ALB 5XX CloudWatch alarm
- ECS Fargate: two services in private subnets (ARM64 tasks, 0.25 vCPU / 512 MB each)
  - jobs-api-svc: DeploymentController CODE_DEPLOY (blue/green)
  - applications-api-svc: ECS rolling (default)
- ALB: HTTP :80; /jobs* -> jobs-blue TG; /applications* -> applications TG
- DynamoDB: Jobs table + Applications table (on-demand, GSI on job_id)
- VPC: inline 10.40.0.0/16; single NAT GW; 4 VPC endpoints (ECR.dkr, ECR.api, S3, CWLogs)
- IAM: 5 least-privilege roles (task-execution, task-role, codebuild, codedeploy, codepipeline)
- CloudFormation: single stack (cfn/template.yaml) with CAPABILITY_NAMED_IAM

## Active Work

HTML UI added to both services (2026-05-31). Jobs-api and applications-api now serve
Bootstrap 5 HTML to browsers and JSON to API clients (content negotiation via
best_match). S17/S18/S19 demo sections rewritten to drive from the browser. Changes
are code-complete; not yet deployed (requires new pipeline run after commit + push).

Key changes in this session:
- app/services/jobs/app.py: JOBS_HTML constant + content negotiation in list_jobs()
- app/services/applications/app.py: APPS_HTML constant + content negotiation in list_applications()
- scripts/seed-ddb.sh: location + salary fields on both jobs; second application (Bob Jones)
- cfn/template.yaml: ALBListener DefaultActions changed from fixed-response to redirect -> /jobs
- guide.md S17: browser-based demo (salary badge commit, F5 during shift)
- guide.md S18: browser shows Flask 500 page; fix commit restores content-negotiation version
- guide.md S19: browser-based demo (total count banner commit)
- guide.md Appendix A: pre-session redirect check + manual listener update command
- teaching-guide.md S17/S18/S19: matching updates, "What students see in the browser" sections added

Key files:
- cfn/template.yaml: single CFN stack; ALB redirects / -> /jobs (changed from fixed-response)
- buildspec.yml: CodeBuild build contract
- appspec.yaml + taskdef.template.json: CodeDeploy ECS blue/green contract
- app/lib/jobboard_common/: shared wheel published to CodeArtifact
- app/services/jobs/app.py: JOBS_HTML + list_jobs() content negotiation
- app/services/applications/app.py: APPS_HTML + list_applications() content negotiation
- guide.md: S17/S18/S19 rewritten for browser-based demos; Appendix A redirect check added
- teaching-guide.md: S17/S18/S19 updated with browser observation notes

## Key Decisions

2026-05-30: ECS Fargate + CodeDeploy blue/green chosen over App Runner (maintenance mode)
  and Beanstalk (legacy). Research-backed: this is the dominant production pattern in 2024-2025.

2026-05-30: jobboard_common published to CodeArtifact to give CodeArtifact a real purpose --
  both services pip-install it during Docker build. CodeArtifact also proxies public PyPI.

2026-05-30: Placeholder image (python:3.12-slim running http.server) in initial task
  definitions so the ECS services pass ALB health checks before the first pipeline run.
  First CodeDeploy deployment replaces it with the real Flask image.

2026-05-30: PIP_INDEX_URL passed as Docker build-arg with CodeArtifact token. Guide notes
  that production deployments should use Docker BuildKit --secret to avoid token in image
  history.

2026-05-30: Two parallel Deploy stage actions: CodeDeployToECS (jobs blue/green) +
  ECS rolling (applications). This shows both strategies in one pipeline run.

2026-05-30: Single NAT GW (not HA) to minimize cost for a teaching demo. VPC endpoints
  for ECR/CWLogs eliminate NAT traffic for image pulls and log shipping.

2026-05-30: S18 rollback demo requires route-level crash, NOT module-level crash. Module-level
  RuntimeError causes a crash loop before traffic shifts -- CodeDeploy never routes traffic to
  the broken task set, ALB never sees 5XX, alarm never fires. The DEPLOYMENT_FAILURE rollback
  fires but silently times out. Correct S18: raise inside list_jobs() so app passes health
  checks, CodeDeploy shifts traffic, alarm fires. Updated guide.md and app.py.

2026-05-30: Custom CodeDeploy deployment config (linear-20pct-1min: 20% per minute, 5 steps,
  ~5 min) added to cfn/template.yaml. AWS built-in ECSLinear10PercentEvery1Minutes (10 min)
  is too slow for classroom demos. DependsOn added to deployment group to ensure creation order.

2026-05-30: ALB / index route: Flask / route is NOT reachable via ALB for jobs-api because
  the ALB default action (fixed-response) intercepts all requests that don't match /jobs/* or
  /applications/*. Use X-Version response header on /jobs endpoint to observe which task set
  is serving -- not the index response body.

2026-05-31: ALB default action changed from fixed-response to redirect (/ -> /jobs, HTTP_302).
  Students paste the ALB URL in a browser and land directly on the job board. No more
  "Job Board API" text response confusion. CFN listener update is non-disruptive (no TG
  recreation). Pre-session check: curl -sI http://<alb>/ | grep -i location -> /jobs.

2026-05-31: Content negotiation in list_jobs() and list_applications() uses
  best_match(['application/json', 'text/html']). json is FIRST so */* from curl/scripts
  falls through to JSON. Browsers send text/html with higher quality and get HTML.
  Cache-Control: no-store required -- without it the browser caches and the blue/green
  version-flipping demo looks broken.

2026-05-31: S17 demo commit: add salary badge span inside JOBS_HTML card-body (not a Python
  code change). S19 demo commit: add alert-info div inside APPS_HTML after the h4 heading.

## Next Steps

- Open architecture.drawio in draw.io, export to architecture.png
- Teardown when done (S22 in guide.md): empty S3/ECR, delete stack, delete CodeArtifact domain, delete CodeStar Connection

## Completed

2026-05-30: Repo created, pushed to GitHub, stack deployed, first pipeline run complete
2026-05-30: S17 (blue/green demo) -- clean 9-step shift 19:03-19:12, green=100% confirmed
2026-05-30: S18 attempt 1 -- stopped; discovered startup crash is wrong failure mode; guide rewritten
2026-05-30: S18 (rollback demo) -- alarm fired at blue=20/green=80 (4th step); CodeDeploy stopped
  deployment d-VI61WYZQJ with ALARM_ACTIVE reason; traffic snapped to blue=100; GET /jobs=200
  restored within seconds of rollback. Guide updated: wait 5 min after rollback for metric window
  to clear before resetting alarm (CloudWatch ALB metric has ~3 min processing delay).
2026-05-30: S19 (ECS rolling update) -- pipeline a17c1a3e; running=2 briefly at task handoff,
  then running=1/desired=1 steady state; no traffic shifting, no TG swap; completed in ~3 min.
2026-05-30: architecture.drawio created -- pipeline-first layout, 2000x1200, AWS4 icon standard.
2026-05-30: teaching-guide.md created -- instructor setup checklist, timing, per-demo talking
  points, critical gotchas (route-level vs startup crash, 5-min alarm cooldown), recovery procedures.

## Session Notes

2026-05-30: S19 rolling update complete. All three demos verified. Stack at clean steady state.
2026-05-30: architecture.drawio created. Pipeline top half, runtime bottom half, VPC outline.
2026-05-30: teaching-guide.md created. Project complete -- only remaining task is PNG export.
2026-05-31: HTML UI added to both services. ALB redirect added. S17/S18/S19 rewritten for
  browser-based demos. Code complete; deploy requires commit + push + pipeline run.
