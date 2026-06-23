output "db_instance_address" {
  description = "RDS hostname (use to build DATABASE_URL)."
  value       = module.db.db_instance_address
}

output "db_instance_port" {
  description = "RDS port."
  value       = module.db.db_instance_port
}

output "db_instance_name" {
  description = "Initial database name."
  value       = module.db.db_instance_name
}

output "db_subnet_group_id" {
  description = "DB subnet group name."
  value       = module.db.db_subnet_group_id
}

output "security_group_id" {
  description = "Security group protecting the database."
  value       = aws_security_group.rds.id
}
