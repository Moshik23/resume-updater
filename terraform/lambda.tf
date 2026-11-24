# ============ The app: one Lambda function behind a function URL ============
# HTTP requests (via CloudFront) run FastAPI through Mangum; the slow Claude
# analysis runs as an asynchronous self-invocation (app/lambda_handler.py).
# Terraform creates the function with a placeholder; GitHub Actions deploys
# the real code, so code changes are ignored here.

data "archive_file" "placeholder" {
  type        = "zip"
  source_dir  = "${path.module}/placeholder"
  output_path = "${path.module}/.build/placeholder.zip"
}

resource "random_password" "origin_secret" {
  length  = 40
  special = false
}

resource "aws_iam_role" "lambda" {
  name = "${local.name}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda" {
  name = "${local.name}-lambda"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject"]
        Resource = "${aws_s3_bucket.data.arn}/*"
      },
      {
        # head_object on a missing key returns 404 (not 403) only with ListBucket
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.data.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameters"]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_prefix}/*"
      },
      {
        # Self-invocation for the background analysis step
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = aws_lambda_function.app.arn
      }
    ]
  })
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.name}"
  retention_in_days = 14
}

resource "aws_lambda_function" "app" {
  function_name = local.name
  role          = aws_iam_role.lambda.arn
  runtime       = "python3.12"
  architectures = ["x86_64"]
  handler       = "app.lambda_handler.handler"
  memory_size   = 1024
  timeout       = 300 # the background analysis; HTTP requests are capped at 60s by CloudFront anyway

  filename         = data.archive_file.placeholder.output_path
  source_code_hash = data.archive_file.placeholder.output_base64sha256

  environment {
    variables = {
      S3_BUCKET_NAME = aws_s3_bucket.data.id
      SSM_PREFIX     = var.ssm_prefix
      ORIGIN_SECRET  = random_password.origin_secret.result
      CLAUDE_MODEL   = var.claude_model
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda, aws_iam_role_policy_attachment.lambda_logs]

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}

# Background analysis: never retry automatically (a retry would bill Claude twice;
# the page shows the error and the user can just resubmit)
resource "aws_lambda_function_event_invoke_config" "app" {
  function_name                = aws_lambda_function.app.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 600
}

# Public URL, but the app rejects any request without CloudFront's x-origin-secret header.
# (Not OAC: OAC needs a payload hash header on POST bodies, which breaks browser file uploads.)
resource "aws_lambda_function_url" "app" {
  function_name      = aws_lambda_function.app.function_name
  authorization_type = "NONE"
}

# Since Oct 2025 a NONE-auth function URL needs both permissions
resource "aws_lambda_permission" "url_invoke_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.app.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "url_invoke_function" {
  statement_id             = "FunctionURLInvokeAllowPublicAccess"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.app.function_name
  principal                = "*"
  invoked_via_function_url = true
}
