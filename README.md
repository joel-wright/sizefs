SizeFS
======

A mock Filesystem that exists in memory only. Returns files of a size as
specified by the filename

For example, reading a file named 128M+1B will return a file of 128 Megabytes
plus 1 byte, reading a file named 128M-1B will return a file of 128 Megabytes
minus 1 byte

Caveats
-------

There are a few caveats to bear in mind for use:

1. The regex will not be broken (must have repeating patterns to fill a
   requested file size).
2. Repeating patterns may be truncated if a pattern is not completed before the
   requested file size is reached, or truncated in favour of a fixed file
   'footer'.

Good example Regexs:

    ^starting_header[a-zA-Z0-9]*ending_footer$
    (([a-z]*)middle([0-9]+)+

Bad examples:

    ^content$  -- fixed size
    ^start(middle1)+(middle2)+(middle3)+end$  -- only final pattern repeated

Example Usage
-------------

The folder structure is used to determine the content of the files

    print sfs.cread('zeros/5B',5,0,None)
    00000

    print sfs.cread('ones/5B',5,0,None)
    11111

File content can be random alphanumeric data::

    print len(sfs.open('alphanum/128KB').read())
    131072

    print len(sfs.open('random/128KB-1').read())
    131071

    print len(sfs.open('random/128KB+1').read())
    131073

File content can be generated that matches a restricted regex pattern by adding
a directory

    sfs.mkdir_regex("regex1","a(bcd)*e{4}[a-z,0,3]*")
    print len(sfs.open('regex1/128KB').read())
    131072

    print len(sfs.open('regex1/128KB-1').read())
    131071

    print len(sfs.open('regex1/128KB+1').read())
    131073

Mounting
--------

Mac Mounting - http://osxfuse.github.com/

Programmatic use:

    from fs.expose import fuse
    from sizefs import sizefs
    sfs = sizefs.SizeFS()
    mp = fuse.mount(sfs,"~/sizefsdir")
