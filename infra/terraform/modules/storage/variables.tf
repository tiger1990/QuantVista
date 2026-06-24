variable "buckets" {
  description = "Map of logical key => globally-unique S3 bucket name (e.g. { app = \"...\", exports = \"...\" })."
  type        = map(string)
}

variable "noncurrent_version_expiration_days" {
  description = "Days after which non-current object versions are expired."
  type        = number
  default     = 90
}

variable "tags" {
  description = "Tags applied to all buckets."
  type        = map(string)
  default     = {}
}
