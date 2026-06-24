variable "name" {
  description = "Base name for the VPC and related resources (caller applies workspace suffix)."
  type        = string
}

variable "cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of Availability Zones to span (>= 2 for multi-AZ)."
  type        = number
  default     = 3

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 4
    error_message = "az_count must be between 2 and 4."
  }
}

variable "single_nat_gateway" {
  description = "Use a single NAT gateway (cheaper, non-HA). Set false for production HA."
  type        = bool
  default     = true
}

variable "cluster_name" {
  description = "EKS cluster name used to tag subnets for Kubernetes ELB/subnet discovery."
  type        = string
}

variable "tags" {
  description = "Tags applied to all network resources."
  type        = map(string)
  default     = {}
}
