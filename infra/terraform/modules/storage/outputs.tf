output "bucket_ids" {
  description = "Map of logical key => bucket name."
  value       = { for k, b in aws_s3_bucket.this : k => b.id }
}

output "bucket_arns" {
  description = "Map of logical key => bucket ARN."
  value       = { for k, b in aws_s3_bucket.this : k => b.arn }
}
