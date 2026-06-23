resource "aws_security_group" "rds" {
  name_prefix = "${var.identifier}-rds-"
  description = "RDS PostgreSQL — ingress from EKS nodes only."
  vpc_id      = var.vpc_id

  #  egress {
  #    description = "Allow all egress."
  #    from_port   = 0
  #    to_port     = 0
  #    protocol    = "-1"
  #    cidr_blocks = ["0.0.0.0/0"]
  #  }
  # No egress block: a passive data store does not initiate outbound
  # connections, so leave egress empty (deny-all) to shrink blast radius (H-4).

  tags = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group_rule" "rds_ingress_from_eks" {
  count = length(var.allowed_security_group_ids)

  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  security_group_id        = aws_security_group.rds.id
  source_security_group_id = var.allowed_security_group_ids[count.index]
  description              = "PostgreSQL from EKS nodes."
}

module "db" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.10"

  identifier = var.identifier

  engine               = "postgres"
  engine_version       = var.engine_version
  family               = var.family
  major_engine_version = var.major_engine_version
  instance_class       = var.instance_class

  allocated_storage     = var.allocated_storage
  max_allocated_storage = var.max_allocated_storage
  storage_encrypted     = true

  db_name  = var.db_name
  username = var.username
  password = var.password
  port     = 5432

  # Caller generates the password and the secrets module stores it in Secrets
  # Manager — disable the module's own managed-password integration.
  manage_master_user_password = false

  multi_az               = var.multi_az
  create_db_subnet_group = true
  subnet_ids             = var.subnet_ids
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible = false

  # Force TLS at the engine level so a misconfigured sslmode=disable client
  # cannot connect in plaintext, even inside the VPC (M-5).
  create_db_parameter_group = true
  parameters = [
    {
      name         = "rds.force_ssl"
      value        = "1"
      apply_method = "immediate"
    }
  ]

  backup_retention_period = var.backup_retention_period
  deletion_protection     = var.deletion_protection
  skip_final_snapshot     = var.skip_final_snapshot

  tags = var.tags
}
