# random-api

> ECS Fargate service with ALB routing, CloudWatch logging, and error alerting

---

## Architecture Overview

\```
Inside VPC
    │
    │  HTTPS :443
    ▼
┌─────────────────────────────────────────────────────┐
│  Application Load Balancer  (pre-existing)          │
│  Listener: HTTPS :443                               │
│  ┌───────────────────────────────────────────────┐  │
│  │  ListenerRule                                 │  │
│  │  path-pattern: /random*  →  forward           │  │
│  │  priority: 100                                │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
    │  HTTP :8080  (path /random*)
    ▼
┌─────────────────────────────────────────────────────┐
│  Target Group: random-api-dev-tg                    │
│  type: ip  |  protocol: HTTP  |  port: 8080         │
│  health-check: GET /random  →  expect HTTP 200      │
└─────────────────────────────────────────────────────┘
    │  registers task ENI IPs
    ▼
┌─────────────────────────────────────────────────────────────────┐
│  ECS Cluster  (pre-existing)                                    │
│  Service: random-api-dev                                        │
│  LaunchType: FARGATE  |  DesiredCount: 1  |  PublicIp: DISABLED │
│                                                                 │
│  Task Definition: random-api-dev                                │
│  CPU: 256 (0.25 vCPU)  |  Memory: 512 MB  |  Network: awsvpc   │
│                                                                 │
│  Container: random-api                                          │
│  Image: cx-devops-ecs:random-api  (pre-built in ECR)            │
│  Port: 8080                                                     │
│                                                                 │
│  GET /random                                                    │
│  ┌────────────────────────────────────────────────────┐         │
│  │  random.random() >= 0.2  (~80%)                   │         │
│  │  → HTTP 200  {"status":"success",                 │         │
│  │               "message":"Hello from random!",     │         │
│  │               "request_id":"<uuid>"}              │         │
│  ├────────────────────────────────────────────────────┤         │
│  │  random.random() < 0.2   (~20%)                   │         │
│  │  → HTTP 500  {"status":"error",                   │         │
│  │               "message":"Something went wrong.",  │         │
│  │               "request_id":"<uuid>"}              │         │
│  └────────────────────────────────────────────────────┘         │
│  Subnets: private-subnet-a, private-subnet-b                    │
│  SecGroup: <pre-existing SG>                                    │
└─────────────────────────────────────────────────────────────────┘
    │  awslogs driver (stdout → CloudWatch)
    ▼
┌──────────────────────────────────────────────────────────────┐
│  CloudWatch Logs                                             │
│  Log Group: /ecs/random-api-dev  |  Retention: 14 days      │
│  Log Stream prefix: random-api                               │
│                                                              │
│  INFO   {"status":"success","message":"...","request_id":"…"}│
│  ERROR  {"status":"error","message":"...","request_id":"…"}  │
└──────────────────────────────────────────────────────────────┘
    │  MetricFilter: { $.status = "error" }
    │  Namespace: random-api/dev  |  MetricName: ErrorCount
    ▼
┌──────────────────────────────────────────────────────────────┐
│  CloudWatch Alarm: random-api-dev-error-rate                 │
│  ErrorCount >= 1  in  1 × 60s period                        │
│  TreatMissingData: notBreaching                              │
└──────────────────────────────────────────────────────────────┘
    │  ALARM / OK state change
    ▼
┌──────────────────────────────────────────────────────────────┐
│  SNS Topic: random-api-dev-error-alarm                       │
│  Subscription: email → <ALARM_EMAIL>                         │
│  (manual confirmation required)                              │
└──────────────────────────────────────────────────────────────┘
\```

---

## ECR Image

> Pre-built — not managed by this pipeline

| Field | Value |
|---|---|
| Repository | `cx-devops-ecs` |
| Image tag | `random-api` |
| Full URI | `<account-id>.dkr.ecr.<region>.amazonaws.com/cx-devops-ecs:random-api` |

The image was built manually on an EC2 instance and pushed to ECR. The GitHub Actions workflow does **not** build or push the image. The full URI is stored as the `ECR_IMAGE_URI` GitHub repo variable and passed to CloudFormation as the `ImageUri` parameter at deploy time.

---

## IAM — Least Privilege

### ECSExecutionRole
Used by the ECS agent (not the container).

- **Principal:** `ecs-tasks.amazonaws.com`
- **Policy:** `AmazonECSTaskExecutionRolePolicy` (AWS managed)
  - `ecr:GetAuthorizationToken`, `ecr:BatchGetImage` — image pull
  - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` — CloudWatch Logs

### ECSTaskRole
Assumed by the running container.

- **Principal:** `ecs-tasks.amazonaws.com`
- **Inline Policy:** `CloudWatchLogsAccess`
  - `logs:CreateLogStream`
  - `logs:PutLogEvents`
  - **Resource:** `arn:aws:logs:*:*:log-group:/ecs/random-api-dev:*`

---

## CloudFormation Stack Dependency Order

\```
root.yaml  (random-api-root-dev)
│
├── IAMStack   [iam.yaml]  ──────────┐
│   ECSExecutionRole                 │  both complete before ECSStack starts
│   ECSTaskRole                      │  (CF infers via !GetAtt references)
│                                    │
├── ALBStack   [alb.yaml]  ──────────┤
│   RandomTargetGroup                │
│   RandomListenerRule (/random*)    │
│                                    ▼
├── ECSStack   [ecs.yaml]  ───────────────────────┐
│   RandomApiLogGroup                             │  complete before CWStack
│   RandomApiTaskDefinition                       │
│   RandomApiService                              │
│                                                 ▼
└── CWStack    [cw.yaml]
    ErrorAlarmTopic  (SNS)
    ErrorMetricFilter
    ErrorAlarm
\```

---

## GitHub Actions — `build.yml`

Triggered on push to `main`.

> **Note:** Docker build and push are **not** part of this workflow. The image is pre-built in ECR. This pipeline only deploys infrastructure.

| Step | Action |
|---|---|
| 1 | Checkout |
| 2 | Validate CF templates (`cfn validate` — PR + push) |
| 3 | `aws s3 sync random-api/infra/ → s3://ctx-devops-cfn-dev/random-api/` |
| 4 | Preflight: delete stack if `ROLLBACK_COMPLETE` |
| 5 | `aws cloudformation deploy` (root.yaml, `CAPABILITY_NAMED_IAM`) — `ImageUri` from `vars.ECR_IMAGE_URI` |
| 6 | Show stack outputs |

### Required GitHub Repo Variables

> Settings → Variables → Actions

| Variable | Description |
|---|---|
| `GIT_RUNNER` | CodeBuild project name |
| `ECS_CLUSTER_ARN` | Pre-existing cluster ARN or name |
| `ECS_SECURITY_GROUP_ID` | Pre-existing SG (allow inbound TCP 8080 from ALB) |
| `PRIVATE_SUBNET_IDS` | `subnet-aaa,subnet-bbb` (comma-separated) |
| `VPC_ID` | Pre-existing VPC ID |
| `ALB_LISTENER_ARN` | Pre-existing HTTPS listener ARN |
| `ALARM_EMAIL` | Email for SNS alarm notifications |
| `ECR_IMAGE_URI` | e.g. `123456789012.dkr.ecr.us-east-1.amazonaws.com/cx-devops-ecs:random-api` |

---

## Resource Summary

### Pre-existing Resources

| Resource |
|---|
| ECS Cluster |
| VPC |
| Private subnets (×2) |
| Security group |
| Application Load Balancer |
| HTTPS Listener (port 443) |
| S3 bucket (`ctx-devops-cfn-dev`) |
| ECR repository (`cx-devops-ecs`) + image tag (`random-api`) |
| CodeBuild GitHub runner |

### Created by CloudFormation

| Resource | Name |
|---|---|
| IAM ECSExecutionRole | `random-api-dev-ecs-execution-role` |
| IAM ECSTaskRole | `random-api-dev-ecs-task-role` |
| ALB Target Group | `random-api-dev-tg` (ip-mode, port 8080) |
| ALB Listener Rule | path `/random*`, priority 100 |
| CloudWatch Log Group | `/ecs/random-api-dev` (14-day retention) |
| ECS Task Definition | `random-api-dev` (0.25 vCPU / 512 MB) |
| ECS Service | `random-api-dev` (Fargate, DesiredCount 1) |
| CloudWatch Metric Filter | `ErrorCount` — `{ $.status = "error" }` |
| CloudWatch Alarm | `random-api-dev-error-rate` (fires at ≥ 1 error/min) |
| SNS Topic | `random-api-dev-error-alarm` (email subscription) |
