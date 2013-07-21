__author__ = 'jjw'

from sizefs.sizefs import SizeFSFuse
import re
import unittest

class XegerGenTestCase(unittest.TestCase):
    def test_regex_dir(self):
        sfs = SizeFSFuse()
        sfs.mkdir("/regex1", None)
        sfs.setxattr("/regex1", "filler", "a(bcd)*e{4}", None)
        sfs.create("/regex1/128K", None)
        regex_file_contents = sfs.read("/regex1/128K", 128 * 1024, 0, None)
        match = re.match("a(bcd)*e{4}", regex_file_contents)
        assert (len(regex_file_contents) == 131072 and not match is None)
