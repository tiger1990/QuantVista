output "cluster_name" {
  description = "EKS cluster name."
  value       = module.eks.cluster_name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = module.eks.cluster_endpoint
}

output "cluster_certificate_authority_data" {
  description = "Base64 cluster CA certificate."
  value       = module.eks.cluster_certificate_authority_data
}

output "cluster_security_group_id" {
  description = "Cluster security group ID (control-plane to node comms)."
  value       = module.eks.cluster_security_group_id
}

output "node_security_group_id" {
  description = "Managed node group security group ID — source for RDS/Redis ingress rules."
  value       = module.eks.node_security_group_id
}

output "oidc_provider_arn" {
  description = "IAM OIDC provider ARN for IRSA roles (e.g. External Secrets Operator)."
  value       = module.eks.oidc_provider_arn
}

output "oidc_provider" {
  description = "OIDC issuer host/path (no https://) for IRSA trust conditions."
  value       = module.eks.oidc_provider
}
