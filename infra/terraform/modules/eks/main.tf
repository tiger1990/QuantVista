# Customer-managed KMS key for etcd envelope encryption of Kubernetes Secrets.
resource "aws_kms_key" "eks" {
  description             = "EKS etcd envelope encryption (${var.cluster_name})."
  enable_key_rotation     = true
  deletion_window_in_days = 7
  tags                    = var.tags
}

resource "aws_kms_alias" "eks" {
  name          = "alias/${var.cluster_name}-eks"
  target_key_id = aws_kms_key.eks.key_id
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.24"

  cluster_name    = var.cluster_name
  cluster_version = var.cluster_version

  # Private endpoint always on; public endpoint on but CIDR-restricted.
  cluster_endpoint_private_access      = true
  cluster_endpoint_public_access       = var.cluster_endpoint_public_access
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs

  # Grant the Terraform principal that creates the cluster admin access (access entries).
  enable_cluster_creator_admin_permissions = true

  # Encrypt Kubernetes Secrets in etcd with the CMK above (H-2).
  cluster_encryption_config = {
    provider_key_arn = aws_kms_key.eks.arn
    resources        = ["secrets"]
  }

  # Ship control-plane audit/API logs to CloudWatch for incident response (M-4).
  cluster_enabled_log_types = var.cluster_enabled_log_types

  vpc_id                   = var.vpc_id
  subnet_ids               = var.subnet_ids
  control_plane_subnet_ids = var.control_plane_subnet_ids

  eks_managed_node_group_defaults = {
    instance_types = var.node_instance_types

    # Enforce IMDSv2 + hop limit 1 so pods can't reach node instance credentials (M-6).
    metadata_options = {
      http_endpoint               = "enabled"
      http_tokens                 = "required"
      http_put_response_hop_limit = 1
    }
  }

  eks_managed_node_groups = {
    default = {
      min_size     = var.node_min_size
      max_size     = var.node_max_size
      desired_size = var.node_desired_size

      instance_types = var.node_instance_types
      capacity_type  = "ON_DEMAND"
    }
  }

  tags = var.tags
}
