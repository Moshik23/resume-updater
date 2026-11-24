# ============ GitHub Actions deploys via OIDC (no stored AWS keys) ============
# Reuses the account's GitHub OIDC provider (managed in the Moshik23/memories
# Terraform). Only the deploy branch (master) of this repo can assume the role, and it can only
# update this one function's code.

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_deploy" {
  name = "${local.name}-github-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = data.aws_iam_openid_connect_provider.github.arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          # deploy branch only, in either subject format GitHub may send
          "token.actions.githubusercontent.com:sub" = compact([
            var.github_sub_prefix_immutable != "" ? "${var.github_sub_prefix_immutable}:ref:refs/heads/${var.deploy_branch}" : "",
            "repo:${var.github_repo}:ref:refs/heads/${var.deploy_branch}",
          ])
        }
      }
    }]
  })
}

resource "aws_iam_role_policy" "github_deploy" {
  name = "${local.name}-github-deploy"
  role = aws_iam_role.github_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:UpdateFunctionCode", "lambda:GetFunction", "lambda:GetFunctionConfiguration"]
      Resource = aws_lambda_function.app.arn
    }]
  })
}
