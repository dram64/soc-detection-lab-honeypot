###############################################################################
# GitHub Actions OIDC trust + deploy role for the SOC honeypot dashboard.
#
# Lets workflows in github.com/dram64/soc-detection-lab-honeypot assume an
# AWS role without any long-lived AWS credentials in the repo. The deploy
# role's permissions are scoped to dram-soc-* resource ARNs only.
#
# Reference: ADR-011 (CI/CD permission boundary). The trust policy is a
# literal copy of Diamond IQ's working version (one string changed:
# var.github_repo). The deploy permissions adapt Diamond IQ's surface
# minus WAFv2 (ADR-007: no AWS WAF), minus apigateway-cw-logs PassRole
# (no such role exists in SOC), minus all IAM user management (Phase 10
# fluent-bit edge users live in the human-managed credentials stack).
###############################################################################

###############################################################################
# OIDC provider — DATA SOURCE only.
#
# The GitHub Actions OIDC provider already exists in account 334856751632
# (Diamond IQ created it). Re-declaring it as a `resource` would conflict
# with Diamond IQ's terraform state. Read by attribute via a data source.
###############################################################################

data "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"
}

###############################################################################
# Trust policy — verbatim copy of Diamond IQ's, one substitution
# (var.github_repo). Loose `repo:<repo>:*` allows any branch / tag / PR
# from the repo to assume; tighten to main + tags in a later phase if the
# attack surface grows.
###############################################################################

data "aws_iam_policy_document" "trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [data.aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Any branch / tag / PR from this repo can assume the role. Tighten in a
    # later phase (e.g. only main + tags).
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:*"]
    }
  }
}

resource "aws_iam_role" "deploy" {
  name               = var.role_name
  assume_role_policy = data.aws_iam_policy_document.trust.json
  tags               = var.tags
}

###############################################################################
# Deploy permissions, scoped to dram-soc-* ARN patterns.
#
# Adapted from Diamond IQ's modules/oidc/main.tf with:
#   - WAFv2 statements DROPPED (ADR-007)
#   - apigateway-cw-logs PassRole DROPPED (no such role in SOC)
#   - All IAM user management DROPPED (Phase 11B-1 + ADR-011: human-managed
#     credentials live in stacks/edge-shippers-credentials/)
#   - ACM certificate management ADDED (Phase 8 dashboard cert + apex SAN)
#   - SSM Parameter Store on /dram-soc/* ADDED, EXCLUDING ssm:DeleteParameter
#     (compromised CI can't wipe the MaxMind license)
#   - Lambda layer management ADDED (geolite2 layer)
#   - CloudFront OAC + ResponseHeadersPolicy + Function management ADDED
###############################################################################

data "aws_iam_policy_document" "deploy" {
  ###########################################################################
  # Lambda — manage just the project's three functions (ingest, aggregator, api).
  ###########################################################################
  statement {
    sid    = "LambdaManageProjectFunctions"
    effect = "Allow"
    actions = [
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
      "lambda:GetFunctionCodeSigningConfig",
      "lambda:ListVersionsByFunction",
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
      "lambda:CreateFunction",
      "lambda:DeleteFunction",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:ListTags",
      "lambda:AddPermission",
      "lambda:RemovePermission",
      "lambda:GetPolicy",
    ]
    resources = ["arn:aws:lambda:${var.aws_region}:${var.account_id}:function:${var.name_prefix}-*"]
  }

  ###########################################################################
  # Lambda layers — the GeoLite2 layer (Phase 10). PublishLayerVersion is
  # the operation terraform invokes when the layer's source_code_hash
  # changes (which it does on every `download_geolite2.sh` rebuild).
  ###########################################################################
  statement {
    sid    = "LambdaManageProjectLayers"
    effect = "Allow"
    actions = [
      "lambda:PublishLayerVersion",
      "lambda:GetLayerVersion",
      "lambda:DeleteLayerVersion",
      "lambda:ListLayerVersions",
    ]
    resources = [
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:${var.name_prefix}-*",
      "arn:aws:lambda:${var.aws_region}:${var.account_id}:layer:${var.name_prefix}-*:*",
    ]
  }

  ###########################################################################
  # Lambda event source mappings (DDB Streams trigger for the aggregator).
  # These actions don't accept resource-level scoping at the mapping ARN.
  # Tag actions are required because the AWS provider applies default_tags
  # to mappings; the function-level TagResource grant doesn't cover the
  # event-source-mapping ARN class.
  ###########################################################################
  statement {
    sid    = "LambdaManageEventSourceMappings"
    effect = "Allow"
    actions = [
      "lambda:CreateEventSourceMapping",
      "lambda:GetEventSourceMapping",
      "lambda:UpdateEventSourceMapping",
      "lambda:DeleteEventSourceMapping",
      "lambda:ListEventSourceMappings",
      "lambda:TagResource",
      "lambda:UntagResource",
      "lambda:ListTags",
    ]
    resources = ["*"]
  }

  ###########################################################################
  # State bucket — full S3 access on the bucket and its objects only.
  # Same shared backend as Diamond IQ.
  ###########################################################################
  statement {
    sid    = "S3StateBucket"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:GetBucketVersioning",
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = [
      "arn:aws:s3:::${var.state_bucket_name}",
      "arn:aws:s3:::${var.state_bucket_name}/*",
    ]
  }

  ###########################################################################
  # SOC-specific S3 buckets — split into bucket-level and object-level
  # statements so the deploy role's per-bucket object access can differ.
  #
  # IMPORTANT (Phase 11B-1 Gate 2 tightening): the deploy role has NO
  # s3:GetObject grant on dram-soc-honeypot-ingest. Compromised CI must
  # not be able to read captured attacker payloads (raw Cowrie commands,
  # uploaded malware-attempt blobs). Object lifecycle on the ingest
  # bucket is owned by fluent-bit (write via the edge-shipper IAM users)
  # and the ingest Lambda (read via its execution role) — neither path
  # is CI.
  ###########################################################################
  statement {
    sid    = "S3ManageProjectBucketsLevel"
    effect = "Allow"
    # Phase 11B Step 4 amendment #2 (post-PR-#2-retry): replaced the
    # explicit Get*/Put* bucket-attribute enumeration with s3:GetBucket*
    # / s3:PutBucket* wildcards. terraform's AWS provider queries a long
    # tail of bucket-attribute APIs on every aws_s3_bucket refresh
    # (Versioning, Policy, Tagging, PublicAccessBlock, Ownership,
    # Notification, CORS, Acl, Website, AccelerateConfiguration, Logging,
    # Replication, ObjectLockConfiguration, IntelligentTiering, etc.).
    # PR #2 enumerated only Website; the next refresh hit Accelerate;
    # the pattern would continue indefinitely.
    #
    # Security envelope preserved: s3:GetObject is a SEPARATE namespace
    # and is NOT covered by s3:GetBucket*. ADR-011's "no object reads on
    # raw/* in honeypot-ingest" property is intact — the role still
    # cannot read attacker-uploaded payloads.
    #
    # Resource scoping unchanged: only the 2 project buckets.
    actions = [
      "s3:CreateBucket",
      "s3:DeleteBucket",
      "s3:ListBucket",
      "s3:DeleteBucketPolicy",
      # Outside the GetBucket* / PutBucket* namespaces — kept explicit:
      "s3:GetBucketLocation",
      "s3:GetEncryptionConfiguration",
      "s3:PutEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:PutLifecycleConfiguration",
      # Wildcards covering all current + future bucket-attribute reads/writes:
      "s3:GetBucket*",
      "s3:PutBucket*",
    ]
    # Bucket-level only — note the absence of `/*` resource entries here.
    resources = [
      "arn:aws:s3:::${var.name_prefix}-honeypot-ingest",
      "arn:aws:s3:::${var.name_prefix}-dashboard-frontend",
    ]
  }

  # Object-level access ONLY on the frontend bundle bucket. The frontend-
  # deploy workflow needs to S3-sync the React bundle. The ingest bucket's
  # objects (raw attack data) are intentionally absent from this scope.
  statement {
    sid    = "S3FrontendBundleObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = [
      "arn:aws:s3:::${var.name_prefix}-dashboard-frontend/*",
    ]
  }

  ###########################################################################
  # Lock table — full DynamoDB access on the lock table only.
  ###########################################################################
  statement {
    sid    = "DynamoDBLockTable"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeTable",
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = ["arn:aws:dynamodb:${var.aws_region}:${var.account_id}:table/${var.lock_table_name}"]
  }

  ###########################################################################
  # Project DynamoDB tables — manage shape, indexes, streams, TTL, backups.
  # Stream and index sub-resource ARNs are listed explicitly because IAM
  # treats them as separate resources from the table itself.
  ###########################################################################
  statement {
    sid    = "DynamoDBProjectTablesManage"
    effect = "Allow"
    actions = [
      "dynamodb:DescribeTable",
      "dynamodb:DescribeContinuousBackups",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:ListTagsOfResource",
      "dynamodb:UpdateTable",
      "dynamodb:UpdateContinuousBackups",
      "dynamodb:UpdateTimeToLive",
      "dynamodb:CreateTable",
      "dynamodb:DeleteTable",
      "dynamodb:TagResource",
      "dynamodb:UntagResource",
      "dynamodb:DescribeStream",
      "dynamodb:ListStreams",
    ]
    resources = [
      "arn:aws:dynamodb:${var.aws_region}:${var.account_id}:table/${var.name_prefix}-*",
      "arn:aws:dynamodb:${var.aws_region}:${var.account_id}:table/${var.name_prefix}-*/index/*",
      "arn:aws:dynamodb:${var.aws_region}:${var.account_id}:table/${var.name_prefix}-*/stream/*",
    ]
  }

  ###########################################################################
  # CloudWatch Logs — manage the project's log groups only.
  ###########################################################################
  statement {
    sid    = "LogsManageProjectGroups"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:DeleteLogGroup",
      "logs:DescribeLogStreams",
      "logs:PutRetentionPolicy",
      "logs:DeleteRetentionPolicy",
      "logs:TagLogGroup",
      "logs:UntagLogGroup",
      "logs:ListTagsLogGroup",
      "logs:ListTagsForResource",
      "logs:PutMetricFilter",
      "logs:DeleteMetricFilter",
      "logs:DescribeMetricFilters",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.name_prefix}-*",
      "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/lambda/${var.name_prefix}-*:*",
      "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/apigateway/${var.name_prefix}-*",
      "arn:aws:logs:${var.aws_region}:${var.account_id}:log-group:/aws/apigateway/${var.name_prefix}-*:*",
    ]
  }

  ###########################################################################
  # logs:DescribeLogGroups requires a wildcard resource because the API
  # does not accept resource-level scoping for it.
  ###########################################################################
  statement {
    sid       = "LogsDescribeAll"
    effect    = "Allow"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  ###########################################################################
  # PassRole — only the Lambda execution roles, only to lambda.amazonaws.com.
  ###########################################################################
  statement {
    sid       = "IamPassRoleToLambda"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.name_prefix}-*"]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }

  ###########################################################################
  # IAM — manage the project's ROLES and policies only.
  #
  # ADR-011: NO USER MANAGEMENT. Phase 10 fluent-bit edge users live in
  # the human-managed stacks/edge-shippers-credentials/ stack, applied
  # manually from the maintainer's workstation. Granting CI any of
  # iam:*User* / iam:*AccessKey* would let a compromised CI mint AWS
  # access keys — an unacceptable blast-radius expansion for a portfolio
  # honeypot.
  ###########################################################################
  statement {
    sid    = "IamManageProjectRoles"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListRolePolicies",
      "iam:UpdateAssumeRolePolicy",
      "iam:TagRole",
      "iam:UntagRole",
    ]
    resources = ["arn:aws:iam::${var.account_id}:role/${var.name_prefix}-*"]
  }

  ###########################################################################
  # OIDC provider — read access on the GitHub Actions provider that this
  # very role's trust policy depends on. Terraform refresh needs Get* on
  # every plan. NO write actions — Diamond IQ owns the provider; SOC's
  # role is read-only here.
  ###########################################################################
  statement {
    sid    = "IamReadGitHubOIDCProvider"
    effect = "Allow"
    actions = [
      "iam:GetOpenIDConnectProvider",
      "iam:ListOpenIDConnectProviderTags",
    ]
    resources = [
      "arn:aws:iam::${var.account_id}:oidc-provider/token.actions.githubusercontent.com",
    ]
  }

  # Phase 11B Step 4 amendment: ListOpenIDConnectProviders is the API the
  # `data "aws_iam_openid_connect_provider"` block calls to look up the
  # provider by URL. List APIs across the account-wide collection don't
  # accept resource-level scoping (same can't-be-scoped pattern as
  # CloudFront/ACM/SNS/SQS list carve-outs above).
  statement {
    sid       = "IamListOidcProviders"
    effect    = "Allow"
    actions   = ["iam:ListOpenIDConnectProviders"]
    resources = ["*"]
  }

  ###########################################################################
  # API Gateway — manage the project's HTTP APIs and sub-resources.
  ###########################################################################
  statement {
    sid    = "ApiGatewayManage"
    effect = "Allow"
    actions = [
      "apigateway:GET",
      "apigateway:POST",
      "apigateway:PUT",
      "apigateway:PATCH",
      "apigateway:DELETE",
      "apigateway:TagResource",
      "apigateway:UntagResource",
    ]
    resources = [
      "arn:aws:apigateway:${var.aws_region}::/apis",
      "arn:aws:apigateway:${var.aws_region}::/apis/*",
      "arn:aws:apigateway:${var.aws_region}::/tags/*",
    ]
  }

  ###########################################################################
  # EventBridge — manage the project's rules only (rank_rebuild,
  # daily_summary, today_summary).
  ###########################################################################
  statement {
    sid    = "EventBridgeManageProjectRules"
    effect = "Allow"
    actions = [
      "events:DescribeRule",
      "events:ListTargetsByRule",
      "events:ListTagsForResource",
      "events:PutRule",
      "events:DeleteRule",
      "events:PutTargets",
      "events:RemoveTargets",
      "events:EnableRule",
      "events:DisableRule",
      "events:TagResource",
      "events:UntagResource",
    ]
    resources = ["arn:aws:events:${var.aws_region}:${var.account_id}:rule/${var.name_prefix}-*"]
  }

  ###########################################################################
  # CloudWatch — read access (metrics) + manage the project's alarms.
  ###########################################################################
  statement {
    sid    = "CloudWatchRead"
    effect = "Allow"
    actions = [
      "cloudwatch:DescribeAlarms",
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
    ]
    resources = ["*"]
  }

  statement {
    sid    = "CloudWatchAlarmsManageProject"
    effect = "Allow"
    actions = [
      "cloudwatch:PutMetricAlarm",
      "cloudwatch:DeleteAlarms",
      "cloudwatch:TagResource",
      "cloudwatch:UntagResource",
      "cloudwatch:ListTagsForResource",
    ]
    resources = [
      "arn:aws:cloudwatch:${var.aws_region}:${var.account_id}:alarm:${var.name_prefix}-*",
    ]
  }

  ###########################################################################
  # SNS — manage the project's topics only (edge-alarms in Phase 10).
  ###########################################################################
  statement {
    sid    = "SnsManageProjectTopics"
    effect = "Allow"
    actions = [
      "sns:CreateTopic",
      "sns:DeleteTopic",
      "sns:GetTopicAttributes",
      "sns:SetTopicAttributes",
      "sns:Subscribe",
      "sns:Unsubscribe",
      "sns:GetSubscriptionAttributes",
      "sns:ListSubscriptionsByTopic",
      "sns:ListTagsForResource",
      "sns:TagResource",
      "sns:UntagResource",
    ]
    resources = [
      "arn:aws:sns:${var.aws_region}:${var.account_id}:${var.name_prefix}-*",
    ]
  }

  statement {
    sid       = "SnsListAll"
    effect    = "Allow"
    actions   = ["sns:ListTopics"]
    resources = ["*"]
  }

  ###########################################################################
  # SQS — manage the project's queues only (ingest + aggregator DLQs).
  ###########################################################################
  statement {
    sid    = "SqsManageProjectQueues"
    effect = "Allow"
    actions = [
      "sqs:CreateQueue",
      "sqs:DeleteQueue",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:SetQueueAttributes",
      "sqs:TagQueue",
      "sqs:UntagQueue",
      "sqs:ListQueueTags",
    ]
    resources = ["arn:aws:sqs:${var.aws_region}:${var.account_id}:${var.name_prefix}-*"]
  }

  statement {
    sid       = "SqsListAll"
    effect    = "Allow"
    actions   = ["sqs:ListQueues"]
    resources = ["*"]
  }

  ###########################################################################
  # CloudFront — split into READ (wildcard, harmless), CREATE (gated by
  # aws:RequestTag/Project so a new distribution must be tagged at birth),
  # and MUTATE/DELETE (gated by aws:ResourceTag/Project so only resources
  # this project owns can be changed). CF distribution IDs are random
  # (e.g., E1A2B3C4D5E6) so ARN-pattern scoping is not possible — tag
  # condition is the only way to scope to "dram-soc-* distributions".
  #
  # ADR-011 threat: a compromised CI must NOT be able to update or delete
  # Diamond IQ's distribution (also in this account) or invalidate its
  # cached objects.
  ###########################################################################

  # Read-only on all CF resources. ListDistributions has no per-resource
  # ARN scoping; tag conditions don't apply to read APIs that return
  # collections, so wildcard is the only practical scope. Read is harmless.
  statement {
    sid    = "CloudFrontRead"
    effect = "Allow"
    actions = [
      "cloudfront:GetDistribution",
      "cloudfront:GetDistributionConfig",
      "cloudfront:ListDistributions",
      "cloudfront:ListTagsForResource",
      "cloudfront:GetCachePolicy",
      "cloudfront:GetOriginRequestPolicy",
      "cloudfront:GetResponseHeadersPolicy",
      "cloudfront:ListResponseHeadersPolicies",
      "cloudfront:GetOriginAccessControl",
      "cloudfront:ListOriginAccessControls",
      "cloudfront:GetFunction",
      "cloudfront:DescribeFunction",
      "cloudfront:ListFunctions",
      "cloudfront:GetInvalidation",
    ]
    resources = ["*"]
  }

  # Create new CF resources — INTENTIONALLY UNCONDITIONAL.
  #
  # CloudFront create-time Project-tag gating cannot be enforced because
  # three of the four resource types we create (OriginAccessControl,
  # Function, ResponseHeadersPolicy) lack a Tags argument at the AWS
  # CreateXxx API surface. default_tags and explicit `tags` blocks both
  # no-op on these — the API simply has nowhere to put the tag. Adding
  # an aws:RequestTag/Project StringEquals condition here would deny all
  # three creates and break the hosting module on first apply.
  #
  # The mutate gate downstream (CloudFrontMutateProjectResources) uses
  # aws:ResourceTag/Project on resources that DO support tags
  # (distributions), which is where the meaningful blast radius lives:
  # a compromised CI cannot UpdateDistribution / DeleteDistribution /
  # CreateInvalidation against any distribution not tagged
  # Project=soc-detection-lab. Orphan OACs / Functions / Policies cost
  # nothing, cannot disrupt service, and cannot exfil data — asymmetric
  # gate matches asymmetric risk.
  #
  # Tighten this statement (re-add the RequestTag condition) if AWS adds
  # Tags to CreateOriginAccessControl / CreateFunction /
  # CreateResponseHeadersPolicy in a future API version.
  statement {
    sid    = "CloudFrontCreateProjectResources"
    effect = "Allow"
    actions = [
      "cloudfront:CreateDistribution",
      "cloudfront:CreateResponseHeadersPolicy",
      "cloudfront:CreateOriginAccessControl",
      "cloudfront:CreateFunction",
      "cloudfront:TagResource",
    ]
    resources = ["*"]
  }

  # Mutate / delete existing CF resources — gated by ResourceTag/Project.
  # A compromised CI cannot UpdateDistribution or DeleteDistribution on
  # any distribution that isn't tagged Project=soc-detection-lab.
  statement {
    sid    = "CloudFrontMutateProjectResources"
    effect = "Allow"
    actions = [
      "cloudfront:UpdateDistribution",
      "cloudfront:DeleteDistribution",
      "cloudfront:UpdateResponseHeadersPolicy",
      "cloudfront:DeleteResponseHeadersPolicy",
      "cloudfront:UpdateOriginAccessControl",
      "cloudfront:DeleteOriginAccessControl",
      "cloudfront:UpdateFunction",
      "cloudfront:DeleteFunction",
      "cloudfront:PublishFunction",
      "cloudfront:CreateInvalidation",
      "cloudfront:UntagResource",
    ]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/Project"
      values   = ["soc-detection-lab"]
    }
  }

  ###########################################################################
  # ACM — manage the dashboard cert (us-east-1 for CloudFront). Diamond IQ
  # doesn't have explicit ACM grants because their CF distribution is
  # default-cert; SOC has a custom-domain cert with SANs.
  #
  # Phase 11B-1 Gate 2: scoped to us-east-1 ONLY. CloudFront-attached
  # certs MUST live in us-east-1 — that is the only region SOC's
  # terraform ever touches. A compromised CI cannot mutate certs in
  # other regions of this account.
  #
  # acm:ListCertificates is scoped to "*" because it is a region-wide
  # listing API that does not accept resource-level scoping; harmless.
  ###########################################################################
  statement {
    sid    = "AcmManageProjectCerts"
    effect = "Allow"
    actions = [
      "acm:RequestCertificate",
      "acm:DeleteCertificate",
      "acm:DescribeCertificate",
      "acm:GetCertificate",
      "acm:ListTagsForCertificate",
      "acm:AddTagsToCertificate",
      "acm:RemoveTagsFromCertificate",
    ]
    resources = ["arn:aws:acm:us-east-1:${var.account_id}:certificate/*"]
  }

  statement {
    sid       = "AcmListAll"
    effect    = "Allow"
    actions   = ["acm:ListCertificates"]
    resources = ["*"]
  }

  ###########################################################################
  # SSM Parameter Store — read/write on /dram-soc/* prefix only.
  #
  # Deliberately EXCLUDES ssm:DeleteParameter so a compromised CI can't
  # wipe the MaxMind license key.
  # KMS:Decrypt for the AWS-managed aws/ssm key is automatic; if a future
  # phase swaps to a CMK, add explicit kms:Decrypt then.
  ###########################################################################
  statement {
    sid    = "SsmParameterStoreProjectRW"
    effect = "Allow"
    actions = [
      "ssm:GetParameter",
      "ssm:GetParameters",
      "ssm:PutParameter",
      "ssm:ListTagsForResource",
      "ssm:AddTagsToResource",
      "ssm:RemoveTagsFromResource",
    ]
    resources = ["arn:aws:ssm:${var.aws_region}:${var.account_id}:parameter/${var.name_prefix}/*"]
  }

  # Phase 11B Step 4 amendment: DescribeParameters is a region-wide list
  # API that doesn't accept resource-level scoping. Same can't-be-scoped
  # pattern as the AcmListAll / SnsListAll / SqsListAll / LogsDescribeAll
  # carve-outs. Terraform calls this on every aws_ssm_parameter refresh.
  statement {
    sid       = "SsmDescribeAll"
    effect    = "Allow"
    actions   = ["ssm:DescribeParameters"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "deploy" {
  name   = "${var.role_name}-policy"
  role   = aws_iam_role.deploy.id
  policy = data.aws_iam_policy_document.deploy.json
}
