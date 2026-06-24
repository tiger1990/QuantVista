provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "quantvista"
      Environment = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}
