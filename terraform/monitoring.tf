# ============ Alerts: errors and spend ============
# Off until alert_email is set (HCP workspace variable, so the address isn't in git).
# AWS emails a confirmation link to that address first; alerts only arrive after it's clicked.

locals {
  alerts = var.alert_email != ""
}

resource "aws_sns_topic" "alerts" {
  count = local.alerts ? 1 : 0
  name  = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = local.alerts ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# The function itself crashing (bad deploy, missing secret, timeout)
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  count               = local.alerts ? 1 : 0
  alarm_name          = "${local.name}-lambda-errors"
  alarm_description   = "Resume Tailor's Lambda is erroring. Check its CloudWatch logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.app.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}

# Claude calls failing (bad key, no credit, API outage). These are caught and shown
# to the user, so they never count as Lambda errors; the app logs ANALYSIS_FAILED instead.
resource "aws_cloudwatch_log_metric_filter" "analysis_failed" {
  count          = local.alerts ? 1 : 0
  name           = "${local.name}-analysis-failed"
  log_group_name = aws_cloudwatch_log_group.lambda.name
  pattern        = "\"ANALYSIS_FAILED\""

  metric_transformation {
    name          = "AnalysisFailed"
    namespace     = "ResumeTailor"
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "analysis_failed" {
  count               = local.alerts ? 1 : 0
  alarm_name          = "${local.name}-analysis-failed"
  alarm_description   = "Claude analysis is failing (API key, credit balance or outage). Check the Lambda logs for ANALYSIS_FAILED."
  namespace           = "ResumeTailor"
  metric_name         = "AnalysisFailed"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 2
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts[0].arn]
}

# Whole-account monthly spend guard (AWS Budgets: the first two budgets are free)
resource "aws_budgets_budget" "monthly" {
  count        = local.alerts ? 1 : 0
  name         = "monthly-account-budget"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
