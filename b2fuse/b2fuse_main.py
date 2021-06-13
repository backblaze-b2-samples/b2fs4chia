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

import errno
import logging
import threading

from collections import defaultdict
from fuse import FuseOSError, Operations
from stat import S_IFDIR, S_IFREG
from time import time, sleep
from typing import Set

from b2sdk.v0 import InMemoryAccountInfo
from b2sdk.v0 import B2Api, B2RawApi, B2Http

from .filetypes.B2SequentialFileMemory import B2SequentialFileMemory
from .directory_structure import DirectoryStructure
from .cached_bucket import CachedBucket


class B2Fuse(Operations):
    def __init__(
            self,
            account_id,
            application_key,
            bucket_id,
            cache_timeout,
    ):
        account_info = InMemoryAccountInfo()
        self.api = B2Api(account_info, raw_api=B2RawApi(B2Http(user_agent_append='b2fs4chia')))
        self.api.authorize_account('production', account_id, application_key)
        self.bucket_api = CachedBucket(self.api, bucket_id, cache_timeout)

        self.logger = logging.getLogger("%s.%s" % (__name__, self.__class__.__name__))

        self.B2File = B2SequentialFileMemory

        self._directories = DirectoryStructure()
        self.local_directories = []

        self.open_files = defaultdict(self.B2File)
        self.files_open_since_last_eviction: Set[str] = set()
        self.files_to_revisit_during_next_eviction: Set[str] = set()
        self.recently_open_files_lock = threading.Lock()

        self.fd = 0
        threading.Thread(target=self.evict_periodically).start()

    def evict_periodically(self):
        while True:
            sleep(30)
            with self.recently_open_files_lock:
                files_to_evict = self.files_open_since_last_eviction | self.files_to_revisit_during_next_eviction
                self.files_to_revisit_during_next_eviction = self.files_open_since_last_eviction
                self.files_open_since_last_eviction = set()
            evict_older_than = time() - 30
            for file_name in files_to_evict:
                try:
                    self.open_files[file_name].evict(evict_older_than)
                except Exception:
                    self.logger.exception(f'Error when performing eviction for file {file_name}')

    def __enter__(self):
        return self

    def __exit__(self, *args, **kwargs):
        return

    # Helper methods
    # ==================

    def _exists(self, path, include_hash=True):
        # Handle hash files
        if include_hash and path.endswith(".sha1"):
            path = path[:-5]

        # File is in bucket
        if self._directories.is_file(path):
            return True

        # File is open (but possibly not in bucket)
        if path in self.open_files.keys():
            return True

        return False

    def _get_memory_consumption(self):
        open_file_sizes = map(lambda f: len(f), self.open_files.values())

        memory = sum(open_file_sizes)

        return float(memory) / (1024 * 1024)

    def _get_cloud_space_consumption(self):

        directories = [self._directories._directories]

        space_consumption = 0
        while len(directories) > 0:
            directory = directories.pop(0)

            directories.extend(directory.get_directories())

            for file_info in directory.get_file_infos():
                space_consumption += file_info['size']

        return space_consumption

    def _update_directory_structure(self):
        # Update the directory structure with online files and local directories
        def build_file_info_dict(file_info_object):
            file_info = file_info_object.as_dict()
            file_info["contentSha1"] = file_info_object.content_sha1
            return file_info

        online_files = [
            build_file_info_dict(file_info_object)
            for file_info_object, _ in self.bucket_api.ls(recursive=True)
        ]
        self._directories.update_structure(online_files, self.local_directories)

    def _remove_local_file(self, path, delete_online=True):
        if path in self.open_files.keys():
            self.open_files[path].delete(delete_online)
            del self.open_files[path]
        elif delete_online:
            file_info = self._directories.get_file_info(path)
            self.bucket_api.delete_file_version(file_info['fileId'], file_info['fileName'])

    def _remove_start_slash(self, path):
        if path.startswith("/"):
            path = path[1:]
        return path

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        self.logger.info("Access %s (mode:%s)", path, mode)
        path = self._remove_start_slash(path)

        # Return access granted if path is a directory
        if self._directories.is_directory(path):
            return

        # Return access granted if path is a file
        if self._exists(path):
            return

        raise FuseOSError(errno.EACCES)

    # def chmod(self, path, mode):
    #    self.logger.debug("Chmod %s (mode:%s)", path, mode)

    # def chown(self, path, uid, gid):
    #    self.logger.debug("Chown %s (uid:%s gid:%s)", path, uid, gid)

    def getattr(self, path, fh=None):
        # self.logger.debug("Get attr %s", path)
        # self.logger.debug("Memory used %s", round(self._get_memory_consumption(), 2))
        path = self._remove_start_slash(path)

        # Check if path is a directory
        if self._directories.is_directory(path):
            return dict(
                st_mode=(S_IFDIR | 0o777),
                st_ctime=time(),
                st_mtime=time(),
                st_atime=time(),
                st_nlink=2
            )

        # Check if path is a file
        elif self._exists(path):
            # If file exist return attributes
            # self.logger.info("Get attr %s", path)

            online_files = [l[0].file_name for l in self.bucket_api.ls()]

            if path in online_files:
                # print "File is in bucket"
                file_info = self._directories.get_file_info(path)

                seconds_since_jan1_1970 = int(file_info['uploadTimestamp'] / 1000.)
                return dict(
                    st_mode=(S_IFREG | 0o777),
                    st_ctime=seconds_since_jan1_1970,
                    st_mtime=seconds_since_jan1_1970,
                    st_atime=seconds_since_jan1_1970,
                    st_nlink=1,
                    st_size=file_info['size']
                )
            else:
                # print "File exists only locally"
                return dict(
                    st_mode=(S_IFREG | 0o777),
                    st_ctime=0,
                    st_mtime=0,
                    st_atime=0,
                    st_nlink=1,
                    st_size=len(self.open_files[path])
                )

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        self.logger.info("Readdir %s", path)
        path = self._remove_start_slash(path)

        self._update_directory_structure()

        dirents = []

        def in_folder(filename):
            if filename.startswith(path):
                relative_filename = filename[len(path):]

                if relative_filename.startswith("/"):
                    relative_filename = relative_filename[1:]

                if "/" not in relative_filename:
                    return True

            return False

        # Add files found in bucket
        directory = self._directories.get_directory(path)

        online_files = map(lambda file_info: file_info['fileName'], directory.get_file_infos())
        dirents.extend(online_files)

        # Add files kept in local memory
        for filename in self.open_files.keys():
            # File already listed
            if filename in dirents:
                continue

            # File is not in current folder
            if not in_folder(filename):
                continue

            dirents.append(filename)

        # If filenames has a prefix (relative to path) remove this
        if len(path) > 0:
            dirents = list(map(lambda f: f[len(path) + 1:], dirents))

        # Add directories
        dirents.extend(['.', '..'])
        dirents.extend(
            [
                str(directory) for directory
                in self._directories.get_directories(path)
            ]
        )
        return dirents

    def rmdir(self, path):
        raise NotImplementedError

    def mkdir(self, path, mode):
        raise NotImplementedError

    def statfs(self, path):
        self.logger.debug("Fetching file system stats %s", path)
        # Returns 1 petabyte free space, arbitrary number
        block_size = 4096 * 16
        total_block_count = 1024 ** 4  # 1 Petabyte
        free_block_count = total_block_count - self._get_cloud_space_consumption() // block_size
        return dict(
            f_bsize=block_size,
            f_blocks=total_block_count,
            f_bfree=free_block_count,
            f_bavail=free_block_count
        )

    def unlink(self, path):
        raise NotImplementedError

    def rename(self, old, new):
        raise NotImplementedError

    def utimens(self, path, times=None):
        raise NotImplementedError

    # File methods
    # ============

    def open(self, path, flags):
        self.logger.debug("Open %s (flags:%s)", path, flags)
        path = self._remove_start_slash(path)

        if not self._exists(path):
            raise FuseOSError(errno.EACCES)

        elif self.open_files.get(path) is None:
            file_info = self._directories.get_file_info(path)
            self.open_files[path] = self.B2File(self, file_info)

        self.fd += 1
        return self.fd

    def create(self, path, mode, fi=None):
        raise NotImplementedError

    def read(self, path, length, offset, fh):
        self.logger.info("Read %s (len:%s offset:%s fh:%s)", path, length, offset, fh)
        file_name = self._remove_start_slash(path)
        with self.recently_open_files_lock:
            self.files_open_since_last_eviction.add(file_name)
        return self.open_files[file_name].read(offset, length)

    def write(self, path, data, offset, fh):
        raise NotImplementedError

    def truncate(self, path, length, fh=None):
        raise NotImplementedError

    def release(self, path, fh):
        raise NotImplementedError

    def release(self, path, fh):  # TODO: see if this should be removed
        self.logger.debug("Release %s %s", path, fh)

        self.logger.debug("Flushing file in case it was dirty")
        self.flush(self._remove_start_slash(path), fh)

        self._remove_local_file(path, False)
