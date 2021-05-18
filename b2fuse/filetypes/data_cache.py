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
        self.last_offset = 0
        self.last_length = 0

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
            self.perm[offset: length+offset] = data
        else:
            self.temp[offset: length+offset] = data
        return data

    def aplify_read(self, offset, length):
        """
        return new_offset <= offset and length >= offset-new_offset+length
        """
        requested_offset = offset
        requested_length = length
        keep_it = False  # TODO: store that on a cache disk, never evict it
        if offset > self.last_offset*2 and offset > 128*1024:
            pass  # TODO: reset cache
        elif offset == 0 and length == 16384:
            # header
            length += 32768
            keep_it = True
        elif self.last_offset == 16384 and self.last_length == 32768 and offset != 0 and length == 12288:
            # harvester is being initialized and we are now touching the precious plot part at the end of the file
            keep_it = True
        elif self.last_offset < offset and length == 12288:
            # the first read after the first high read is actually accurate
            # TODO: actually usually it's two of them
            pass
        elif length == 12288:
            length += 16384
        elif length >= 16384:
            length *= 3
        else:
            pass

        if offset <= requested_offset and length >= (requested_offset-offset+requested_length):
            pass
        else:
            logger.error('messed up offsets %s', locals())

        self.last_offset = requested_offset
        self.last_length = requested_length
        return offset, length, keep_it

    def get(self, offset, length):
        logger.info('getting: %s; offset = %s; length = %s' % (
            self.b2_file.file_info['fileName'], offset, length))
        with self.lock:
            read_range_start = offset
            read_range_end = offset + length - 1

            intervals = sorted(self.temp[read_range_start: read_range_end] | self.perm[read_range_start: read_range_end])
            if not intervals:
                return self._fetch_data(offset, length, True)
                new_offset, new_length, keep_it = self.aplify_read(offset, length)
                return self._fetch_data(new_offset, new_length, keep_it)[(offset - new_offset): (offset - new_offset + length)]

            result = bytearray()

            if intervals[0].begin > read_range_start:
                result.extend(self._fetch_data(read_range_start, intervals[0].begin - read_range_start, False))

            for interval in intervals:
                # TODO: check for holes and download missing bytes + cache them
                # interval_slice_start = max(read_range_start, interval.begin) - read_range_start
                interval_slice_start = max(read_range_start - interval.begin, 0)
                interval_slice_end = min(interval.end, read_range_end) - interval.begin
                # interval_slice_end = min(read_range_end, interval.end) - read_range_start
                logger.info(f'adding from cache: {self.b2_file.file_info["fileName"]}. \n'
                            f'Original interval parameters: offset = {interval.begin}; length = {interval.end - interval.begin}\n'
                            f'Using slice: [{interval_slice_start}: {interval_slice_end}]')
                result.extend(interval.data[interval_slice_start: interval_slice_end])

            if intervals[-1].end < read_range_end:
                result.extend(self._fetch_data(intervals[-1].end + 1, read_range_end - intervals[-1].end, False))

            return bytes(result)
