output "state_bucket_name" {
  description = "S3 bucket holding Terraform remote state. Use as `bucket` in each env backend."
  value       = aws_s3_bucket.state.id
}

output "lock_table_name" {
  description = "DynamoDB state-lock table. Use as `dynamodb_table` in each env backend."
  value       = aws_dynamodb_table.lock.name
}

output "aws_region" {
  description = "Region the state bucket + lock table live in. Use as `region` in each env backend."
  value       = var.aws_region
}
