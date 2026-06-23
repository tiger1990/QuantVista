output "db_secret_arn" {
  description = "ARN of the database connection secret."
  value       = aws_secretsmanager_secret.db.arn
}

output "redis_secret_arn" {
  description = "ARN of the Redis connection secret."
  value       = aws_secretsmanager_secret.redis.arn
}

output "external_secrets_role_arn" {
  description = "IRSA role ARN to annotate on the External Secrets Operator service account."
  value       = aws_iam_role.external_secrets.arn
}
