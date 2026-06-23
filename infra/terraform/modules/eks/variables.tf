variable "cluster_name" {
  description = "EKS cluster name (caller applies workspace suffix)."
  type        = string
}

variable "cluster_version" {
  description = "Kubernetes control-plane version."
  type        = string
  default     = "1.31"
}

variable "vpc_id" {
  description = "VPC the cluster runs in."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for the managed node group."
  type        = list(string)
}

variable "control_plane_subnet_ids" {
  description = "Private subnet IDs for the EKS control-plane ENIs."
  type        = list(string)
}

variable "node_instance_types" {
  description = "Instance types for the managed node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_min_size" {
  description = "Minimum nodes in the managed node group."
  type        = number
  default     = 2
}

variable "node_max_size" {
  description = "Maximum nodes in the managed node group."
  type        = number
  default     = 4
}

variable "node_desired_size" {
  description = "Desired nodes in the managed node group."
  type        = number
  default     = 2
}

variable "cluster_endpoint_public_access" {
  description = "Whether the API server has a public endpoint (restricted by CIDR below)."
  type        = bool
  default     = true
}

variable "cluster_endpoint_public_access_cidrs" {
  description = "CIDRs allowed to reach the public API endpoint. Restrict for production."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "cluster_enabled_log_types" {
  description = "EKS control-plane log types shipped to CloudWatch."
  type        = list(string)
  default     = ["audit", "api", "authenticator"]
}

variable "tags" {
  description = "Tags applied to cluster resources."
  type        = map(string)
  default     = {}
}
