# Resume Tailor on AWS: CloudFront -> Lambda function URL (FastAPI via Mangum) -> S3,
# with the Anthropic API key and site password in SSM Parameter Store.
terraform {
  cloud {
    organization = "Moshik_Seetloo"
    workspaces {
      name = "resume-tailor"
    }
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.28" # 6.28+ for invoked_via_function_url on aws_lambda_permission
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { Project = "resume-tailor" }
  }
}

# ACM certificates for CloudFront must live in us-east-1
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
  default_tags {
    tags = { Project = "resume-tailor" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name          = "resume-tailor"
  custom_domain = var.domain_name != ""
}
