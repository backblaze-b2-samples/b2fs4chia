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


def load_config(config_filename):
    config = {}
    if config_filename and os.path.exists(config_filename):
        with open(config_filename) as f:
            config.update(yaml.safe_load(f.read()) or {})

    for key in CONFIG_KEYS:
        if os.environ.get(key):
            config[key] = os.environ[key]

    return config


def require_config(config):
    missing = [key for key in REQUIRED_CONFIG_KEYS if not config.get(key)]
    if missing:
        raise SystemExit("Missing required config values: %s" % ", ".join(missing))


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

    if args.application_key:
        config[B2_APPLICATION_KEY] = args.application_key

    if args.bucket_name:
        config[B2_BUCKET_NAME] = args.bucket_name

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

    from fuse import FUSE
    from .b2fuse_main import B2Fuse

    with B2Fuse(
            config[B2_APPLICATION_KEY_ID],
            config[B2_APPLICATION_KEY],
            config[B2_BUCKET_NAME],
            config[B2_REGION],
            config["cacheTimeout"],
    ) as filesystem:
        FUSE(filesystem, args.mountpoint, nothreads=False, foreground=True, entry_timeout=1800, attr_timeout=1800,
             direct_io=True, kernel_cache=True, **args.options)


if __name__ == '__main__':
    main()
