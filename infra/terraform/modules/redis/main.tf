resource "aws_security_group" "redis" {
  name_prefix = "${var.name}-redis-"
  description = "ElastiCache Redis — ingress from EKS nodes only."
  vpc_id      = var.vpc_id

  #  egress {
  #    description = "Allow all egress."
  #    from_port   = 0
  #    to_port     = 0
  #    protocol    = "-1"
  #    cidr_blocks = ["0.0.0.0/0"]
  #  }

  # No egress block: ElastiCache is a passive data store; leave egress empty
  # (deny-all) to shrink blast radius (H-4). Inter-node replication is managed
  # by AWS and is not governed by this client-access security group.

  tags = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "redis_ingress_from_eks" {
  count = length(var.allowed_security_group_ids)

  type                     = "ingress"
  from_port                = 6379
  to_port                  = 6379
  protocol                 = "tcp"
  security_group_id        = aws_security_group.redis.id
  source_security_group_id = var.allowed_security_group_ids[count.index]
  description              = "Redis from EKS nodes."
}

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${var.name}-redis"
  subnet_ids = var.subnet_ids
  tags       = var.tags
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = var.name
  description          = "QuantVista Redis (cache + Celery broker + Redis Streams bus)."

  engine         = "redis"
  engine_version = var.engine_version
  node_type      = var.node_type
  port           = 6379

  num_cache_clusters         = var.num_cache_clusters
  automatic_failover_enabled = var.num_cache_clusters > 1
  multi_az_enabled           = var.num_cache_clusters > 1

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  auth_token                 = var.auth_token
  # Allow in-place AUTH token rotation instead of destroy/recreate (L-3).
  auth_token_update_strategy = "ROTATE"

  apply_immediately = true

  tags = var.tags
}
