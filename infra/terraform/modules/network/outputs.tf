output "vpc_id" {
  description = "VPC ID."
  value       = module.vpc.vpc_id
}

output "vpc_cidr_block" {
  description = "VPC CIDR block."
  value       = module.vpc.vpc_cidr_block
}

output "private_subnets" {
  description = "Private subnet IDs (EKS nodes + data stores)."
  value       = module.vpc.private_subnets
}

output "public_subnets" {
  description = "Public subnet IDs (load balancers / NAT)."
  value       = module.vpc.public_subnets
}

output "azs" {
  description = "Availability Zones spanned."
  value       = local.azs
}
