# Staging sizing — NON-SECRET values only (region, sizes, AZ count).
# Apply with: terraform apply -var-file=staging.tfvars

aws_region = "ap-south-1"

# Network
vpc_cidr           = "10.0.0.0/16"
az_count           = 3
single_nat_gateway = true # staging: single NAT to save cost (set false for prod HA)

# EKS
cluster_version     = "1.31"
node_instance_types = ["t3.large"]
node_min_size       = 2
node_max_size       = 4
node_desired_size   = 2

# SECURITY (H-1): the EKS public API endpoint defaults to 0.0.0.0/0. Before
# `terraform apply`, restrict it to your operator/CI egress ranges (or disable
# the public endpoint entirely and use the private endpoint via VPN/bastion).
# cluster_endpoint_public_access_cidrs = ["203.0.113.0/24"]  # <-- set real ranges

# RDS (staging sizing)
db_instance_class        = "db.t3.medium"
db_allocated_storage     = 50
db_max_allocated_storage = 200
db_multi_az              = false

# Redis (staging sizing)
redis_node_type          = "cache.t3.micro"
redis_num_cache_clusters = 2
