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

from time import time

logger = logging.getLogger(__name__)


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
    def __init__(self, object_summary):
        self.file_name = object_summary['Key']
        self.content_sha1 = object_summary.get('ETag', '').strip('"')
        self.size = object_summary['Size']
        self.upload_timestamp = self._timestamp_ms(object_summary['LastModified'])

    def as_dict(self):
        return {
            'fileId': self.file_name,
            'fileName': self.file_name,
            'size': self.size,
            'uploadTimestamp': self.upload_timestamp,
        }

    @staticmethod
    def _timestamp_ms(value):
        if isinstance(value, datetime.datetime):
            return int(value.timestamp() * 1000)
        return int(value)


class CachedBucket(object):
    def __init__(self, s3_client, bucket_name, timeout=120):
        self.s3_client = s3_client
        self.bucket_name = bucket_name

        self._cache = {}

        self._cache_timeout = timeout

    def _reset_cache(self):
        self._cache = {}

    def _update_cache(self, cache_name, result, params=""):
        logger.info('cache miss: %s, %s', cache_name, str(params))
        self._cache[cache_name].update(result, params)
        return result

    def _get_cache(self, cache_name, params="", cache_type=Cache):
        if self._cache.get(cache_name) is None:
            self._cache[cache_name] = cache_type(self._cache_timeout)

        if self._cache[cache_name].get(params) is not None:
            return self._cache[cache_name].get(params)

        raise CacheNotFound()

    def ls(self, folder_to_list='', show_versions=False, recursive=False, fetch_count=10000):
        func_name = "ls"
        cache_params = (folder_to_list, show_versions, recursive, fetch_count)

        try:
            return self._get_cache(func_name, cache_params)
        except CacheNotFound:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            page_iterator = paginator.paginate(
                Bucket=self.bucket_name,
                Prefix=folder_to_list,
                PaginationConfig={'PageSize': fetch_count},
            )
            result = []
            for page in page_iterator:
                for object_summary in page.get('Contents', []):
                    result.append((S3FileInfo(object_summary), None))
            return self._update_cache(func_name, result, cache_params)

    def download_file_by_id(self, file_id, destination, range_=None):
        request = {
            'Bucket': self.bucket_name,
            'Key': file_id,
        }
        if range_:
            request['Range'] = 'bytes=%s-%s' % (range_[0], range_[1])
        response = self.s3_client.get_object(**request)
        destination.write(response['Body'].read())

    def delete_file_version(self, file_id, file_name):
        self.s3_client.delete_object(Bucket=self.bucket_name, Key=file_name)
        self._reset_cache()

    def upload_bytes(self, *args, **kwargs):
        raise NotImplementedError
