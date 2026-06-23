data "aws_caller_identity" "current" {}

locals {
  # Workspace-suffixed base name → quantvista-staging, quantvista-production, …
  name       = "${var.name_prefix}-${terraform.workspace}"
  account_id = data.aws_caller_identity.current.account_id

  tags = {
    Project     = "quantvista"
    Environment = terraform.workspace
    ManagedBy   = "terraform"
  }
}

# --- Generated credentials (no secret values ever live in source) ------------
# Alphanumeric to keep the assembled DATABASE_URL / REDIS_URL free of escaping.
resource "random_password" "db" {
  length  = 40
  special = false
}

resource "random_password" "redis" {
  length  = 48
  special = false
}

module "network" {
  source = "../../modules/network"

  name               = local.name
  cidr               = var.vpc_cidr
  az_count           = var.az_count
  single_nat_gateway = var.single_nat_gateway
  cluster_name       = local.name
  tags               = local.tags
}

module "eks" {
  source = "../../modules/eks"

  cluster_name                         = local.name
  cluster_version                      = var.cluster_version
  vpc_id                               = module.network.vpc_id
  subnet_ids                           = module.network.private_subnets
  control_plane_subnet_ids             = module.network.private_subnets
  node_instance_types                  = var.node_instance_types
  node_min_size                        = var.node_min_size
  node_max_size                        = var.node_max_size
  node_desired_size                    = var.node_desired_size
  cluster_endpoint_public_access_cidrs = var.cluster_endpoint_public_access_cidrs
  tags                                 = local.tags
}

module "rds" {
  source = "../../modules/rds"

  identifier                 = local.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnets
  allowed_security_group_ids = [module.eks.node_security_group_id]
  instance_class             = var.db_instance_class
  allocated_storage          = var.db_allocated_storage
  max_allocated_storage      = var.db_max_allocated_storage
  multi_az                   = var.db_multi_az
  db_name                    = var.db_name
  username                   = var.db_username
  password                   = random_password.db.result
  tags                       = local.tags
}

module "redis" {
  source = "../../modules/redis"

  name                       = local.name
  vpc_id                     = module.network.vpc_id
  subnet_ids                 = module.network.private_subnets
  allowed_security_group_ids = [module.eks.node_security_group_id]
  node_type                  = var.redis_node_type
  num_cache_clusters         = var.redis_num_cache_clusters
  auth_token                 = random_password.redis.result
  tags                       = local.tags
}

module "storage" {
  source = "../../modules/storage"

  buckets = {
    app     = "${local.name}-app-${local.account_id}"
    exports = "${local.name}-exports-${local.account_id}"
  }
  tags = local.tags
}

module "secrets" {
  source = "../../modules/secrets"

  name_prefix = "quantvista/${terraform.workspace}"

  db_username = var.db_username
  db_password = random_password.db.result
  db_host     = module.rds.db_instance_address
  db_port     = module.rds.db_instance_port
  db_name     = var.db_name

  redis_auth_token = random_password.redis.result
  redis_host       = module.redis.primary_endpoint_address
  redis_port       = module.redis.port

  eks_oidc_provider_arn = module.eks.oidc_provider_arn
  eks_oidc_provider     = module.eks.oidc_provider

  tags = local.tags
}
