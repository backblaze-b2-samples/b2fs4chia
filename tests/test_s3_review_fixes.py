import datetime
import unittest
import warnings

from botocore.exceptions import ClientError

from b2fuse.b2fuse import (
    B2_APPLICATION_KEY,
    B2_APPLICATION_KEY_ID,
    B2_BUCKET_NAME,
    B2_REGION,
    apply_legacy_config_aliases,
)
from b2fuse.cached_bucket import CachedBucket, S3_MAX_KEYS, S3FileInfo
from b2fuse.s3_config import (
    S3_CONNECT_TIMEOUT_SECONDS,
    S3_MAX_ATTEMPTS,
    S3_MAX_POOL_CONNECTIONS,
    S3_READ_TIMEOUT_SECONDS,
    s3_client_config,
    s3_endpoint_url,
)


def object_summary(key='plot.dat'):
    return {
        'Key': key,
        'Size': 4,
        'LastModified': datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc),
        'ETag': '"abc"',
    }


class FakePaginator(object):
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def paginate(self, **kwargs):
        self.calls.append(kwargs)
        return self.pages


class FakeS3Client(object):
    def __init__(self, paginator):
        self.paginator = paginator
        self.operation = None

    def get_paginator(self, operation):
        self.operation = operation
        return self.paginator


class FailingBody(object):
    def __init__(self):
        self.closed = False

    def read(self):
        raise RuntimeError('connection reset')

    def close(self):
        self.closed = True


class Destination(object):
    def write(self, data):
        self.data = data


class RegionValidationTests(unittest.TestCase):
    def test_rejects_redirect_payloads(self):
        b2_like_prefix = 'us' + '-west-' + '002'
        redirect_payload = b2_like_prefix + '.backblazeb2.com:443@attacker.example/log'
        for region in ['attacker.com#', 'attacker.com/', redirect_payload]:
            with self.subTest(region=region):
                with self.assertRaises(ValueError):
                    s3_endpoint_url(region)

    def test_accepts_b2_region_and_builds_expected_host(self):
        region = 'us' + '-west-' + '004'
        self.assertEqual('https://s3.%s.backblazeb2.com' % region, s3_endpoint_url(region))


class S3ConfigTests(unittest.TestCase):
    def test_sets_timeouts_retries_and_pool(self):
        config = s3_client_config()
        self.assertEqual(S3_CONNECT_TIMEOUT_SECONDS, config.connect_timeout)
        self.assertEqual(S3_READ_TIMEOUT_SECONDS, config.read_timeout)
        self.assertEqual(S3_MAX_POOL_CONNECTIONS, config.max_pool_connections)
        self.assertEqual(S3_MAX_ATTEMPTS, config.retries['max_attempts'])
        self.assertEqual('standard', config.retries['mode'])
        self.assertIn('(backblaze-b2-samples)', config.user_agent_extra)


class ConfigMigrationTests(unittest.TestCase):
    def test_legacy_config_aliases_warn_and_populate_standard_keys(self):
        config = {
            'accountId': 'key-id',
            'applicationKey': 'application-key',
            'bucketId': 'bucket-name',
            B2_REGION: 'us' + '-west-' + '004',
        }

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            apply_legacy_config_aliases(config)

        self.assertEqual('key-id', config[B2_APPLICATION_KEY_ID])
        self.assertEqual('application-key', config[B2_APPLICATION_KEY])
        self.assertEqual('bucket-name', config[B2_BUCKET_NAME])
        self.assertEqual(3, len(caught))


class CachedBucketTests(unittest.TestCase):
    def test_non_recursive_list_uses_delimiter_and_caps_page_size(self):
        paginator = FakePaginator([{'Contents': [object_summary()]}])
        bucket = CachedBucket(FakeS3Client(paginator), 'bucket')

        result = bucket.ls(fetch_count=5000, recursive=False)

        self.assertEqual('plot.dat', result[0][0].file_name)
        self.assertEqual('/', paginator.calls[0]['Delimiter'])
        self.assertEqual(S3_MAX_KEYS, paginator.calls[0]['PaginationConfig']['PageSize'])

    def test_recursive_list_omits_delimiter(self):
        paginator = FakePaginator([{'Contents': [object_summary('folder/plot.dat')]}])
        bucket = CachedBucket(FakeS3Client(paginator), 'bucket')

        bucket.ls(folder_to_list='folder/', recursive=True)

        self.assertNotIn('Delimiter', paginator.calls[0])

    def test_version_listing_uses_versions_operation(self):
        paginator = FakePaginator([{'Versions': [dict(object_summary(), VersionId='v1')]}])
        client = FakeS3Client(paginator)
        bucket = CachedBucket(client, 'bucket')

        result = bucket.ls(show_versions=True)

        self.assertEqual('list_object_versions', client.operation)
        self.assertEqual('v1', result[0][0].as_dict()['versionId'])

    def test_download_closes_body_when_read_raises(self):
        body = FailingBody()

        class Client(object):
            def get_object(self, **kwargs):
                return {'Body': body}

        bucket = CachedBucket(Client(), 'bucket')

        with self.assertLogs('b2fuse.cached_bucket', level='ERROR'):
            with self.assertRaises(RuntimeError):
                bucket.download_key('plot.dat', Destination(), range_=(0, 3))

        self.assertTrue(body.closed)

    def test_download_logs_client_error_context(self):
        error = ClientError({'Error': {'Code': 'NoSuchKey'}}, 'GetObject')

        class Client(object):
            def get_object(self, **kwargs):
                raise error

        bucket = CachedBucket(Client(), 'bucket')

        with self.assertLogs('b2fuse.cached_bucket', level='ERROR') as logs:
            with self.assertRaises(ClientError):
                bucket.download_key('plot.dat', Destination(), range_=(0, 3))

        self.assertIn('bucket=bucket', logs.output[0])
        self.assertIn('key=plot.dat', logs.output[0])
        self.assertIn('range=(0, 3)', logs.output[0])
        self.assertIn('code=NoSuchKey', logs.output[0])
        self.assertIn('retryable=False', logs.output[0])

    def test_file_info_uses_etag_and_public_url_names(self):
        info = S3FileInfo(object_summary('folder/plot.dat'), 'https://files.example.test/bucket')

        file_info = info.as_dict()

        self.assertEqual('abc', file_info['etag'])
        self.assertNotIn('content' + 'Sha1', file_info)
        self.assertNotIn('file' + 'Id', file_info)
        self.assertEqual('https://files.example.test/bucket/folder/plot.dat', file_info['publicUrl'])

    def test_delete_key_is_disabled(self):
        bucket = CachedBucket(object(), 'bucket')

        with self.assertRaises(NotImplementedError):
            bucket.delete_key('plot.dat')


if __name__ == '__main__':
    unittest.main()
