<!-- Updated by Claude. Last write: 2026-05-30. Overwrite in place -- preserve section headings. -->

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

All three demo scenarios (S17, S18, S19) complete and verified. Stack at clean steady state.
architecture.drawio created (pipeline-first layout, 2000x1200 canvas). Export to architecture.png pending.
teaching-guide.md created -- instructor-facing guide covering setup, timing, talking points, gotchas, recovery.

Both ECS services healthy (running=1/desired=1). Alarm OK. Latest ECR image = 64fee982 (git HEAD).

Key files:
- cfn/template.yaml: single CFN stack; custom deploy config linear-20pct-1min added
- buildspec.yml: CodeBuild build contract
- appspec.yaml + taskdef.template.json: CodeDeploy ECS blue/green contract
- app/lib/jobboard_common/: shared wheel published to CodeArtifact
- app/services/jobs/app.py: jobs-api Flask service (clean v2)
- app/services/applications/app.py: applications-api with version:v2 index response
- guide.md: all demo sections updated including S18 alarm-wait clarification
- architecture.drawio: pipeline-first diagram (pipeline top half, runtime bottom half)

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

2026-05-30: S18 rollback demo succeeded -- alarm fired during 4th of 5 shift steps, immediate
  rollback to blue TG. S19 queued (applications-api rolling update, commit 958fb6d local only).
2026-05-30: S19 rolling update complete. All three demos verified. Stack at clean steady state.
2026-05-30: architecture.drawio created. Pipeline top half, runtime bottom half, VPC outline.
2026-05-30: teaching-guide.md created. Project complete -- only remaining task is PNG export.
