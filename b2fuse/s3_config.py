# The MIT License (MIT)

# Copyright 2021 Backblaze Inc. All Rights Reserved.

import re
from urllib.parse import urlparse

from botocore.config import Config

S3_CONNECT_TIMEOUT_SECONDS = 10
S3_READ_TIMEOUT_SECONDS = 30
S3_MAX_ATTEMPTS = 3
S3_MAX_POOL_CONNECTIONS = 32
S3_USER_AGENT = 'b2fs4chia (backblaze-b2-samples)'

B2_REGION_RE = re.compile(r'^[a-z]{2}(?:-[a-z]+)+-\d{3}$')


def s3_endpoint_url(region):
    if not B2_REGION_RE.fullmatch(region or ''):
        raise ValueError('Invalid B2_REGION: %r' % region)

    endpoint_url = 'https://s3.%s.backblazeb2.com' % region
    parsed_endpoint = urlparse(endpoint_url)
    expected_host = 's3.%s.backblazeb2.com' % region
    if parsed_endpoint.scheme != 'https' or parsed_endpoint.hostname != expected_host:
        raise ValueError('Invalid B2 S3 endpoint host for region: %r' % region)
    return endpoint_url


def s3_client_config():
    return Config(
        signature_version='s3v4',
        user_agent_extra=S3_USER_AGENT,
        connect_timeout=S3_CONNECT_TIMEOUT_SECONDS,
        read_timeout=S3_READ_TIMEOUT_SECONDS,
        retries={
            'max_attempts': S3_MAX_ATTEMPTS,
            'mode': 'standard',
        },
        max_pool_connections=S3_MAX_POOL_CONNECTIONS,
    )
