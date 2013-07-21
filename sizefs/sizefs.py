#!/usr/bin/env python

import logging

from collections import defaultdict
from errno import ENOENT, EPERM, EEXIST, ENODATA, ENOTEMPTY
from stat import S_IFDIR, S_IFLNK, S_IFREG
from sys import argv, exit
from time import time

import re
import os
from contents import XegerGen

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

FILE_REGEX = re.compile("^(?P<size>[0-9]+(\.[0-9])?)(?P<size_si>[EPTGMKB])"
                        "((?P<operator>[\+|\-])(?P<shift>\d+)"
                        "(?P<shift_si>[EPTGMKB]))?$")

DEBUG = True

if DEBUG:
    logging.debug("Starting SizeFS")


class SizeFSFuse(LoggingMixIn, Operations):
    """
    Size Filesystem.

    Allows 1 level of folders to be created that have an xattr describing how
    files should be filled (regex). Each directory contains a list of commonly
    useful file sizes, however non-listed files of arbitrary size can be opened
    and read from. The size spec comes from the filename, e.g.

      open("/<folder>/1.1T-1B")
    """

    #__metaclass__ = LogTheMethods
    default_files = ['100K', '4M', '4M-1B', '4M+1B']
    sizes = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3,
             'T': 1024**4, 'P': 1024**5, 'E': 1024**6}

    def __init__(self):
        self.folders = {}
        self.files = {}
        self.xattrs = {}
        self.data = defaultdict(bytes)
        self.fd = 0
        now = time()
        self.folders['/'] = dict(st_mode=(S_IFDIR | 0664), st_ctime=now,
                                 st_mtime=now, st_atime=now, st_nlink=0)

        # Create the default dirs (zeros, ones, common)
        self.mkdir('/zeros', (S_IFDIR | 0664))
        self.setxattr('/zeros', u'user.filler', '0', None)
        self.__add_default_files__('/zeros')
        self.mkdir('/ones', (S_IFDIR | 0664))
        self.setxattr('/ones', u'user.filler', '1', None)
        self.__add_default_files__('/ones')
        self.mkdir('/alpha_num', (S_IFDIR | 0664))
        self.setxattr('/alpha_num', u'user.filler', '[a-zA-Z0-9]', None)
        self.__add_default_files__('/alpha_num')

    def chmod(self, path, mode):
        """
        We'll return EPERM error to indicate that the user cannot change the
        permissions of files/folders
        """
        raise FuseOSError(EPERM)

    def chown(self, path, uid, gid):
        """
        We'll return EPERM error to indicate that the user cannot change the
        ownership of files/folders
        """
        raise FuseOSError(EPERM)

    def create(self, path, mode):
        """
        We'll return EPERM error to indicate that the user cannot create files
        anywhere but within folders created to serve regex filled files, and
        only with valid filenames
        """
        (folder, filename) = os.path.split(path)

        if folder in self.folders and not folder == "/":
            __m__ = FILE_REGEX.match(filename)
            if __m__:
                attrs = self.__file_attrs__(__m__)
                size_bytes = attrs['st_size']

                # Get the inherited xattrs from the containing folder and create
                # the content generator
                folder_xattrs = self.xattrs[folder]
                filler = folder_xattrs.get(u'user.filler', None)
                prefix = folder_xattrs.get(u'user.prefix', None)
                suffix = folder_xattrs.get(u'user.suffix', None)
                padder = folder_xattrs.get(u'user.padder', None)
                max_random = folder_xattrs.get(u'user.max_random', u'10')

                self.xattrs[path] = {}
                if filler is not None:
                    self.setxattr(path, u'user.filler', filler, None)
                if prefix is not None:
                    self.setxattr(path, u'user.prefix', prefix, None)
                if suffix is not None:
                    self.setxattr(path, u'user.suffix', suffix, None)
                if padder is not None:
                    self.setxattr(path, u'user.padder', padder, None)
                self.setxattr(path, u'user.max_random', max_random, None)

                self.files[path] = {
                    'attrs': attrs,
                    'generator': self.__create_generator__(path, size_bytes)
                }
            else:
                raise FuseOSError(EPERM)
        else:
            raise FuseOSError(EPERM)

        self.fd += 1
        return self.fd

    def getattr(self, path, fh=None):
        """
        Getattr either returns an attribute dict for a folder from the
        self.folders map, or it returns a standard attribute dict for any valid
        files
        """
        if path in self.folders:
            return self.folders[path]

        if path in self.files:
            return self.files[path]['attrs']

        (folder, filename) = os.path.split(path)

        if filename == ".":
            if folder in self.folder:
                return self.folders[folder]

        if filename == "..":
            (parent_folder, child_folder) = os.path.split(folder)
            if parent_folder in self.folders:
                return self.folders[parent_folder]

        raise FuseOSError(ENOENT)

    def getxattr(self, path, name, position=0):
        """
        Returns an extended attribute of a file/folder

        If the xattr does not exist we return ENODATA (synonymous with ENOATTR)
        """
        if not name.startswith(u'user.'):
            name = u'user.%s' % name
        else:
            name = u'%s' % name

        if path in self.xattrs:
            path_xattrs = self.xattrs[path]
            if name in path_xattrs:
                return path_xattrs[name]
            else:
                raise FuseOSError(ENODATA)

    def listxattr(self, path):
        """
        Return a list of all extended attribute names for a file/folder
        """
        path_xattrs = self.xattrs.get(path, {})
        xattr_names = map(lambda xa: xa if xa.startswith(u'user.') else xa[5:],
                          path_xattrs)
        return xattr_names

    def mkdir(self, path, mode):
        """
        Here we ignore the mode because we only allow 0444 directories to be
        created
        """
        (parent, folder) = os.path.split(path)

        if not parent == "/":
            raise FuseOSError(EPERM)

        self.folders[path] = dict(st_mode=(S_IFDIR | 0664), st_nlink=2,
                                  st_size=0, st_ctime=time(), st_mtime=time(),
                                  st_atime=time())
        self.xattrs[path] = {}
        self.folders['/']['st_nlink'] += 1

    def open(self, path, flags):
        """
        We check that a file exists in the file dictionary and return a
        unique file descriptor if so
        """
        if not path in self.files:
            raise FuseOSError(ENOENT)

        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        """
        Returns content based on the pattern of the containing folder
        """
        if path in self.files:
            content = self.files[path]['generator'].read(offset, offset+size-1)
            return content
        else:
            raise FuseOSError(ENOENT)

    def readdir(self, path, fh):
        contents = ['.', '..']

        if path == "/":
            for folder_path in self.folders:
                if not folder_path == "/":
                    (parent, folder_name) = os.path.split(folder_path)
                    if parent == path:
                        contents.append(folder_name)
        else:
            for file_path in self.files:
                if file_path.startswith(path):
                    (folder, filename) = os.path.split(file_path)
                    contents.append(filename)

        return contents

    def readlink(self, path):
        return self.data[path]

    def removexattr(self, path, name):
        if not name.startswith(u'user.'):
            name = u'user.%s' % name
        else:
            name = u'%s' % name

        path_xattrs = self.xattrs[path]

        if name in path_xattrs:
            del path_xattrs[name]
            self.__update_mtime__()
        else:
            raise FuseOSError(ENODATA)

        if path in self.folders:
            file_names = self.files.keys()
            files_to_update = [filename for filename in file_names
                               if filename.startswith(path)]
            for file in files_to_update:
                self.removexattr(file, name)
        elif path in self.files:
            size_bytes = self.files[path]['attrs']['st_size']
            self.files[path]['generator'] =\
                self.__create_generator__(path, size_bytes)

    def rename(self, old, new):
        """
        Rename a folder

        We allow renaming of folders as this will not affect the contents of
        the folder. We raise a permissions error for files, because renaming
        a file changes the meaning of its content generator.
        """
        if old in self.folders:
            if new in self.folders:
                raise FuseOSError(EPERM)

            self.folders[new] = self.folders.pop(old)
            for file in self.files:
                (folder, filename) = os.path.split(file)
                if old == folder:
                    new_path = os.path.join(new, filename)
                    self.files[new_path] = self.files.pop(file)

        if old in self.files:
            raise FuseOSError(EPERM)

        raise FuseOSError(ENOENT)

    def rmdir(self, path):
        if path in self.folders:
            for file in self.files:
                (parent_folder, filename) = os.path.split(file)
                if parent_folder == path:
                    raise FuseOSError(ENOTEMPTY)

            del self.folders[path]
            del self.xattrs[path]
            self.folders['/']['st_nlink'] -= 1
        else:
            raise FuseOSError(ENOENT)

    def setxattr(self, path, name, value, options, position=0):
        # Ignore options

        if not '.' in name and not name.startswith(u'user.'):
            name = u'user.%s' % name
        else:
            name = u'%s' % name

        if path in self.xattrs:
            path_xattrs = self.xattrs[path]
            if name in path_xattrs and value == path_xattrs[name]:
                return
            else:
                self.__update_mtime__(path)
            path_xattrs[name] = value
        else:
            raise FuseOSError(ENOENT)

        if path in self.folders:
            filenames = self.files.keys()
            files_to_update = [filename for filename in filenames
                               if filename.startswith(path)]
            for file in files_to_update:
                self.setxattr(file, name, value, options, position)

        elif path in self.files:
            size_bytes = self.files[path]['attrs']['st_size']
            self.files[path]['generator'] =\
                self.__create_generator__(path, size_bytes)

    def statfs(self, path):
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def symlink(self, target, source):
        raise FuseOSError(EPERM)

    def truncate(self, path, length, fh=None):
        raise FuseOSError(EPERM)

    def unlink(self, path):
        if path in self.files:
            del self.files[path]
            del self.xattrs[path]
        else:
            raise FuseOSError(ENOENT)

    def utimens(self, path, times=None):
        pass

    def write(self, path, data, offset, fh):
        raise FuseOSError(EPERM)

    def __calculate_file_size__(self, regex_match):
        file_groupdict = regex_match.groupdict()
        init_size = float(file_groupdict["size"])
        size_unit = self.sizes[file_groupdict["size_si"]]
        size = int(init_size * size_unit)

        operator = file_groupdict["operator"]
        if operator is not None:
            shift = file_groupdict["shift"]
            shift_unit = self.sizes[file_groupdict["shift_si"]]
            shift_size = int(shift) * shift_unit
            if operator == "-":
                size -= shift_size
            elif operator == "+":
                size += shift_size

        if size < 0:
            return 0
        else:
            return int(size)

    def __file_attrs__(self, m):
        size = self.__calculate_file_size__(m)
        return dict(st_mode=(S_IFREG | 0444), st_nlink=1,
                    st_size=size, st_ctime=time(),
                    st_mtime=time(), st_atime=time())

    def __update_mtime__(self, path):
        if path in self.folders:
            self.folders[path]['st_mtime'] = time()
        elif path in self.files:
            self.files[path]['attrs']['st_mtime'] = time()

    def __add_default_files__(self, path):
        """
        Add a set of example files to a directory (only for demo dirs)
        """
        for default_file in self.default_files:
            new_filepath = os.path.join(path, default_file)
            self.create(new_filepath, 0444)
            #attr = self.__file_attrs__(FILE_REGEX.match(default_file))
            #self.files.setdefault(new_filepath, {"attrs": attr})

    def __create_generator__(self, path, size_bytes):
        """
        Create a generator from xattr values
        """
        filler = self.xattrs[path].get(u'user.filler', None)
        prefix = self.xattrs[path].get(u'user.prefix', None)
        suffix = self.xattrs[path].get(u'user.suffix', None)
        padder = self.xattrs[path].get(u'user.padder', None)
        max_random = self.xattrs[path].get(u'user.max_random', u'10')

        genr = XegerGen(size_bytes,
                        filler=filler,
                        prefix=prefix,
                        suffix=suffix,
                        padder=padder,
                        max_random=int(max_random))

        return genr

if __name__ == '__main__':
    if len(argv) != 2:
        print('usage: %s <mountpoint>' % argv[0])
        exit(1)

    logging.getLogger().setLevel(logging.DEBUG)
    fuse = FUSE(SizeFSFuse(), argv[1], foreground=True, auto_cache=True)
