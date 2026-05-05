terraform {
  backend "s3" {
    bucket         = "diamond-iq-tfstate-334856751632"
    key            = "soc-detection-lab/dashboard/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
    dynamodb_table = "diamond-iq-tfstate-locks"
  }
}
