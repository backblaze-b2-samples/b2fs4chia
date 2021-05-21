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


from .B2BaseFile import B2BaseFile

from .data_cache import DataCache


class B2SequentialFileMemory(B2BaseFile):
    DATA_CACHE_CLASS = DataCache

    def __init__(self, b2fuse, file_info, new_file=False):
        super(B2SequentialFileMemory, self).__init__(b2fuse, file_info)
        self.data_cache = self.DATA_CACHE_CLASS(self)

        self._dirty = False

    def __len__(self):
        return self.file_info['size']

    def read(self, offset, length):
        return self.data_cache.get(offset, length)

    def set_dirty(self, new_value):
        self._dirty = new_value
