#!/usr/bin/env python

import logging

from collections import defaultdict
from errno import ENOENT, EPERM, EEXIST
from stat import S_IFDIR, S_IFLNK, S_IFREG
from sys import argv, exit
from time import time

import re
import os
from contents import Filler

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
    default_files = ['4M', '4M-1B', '4M+1B']
    sizes = {'B': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3,
             'T': 1024**4, 'P': 1024**5, 'E': 1024**6}


    def __init__(self):
        self.folders = {}
        self.files = {}
        self.data = defaultdict(bytes)
        self.fd = 0
        now = time()
        self.folders['/'] = dict(st_mode=(S_IFDIR | 0664), st_ctime=now,
                                 st_mtime=now, st_atime=now, st_nlink=0)

        # Create the default dirs (zeros, ones, common)
        self.mkdir('/zeros', (S_IFDIR | 0664))
        self.setxattr('/zeros', "pattern", "0", None)
        self.mkdir('/ones', (S_IFDIR | 0664))
        self.setxattr('/ones', "pattern", "1", None)
        self.mkdir('/alpha_num', (S_IFDIR | 0664))
        self.setxattr('/alpha_num', "pattern", "[a-z,A-Z,0-9]", None)


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
            if FILE_REGEX.match(filename):
                self.files[path] = "Create a generator for it"
            else:
                raise FuseOSError(EPERM)
        else:
            raise FuseOSError(EPERM)

    def cread(self, path, size, offset, fh):
        """
         For code use only - creates a file and allows it to be read
         combined create and read **for programmatic use - ignored by fuse**
        """
        if path in self.files:
            self.read(path, size, offset, fh)
        else:
            self.create(path, 0664)
            self.read(path, size, offset, fh)

    def getattr(self, path, fh=None):
        """
         Getattr either returns an attribute dict for a folder from the
         self.folders map, or it returns a standard attribute dict for any valid
         files
        """
        (folder, filename) = os.path.split(path)

        if not folder in self.folders:
            raise FuseOSError(ENOENT)

        if path in self.folders:
            return self.folders[path]
        else:
            if filename == "." or filename == "..":
                return dict(st_mode=(S_IFDIR | 0444), st_nlink=1,
                            st_size=0, st_ctime=time(), st_mtime=time(),
                            st_atime=time())
            else:
                if folder == "/":
                    raise FuseOSError(ENOENT)
                else:
                    m = FILE_REGEX.match(filename)
                    if m:
                        return self.__file_attrs__(m)
                    else:
                        raise FuseOSError(ENOENT)

    def getxattr(self, path, name, position=0):
        """
         Returns an extended attribute of a file/folder
         This is always an ENOATTR error for files, and the only thing that
         should ever really be used for folders is the pattern
        """
        folder_meta = self.folders.get(path, {})
        attrs = folder_meta.get('attrs', {})

        if name in attrs:
            return attrs[name]
        else:
            return " "

    def listxattr(self, path):
        """
         Return a list of all extended attribute names for a folder
         (always empty for files)
        """
        folder_meta = self.folders.get(path, {})
        attrs = folder_meta.get('attrs', {})
        return attrs.keys()

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

        # Set the default pattern for a folder to "0" so that all new folders
        # default to filling files with zeros
        self.setxattr(path, "pattern", "0", None)
        self.folders['/']['st_nlink'] += 1

        # Add default files
        for default_file in self.default_files:
            attr = self.__file_attrs__(FILE_REGEX.match(default_file))
            new_filepath = os.path.join(path, default_file)
            self.files.setdefault(new_filepath, {"attrs": attr})

    def mkdir_regex(self, path, regex):
        """
         Only for programmatic use, never called by FUSE
        """
        if path in self.folders:
            raise FuseOSError(EEXIST)
        else:
            self.mkdir(path, 0644)
            self.setxattr(path, "pattern", regex, None)

    def open(self, path, flags):
        """
         We check that a file conforms to a size spec and is from a requested
         folder
        """
        (folder, filename) = os.path.split(path)

        # Does the folder exist?
        if not folder in self.folders:
            raise FuseOSError(ENOENT)

        # Does the requested filename match our size spec?
        if not FILE_REGEX.match(filename):
            raise FuseOSError(ENOENT)

        # Now do the right thing and open one of the file objects
        # (add it to files)

        self.fd += 1
        return self.fd

    # FIX ME!!! - need to read from, and keep track of position in, generator
    def read(self, path, size, offset, fh):
        """
         Returns content based on the pattern of the containing folder
        """
        return "Hello, World!"[offset:size+offset]

    def readdir(self, path, fh):
        folder_names = ['.', '..']

        if path == "/":
            for folder_path in self.folders:
                if not folder_path == "/":
                    (parent, folder_name) = os.path.split(folder_path)
                    if parent == path:
                        folder_names.append(folder_name)
        else:
            folder_names += self.default_files

        return folder_names

    def readlink(self, path):
        return self.data[path]

    def removexattr(self, path, name):
        attrs = self.folders[path].get('attrs', {})

        if name in attrs:
            del attrs[name]

    def rename(self, old, new):
        self.folders[new] = self.folders.pop(old)


    # FIX ME
    def rmdir(self, path):
        raise FuseOSError(EPERM)
        #self.files.pop(path)
        #self.files['/']['st_nlink'] -= 1

    def setxattr(self, path, name, value, options, position=0):
        # Ignore options
        if path in self.folders:
            attrs = self.folders[path].setdefault('attrs', {})
            attrs[name] = value
        else:
            raise FuseOSError(EPERM)

    def statfs(self, path):
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)

    def symlink(self, target, source):
        raise FuseOSError(EPERM)

    def truncate(self, path, length, fh=None):
        raise FuseOSError(EPERM)

    def unlink(self, path):
        if path in self.folders:
            self.folders.pop(path)
        else:
            raise FuseOSError(EPERM)

    def utimens(self, path, times=None):
        pass

    def write(self, path, data, offset, fh):
        raise FuseOSError(EPERM)

    def __calculate_file_size__(self, regex_match):
        file_groupdict = regex_match.groupdict()
        init_size = int(file_groupdict["size"])
        size_unit = self.sizes[file_groupdict["size_si"]]
        size = init_size * size_unit

        operator = file_groupdict["operator"]
        if operator is not None:
            shift = file_groupdict["shift"]
            shift_unit = self.sizes[file_groupdict["shift_si"]]
            shift_size = int(shift) * shift_unit
            if operator == "-":
                shift_size = -shift_size
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


if __name__ == '__main__':
    if len(argv) != 2:
        print('usage: %s <mountpoint>' % argv[0])
        exit(1)

    logging.getLogger().setLevel(logging.DEBUG)
    fuse = FUSE(SizeFSFuse(), argv[1], foreground=True)
