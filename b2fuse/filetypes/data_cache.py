# The MIT License (MIT)

# Copyright 2021 Backblaze Inc. All Rights Reserved.

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

import logging
import time
import threading
from .evicted_interval_tree import EvictedIntervalTree

from b2sdk.v0 import DownloadDestBytes
from intervaltree import IntervalTree

logger = logging.getLogger(__name__)

MIN_READ_LEN_WITHOUT_CACHE = 16384


class DataCache:

    def __init__(self, b2_file):
        self.b2_file = b2_file
        self.lock = threading.Lock()
        self.perm = IntervalTree()
        self.temp = EvictedIntervalTree()
        self.parallel_counter = 0

    def _fetch_data(self, offset, length, keep_it):
        download_dest = DownloadDestBytes()
        self.parallel_counter += 1
        start = time.time()
        self.b2_file.b2fuse.bucket_api.download_file_by_id(
            self.b2_file.file_info['fileId'],
            download_dest,
            range_=(
                offset,
                length + offset - 1,
            ),
        )
        data = download_dest.get_bytes_written()
        end = time.time()
        logger.info('\033[33mdownloading from b2: %s; offset = %s; length = %s; time=\033[0m%f, thr=%i' % (self.b2_file.file_info['fileName'], offset, length, end-start, self.parallel_counter))
        self.parallel_counter -= 1

        with self.lock:
            if keep_it:
                self.perm[offset: length + offset] = data
            else:
                self.temp.add_and_remember(offset, length + offset, data, start)
        return data

    def amplify_read(self, offset, length):
        """
        return new_offset <= offset and length >= offset-new_offset+length
        """
        requested_length = length

        length = max(MIN_READ_LEN_WITHOUT_CACHE, requested_length)

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
            intervals_set = self.temp[read_range_start: read_range_end] | self.perm[read_range_start: read_range_end]

        intervals = list(intervals_set)
        intervals.sort()

        if not intervals:
            new_offset, new_length, keep_it = self.amplify_read(offset, length)
            return self._fetch_data(new_offset, new_length, keep_it)[
                   (offset - new_offset): (offset - new_offset + length)]

        result = bytearray()

        if intervals[0].begin > read_range_start:
            logger.info('extending read range start of %s by %s', intervals[0].begin,
                        intervals[0].begin - read_range_start)
            result.extend(self._fetch_data(read_range_start, intervals[0].begin - read_range_start, False))

        prev_end = None
        overlap = 0
        for interval in intervals:
            if prev_end:

                if interval.begin > prev_end:
                    logger.info('filling up a hole')
                    result.extend(self._fetch_data(prev_end, interval.begin - prev_end, False))
                overlap = max(prev_end - interval.begin, 0)
            interval_slice_start = max(read_range_start - interval.begin, 0) + overlap
            interval_slice_end = min(interval.end, read_range_end) - interval.begin + 1
            logger.info(f'\033[32madding from cache: {self.b2_file.file_info["fileName"]}. \n'
                        f'Original interval parameters: offset = {interval.begin}; length = {interval.end - interval.begin}\n'
                        f'Using slice: [{interval_slice_start}: {interval_slice_end}]\033[0m')

            prev_end = interval.end
            result.extend(interval.data[interval_slice_start: interval_slice_end])

        result_len = len(result)
        if result_len < length:
            logger.info('extending read range end of %s by %s', result_len + offset, length - result_len)
            result.extend(self._fetch_data(result_len + offset, length - result_len, False))

        return bytes(result)

    def evict(self, older_than_timestamp: float):
        with self.lock:
            self.temp.evict(older_than_timestamp)
