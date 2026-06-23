terraform {
  # Remote state in the S3 bucket + DynamoDB lock table created by `bootstrap/`.
  # Per-env isolation is by WORKSPACE: state is stored at
  #   env:/<workspace>/quantvista/infra.tfstate
  # so `staging` and a future `production` never share state.
  #
  # `terraform init -backend=false` (used by CI + offline validation) ignores
  # this block. A credentialed operator runs `terraform init` to wire it up.
  backend "s3" {
    bucket         = "quantvista-tfstate-ap-south-1"
    key            = "quantvista/infra.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "quantvista-tflock"
    encrypt        = true
  }
}
