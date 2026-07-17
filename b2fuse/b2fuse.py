# The MIT License (MIT)

# Copyright 2021 Backblaze Inc. All Rights Reserved.
# Copyright (c) 2015 Sondre Engebraaten

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import argparse
import logging
import os
import warnings
import yaml

from .version import VERSION

B2_APPLICATION_KEY_ID = "B2_APPLICATION_KEY_ID"
B2_APPLICATION_KEY = "B2_APPLICATION_KEY"
B2_BUCKET_NAME = "B2_BUCKET_NAME"
B2_REGION = "B2_REGION"
B2_PUBLIC_URL_BASE = "B2_PUBLIC_URL_BASE"

CONFIG_KEYS = [
    B2_APPLICATION_KEY_ID,
    B2_APPLICATION_KEY,
    B2_BUCKET_NAME,
    B2_REGION,
    B2_PUBLIC_URL_BASE,
]

REQUIRED_CONFIG_KEYS = [
    B2_APPLICATION_KEY_ID,
    B2_APPLICATION_KEY,
    B2_BUCKET_NAME,
    B2_REGION,
]

LEGACY_CONFIG_ALIASES = {
    "accountId": B2_APPLICATION_KEY_ID,
    "applicationKey": B2_APPLICATION_KEY,
    "bucketId": B2_BUCKET_NAME,
}


def create_parser():
    parser = argparse.ArgumentParser()
    parser.add_argument("mountpoint", type=str, help="Mountpoint for the B2 bucket")

    parser.add_argument('--version', action='version', version=f"b2fs4chia version {VERSION}")

    parser.add_argument('--debug', dest='debug', action='store_true')
    parser.set_defaults(debug=False)

    parser.add_argument(
        "--application_key_id",
        type=str,
        default=None,
        help="B2 application key ID (overrides config)"
    )
    parser.add_argument(
        "--application_key",
        type=str,
        default=None,
        help="Application key for your account  (overrides config)"
    )
    parser.add_argument(
        "--bucket_name",
        type=str,
        default=None,
        help="B2 bucket name to mount (overrides config)"
    )
    parser.add_argument(
        "--account_id",
        type=str,
        default=None,
        help="Deprecated alias for --application_key_id"
    )
    parser.add_argument(
        "--bucket_id",
        type=str,
        default=None,
        help="Deprecated alias for --bucket_name; S3 access requires a bucket name"
    )
    parser.add_argument(
        "--region",
        type=str,
        default=None,
        help="B2 region (overrides config)"
    )
    parser.add_argument(
        "--public_url_base",
        type=str,
        default=None,
        help="Public download URL base for the bucket (overrides config)"
    )

    parser.add_argument("--config_filename", type=str, default="config.yaml", help="Config file")

    parser.add_argument('--allow_other', dest='allow_other', action='store_true', help="option passed to FUSE")

    parser.add_argument('--cache_timeout', type=int, help="B2 Bucket cache lifetime")

    return parser


def warn_deprecated_alias(alias, replacement):
    warnings.warn(
        "%s is deprecated; use %s for S3-compatible B2 access" % (alias, replacement),
        FutureWarning,
        stacklevel=3,
    )


def apply_legacy_config_aliases(config):
    for alias, replacement in LEGACY_CONFIG_ALIASES.items():
        if config.get(alias) and not config.get(replacement):
            warn_deprecated_alias(alias, replacement)
            config[replacement] = config[alias]
    return config


def load_config(config_filename):
    config = {}
    if config_filename and os.path.exists(config_filename):
        with open(config_filename) as f:
            config.update(yaml.safe_load(f.read()) or {})

    apply_legacy_config_aliases(config)

    for key in CONFIG_KEYS:
        if os.environ.get(key):
            config[key] = os.environ[key]

    return config


def require_config(config):
    missing = [key for key in REQUIRED_CONFIG_KEYS if not config.get(key)]
    if missing:
        raise SystemExit(
            "Missing required config values: %s. For zero-downtime migration, "
            "add the new B2_* keys alongside legacy accountId/applicationKey/"
            "bucketId before rolling out this S3-compatible version."
            % ", ".join(missing)
        )


def main():
    parser = create_parser()
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s:%(levelname)s:%(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s:%(levelname)s:%(message)s")

    if args.config_filename:
        config = load_config(args.config_filename)
    else:
        config = {}

    if args.application_key_id:
        config[B2_APPLICATION_KEY_ID] = args.application_key_id
    elif args.account_id:
        warn_deprecated_alias("--account_id", "--application_key_id")
        config[B2_APPLICATION_KEY_ID] = args.account_id

    if args.application_key:
        config[B2_APPLICATION_KEY] = args.application_key

    if args.bucket_name:
        config[B2_BUCKET_NAME] = args.bucket_name
    elif args.bucket_id:
        warn_deprecated_alias("--bucket_id", "--bucket_name")
        config[B2_BUCKET_NAME] = args.bucket_id

    if args.region:
        config[B2_REGION] = args.region

    if args.public_url_base:
        config[B2_PUBLIC_URL_BASE] = args.public_url_base

    if args.cache_timeout:
        config["cacheTimeout"] = args.cache_timeout
    else:
        config["cacheTimeout"] = 120

    require_config(config)

    args.options = {}  # additional options passed to FUSE

    if args.allow_other:
        args.options['allow_other'] = True

    # Keep FUSE imports local so config parsing and --help work on hosts
    # without libfuse installed.
    from fuse import FUSE
    from .b2fuse_main import B2Fuse

    with B2Fuse(
            config[B2_APPLICATION_KEY_ID],
            config[B2_APPLICATION_KEY],
            config[B2_BUCKET_NAME],
            config[B2_REGION],
            config["cacheTimeout"],
            config.get(B2_PUBLIC_URL_BASE),
    ) as filesystem:
        FUSE(filesystem, args.mountpoint, nothreads=False, foreground=True, entry_timeout=1800, attr_timeout=1800,
             direct_io=True, kernel_cache=True, **args.options)


if __name__ == '__main__':
    main()
