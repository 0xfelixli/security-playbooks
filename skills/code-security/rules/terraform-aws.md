---
title: Secure AWS Terraform Configurations
impact: HIGH
impactDescription: Cloud misconfigurations and data exposure
tags: security, terraform, aws, infrastructure, iac, s3, iam, ec2
kind: infrastructure
detect:
  files: ["*.tf", "*.tfvars"]
  content: ["aws_", "provider \"aws\""]
---

## Secure AWS Terraform Configurations

Security best practices for AWS Terraform configurations to prevent common misconfigurations.

### S3 Encryption

**Incorrect (bucket without server-side encryption):**
```hcl
resource "aws_s3_bucket" "bucket" {
  bucket = "my-bucket"
}
```

**Correct (bucket-level KMS encryption via `aws_s3_bucket_server_side_encryption_configuration`):**
```hcl
resource "aws_s3_bucket" "bucket" {
  bucket = "my-bucket"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pass" {
  bucket = aws_s3_bucket.bucket.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.example.arn
    }
    bucket_key_enabled = true
  }
}
```

> **Note:** `aws_s3_bucket_object` is deprecated in AWS provider 4+. Use `aws_s3_object` for individual objects, and configure encryption at the bucket level with `aws_s3_bucket_server_side_encryption_configuration` so all objects inherit it automatically.

### IAM Overly Permissive Policies

**Incorrect (wildcard admin):**
```hcl
resource "aws_iam_policy" "fail" {
  policy = <<POLICY
{"Version":"2012-10-17","Statement":[{"Action":"*","Effect":"Allow","Resource":"*"}]}
POLICY
}
```

**Correct (least privilege):**
```hcl
resource "aws_iam_policy" "pass" {
  policy = <<POLICY
{"Version":"2012-10-17","Statement":[{"Action":["s3:GetObject*"],"Effect":"Allow","Resource":"arn:aws:s3:::bucket/*"}]}
POLICY
}
```

**Incorrect (wildcard AssumeRole):**
```hcl
resource "aws_iam_role" "fail" {
  assume_role_policy = <<POLICY
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"*"},"Action":"sts:AssumeRole"}]}
POLICY
}
```

**Correct (restricted AssumeRole):**
```hcl
resource "aws_iam_role" "pass" {
  assume_role_policy = <<POLICY
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"AWS":"arn:aws:iam::123456789012:root"},"Action":"sts:AssumeRole"}]}
POLICY
}
```

### Unencrypted Storage

**Incorrect (EBS):**
```hcl
resource "aws_ebs_volume" "fail" {
  availability_zone = "us-west-2a"
  encrypted         = false
}
```

**Correct (EBS):**
```hcl
resource "aws_ebs_volume" "pass" {
  availability_zone = "us-west-2a"
  encrypted         = true
}
```

**Incorrect (RDS no backup):**
```hcl
resource "aws_db_instance" "fail" { backup_retention_period = 0 }
```

**Correct (RDS with backup):**
```hcl
resource "aws_db_instance" "pass" { backup_retention_period = 35 }
```

**Incorrect (DynamoDB):**
```hcl
resource "aws_dynamodb_table" "fail" {
  name = "Table"; hash_key = "Id"
  attribute { name = "Id"; type = "S" }
}
```

**Correct (DynamoDB with CMK):**
```hcl
resource "aws_dynamodb_table" "pass" {
  name = "Table"; hash_key = "Id"
  attribute { name = "Id"; type = "S" }
  server_side_encryption { enabled = true; kms_key_arn = "arn:aws:kms:..." }
}
```

**Incorrect (SQS/SNS):**
```hcl
resource "aws_sqs_queue" "fail" { name = "queue" }
resource "aws_sns_topic" "fail" {}
```

**Correct (SQS/SNS encrypted):**
```hcl
resource "aws_sqs_queue" "pass" { name = "queue"; sqs_managed_sse_enabled = true }
resource "aws_sns_topic" "pass" { kms_master_key_id = "alias/aws/sns" }
```

### Network Security

**Incorrect (public SSH):**
```hcl
resource "aws_security_group_rule" "fail" {
  type = "ingress"; protocol = "tcp"; from_port = 22; to_port = 22
  cidr_blocks = ["0.0.0.0/0"]
}
```

**Correct (restricted CIDR):**
```hcl
resource "aws_security_group_rule" "pass" {
  type = "ingress"; protocol = "tcp"; from_port = 22; to_port = 22
  cidr_blocks = ["10.0.0.0/8"]
}
```

**Incorrect (public IP):**
```hcl
resource "aws_instance" "fail" {
  ami = "ami-12345"; instance_type = "t3.micro"
  associate_public_ip_address = true
}
```

**Correct (no public IP):**
```hcl
resource "aws_instance" "pass" {
  ami = "ami-12345"; instance_type = "t3.micro"
  associate_public_ip_address = false
}
```

### Key Management

**Incorrect (KMS no rotation):**
```hcl
resource "aws_kms_key" "fail" { enable_key_rotation = false }
```

**Correct (KMS with rotation):**
```hcl
resource "aws_kms_key" "pass" { enable_key_rotation = true }
```

**Incorrect (CloudTrail):**
```hcl
resource "aws_cloudtrail" "fail" { name = "trail"; s3_bucket_name = "bucket" }
```

**Correct (CloudTrail encrypted):**
```hcl
resource "aws_cloudtrail" "pass" {
  name = "trail"; s3_bucket_name = "bucket"; kms_key_id = aws_kms_key.key.arn
}
```

### Credentials

**Incorrect (hardcoded):**
```hcl
provider "aws" {
  region = "us-west-2"; access_key = "AKIAEXAMPLE"; secret_key = "secret"
}
```

**Correct (external credentials):**
```hcl
provider "aws" {
  region = "us-west-2"; shared_credentials_file = "~/.aws/creds"; profile = "myprofile"
}
```

## Not a Finding

- **S3 静态网站托管**：`aws_s3_bucket_website_configuration` 配合 `aws_s3_bucket_public_access_block` 显式开放公开读，属于预期行为，不是未加密风险。
- **公开 HTTP/HTTPS 入站**：`cidr_blocks = ["0.0.0.0/0"]` 用于 80/443 端口的 ALB/NLB Security Group 规则，是合理的公网服务配置。
- **Bastion / 跳板机公网 IP**：`associate_public_ip_address = true` 配合限定 CIDR 的 SSH 规则，不构成风险（关键看 CIDR 是否为 `0.0.0.0/0`）。
- **Dev/test 环境简化配置**：文件名或模块名明确含 `dev`/`test`/`staging` 且无生产数据时，告警降级处理，不作为高危 finding。
- **AWS 托管密钥（SSE-S3）**：`sse_algorithm = "AES256"` 是有效加密，仅 CMK 场景要求 KMS；单纯使用 SSE-S3 不应报告为"无加密"。
