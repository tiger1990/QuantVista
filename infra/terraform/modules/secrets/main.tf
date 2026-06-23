locals {
  database_url = "postgresql://${var.db_username}:${var.db_password}@${var.db_host}:${var.db_port}/${var.db_name}"
  redis_url    = "rediss://:${var.redis_auth_token}@${var.redis_host}:${var.redis_port}/0"

  # IAM role names cannot contain "/"; derive a flat name from the prefix.
  flat_name = replace(var.name_prefix, "/", "-")
}

# --- Customer-managed KMS key for the secrets (M-1) ---------------------------
resource "aws_kms_key" "secrets" {
  description             = "QuantVista Secrets Manager CMK (${var.name_prefix})."
  enable_key_rotation     = true
  deletion_window_in_days = 7
  tags                    = var.tags
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${local.flat_name}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# --- Secrets Manager: DB + Redis connection material -------------------------
resource "aws_secretsmanager_secret" "db" {
  name                    = "${var.name_prefix}/database"
  description             = "QuantVista database connection (Terraform-managed)."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 30
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    username     = var.db_username
    password     = var.db_password
    host         = var.db_host
    port         = var.db_port
    dbname       = var.db_name
    DATABASE_URL = local.database_url
  })
}

resource "aws_secretsmanager_secret" "redis" {
  name                    = "${var.name_prefix}/redis"
  description             = "QuantVista Redis connection (Terraform-managed)."
  kms_key_id              = aws_kms_key.secrets.arn
  recovery_window_in_days = 30
  tags                    = var.tags
}

resource "aws_secretsmanager_secret_version" "redis" {
  secret_id = aws_secretsmanager_secret.redis.id
  secret_string = jsonencode({
    auth_token = var.redis_auth_token
    host       = var.redis_host
    port       = var.redis_port
    REDIS_URL  = local.redis_url
  })
}

# --- IRSA role for External Secrets Operator ---------------------------------
data "aws_iam_policy_document" "irsa_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [var.eks_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider}:sub"
      values   = ["system:serviceaccount:${var.external_secrets_namespace}:${var.external_secrets_service_account}"]
    }

    condition {
      test     = "StringEquals"
      variable = "${var.eks_oidc_provider}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "external_secrets" {
  name               = "${local.flat_name}-external-secrets"
  description        = "IRSA role for External Secrets Operator to read QuantVista secrets."
  assume_role_policy = data.aws_iam_policy_document.irsa_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "secrets_read" {
  statement {
    sid    = "ReadQuantVistaSecrets"
    effect = "Allow"

    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret",
    ]

    # Least privilege: only the two secrets this stack owns.
    resources = [
      aws_secretsmanager_secret.db.arn,
      aws_secretsmanager_secret.redis.arn,
    ]
  }

  # Decrypt rights on the CMK only — required to read the CMK-encrypted secrets.
  statement {
    sid       = "DecryptSecretsKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.secrets.arn]
  }
}

resource "aws_iam_policy" "secrets_read" {
  name   = "${local.flat_name}-secrets-read"
  policy = data.aws_iam_policy_document.secrets_read.json
  tags   = var.tags
}

resource "aws_iam_role_policy_attachment" "secrets_read" {
  role       = aws_iam_role.external_secrets.name
  policy_arn = aws_iam_policy.secrets_read.arn
}
