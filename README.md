# Job Board CI/CD -- CodePipeline + CodeDeploy ECS Blue/Green

A production-realistic AWS CI/CD pipeline demonstrated with a real-world domain:
a job board where companies post openings and candidates apply.

![architecture](architecture.png)

## What you build

Two ECS Fargate services -- `jobs-api` and `applications-api` -- delivered by a single
CodePipeline that illustrates both ECS deployment strategies side-by-side:

| Service | Endpoint | Deployment style |
|---|---|---|
| jobs-api | `/jobs*` | CodeDeploy **blue/green** (linear 10%/min traffic shift) |
| applications-api | `/applications*` | ECS **rolling update** |

The pipeline demonstrates the complete AWS-managed CI/CD stack:

```
GitHub
  --> CodeStar Connection (webhook trigger)
  --> CodePipeline (orchestration)
      Source  -- pulls source ZIP from GitHub
      Build   -- CodeBuild (Docker build + push to ECR)
                     CodeArtifact supplies pip deps (jobboard-common + pypi upstream proxy)
      Deploy  -- CodeDeployToECS (blue/green, jobs-api)
             -- ECS rolling update (applications-api)
```

### Services and backing resources

- **CodePipeline** -- three-stage pipeline triggered on every push to `main`
- **CodeBuild** -- ARM64 container build; authenticates pip to CodeArtifact, builds both images, pushes to ECR, renders `taskdef.json` + `imagedefinitions.json`
- **CodeArtifact** -- private Python package registry; hosts `jobboard-common` wheel + proxies public PyPI
- **ECR** -- two repos; images tagged with git SHA for traceability
- **CodeDeploy** -- ECS blue/green for jobs-api; shifts 10% of traffic per minute; auto-rollback on ALB 5XX alarm
- **ECS Fargate** -- two services on ARM64 tasks in private subnets behind an ALB
- **DynamoDB** -- on-demand tables for `Jobs` and `Applications`
- **CloudWatch Alarm** -- gates CodeDeploy rollback when 5XX rate exceeds threshold

## Prerequisites

- AWS CLI configured with admin credentials (`aws sts get-caller-identity` should succeed)
- Docker (for the placeholder-image push in S2 -- not required if you skip to S4 with CFN only)
- Python 3.11+ with `pip`, `build`, and `twine` (for publishing `jobboard_common`)
- A GitHub account with a fork of this repository

## Repository layout

```
.
+-- cfn/
|   +-- template.yaml          single CFN stack (VPC + all CI/CD + ECS + DDB)
+-- app/
|   +-- lib/
|   |   +-- jobboard_common/   shared Python package published to CodeArtifact
|   +-- services/
|       +-- jobs/              Flask jobs-api (port 8080)
|       +-- applications/      Flask applications-api (port 8081)
+-- scripts/
|   +-- publish-common-lib.sh  one-time: publish jobboard_common wheel to CodeArtifact
|   +-- seed-ddb.sh            optional: seed sample data via ALB
+-- buildspec.yml              CodeBuild build contract
+-- appspec.yaml               CodeDeploy ECS blue/green deployment spec
+-- taskdef.template.json      task definition template; rendered to taskdef.json by CodeBuild
```

## Estimated cost

| Resource | Cost |
|---|---|
| NAT Gateway | ~$1.10/day |
| ALB | ~$0.50/day |
| ECS Fargate 2 tasks (ARM64, 0.25 vCPU / 0.5 GB each) | ~$0.50/day |
| DynamoDB on-demand | ~$0 |
| CodeArtifact + ECR storage | ~$0.10/day |
| CodeBuild | ~$0.005/min (only during builds) |
| CodePipeline | First execution/month free, then $1 each |

**Total: ~$2.20/day idle.** Tear down after each session -- see guide.md S11.

## Guide

See [guide.md](guide.md) for the full step-by-step walkthrough (S0-S12).
