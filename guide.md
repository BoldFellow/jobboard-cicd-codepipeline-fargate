# Job Board CI/CD -- Step-by-Step Guide

This guide walks through building the full CI/CD pipeline for two ECS Fargate services
using the AWS console. You will create every resource by hand so you can see exactly
what each service does. A CloudFormation shortcut is provided at the end for repeat
deployments.

---

## S0 -- Prerequisites

1. AWS CLI configured: `aws sts get-caller-identity` must return your account ID.
2. Python 3.11+ with pip: `python3 --version`.
3. Fork this repository to your GitHub account.
4. Set a shell variable (used in CLI commands throughout this guide):
   ```bash
   export ENV=jobboard-cicd
   export REGION=us-east-1
   export ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
   ```

---

## S1 -- Create a CodeStar Connection to GitHub

CodePipeline uses a CodeStar Connection to pull source from GitHub and receive push
webhooks. This requires a one-time manual OAuth flow in the console.

1. Open: **AWS Console > Developer Tools > Settings > Connections**
2. Click **Create connection**, choose **GitHub**, name it `jobboard-github`
3. Click **Connect to GitHub** -- authorize the AWS Connector for GitHub app
4. Once status shows **Available**, copy the Connection ARN
5. Save it:
   ```bash
   export CONNECTION_ARN=arn:aws:codeconnections:us-east-1:ACCOUNT:connection/...
   ```

---

## S2 -- Create the VPC and networking

### VPC

1. Open: **VPC > Your VPCs > Create VPC**
2. Choose **VPC and more**
3. Name tag: `jobboard-cicd`
4. IPv4 CIDR: `10.40.0.0/16`
5. Number of AZs: **2**
6. Public subnets: **2** (CIDRs `10.40.1.0/24` and `10.40.2.0/24`)
7. Private subnets: **2** (CIDRs `10.40.11.0/24` and `10.40.12.0/24`)
8. NAT gateways: **1 per AZ** -- change to **In 1 AZ** to save cost
9. VPC endpoints: leave as none (we add them next)
10. Click **Create VPC**

Save the VPC ID and subnet IDs -- you will need them for the ECS service configuration.

### VPC Endpoints (keep ECR image pulls and CloudWatch off the NAT)

1. Open: **VPC > Endpoints > Create endpoint**
2. Create four endpoints inside `jobboard-cicd-vpc`, all in the two private subnets:

   | Name | Service | Type |
   |---|---|---|
   | `jobboard-cicd-ecr-dkr` | `com.amazonaws.us-east-1.ecr.dkr` | Interface |
   | `jobboard-cicd-ecr-api` | `com.amazonaws.us-east-1.ecr.api` | Interface |
   | `jobboard-cicd-cwlogs` | `com.amazonaws.us-east-1.logs` | Interface |
   | `jobboard-cicd-s3` | `com.amazonaws.us-east-1.s3` | Gateway |

   For each Interface endpoint: enable **Private DNS names**, attach the endpoint
   security group you will create in S3.

### Security Groups

Create two security groups in `jobboard-cicd-vpc`:

**ALB security group** (`jobboard-cicd-alb-sg`):
- Inbound: TCP 80 from `0.0.0.0/0`
- Outbound: all traffic

**ECS security group** (`jobboard-cicd-ecs-sg`):
- Inbound: TCP 8080 from the ALB security group
- Inbound: TCP 8081 from the ALB security group
- Outbound: all traffic

**Endpoint security group** (`jobboard-cicd-endpoint-sg`):
- Inbound: TCP 443 from the ECS security group
- Go back and attach this group to the three Interface VPC endpoints above

---

## S3 -- Create DynamoDB tables

### Jobs table

1. Open: **DynamoDB > Create table**
2. Table name: `jobboard-cicd-jobs`
3. Partition key: `job_id` (String)
4. Table settings: **Customize settings**
5. Capacity mode: **On-demand**
6. Click **Create table**

### Applications table

1. Open: **DynamoDB > Create table**
2. Table name: `jobboard-cicd-applications`
3. Partition key: `application_id` (String)
4. Table settings: **Customize settings**
5. Capacity mode: **On-demand**
6. Click **Create table**
7. After creation, open the table > **Indexes > Create index**
   - Partition key: `job_id` (String)
   - Index name: `job_id-index`
   - Projection: **All**
   - Click **Create index**

---

## S4 -- Create ECR repositories

1. Open: **ECR > Create repository**
2. Create two private repositories:
   - `jobboard-cicd/jobs-api`
   - `jobboard-cicd/applications-api`
3. For each: enable **Scan on push**, leave encryption as AES-256

---

## S5 -- Create CloudWatch Log Group

1. Open: **CloudWatch > Logs > Log groups > Create log group**
2. Log group name: `/ecs/jobboard-cicd`
3. Retention: **1 week**

---

## S6 -- Create IAM roles

You need five roles. Create each one under **IAM > Roles > Create role**.

### Role 1 -- Task execution role

- Trusted entity: **AWS service -- Elastic Container Service Task**
- Add managed policy: `AmazonECSTaskExecutionRolePolicy`
- Role name: `jobboard-cicd-task-execution`

### Role 2 -- Task role (DynamoDB access)

- Trusted entity: **AWS service -- Elastic Container Service Task**
- Role name: `jobboard-cicd-task-role`
- After creation, attach this inline policy (replace `ACCOUNT` and `REGION`):
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
          "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan"
        ],
        "Resource": [
          "arn:aws:dynamodb:REGION:ACCOUNT:table/jobboard-cicd-jobs",
          "arn:aws:dynamodb:REGION:ACCOUNT:table/jobboard-cicd-applications",
          "arn:aws:dynamodb:REGION:ACCOUNT:table/jobboard-cicd-applications/index/job_id-index"
        ]
      }
    ]
  }
  ```

### Role 3 -- CodeBuild role

- Trusted entity: **AWS service -- CodeBuild**
- Role name: `jobboard-cicd-codebuild`
- After creation, attach this inline policy (replace `ACCOUNT` and `REGION`):
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
        "Resource": [
          "arn:aws:logs:REGION:ACCOUNT:log-group:/ecs/jobboard-cicd",
          "arn:aws:logs:REGION:ACCOUNT:log-group:/ecs/jobboard-cicd:*",
          "arn:aws:logs:REGION:ACCOUNT:log-group:/aws/codebuild/*",
          "arn:aws:logs:REGION:ACCOUNT:log-group:/aws/codebuild/*:*"
        ]
      },
      {
        "Effect": "Allow",
        "Action": ["ecr:GetAuthorizationToken"],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ecr:BatchCheckLayerAvailability", "ecr:PutImage",
          "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload", "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ],
        "Resource": [
          "arn:aws:ecr:REGION:ACCOUNT:repository/jobboard-cicd/jobs-api",
          "arn:aws:ecr:REGION:ACCOUNT:repository/jobboard-cicd/applications-api"
        ]
      },
      {
        "Effect": "Allow",
        "Action": ["codeartifact:GetAuthorizationToken"],
        "Resource": "arn:aws:codeartifact:REGION:ACCOUNT:domain/jobboard-cicd"
      },
      {
        "Effect": "Allow",
        "Action": ["codeartifact:GetRepositoryEndpoint", "codeartifact:ReadFromRepository"],
        "Resource": "arn:aws:codeartifact:REGION:ACCOUNT:repository/jobboard-cicd/jobboard-internal"
      },
      {
        "Effect": "Allow",
        "Action": ["sts:GetServiceBearerToken"],
        "Resource": "*",
        "Condition": {"StringEquals": {"sts:AWSServiceName": "codeartifact.amazonaws.com"}}
      },
      {
        "Effect": "Allow",
        "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:GetBucketVersioning"],
        "Resource": [
          "arn:aws:s3:::jobboard-cicd-artifacts-ACCOUNT",
          "arn:aws:s3:::jobboard-cicd-artifacts-ACCOUNT/*"
        ]
      },
      {
        "Effect": "Allow",
        "Action": ["sts:GetCallerIdentity"],
        "Resource": "*"
      }
    ]
  }
  ```

### Role 4 -- CodeDeploy role

- Trusted entity: **AWS service -- CodeDeploy**
- Add managed policy: `AWSCodeDeployRoleForECS`
- Role name: `jobboard-cicd-codedeploy`

### Role 5 -- CodePipeline role

- Trusted entity: **AWS service -- CodePipeline**
- Role name: `jobboard-cicd-codepipeline`
- After creation, attach this inline policy (replace `ACCOUNT`, `REGION`,
  and `CONNECTION_ARN`):
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": ["codestar-connections:UseConnection"],
        "Resource": "CONNECTION_ARN"
      },
      {
        "Effect": "Allow",
        "Action": ["codebuild:BatchGetBuilds", "codebuild:StartBuild", "codebuild:StopBuild"],
        "Resource": "arn:aws:codebuild:REGION:ACCOUNT:project/jobboard-cicd-build"
      },
      {
        "Effect": "Allow",
        "Action": [
          "codedeploy:CreateDeployment", "codedeploy:GetApplication",
          "codedeploy:GetApplicationRevision", "codedeploy:GetDeployment",
          "codedeploy:GetDeploymentConfig", "codedeploy:RegisterApplicationRevision"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": [
          "ecs:DescribeServices", "ecs:DescribeTaskDefinition", "ecs:DescribeTasks",
          "ecs:ListTasks", "ecs:RegisterTaskDefinition", "ecs:UpdateService"
        ],
        "Resource": "*"
      },
      {
        "Effect": "Allow",
        "Action": ["iam:PassRole"],
        "Resource": [
          "arn:aws:iam::ACCOUNT:role/jobboard-cicd-task-execution",
          "arn:aws:iam::ACCOUNT:role/jobboard-cicd-task-role"
        ]
      },
      {
        "Effect": "Allow",
        "Action": ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:GetBucketVersioning"],
        "Resource": [
          "arn:aws:s3:::jobboard-cicd-artifacts-ACCOUNT",
          "arn:aws:s3:::jobboard-cicd-artifacts-ACCOUNT/*"
        ]
      }
    ]
  }
  ```

---

## S7 -- Create the S3 artifact bucket

1. Open: **S3 > Create bucket**
2. Bucket name: `jobboard-cicd-artifacts-ACCOUNT` (replace with your account ID)
3. Region: `us-east-1`
4. Enable versioning
5. Leave all other defaults and create

---

## S8 -- Create ALB, target groups, and listener

### Target groups (create all three first)

**Target group 1 -- jobs-blue** (for the blue task set):
1. Open: **EC2 > Target groups > Create target group**
2. Type: **IP addresses**
3. Name: `jobboard-cicd-jobs-blue`
4. Protocol: HTTP / Port: **8080**
5. VPC: `jobboard-cicd-vpc`
6. Health check: HTTP `/health`
7. Healthy threshold: 2

**Target group 2 -- jobs-green** (for the green task set):
- Same settings, name: `jobboard-cicd-jobs-green`

**Target group 3 -- applications**:
1. Name: `jobboard-cicd-applications`
2. Protocol: HTTP / Port: **8081**
3. VPC: `jobboard-cicd-vpc`
4. Health check: HTTP `/health`
5. Healthy threshold: 2

### Application Load Balancer

1. Open: **EC2 > Load balancers > Create load balancer > Application Load Balancer**
2. Name: `jobboard-cicd-alb`
3. Scheme: **Internet-facing**
4. Subnets: select both public subnets (`10.40.1.0/24` and `10.40.2.0/24`)
5. Security group: `jobboard-cicd-alb-sg`
6. Listener: HTTP:80
7. Default action: forward to `jobboard-cicd-jobs-blue`
8. Create

### Listener rules

After the ALB is created, open the HTTP:80 listener and add two rules:

**Rule 1** (insert before default):
- Condition: Path is `/jobs*`
- Action: Forward to `jobboard-cicd-jobs-blue`
- Priority: 1

**Rule 2** (insert before default):
- Condition: Path is `/applications*`
- Action: Forward to `jobboard-cicd-applications`
- Priority: 2

Save the ALB DNS name:
```bash
export ALB=<ALB-DNS-name-from-console>
```

---

## S9 -- Create CodeArtifact domain and repository

### Domain

1. Open: **CodeArtifact > Domains > Create domain**
2. Domain name: `jobboard-cicd`
3. Encryption: AWS managed key
4. Create

### Repository

1. Open: **CodeArtifact > Repositories > Create repository**
2. Repository name: `jobboard-internal`
3. Public upstream repository: select **pypi-store** (public PyPI upstream proxy)
4. Domain: `jobboard-cicd`
5. Create

---

## S10 -- Publish the shared library to CodeArtifact

The `jobboard_common` package is used by both Flask services as a pip dependency.
Publish it once before the first pipeline run.

```bash
./scripts/publish-common-lib.sh jobboard-cicd jobboard-internal
```

Verify it appears:
```bash
aws codeartifact list-package-versions \
  --domain jobboard-cicd --repository jobboard-internal \
  --package jobboard-common --format pypi --output table
```

---

## S11 -- Create ECS cluster, task definitions, and services

### Cluster

1. Open: **ECS > Clusters > Create cluster**
2. Cluster name: `jobboard-cicd`
3. Infrastructure: **AWS Fargate** (serverless)
4. Create

### Task definition -- jobs-api (placeholder)

1. Open: **ECS > Task definitions > Create new task definition**
2. Family: `jobboard-cicd-jobs-api`
3. CPU: `0.25 vCPU`, Memory: `0.5 GB`
4. Task role: `jobboard-cicd-task-role`
5. Task execution role: `jobboard-cicd-task-execution`
6. Operating system / Architecture: **Linux/ARM64**
7. Container:
   - Name: `jobs-api`
   - Image URI: `public.ecr.aws/docker/library/python:3.12-slim`
   - Port: `8080`
   - Environment variables:
     - `JOBS_TABLE` = `jobboard-cicd-jobs`
     - `APPLICATIONS_TABLE` = `jobboard-cicd-applications`
   - Command override: `python3,-m,http.server,8080`
   - Log collection: **Amazon CloudWatch**, log group `/ecs/jobboard-cicd`,
     stream prefix `jobs-api`
8. Create

This placeholder passes ALB health checks on port 8080. The first CodeDeploy
deployment replaces it with the real Flask image.

### Task definition -- applications-api (placeholder)

Same as above with these differences:
- Family: `jobboard-cicd-applications-api`
- Container name: `applications-api`
- Port: `8081`
- Command override: `python3,-m,http.server,8081`
- Stream prefix: `applications-api`

### ECS service -- jobs-api (blue/green via CodeDeploy)

1. Open: **ECS > Clusters > jobboard-cicd > Create service**
2. Launch type: **Fargate**
3. Task definition: `jobboard-cicd-jobs-api` (latest)
4. Service name: `jobboard-cicd-jobs-api-svc`
5. Desired tasks: **1**
6. Deployment type: **Blue/green deployment (powered by CodeDeploy)**
   - This is the critical choice. It locks the service to the CODE_DEPLOY
     deployment controller, which is required for blue/green traffic shifting.
7. Load balancer: `jobboard-cicd-alb`
8. Container to load balance: `jobs-api:8080`
9. Production listener: HTTP:80
10. Target group 1 (blue): `jobboard-cicd-jobs-blue`
11. Target group 2 (green): `jobboard-cicd-jobs-green`
12. Networking: private subnets, `jobboard-cicd-ecs-sg`
13. Create

### ECS service -- applications-api (rolling update)

1. Open: **ECS > Clusters > jobboard-cicd > Create service**
2. Launch type: **Fargate**
3. Task definition: `jobboard-cicd-applications-api` (latest)
4. Service name: `jobboard-cicd-applications-api-svc`
5. Desired tasks: **1**
6. Deployment type: **Rolling update**
   - This is the default. ECS replaces tasks directly with no traffic-shifting UI.
     Compare this to the blue/green service -- both strategies run in the same
     pipeline run, side-by-side.
7. Load balancer: `jobboard-cicd-alb`
8. Container to load balance: `applications-api:8081`
9. Target group: `jobboard-cicd-applications`
10. Networking: private subnets, `jobboard-cicd-ecs-sg`
11. Create

Wait for both services to reach **ACTIVE** and show 1 running task each.

---

## S12 -- Create the CloudWatch alarm (CodeDeploy rollback trigger)

1. Open: **CloudWatch > Alarms > Create alarm**
2. Metric: **ApplicationELB > Per AppELB Metrics > HTTPCode_Target_5XX_Count**
3. Select the `jobboard-cicd-alb` load balancer
4. Statistic: **Sum**, Period: **1 minute**
5. Threshold: Greater than **5**
6. Missing data treatment: **Treat as good**
7. Alarm name: `jobboard-cicd-alb-5xx`
8. Skip notification actions (no SNS needed for the rollback trigger)
9. Create

CodeDeploy will watch this alarm during every blue/green deployment. If it fires,
traffic is shifted back to the original task set automatically.

---

## S13 -- Create the CodeBuild project

1. Open: **CodeBuild > Build projects > Create build project**
2. Project name: `jobboard-cicd-build`

**Source:**
- Provider: **GitHub** (via CodeStar Connection `jobboard-github`)
- Repository: your fork of `jobboard-cicd-codepipeline-fargate`
- Source version: `main`

**Environment:**
- Managed image
- Operating system: **Amazon Linux**
- Runtime: **Standard**
- Image: `aws/codebuild/amazonlinux-aarch64-standard:3.0`
- Image version: Always use the latest
- Environment type: **Linux ARM64**
- Enable **Privileged mode** (required for Docker builds)
- Service role: **Existing role** -- `jobboard-cicd-codebuild`

**Environment variables** (add all of these):

| Name | Value |
|---|---|
| `JOBS_ECR_REPO` | `ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/jobboard-cicd/jobs-api` |
| `APPS_ECR_REPO` | `ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/jobboard-cicd/applications-api` |
| `CODEARTIFACT_DOMAIN` | `jobboard-cicd` |
| `CODEARTIFACT_REPO` | `jobboard-internal` |
| `TASK_EXECUTION_ROLE_ARN` | `arn:aws:iam::ACCOUNT:role/jobboard-cicd-task-execution` |
| `TASK_ROLE_ARN` | `arn:aws:iam::ACCOUNT:role/jobboard-cicd-task-role` |
| `JOBS_TABLE` | `jobboard-cicd-jobs` |
| `APPLICATIONS_TABLE` | `jobboard-cicd-applications` |
| `ECS_LOG_GROUP` | `/ecs/jobboard-cicd` |
| `ENVIRONMENT_NAME` | `jobboard-cicd` |

**Buildspec:**
- Use buildspec file (the `buildspec.yml` in the repository root)

**Logs:**
- CloudWatch Logs: enable
- Log group: `/ecs/jobboard-cicd`
- Stream name prefix: `codebuild`

3. Create build project

---

## S14 -- Create the CodeDeploy application and deployment group

### Application

1. Open: **CodeDeploy > Applications > Create application**
2. Application name: `jobboard-cicd-jobs`
3. Compute platform: **Amazon ECS**
4. Create

### Deployment group

1. Open the `jobboard-cicd-jobs` application > **Create deployment group**
2. Deployment group name: `jobboard-cicd-jobs-bluegreen`
3. Service role: `jobboard-cicd-codedeploy`
4. ECS cluster: `jobboard-cicd`
5. ECS service: `jobboard-cicd-jobs-api-svc`
6. Load balancer: `jobboard-cicd-alb`
7. Production listener: HTTP:80
8. Target group 1: `jobboard-cicd-jobs-blue`
9. Target group 2: `jobboard-cicd-jobs-green`
10. Deployment configuration: **jobboard-cicd-linear-20pct-1min** (created by the CFN stack)
    - This shifts 20% of traffic to the new task set every minute -- 5 steps over
      ~5 minutes. Faster than the AWS default (10%/min) while still showing the
      gradual shift clearly in the console.
11. Rollback: enable **Roll back when a deployment fails** and
    **Roll back when alarm thresholds are met**
12. Alarms: add `jobboard-cicd-alb-5xx`
13. Create deployment group

---

## S15 -- Create the CodePipeline

1. Open: **CodePipeline > Pipelines > Create pipeline**
2. Pipeline name: `jobboard-cicd-pipeline`
3. Service role: **Existing role** -- `jobboard-cicd-codepipeline`
4. Artifact store: **Custom location** -- S3 bucket `jobboard-cicd-artifacts-ACCOUNT`

**Source stage:**
- Provider: **GitHub (via GitHub App / CodeStar Connections)**
- Connection: `jobboard-github`
- Repository: `BoldFellow/jobboard-cicd-codepipeline-fargate` (your fork)
- Branch: `main`
- Detection: **Webhooks** (automatic trigger on push)
- Output artifact: `SourceOutput`

**Build stage:**
- Provider: **AWS CodeBuild**
- Project: `jobboard-cicd-build`
- Input: `SourceOutput`
- Output: `BuildOutput`

**Deploy stage:**

Add two parallel actions (both at Run Order 1):

**Action 1 -- jobs-api blue/green:**
- Action name: `DeployJobsBlueGreen`
- Provider: **Amazon ECS (Blue/Green)**
- Input: `BuildOutput`
- Application: `jobboard-cicd-jobs`
- Deployment group: `jobboard-cicd-jobs-bluegreen`
- Task definition: `BuildOutput` -- `taskdef.json`
- AppSpec: `BuildOutput` -- `appspec.yaml`

**Action 2 -- applications-api rolling:**
- Action name: `DeployApplicationsRolling`
- Provider: **Amazon ECS**
- Input: `BuildOutput`
- Cluster: `jobboard-cicd`
- Service: `jobboard-cicd-applications-api-svc`
- Image definitions file: `imagedefinitions.json`

5. Create pipeline

CodePipeline immediately executes once on creation. Watch all three stages turn
green in the console.

---

## S16 -- Smoke test the API

Once the first pipeline run completes, both ECS services are running the real Flask
app. Set the ALB DNS name:
```bash
export ALB=$(aws elbv2 describe-load-balancers \
  --names jobboard-cicd-alb \
  --query 'LoadBalancers[0].DNSName' --output text)
```

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

## S17 -- Demo: ECS blue/green deployment

This is the main teaching moment. Make a visible change to `jobs-api`, push, then
watch CodeDeploy shift traffic from the blue task set to the green task set at 20%
per minute (5 steps, ~5 minutes) -- all without dropping a single request.

1. Edit `app/services/jobs/app.py` -- add a `version` field to the `list_jobs()` response
   header or change a log message. The cleanest visible change is adding a custom
   response header in `list_jobs()`:
   ```python
   @app.route("/jobs", methods=["GET"])
   def list_jobs():
       resp = jsonify(scan_items(JOBS_TABLE))
       resp.headers["X-Version"] = "v2"
       return resp, 200
   ```

2. Commit and push:
   ```bash
   git commit -am "feat(jobs): add X-Version header to list_jobs"
   git push
   ```

3. Manually trigger the pipeline (webhook is unreliable):
   ```bash
   aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
   ```

4. Open the deployment in the console:
   ```
   CodeDeploy > Applications > jobboard-cicd-jobs
     > Deployment Groups > jobboard-cicd-jobs-bluegreen > Deployments
   ```

5. Watch the **Traffic shifting** tab. Every minute CodeDeploy shifts 20% more
   traffic to the new target group. At 100%, CodeDeploy waits 5 minutes then
   terminates the old task set.

6. Monitor the ALB rule weights while the shift is in progress:
   ```bash
   LISTENER="<your ALB listener ARN>"
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

   **Note:** The `/` (index) route on `jobs-api` is not reachable via ALB because the
   ALB default action intercepts it before the `/jobs/*` rule. Use the `X-Version`
   header on `/jobs` responses, or watch the CodeDeploy Traffic shifting tab in the
   console, as the primary indicator of the shift.

---

## S18 -- Demo: automatic rollback

Introduce a bug inside a route handler so the app starts normally, passes health
checks, but returns 500 on API requests. CodeDeploy shifts traffic, the ALB 5XX
alarm fires, and CodeDeploy rolls back automatically.

**Why not a startup crash?** If the app crashes at startup (e.g. `raise RuntimeError`
at module level), ECS keeps the tasks crash-looping, CodeDeploy never shifts traffic,
and the ALB never sees 5XX responses. The alarm never fires. CodeDeploy eventually
times out and fails -- a DEPLOYMENT_FAILURE rollback, not an alarm-triggered one.
A route-level error gives the more interesting demo.

1. Edit `app/services/jobs/app.py` -- add an intentional error inside `list_jobs()`:
   ```python
   @app.route("/jobs", methods=["GET"])
   def list_jobs():
       raise RuntimeError("simulated database connection failure")
       return jsonify(scan_items(JOBS_TABLE)), 200
   ```

2. Commit and push:
   ```bash
   git commit -am "demo: intentional 500 on GET /jobs for rollback demo"
   git push
   aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
   ```

3. The Build stage succeeds (the app imports fine). CodeDeploy starts shifting 20%
   traffic to the new task set. Once traffic reaches the broken set, GET /jobs
   returns 500.

4. Generate load to trigger the alarm (threshold: > 5 HTTP 5XX in 60 seconds):
   ```bash
   for i in $(seq 1 30); do curl -s "http://$ALB/jobs" > /dev/null; sleep 2; done
   ```

5. Watch the `jobboard-cicd-alb-5xx` CloudWatch alarm turn ALARM. CodeDeploy detects
   the DEPLOYMENT_STOP_ON_ALARM event and initiates an automatic rollback. Traffic
   shifts back to the original task set.

6. Fix the bug, commit, and push:
   ```python
   # remove the raise RuntimeError line, restore list_jobs to:
   @app.route("/jobs", methods=["GET"])
   def list_jobs():
       return jsonify(scan_items(JOBS_TABLE)), 200
   ```
   ```bash
   git commit -am "fix(jobs): remove intentional 500 from list_jobs"
   git push
   aws codepipeline start-pipeline-execution --name jobboard-cicd-pipeline
   ```

---

## S19 -- Demo: ECS rolling update (contrast)

Change `applications-api` and observe the simpler rolling update behavior --
no traffic-shifting UI, no target group swap.

1. Edit `app/services/applications/app.py` -- change the `index()` response:
   ```python
   return jsonify({"service": "applications-api", "status": "ok", "version": "v2"}), 200
   ```

2. Commit and push:
   ```bash
   git commit -am "feat(applications): add version field to index response"
   git push
   ```

3. Watch the ECS service in the console:
   ```
   ECS > Clusters > jobboard-cicd > Services > jobboard-cicd-applications-api-svc
     > Deployments
   ```

   ECS replaces the running task with the new task definition revision directly.
   Compare this to the blue/green experience from S17 -- no traffic-shifting tab,
   no target group swap, no 10-minute window. This is the trade-off: simpler and
   faster, but no controlled canary-style rollout.

---

## S20 -- Inspect CodeArtifact

```bash
# List all packages in the private repo (includes PyPI upstream cache)
aws codeartifact list-packages \
  --domain jobboard-cicd --repository jobboard-internal --output table

# Show the private package you published in S10
aws codeartifact list-package-versions \
  --domain jobboard-cicd --repository jobboard-internal \
  --package jobboard-common --format pypi --output table

# Authenticate pip locally and do a dry-run install
aws codeartifact login --tool pip --domain jobboard-cicd --repository jobboard-internal
pip install --dry-run jobboard-common==1.0.0
```

After a few builds, popular packages (flask, boto3, gunicorn) appear in the cache.
Subsequent builds hit the cache instead of public PyPI -- faster and isolated from
upstream outages.

---

## S21 -- Inspect ECR image tagging

```bash
aws ecr list-images \
  --repository-name "jobboard-cicd/jobs-api" \
  --query 'imageIds[*].imageTag' --output table
```

Each image is tagged with the full `CODEBUILD_RESOLVED_SOURCE_VERSION` (git SHA),
not just `latest`. Every image is traceable back to a commit, and you can roll back
to any previous SHA by redeploying a named image tag.

---

## S22 -- Teardown

Run these steps in order to avoid dependency errors.

```bash
# 1. Empty the S3 artifact bucket (required before stack deletion)
aws s3 rm "s3://jobboard-cicd-artifacts-$ACCOUNT" --recursive

# 2. Force-delete both ECR repos
aws ecr delete-repository --repository-name "jobboard-cicd/jobs-api" --force
aws ecr delete-repository --repository-name "jobboard-cicd/applications-api" --force

# 3. Delete ECS services (scale to 0 first)
aws ecs update-service --cluster jobboard-cicd \
  --service jobboard-cicd-jobs-api-svc --desired-count 0
aws ecs update-service --cluster jobboard-cicd \
  --service jobboard-cicd-applications-api-svc --desired-count 0
aws ecs delete-service --cluster jobboard-cicd \
  --service jobboard-cicd-jobs-api-svc --force
aws ecs delete-service --cluster jobboard-cicd \
  --service jobboard-cicd-applications-api-svc --force

# 4. Delete ECS cluster
aws ecs delete-cluster --cluster jobboard-cicd

# 5. Delete ALB and target groups
aws elbv2 delete-load-balancer \
  --load-balancer-arn $(aws elbv2 describe-load-balancers \
    --names jobboard-cicd-alb --query 'LoadBalancers[0].LoadBalancerArn' --output text)
# Wait ~30s then delete target groups
for TG in jobboard-cicd-jobs-blue jobboard-cicd-jobs-green jobboard-cicd-applications; do
  ARN=$(aws elbv2 describe-target-groups --names $TG \
    --query 'TargetGroups[0].TargetGroupArn' --output text)
  aws elbv2 delete-target-group --target-group-arn "$ARN"
done

# 6. Delete CodePipeline, CodeDeploy, CodeBuild
aws codepipeline delete-pipeline --name jobboard-cicd-pipeline
aws deploy delete-deployment-group \
  --application-name jobboard-cicd-jobs \
  --deployment-group-name jobboard-cicd-jobs-bluegreen
aws deploy delete-application --application-name jobboard-cicd-jobs
aws codebuild delete-project --name jobboard-cicd-build

# 7. Delete CodeArtifact (domain and repo)
aws codeartifact delete-repository \
  --domain jobboard-cicd --repository jobboard-internal
aws codeartifact delete-domain --domain jobboard-cicd

# 8. Delete DynamoDB tables
aws dynamodb delete-table --table-name jobboard-cicd-jobs
aws dynamodb delete-table --table-name jobboard-cicd-applications

# 9. Delete IAM roles (detach policies first)
for ROLE in task-execution task-role codebuild codedeploy codepipeline; do
  aws iam delete-role --role-name "jobboard-cicd-$ROLE" 2>/dev/null || true
done

# 10. Delete NAT gateway (takes a few minutes), then release EIP
NAT_ID=$(aws ec2 describe-nat-gateways \
  --filter "Name=tag:Name,Values=jobboard-cicd-nat" \
  --query 'NatGateways[0].NatGatewayId' --output text)
aws ec2 delete-nat-gateway --nat-gateway-id "$NAT_ID"

# 11. Delete VPC (after NAT is deleted -- poll until NAT state = deleted)
# Then delete in console: VPC > Your VPCs > jobboard-cicd-vpc > Delete VPC

# 12. Delete CodeStar Connection (created manually in S1)
aws codeconnections delete-connection --connection-arn "$CONNECTION_ARN"

echo "Teardown complete."
```

---

## Appendix A -- CloudFormation shortcut

If you want to deploy the full stack without going through every console step above,
use the single CloudFormation template. This is useful for repeat sessions or for
resetting the environment quickly.

**Prerequisites:** complete S0 and S1 (fork the repo and create the CodeStar
Connection) -- the CFN template cannot automate the GitHub OAuth flow.

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
```

Wait for CREATE_COMPLETE:
```bash
aws cloudformation wait stack-create-complete --stack-name "$ENV"
aws cloudformation describe-stacks --stack-name "$ENV" \
  --query 'Stacks[0].Outputs' --output table
```

Note the `ALBDnsName` output, then proceed from S10 (publish the shared library)
and S16 (first pipeline run).

**Teardown with CFN:**
```bash
# 1. Empty the S3 artifact bucket
BUCKET="${ENV}-artifacts-$(aws sts get-caller-identity --query Account --output text)"
aws s3 rm "s3://$BUCKET" --recursive

# 2. Force-delete both ECR repos
aws ecr delete-repository --repository-name "${ENV}/jobs-api" --force
aws ecr delete-repository --repository-name "${ENV}/applications-api" --force

# 3. Delete the stack
aws cloudformation delete-stack --stack-name "$ENV"
aws cloudformation wait stack-delete-complete --stack-name "$ENV"

# 4. Delete CodeArtifact domain (the repo is deleted by the stack; domain may persist)
aws codeartifact delete-domain --domain "$ENV" 2>/dev/null || true

# 5. Delete the CodeStar Connection (not managed by CFN)
aws codeconnections delete-connection --connection-arn "$CONNECTION_ARN"

echo "Teardown complete."
```

---

## Appendix B -- Optional HTTPS with ACM and Route 53

To expose the job board over HTTPS at a custom domain, add these resources after
the core stack is running:

1. Request an ACM certificate in the same region as the ALB:
   ```bash
   CERT_ARN=$(aws acm request-certificate \
     --domain-name api.yourdomain.com \
     --validation-method DNS \
     --query CertificateArn --output text)
   ```
   Add the CNAME record to Route 53 to complete DNS validation.

2. Add an HTTPS listener to the ALB (port 443) referencing the certificate ARN.

3. Update the Jobs and Applications listener rules to attach to the HTTPS listener.

4. Add an HTTP-to-HTTPS redirect as the port 80 default action.
