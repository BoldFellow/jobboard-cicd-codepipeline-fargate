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

Initial build complete 2026-05-30. Not yet deployed or pushed to GitHub.

Key files:
- cfn/template.yaml: single CFN stack (all resources)
- buildspec.yml: CodeBuild build contract
- appspec.yaml + taskdef.template.json: CodeDeploy ECS blue/green contract
- app/lib/jobboard_common/: shared wheel published to CodeArtifact (guide S3)
- app/services/jobs/app.py + Dockerfile: jobs-api Flask service
- app/services/applications/app.py + Dockerfile: applications-api Flask service
- scripts/publish-common-lib.sh: publishes jobboard-common wheel to CodeArtifact
- guide.md: S0 prereqs -> S11 teardown + Appendix HTTPS

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

## Next Steps

- Validate CFN template: aws cloudformation validate-template --template-body file://cfn/template.yaml
- Create GitHub repo, push, set as remote origin
- Follow guide S0-S4 to deploy and run first pipeline
- Export architecture.drawio to architecture.png (requires draw.io desktop or CLI)
- Push to GitHub after validation

## Completed

## Session Notes

2026-05-30: Initial build -- all files created (CFN, buildspec, appspec, taskdef template,
  Flask apps, jobboard_common, scripts, guide, README, .claude/context.md). Not yet deployed.
