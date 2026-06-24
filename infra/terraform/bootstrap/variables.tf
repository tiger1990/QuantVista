variable "aws_region" {
  description = "AWS region for the remote-state bucket and lock table (D8: ap-south-1)."
  type        = string
  default     = "ap-south-1"
}

variable "state_bucket_name" {
  description = "Globally-unique name for the S3 bucket that stores Terraform remote state."
  type        = string
  default     = "quantvista-tfstate-ap-south-1"
}

variable "lock_table_name" {
  description = "Name of the DynamoDB table used for Terraform state locking."
  type        = string
  default     = "quantvista-tflock"
}

variable "noncurrent_version_expiration_days" {
  description = "Days after which non-current (superseded) state object versions are expired."
  type        = number
  default     = 90
}
