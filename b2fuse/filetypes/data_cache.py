import logging
import threading

from b2sdk.v0 import DownloadDestBytes

logger = logging.getLogger(__name__)


class DataCache:
    def __init__(self, b2_file):  # B2BaseFile
        self.b2_file = b2_file
        self.lock = threading.Lock()
        # TODO: use something smart + maybe a queue for eviction
        #self.perm = intervaltree()
        #self.temp = intervaltree()
        self.last_offset = 0
        self.last_length = 0

    def _get_data(self, offset, length, keep_it):
        download_dest = DownloadDestBytes()
        self.b2fuse.bucket_api.download_file_by_id(
            self.b2_file.file_info['fileId'],
            download_dest,
            range_=(
                offset,
                length+offset - 1,
            ),
        )
        data = download_dest.get_bytes_written()
        if keep_it:
            self.perm.set(offset, length, data)
        else:
            self.temp.set(offset, length, data)
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
            # the first read after the first "random" read is actually accurate
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
        with self.lock: # chia read pattern is sequental in nature and we don't want to risk it
            new_offset, new_length, keep_it = self.aplify_read(offset, length)
            self.data = self._get_data(
                new_offset,
                new_length,
                keep_it,
            )
            return self._get_data(
                new_offset,
                new_length,
            )
