__author__ = 'jjw'

from sizefs import SizeFS
import re

sfs = SizeFS()

def test_regex_dir():
    sfs.mkdir("/regex1")
    sfs.setxattr("regex1", "filler", "a(bcd)*e{4}")
    sfs.create("/regex1/128K")
    regex_file = sfs.open("/regex1/128K")
    regex_file_contents = regex_file.read("/regex1/128K", 128*1024, 0)
    match = re.match("a(bcd)*e{4}", regex_file_contents)
    assert (len(regex_file_contents) == 131072 and not match is None)
