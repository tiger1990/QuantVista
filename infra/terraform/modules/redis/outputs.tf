output "primary_endpoint_address" {
  description = "Primary endpoint hostname (use to build REDIS_URL)."
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "reader_endpoint_address" {
  description = "Reader endpoint hostname."
  value       = aws_elasticache_replication_group.redis.reader_endpoint_address
}

output "port" {
  description = "Redis port."
  value       = aws_elasticache_replication_group.redis.port
}

output "security_group_id" {
  description = "Security group protecting the cache."
  value       = aws_security_group.redis.id
}
