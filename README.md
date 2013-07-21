SizeFS
======

A mock Filesystem that exists in memory only. Returns files of a size as
specified by the filename

For example, reading a file named 128M+1B will return a file of 128 Megabytes
plus 1 byte, reading a file named 128M-1B will return a file of 128 Megabytes
minus 1 byte

We can set up to 5 properties:

    header     - defined pattern for the start of a file (default = "")
    footer     - defined pattern for the end of a file (default = "")
    filler     - repeating pattern to fill file content (default = 0)
    padding    - single character to fill between content and footer (default = 0)
    max_random - the largest number a + or * will resolve to 

If the requested file sizes are too small for the combination of header, footer
and some padding, then a warning will be logged, but the file will still
return as much content as possible to fill the exact file size requested.

The file contents will always match the following regex:

    ^header(filler)*(padding)*footer$

Example Usage
-------------

Create sizefs filesystem

    > sfs = SizeFSFuse()

The folder structure is used to determine the content of the files

    > sfs.mkdir('/zeros')
    > sfs.setxattr('/zeros','filler','0')
    > sfs.create('/zeros','5B')
    > print sfs.read('zeros/5B',5,0,None)

    out> 00000

    > sfs.mkdir('/ones')
    > sfs.setxattr('/ones','filler','1')
    > sfs.create('/ones','5B')
    > print sfs.read('ones/5B',5,0,None)

    out> 11111

File content can be random alphanumeric data::

    > sfs.mkdir('/alphanum')
    > sfs.setxattr('/alphanum','filler','[a-zA-Z0-9]')
    > sfs.create('/alphanum','5B')
    > print sfs.read('ones/5B',5,0,None)

    out> aS8yG

    > sfs.create('/alphanum','128K')
    > print len(sfs.open('alphanum/128K').read(0, 128*1024))

    out> 131072

    > sfs.create('/alphanum','128K-1B')
    print len(sfs.open('alphanum/128K-1B').read(0, 128*1024-1))

    out> 131071

    > sfs.create('/alphanum','128K+1B')
    print len(sfs.open('alphanum/128K+1B').read(0, 128*1024+1))

    out> 131073

File content can be generated that matches a restricted regex pattern by adding
a directory

    > sfs.mkdir('/regex1')
    > sfs.setxattr('/regex1','filler','a(bcd)*e{4}[a-z,0,3]*')
    > sfs.create('/regex1','128K')
    > print len(sfs.open('regex1/128KB').read(0, 128*1024))

    out> 131072

    > sfs.create('/regex1','128K-1B')
    > print len(sfs.open('regex1/128K-1B').read(0, 128*1024-1))

    out> 131071

    > sfs.create('/regex1','128K+1B')
    > print len(sfs.open('regex1/128KB+1B').read(0, 128*1024+1))

    out> 131073

Mounting
--------

From the command line:

   python ./sizefs.py <mount_point>

Mac Mounting - http://osxfuse.github.com/

Programmatic use:

    from sizefs import SizeFSFuse
    sfs = SizeFSFuse()

