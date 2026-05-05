locals {
  bucket_name = "${var.name_prefix}-dashboard-frontend"
  oac_name    = "${var.name_prefix}-dashboard-oac"
  cf_name     = "${var.name_prefix}-dashboard-cf"
}

###############################################################################
# ACM cert (us-east-1; CloudFront requirement). Validation method: DNS.
#
# The validation CNAME is surfaced via the `acm_validation_record` output
# below. The user adds it to Cloudflare DNS-only (grey cloud) and ACM
# completes validation. The aws_acm_certificate_validation resource then
# blocks the apply until the cert is ISSUED.
###############################################################################

resource "aws_acm_certificate" "dashboard" {
  domain_name = var.domain_name
  # ACM replaces the cert when the SAN list changes; create_before_destroy
  # plus the lifecycle on the validation resource handle the swap with no
  # service window. New validation CNAMEs surface on acm_validation_record;
  # add them in Cloudflare DNS-only (grey cloud).
  subject_alternative_names = [var.apex_domain_name, var.www_domain_name]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-dashboard-cert" })
}

resource "aws_acm_certificate_validation" "dashboard" {
  certificate_arn = aws_acm_certificate.dashboard.arn

  timeouts {
    create = "60m"
  }
}

###############################################################################
# S3 origin bucket. Private, OAC-only, versioning on, SSE-S3.
###############################################################################

resource "aws_s3_bucket" "frontend" {
  bucket = local.bucket_name
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "frontend" {
  bucket                  = aws_s3_bucket.frontend.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

###############################################################################
# CloudFront Origin Access Control + distribution.
###############################################################################

resource "aws_cloudfront_origin_access_control" "frontend" {
  name                              = local.oac_name
  description                       = "OAC for ${local.bucket_name}"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

###############################################################################
# Host-header URI rewrite.
#
# CloudFront cache behaviors match on path-pattern only, not Host header.
# This function rewrites the URI to /apex/... when the request Host is the
# apex or www, so the same distribution + same S3 bucket can serve two
# distinct site contents (dashboard SPA at /, apex landing at /apex/).
#
# Trailing-slash and bare-host requests get /index.html appended.
###############################################################################

resource "aws_cloudfront_function" "host_router" {
  name    = "${var.name_prefix}-host-router"
  runtime = "cloudfront-js-2.0"
  comment = "Phase 8.5 — rewrite apex/www requests to /apex/* prefix"
  publish = true
  code    = <<-EOT
    function handler(event) {
      var req = event.request;
      var host = (req.headers.host && req.headers.host.value) || '';
      var apexHosts = ['${var.apex_domain_name}', '${var.www_domain_name}'];

      var isApex = apexHosts.indexOf(host) !== -1;
      if (!isApex) return req;

      var uri = req.uri;
      // bare-host / dir-style → /index.html
      if (uri === '/' || uri === '') uri = '/index.html';
      else if (uri.charAt(uri.length - 1) === '/') uri = uri + 'index.html';

      // already-rewritten requests (re-entrancy guard): don't double-prefix.
      if (uri.indexOf('/apex/') !== 0) {
        req.uri = '/apex' + uri;
      }
      return req;
    }
  EOT
}

###############################################################################
# Response headers policy. CSP, HSTS, X-Frame-Options, Referrer-Policy,
# Permissions-Policy. PROJECT_PLAN.md §11 Phase 8.
#
# CSP notes:
#   - connect-src MUST include the API GW URL or every fetch is blocked.
#   - style-src includes 'unsafe-inline' because Tailwind's runtime emits
#     inline <style> in some configurations. Tightening this requires a
#     report-only-mode dry run first; documented in PHASE_8_LOG.md.
#   - frame-ancestors 'none' is the modern equivalent of X-Frame-Options:DENY;
#     both are sent for older-browser belt-and-suspenders.
###############################################################################

resource "aws_cloudfront_response_headers_policy" "frontend" {
  name    = "${var.name_prefix}-dashboard-headers"
  comment = "Security headers for the dashboard SPA (Phase 8)"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 63072000 # 2y
      include_subdomains         = true
      preload                    = true
      override                   = true
    }

    content_security_policy {
      content_security_policy = join(" ", [
        "default-src 'self';",
        "script-src 'self';",
        "style-src 'self' 'unsafe-inline';",
        "img-src 'self' data:;",
        "connect-src 'self' https://mlncxsr5a9.execute-api.us-east-1.amazonaws.com;",
        "font-src 'self' data:;",
        "object-src 'none';",
        "base-uri 'self';",
        "frame-ancestors 'none'",
      ])
      override = true
    }

    content_type_options {
      override = true
    }

    frame_options {
      frame_option = "DENY"
      override     = true
    }

    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }

  custom_headers_config {
    items {
      header   = "Permissions-Policy"
      value    = "geolocation=(), microphone=(), camera=(), payment=()"
      override = true
    }
  }
}

resource "aws_cloudfront_distribution" "frontend" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  comment             = "${var.name_prefix} dashboard (Phase 8)"
  price_class         = "PriceClass_100" # US/EU/IL only — cheapest, fine for portfolio

  aliases = [var.domain_name, var.apex_domain_name, var.www_domain_name]

  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3-${aws_s3_bucket.frontend.id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # Default behavior: aggressive caching for hashed Vite bundle artifacts.
  default_cache_behavior {
    target_origin_id       = "s3-${aws_s3_bucket.frontend.id}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # CachingOptimized managed policy.
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.frontend.id
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.host_router.arn
    }
  }

  # /index.html: no-cache so users always pick up the latest entry point
  # that references the currently-hashed asset bundle. Phase 8.5: same
  # behavior, but the function runs here too so apex requests for
  # /index.html get rewritten to /apex/index.html.
  ordered_cache_behavior {
    path_pattern           = "/index.html"
    target_origin_id       = "s3-${aws_s3_bucket.frontend.id}"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    # CachingDisabled managed policy.
    cache_policy_id            = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    response_headers_policy_id = aws_cloudfront_response_headers_policy.frontend.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.host_router.arn
    }
  }

  # SPA fallback: client-side routing returns 200 with index.html for any
  # path the bucket doesn't have. Keeps deep links working.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.dashboard.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = merge(var.tags, { Name = local.cf_name })
}

###############################################################################
# S3 bucket policy: only the CloudFront distribution (via OAC) can GetObject.
###############################################################################

data "aws_iam_policy_document" "frontend" {
  statement {
    sid     = "AllowCloudFrontOACRead"
    effect  = "Allow"
    actions = ["s3:GetObject"]
    resources = [
      "${aws_s3_bucket.frontend.arn}/*",
    ]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.frontend.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "frontend" {
  bucket = aws_s3_bucket.frontend.id
  policy = data.aws_iam_policy_document.frontend.json
}

###############################################################################
# Billing alarm. AWS/Billing metrics are us-east-1 only. The default provider
# in this stack is us-east-1, so this alarm lands correctly.
#
# Note: billing alerts must be enabled once per account in Billing
# Preferences ("Receive Billing Alerts"). If not enabled, the alarm
# exists but EstimatedCharges never publishes and it stays in INSUFFICIENT_DATA.
###############################################################################

resource "aws_cloudwatch_metric_alarm" "billing" {
  alarm_name          = "${var.name_prefix}-billing-${var.billing_alarm_threshold_usd}usd"
  alarm_description   = "Account-wide estimated charges exceeded $${var.billing_alarm_threshold_usd}. Defense before the Phase 9 viral-traffic guard. PROJECT_PLAN.md §10."
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = 21600 # 6h — billing metric publishes every ~6h
  statistic           = "Maximum"
  threshold           = var.billing_alarm_threshold_usd
  treat_missing_data  = "ignore"
  dimensions = {
    Currency = "USD"
  }
  tags = var.tags
}
