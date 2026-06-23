# Endpoints + ARNs only — NO secret values are ever output.

output "vpc_id" {
  description = "VPC ID."
  value       = module.network.vpc_id
}

output "eks_cluster_name" {
  description = "EKS cluster name (use with `aws eks update-kubeconfig`)."
  value       = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  description = "RDS PostgreSQL host:port."
  value       = "${module.rds.db_instance_address}:${module.rds.db_instance_port}"
}

output "redis_endpoint" {
  description = "Redis primary host:port."
  value       = "${module.redis.primary_endpoint_address}:${module.redis.port}"
}

output "s3_bucket_names" {
  description = "Logical key => S3 bucket name."
  value       = module.storage.bucket_ids
}

output "db_secret_arn" {
  description = "Secrets Manager ARN for the DB connection (External Secrets source)."
  value       = module.secrets.db_secret_arn
}

output "redis_secret_arn" {
  description = "Secrets Manager ARN for the Redis connection (External Secrets source)."
  value       = module.secrets.redis_secret_arn
}

output "external_secrets_role_arn" {
  description = "IRSA role ARN for the External Secrets Operator service account."
  value       = module.secrets.external_secrets_role_arn
}
