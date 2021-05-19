import logging
import threading
from intervaltree import IntervalTree

from b2sdk.v0 import DownloadDestBytes

logger = logging.getLogger(__name__)


class DataCache:
    def __init__(self, b2_file):  # B2BaseFile
        self.b2_file = b2_file
        self.lock = threading.Lock()
        self.perm = IntervalTree()
        self.temp = IntervalTree()

    def _fetch_data(self, offset, length, keep_it):
        download_dest = DownloadDestBytes()
        logger.info('downloading from b2: %s; offset = %s; length = %s' % (self.b2_file.file_info['fileName'], offset, length))
        self.b2_file.b2fuse.bucket_api.download_file_by_id(
            self.b2_file.file_info['fileId'],
            download_dest,
            range_=(
                offset,
                length+offset - 1,
            ),
        )
        data = download_dest.get_bytes_written()
        if keep_it:
            storage = self.perm
        else:
            storage = self.temp

        with self.lock:
            storage[offset: length+offset] = data

        return data

    def aplify_read(self, offset, length):
        """
        return new_offset <= offset and length >= offset-new_offset+length
        """
        requested_offset = offset
        requested_length = length

        length == 16384*3  # KISS

        if offset <= requested_offset and length >= (requested_offset-offset+requested_length):
            pass
        else:
            logger.error('messed up offsets %s', locals())

        return offset, length, offset == 0

    def get(self, offset, length):
        logger.info(
            'getting: %s; offset = %s; length = %s',
            self.b2_file.file_info['fileName'],
            offset,
            length,
        )
        read_range_start = offset
        read_range_end = offset + length - 1

        with self.lock:
            intervals = self.temp[read_range_start: read_range_end] | self.perm[read_range_start: read_range_end]

        intervals.sort()

        if not intervals:
            new_offset, new_length, keep_it = self.aplify_read(offset, length)
            return self._fetch_data(new_offset, new_length, keep_it)[(offset - new_offset): (offset - new_offset + length)]

        result = bytearray()

        if intervals[0].begin > read_range_start:
            result.extend(self._fetch_data(read_range_start, intervals[0].begin - read_range_start, False))

        for interval in intervals:
            interval_slice_start = max(read_range_start - interval.begin, 0)
            interval_slice_end = min(interval.end, read_range_end) - interval.begin + 1
            logger.info(f'adding from cache: {self.b2_file.file_info["fileName"]}. \n'
                        f'Original interval parameters: offset = {interval.begin}; length = {interval.end - interval.begin}\n'
                        f'Using slice: [{interval_slice_start}: {interval_slice_end}]')
            result.extend(interval.data[interval_slice_start: interval_slice_end])

        if intervals[-1].end < read_range_end:
            result.extend(self._fetch_data(intervals[-1].end + 1, read_range_end - intervals[-1].end, False))

        return bytes(result)
