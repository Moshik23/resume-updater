# Placeholder so Terraform can create the function before the first deploy.
# GitHub Actions replaces the code with the real app (terraform ignores code changes).
def handler(event, context):
    return {"statusCode": 503, "body": "Resume Tailor is being deployed - try again in a minute."}
