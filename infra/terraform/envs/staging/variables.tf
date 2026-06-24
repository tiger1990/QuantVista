variable "aws_region" {
  description = "AWS region (D8: ap-south-1)."
  type        = string
  default     = "ap-south-1"
}

variable "name_prefix" {
  description = "Base name for resources; workspace is appended (e.g. quantvista-staging)."
  type        = string
  default     = "quantvista"
}

# --- Network -----------------------------------------------------------------
variable "vpc_cidr" {
  description = "VPC CIDR block."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones to span."
  type        = number
  default     = 3
}

variable "single_nat_gateway" {
  description = "Single NAT gateway (cheaper, non-HA). False for production."
  type        = bool
  default     = true
}

# --- EKS ---------------------------------------------------------------------
variable "cluster_version" {
  description = "Kubernetes control-plane version."
  type        = string
  default     = "1.31"
}

variable "node_instance_types" {
  description = "Managed node group instance types."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_min_size" {
  description = "Minimum nodes."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum nodes."
  type        = number
  default     = 4
}

variable "node_desired_size" {
  description = "Desired nodes."
  type        = number
  default     = 2
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the EKS public API endpoint. Restrict for production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# --- RDS ---------------------------------------------------------------------
variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t3.medium"
}

variable "db_allocated_storage" {
  description = "RDS initial storage (GiB)."
  type        = number
  default     = 50
}

variable "db_max_allocated_storage" {
  description = "RDS storage autoscaling ceiling (GiB)."
  type        = number
  default     = 200
}

variable "db_multi_az" {
  description = "RDS multi-AZ standby. Enable for production."
  type        = bool
  default     = false
}

variable "db_name" {
  description = "Initial database name."
  type        = string
  default     = "quantvista"
}

variable "db_username" {
  description = "Database master username."
  type        = string
  default     = "quantvista_admin"
}

# --- Redis -------------------------------------------------------------------
variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_num_cache_clusters" {
  description = "Redis node count (>= 2 enables failover + multi-AZ)."
  type        = number
  default     = 2
}
