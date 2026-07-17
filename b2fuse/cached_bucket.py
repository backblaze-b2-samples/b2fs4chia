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

import datetime
import logging

from botocore.exceptions import BotoCoreError, ClientError
from time import time
from urllib.parse import quote

logger = logging.getLogger(__name__)

S3_MAX_KEYS = 1000
MAX_CACHED_LIST_ITEMS = 10000

RETRYABLE_CLIENT_ERROR_CODES = {
    '500',
    '503',
    'InternalError',
    'RequestTimeout',
    'ServiceUnavailable',
    'SlowDown',
    'Throttling',
    'ThrottlingException',
    'TooManyRequestsException',
}


# General cache used for B2Bucket
class Cache(object):
    def __init__(self, cache_timeout):
        self.data = {}

        self.cache_timeout = cache_timeout

    def update(self, result, params=""):
        self.data[params] = (time(), result)

    def get(self, params=""):
        if self.data.get(params) is not None:
            entry_time, result = self.data.get(params)
            if time() - entry_time < self.cache_timeout:
                return result
            else:
                del self.data[params]

        return


class CacheNotFound(BaseException):
    pass


class S3FileInfo(object):
    def __init__(self, object_summary, public_url_base=None):
        self.file_name = object_summary['Key']
        self.etag = object_summary.get('ETag', '').strip('"')
        self.size = object_summary['Size']
        self.upload_timestamp = self._timestamp_ms(object_summary['LastModified'])
        self.version_id = object_summary.get('VersionId')
        self.public_url = self._public_url(public_url_base, self.file_name)

    def as_dict(self):
        file_info = {
            'fileName': self.file_name,
            'size': self.size,
            'uploadTimestamp': self.upload_timestamp,
            'etag': self.etag,
        }
        if self.version_id:
            file_info['versionId'] = self.version_id
        if self.public_url:
            file_info['publicUrl'] = self.public_url
        return file_info

    @staticmethod
    def _timestamp_ms(value):
        if isinstance(value, datetime.datetime):
            return int(value.timestamp() * 1000)
        return int(value)

    @staticmethod
    def _public_url(public_url_base, file_name):
        if not public_url_base:
            return None
        return '%s/%s' % (public_url_base.rstrip('/'), quote(file_name.lstrip('/'), safe='/'))


class CachedBucket(object):
    def __init__(self, s3_client, bucket_name, timeout=120, public_url_base=None):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.public_url_base = public_url_base

        self._cache = {}

        self._cache_timeout = timeout

    def _reset_cache(self):
        self._cache = {}

    def _update_cache(self, cache_name, result, params=""):
        logger.info('cache miss: %s, %s', cache_name, str(params))
        if len(result) > MAX_CACHED_LIST_ITEMS:
            logger.warning(
                'not caching %s result with %s items; max cached items is %s',
                cache_name,
                len(result),
                MAX_CACHED_LIST_ITEMS,
            )
            return result
        self._cache[cache_name].update(result, params)
        return result

    def _get_cache(self, cache_name, params="", cache_type=Cache):
        if self._cache.get(cache_name) is None:
            self._cache[cache_name] = cache_type(self._cache_timeout)

        if self._cache[cache_name].get(params) is not None:
            return self._cache[cache_name].get(params)

        raise CacheNotFound()

    def ls(self, folder_to_list='', show_versions=False, recursive=False, fetch_count=S3_MAX_KEYS):
        func_name = "ls"
        page_size = min(max(int(fetch_count or S3_MAX_KEYS), 1), S3_MAX_KEYS)
        cache_params = (folder_to_list, show_versions, recursive, page_size)

        try:
            return self._get_cache(func_name, cache_params)
        except CacheNotFound:
            pass

        operation = 'list_object_versions' if show_versions else 'list_objects_v2'
        request = {
            'Bucket': self.bucket_name,
            'Prefix': folder_to_list,
            'PaginationConfig': {'PageSize': page_size},
        }
        if not recursive:
            request['Delimiter'] = '/'

        try:
            paginator = self.s3_client.get_paginator(operation)
            page_iterator = paginator.paginate(**request)
            result = []
            item_key = 'Versions' if show_versions else 'Contents'
            for page in page_iterator:
                for object_summary in page.get(item_key, []):
                    result.append((S3FileInfo(object_summary, self.public_url_base), None))
            return self._update_cache(func_name, result, cache_params)
        except ClientError as error:
            self._log_s3_error(operation, error, prefix=folder_to_list)
            raise
        except BotoCoreError as error:
            self._log_s3_error(operation, error, prefix=folder_to_list)
            raise

    def download_key(self, key, destination, range_=None):
        request = {
            'Bucket': self.bucket_name,
            'Key': key,
        }
        if range_:
            request['Range'] = 'bytes=%s-%s' % (range_[0], range_[1])
        body = None
        try:
            response = self.s3_client.get_object(**request)
            body = response['Body']
            destination.write(body.read())
        except ClientError as error:
            self._log_s3_error('get_object', error, key=key, range_=range_)
            raise
        except BotoCoreError as error:
            self._log_s3_error('get_object', error, key=key, range_=range_)
            raise
        except Exception as error:
            self._log_s3_error('get_object', error, key=key, range_=range_)
            raise
        finally:
            if body is not None:
                body.close()

    def delete_key(self, key):
        raise NotImplementedError('Deleting B2 objects through this FUSE adapter is disabled')

    def upload_bytes(self, *args, **kwargs):
        raise NotImplementedError

    def _log_s3_error(self, operation, error, key=None, prefix=None, range_=None):
        logger.error(
            'S3 %s failed: bucket=%s key=%s prefix=%s range=%s code=%s retryable=%s',
            operation,
            self.bucket_name,
            key,
            prefix,
            range_,
            self._error_code(error),
            self._is_retryable_error(error),
        )

    @staticmethod
    def _error_code(error):
        if isinstance(error, ClientError):
            return error.response.get('Error', {}).get('Code')
        return error.__class__.__name__

    @staticmethod
    def _is_retryable_error(error):
        if isinstance(error, ClientError):
            return error.response.get('Error', {}).get('Code') in RETRYABLE_CLIENT_ERROR_CODES
        return isinstance(error, BotoCoreError)
