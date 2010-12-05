#!/usr/bin/env python
'''

Welcome to GhettoNet!
======================


Introduction
------------

GhettoNet helps you see censored websites by adding their names to a file on
your computer.

This initial version of GhettoNet is a "command line app".  That means that
it must be run from a prompt, as a privileged user.  If you don't know what
that means then you need more help - I can't explain everything here, but I
hope that other people will, so please search on the internet for advaice.

To see all the options available, run ghettonet.py without any arguments.

Requires Python 2.4 or later.


File Format
-----------

GhettoNet data can be embedded in files a variety of formats.  A valid data
block is detected by:
o  splitting into lines based on (optional) carriage return and newline.
o  looking for the begin line
o  reading all data lines until the (optional) end line or bad data

The EOL expression below is used to split lines:
>>> EOL.split('a\\nb\\r\\nc')
['a', 'b', 'c']


More than one data block may be present in a file.  The encoding is assumed to
be whatever Python detects as the "system" encoding, unless otherwise
specified.

A valid begin line looks like this:
### BEGIN GHETTONET
More exactly, see the BEGIN regular expression below, with the tests:
>>> bool(BEGIN.match('### BEGIN GHETTONET'))
True
>>> bool(BEGIN.match('##beginghettonet'))
True

A valid end line looks like:
### END GHETTONET
or see the END regular expression below, with tests:
>>> bool(END.match('### END GHETTONET'))
True
>>> bool(END.match('##endghettonet'))
True


A valid data line is one of:
o  a comment, prefixed by #
o  a blank line
o  a date (simplified ISO 8601: yyyy-mm-dd hh:mm:ss) prefixed by ## DATE
o  a valid IPv4 line (only, currently) for a hosts file 
Any other data are taken to indicate the end of the block (if these don't
match the end line then a warning is given; if we are parsing hosts then
we refuse to continue).

The DATE regular expression matches dates:
>>> bool(DATE.match('## DATE 1967-05-19'))
True
>>> bool(DATE.match('## DATE 1967-05-19 10:12'))
True
>>> bool(DATE.match('## DATE 1967-05-19 10:12:45'))
True
>>> bool(DATE.match('### DATE 1967-05-19 10:12:45 - future expansion'))
True
>>> bool(DATE.match('## DATE 1967-05-19bad'))
False
>>> bool(POSSIBLE_DATE.match('## DATE 1967-05-19bad')) # used to warn user
True


The aim above is to define something that is easy for people to generate and
send, and which can be stored directly in the hosts file, but which has a 
low probability of causing errors.

The date indicates when the information was known and is used to prioritise
conflicting entries, if present (most recent date wins).


Here is a complete example of a GhettoNet file:

  ### BEGIN GHETTONET

  # wikileaks.ch from DNS
  ## DATE 2010-12-4
  213.251.145.96    www.wikileaks.org wikileaks.org

  ### END GHETTONET

Note that indentation and blank lines are optional, as are the comment and 
date.

The most important part of this program is the file format.  Please write new
clients or design new ways of spreading this data - this is very much a proof
of concept (and, I hope, a librray others can build on).


Licence
-------

This code is placed into the public domain.  You can do whatever you want with
it, but it comes with no warranty or guarantee.
'''


from datetime import datetime
from doctest import testmod
from optparse import OptionParser
from os import linesep, environ, remove, rename
from os.path import exists, isfile
from platform import system
from re import compile as compile_
from sys import stdout, stderr, stdin, exc_info
from urllib import urlretrieve


__VERSION__ = '0.0'

EOL = compile_(r'\r?\n')

# these match entire lines
BEGIN = compile_(r'(?i)^\s*#{2,}\s*BEGIN\s*GHETTONET')
END = compile_(r'(?i)^\s*#{2,}\s*END\s*GHETTONET')
DATE = compile_(r'(?i)^\s*#{2,}\s*DATE\s*(?P<year>\d{4})-(?P<month>\d\d?)-(?P<day>\d\d?)(\s+(?P<hour>\d\d?):(?P<min>\d\d?)(:(?P<sec>\d\d?))?)?(\s+(?P<extra>.*))?$')
POSSIBLE_DATE = compile_(r'(?i)^\s*#{2,}\s*DATE')
COMMENT_OR_BLANK = compile_(r'^\s*(?:#.*)?$')

# these match fragments of a line
IPV4 = compile_(r'^\s*(\d{1,3}.\d{1,3}.\d{1,3}.\d{1,3})(.*)')
# this attempts to drop embedded HTML to help pull from web pages
NAME = compile_(r'^\s*(?:<[^>]+>\s*)?(\w+(?:\.\w+)*)\s*(?:<[^>]+>\s*)?(.*)')

# default paths for hosts file, by platform (please extend/correct)
DEFAULT_HOSTS = {'Windows': environ.get('SystemRoot', 'C:') + '\system32\drivers\etc\hosts',
                 'Linux': '/etc/hosts',
                 'Darwin': '/private/etc/hosts'}


def build_parser():
    '''
    Construct the command line parser.  We use optparse rather than argparse
    so that people with Python before 2.7 can use the script.
    '''
    parser = OptionParser('''

  %prog [options]

GhettoNet manages IPv4/DNS data in a format compatible with hosts files.

The format can be easily embedded in files, emails and web pages:

  ### BEGIN GHETTONET
  213.251.145.96    www.wikileaks.org wikileaks.org
  ### END GHETTONET

By default, all inputs are combined and written to stdout.  Inputs are
taken from the local hosts file, any files specified with '-i', and any
URLs specified with '-u'.

If the -w option is given then hosts is written to instead.


Examples:

  To update your hosts file from the file 'new-addresses.txt'
    %prog -w -i new-addresses.txt

  To update hosts from a URL
    %prog -w -u http://example.com/ghettonet.html

  To display ghettonet entries in your hosts file
    %prog

  To remove all ghettonet entries from your hosts file
    %prog -w -x

  To update hosts file from a web page:
    %prog -w -u https://github.com/ghettonet/GhettoNet
''', version=__VERSION__)
    parser.add_option('-i', '--input', action='append', type='string',
                      dest='inputs', metavar='FILE', default=[],
                      help='read input from FILE')
    parser.add_option('-p', '--path', action='store', type='string',
                      dest='path', metavar='PATH', default=None,
                      help='path to hosts file')
    parser.add_option('-q', '--quiet', action='store_true', default=False,
                      dest='quiet', help='suppress messages')
    parser.add_option('-s', '--stdin', action='store_true', default=False,
                      dest='stdin', help='read input from stdin')
    parser.add_option('-t', '--test', action='store_true', default=False,
                      dest='doctests', help='run doctests')
    parser.add_option('-u', '--url', action='append', type='string',
                      dest='urls', metavar='URL', default=[],
                      help='read input from FILE')
    parser.add_option('-w', '--write', action='store_true', default=False,
                      dest='write', help='write to the hosts file')
    parser.add_option('-x', '--exclude', action='store_true', default=False,
                      dest='exclude', help='exclude the hosts file from input')
    return parser


class ParseException(Exception):
    pass


class Entry(object):
    '''
    An entry, combining an IPv4 address, some names, a possible date,
    and additional comments.
    '''
    
    def __init__(self, ipv4=None, names=None, date=None, date_extra=None, 
                 comments=None):
        if names is None: names = []
        if comments is None: comments = []
        self.ipv4 = ipv4
        self.names = names
        self.date = date
        self.date_extra = date_extra
        self.comments = comments

    @classmethod
    def from_lines(cls, lines):
        '''
        Create a single object from a set of lines, as extracted by parse().
        '''
        entry = cls()
        for line in lines:
            if POSSIBLE_DATE.match(line) and not entry.date:
                entry.set_date(line)
            elif COMMENT_OR_BLANK.match(line):
                entry.comments.append(line)
            else:
                entry.set_address(line)
        if not entry.ipv4:
            raise ParseException('No IPv4 address in%s%s' %
                                 (linesep, linesep.join(lines)))
        if not entry.names:
            raise ParseException('No names in%s%s' %
                                 (linesep, linesep.join(lines)))
        return entry

    def set_date(self, line):
        '''
        Parse date from the given line.  See DATE for the regular expression
        accepted.  We parse by hand because Python 2.4 didn't have strptime.

        >>> Entry().set_date('## DATE 2010-12-04').format_date()
        ['## DATE 2010-12-04 00:00:00']
        >>> Entry().set_date('## DATE 2010-12-04 17:44').format_date()
        ['## DATE 2010-12-04 17:44:00']
        >>> Entry().set_date('## DATE 2010-12-04 00:00:00 extra').format_date()
        ['## DATE 2010-12-04 00:00:00 extra']
        '''
        if self.date:
            raise ParseException('Duplicate date: %s' % line)
        match = DATE.match(line)
        if not match:
            raise ParseException('Bad date: %s' % line)
        try:
            data = match.groupdict()
            for (name, value) in \
                    [('hour', '0'), ('min', '0'), ('sec', '0'), ('extra', '')]:
                if name not in data or data[name] is None:
                    data[name] = value
            for name in data.keys():
                if name not in ('tz', 'extra'):
                    data[name] = int(data[name])
            self.date = datetime(data['year'], data['month'], data['day'],
                                 data['hour'], data['min'], data['sec'],
                                 tzinfo=None)
            self.date_extra = data['extra']
            return self # allow chaining
        except:
            raise ParseException('Could not parse date: %s (%s)' % 
                                 (line, exc_info()[1]))
    
    def format_date(self):
        '''
        Returns a list containing at most one line, with the formatted date
        '''
        if self.date:
            line = '## DATE ' + self.date.isoformat(' ')
            if self.date_extra:
                line = line + ' ' + self.date_extra
            return [line]
        else:
            return []

    def set_address(self, line):
        '''
        Parse the IPv4 address and associated names from the given line.
        
        >>> Entry().set_address('1.2.3.4 a.b.c p.q').format_address()
        ['1.2.3.4    p.q a.b.c']
        >>> Entry().set_address('1.2.3.4 <a href="">p.q</a>').format_address()
        ['1.2.3.4    p.q']
        '''
        try:
            match = IPV4.match(line)
            (self.ipv4, rest) = match.groups()
            while rest:
                match = NAME.match(rest)
                (name, rest) = match.groups()
                self.names.append(name.lower())
            return self # allow chaining
        except:
            raise ParseException('Could not parse addresses: %s (%s)' % 
                                 (line, exc_info()[1]))

    def format_address(self):
        '''
        Returns a list containing a single line, with the formatted date
        '''
        names = list(self.names)
        names.sort(key=lambda n: len(n))
        return ['%s    %s' % (self.ipv4, ' '.join(names))]

    def format_comments(self):
        '''
        Strip leading blank lines, since they are added on writing.
        '''
        comments = list(self.comments)
        while comments and not comments[0].strip():
            comments = comments[1:]
        return comments

    def __str__(self):
        '''
        In the GhettoNet format.
        '''
        return linesep.join(self.format_comments() + self.format_date() + 
                            self.format_address())

    def __repr__(self):
        '''
        Compact display fro debuging.
        '''
        return '<Entry %s:%s %s %s>' % (self.ipv4, ';'.join(self.names),
                                        self.format_date(), self.comments)

    def single_name(self, name):
        '''
        Return an entry with a single name (we can re-use this instance if
        this entry only has one name).
        '''
        assert name in self.names
        if len(self.names) == 1:
            return self
        else:
            self.names = filter(lambda n: n != name, self.names)
            clone = Entry(ipv4=self.ipv4, names=[name], date=self.date, 
                          date_extra=self.date_extra, comments=self.comments)
            return clone


def parse(contents, quiet=True, fragile=False):
    '''
    Parse lines of input, generating a sequence of (True, entry) or 
    (False, lines) pairs.

    >>> list(parse(['a', 'b']))
    [(False, ['a', 'b'])]
    >>> list(parse(['### BEGIN GHETTONET',
    ...             '# comment',
    ...             '',
    ...             '## DATE 2010-12-04',
    ...             '127.0.0.1 localhost',
    ...             '### END GHETTONET']))
    [(True, <Entry 127.0.0.1:localhost ['## DATE 2010-12-04 00:00:00'] ['# comment', '']>)]
    '''

    in_text, lines = True, []

    def discard():
        if ''.join(lines):
            if fragile:
                raise ParseException('Unexpected text:%s%s' %
                                     (linesep, linesep.join(lines)))
            elif not quiet:
                print >> stderr, 'Ignoring text:%s%s' % \
                                     (linesep, linesep.join(lines))

    for line in contents:
        line = line.strip()
        lines.append(line)
        if in_text:
            if BEGIN.match(line):
                lines.pop() # drop begin
                if lines:
                    yield (False, lines)
                in_text, lines = False, []
        else:
            if END.match(line):
                lines.pop() # drop end
                discard()
                in_text, lines = True, []
            elif not COMMENT_OR_BLANK.match(line):
                try:
                    yield (True, Entry.from_lines(lines))
                except ParseException:
                    discard()
                lines = []
    if in_text:
        if lines:
            yield (False, lines)
    else:
        discard()
        if fragile:
            raise ParseException('Missing END GHETTONET')
        if not quiet:
            print >> stderr, 'Missing END GHETTONET'


def merge(entries, quiet=True, merge_names=None):
    '''
    Combine entries so that addresses are not duplicated.

    Setting merge_names allows merging logic to be modified.  The default uses
    dates, then combines everything with the same IPv4, and finally
    discards duplicates or fails (if quiet=True).

    Any merge_names function takes two arguments (entries, quiet), where all
    entries have a single, identical name, and should return a list of 
    merged entries.
    '''
    if merge_names is None:
        merge_names = [merge_by_date, merge_same_ipv4, merge_force]
    # first, split into separate entries for each name
    by_name = {}
    for entry in entries:
        for name in entry.names:
            # drop localhost and ipv6 names - going to cause problems and 
            # shouldn't ever be there
            if 'localhost' in name or name.startswith('ipv6-'):
                if not quiet:
                    print >> stderr, 'Skipping %s' % name
            else:
                if name not in by_name:
                    by_name[name] = []
                by_name[name].append(entry.single_name(name))
    # next, try to reduce to a single entry
    for name in by_name.keys():
        for merge in merge_names:
            if len(by_name[name]) > 1:
                by_name[name] = merge(by_name[name], quiet)
        if len(by_name[name]) > 1:
            raise Exception('Multiple entries for %s' % name)
    # finally, combine by IPv4
    by_ipv4 = {}
    for name in by_name.keys():
        entry = by_name[name][0]
        if entry.ipv4 not in by_ipv4:
            by_ipv4[entry.ipv4] = entry
        else:
            combine_comments(by_ipv4[entry.ipv4], entry)
            by_ipv4[entry.ipv4].names.append(name)
    return by_ipv4.values()
                
                
def merge_by_date(entries, quiet=True):
    '''
    Merge entries so that the most recent date wins.

    >>> merge_by_date([Entry(date=datetime(2009,1,1), names=['x']),
    ...                Entry(date=datetime(2010,1,1), names=['x'])])
    [<Entry None:x ['## DATE 2010-01-01 00:00:00'] []>]
    >>> merge_by_date([Entry(date=datetime(2010,1,1), names=['x']),
    ...                Entry(date=datetime(2009,1,1), names=['x'])])
    [<Entry None:x ['## DATE 2010-01-01 00:00:00'] []>]
    >>> merge_by_date([Entry(date=datetime(2010,1,1), names=['x']),
    ...                Entry(date=datetime(2010,1,1), names=['x'])])
    [<Entry None:x ['## DATE 2010-01-01 00:00:00'] []>, <Entry None:x ['## DATE 2010-01-01 00:00:00'] []>]
    '''
    if entries:
        assert reduce(lambda same, e: same and len(e.names) == 1,
                      entries, True), 'Multiple names'
    else:
        return entries
    with_dates = filter(lambda e: e.date != None, entries)
    if not with_dates:
        return entries
    with_dates.sort(key=lambda e: e.date, reverse=True)
    with_dates = filter(lambda e: e.date == with_dates[0].date, with_dates)
    if not quiet:
        n = len(entries) - len(with_dates)
        if n == 1:
            noun = 'entry'
        else:
            noun = 'entries'
        print >> stderr, 'Discarded %d old %s for %s' % \
            (n, noun, with_dates[0].names[0])
    return with_dates


def merge_same_ipv4(entries, quiet=True):
    '''
    Merge entries (all with identical dates) by ipv4 address.

    >>> merge_same_ipv4([Entry(ipv4='1.2', names=['x']), 
    ...                  Entry(ipv4='1.3', names=['x'])])
    [<Entry 1.2:x [] []>, <Entry 1.3:x [] []>]
    >>> merge_same_ipv4([Entry(ipv4='1.2', names=['x']), 
    ...                  Entry(ipv4='1.2', names=['x'])])
    [<Entry 1.2:x [] []>]
    >>> merge_same_ipv4([Entry(ipv4='1.2', names=['x'], comments=['a', 'b']), 
    ...                  Entry(ipv4='1.2', names=['x'], comments=['a', 'c'])])
    [<Entry 1.2:x [] ['a', 'b', 'c']>]
    >>> merge_same_ipv4([Entry(ipv4='1.2', names=['x'], comments=['a', 'b']), 
    ...                  Entry(ipv4='1.2', names=['x'], comments=['#a', 'c'])])
    [<Entry 1.2:x [] ['a', 'b', 'c']>]
    '''
    if entries:
        assert reduce(lambda same, e: same and len(e.names) == 1,
                      entries, True), 'Multiple names'
        assert reduce(lambda same, e: same and e.date == entries[0].date,
                      entries, True), 'Dates vary'
    else:
        return entries
    entries.sort(key=lambda e: e.ipv4)
    def groups():
        ipv4, group = entries[0].ipv4, []
        for entry in entries:
            if ipv4 != entry.ipv4:
                yield group
                ipv4, group = entry.ipv4, [entry]
            else:
                group.append(entry)
        yield group
    def combine():
        for group in groups():
            merged = group[0]
            known_comments = set(map(strip, merged.comments))
            for other in group[1:]:
                combine_comments(merged, other, known_comments)
            if not quiet and len(group) > 1:
                print >> stderr, 'Merged %d entries with IPv4 %s for %s' % \
                    (len(group) - 1, merged.ipv4, merged.names[0])
            yield merged
    return list(combine())


def strip(comment):
    '''
    Remove all excess text and prefixes from a comment.

    >>> strip('a b')
    'a b'
    >>> strip('##  a b  ')
    'a b'
    >>> strip(' ## # a b  ')
    'a b'
    >>> strip(' ##    ')
    ''
    '''
    comment = comment.strip()
    while comment.startswith('#') or comment.startswith(' '):
        comment = comment[1:]
    return comment


def combine_comments(merged, other, known_comments=None):
    '''
    Copy non-duplicate comments from other to merged.
    >>> combine_comments(Entry(comments=['a', 'b']),
    ...                  Entry(comments=['a', 'c']))
    <Entry None: [] ['a', 'b', 'c']>
    '''
    if known_comments is None:
        known_comments = set(map(strip, merged.comments))
    for comment in other.comments:
        stripped = strip(comment)
        if stripped not in known_comments:
            known_comments.add(stripped)
            merged.comments.append(comment)
    return merged


def merge_force(entries, quiet=True):
    '''
    Force entries to agree by marking some as duplicates.

    >>> merge_force([Entry(ipv4='1.2', names=['x'], comments=['a', 'b']), 
    ...              Entry(ipv4='1.3', names=['x'], comments=['a', 'c'])])
    Traceback (most recent call last):
    Exception: Conflicting IPv4 addresses (1.2,1.3) for x
    >>> merge_force([Entry(ipv4='1.2', names=['x'], comments=['a', 'b']), 
    ...              Entry(ipv4='1.3', names=['x'], comments=['a', 'c'])], 
    ...             quiet=False)
    [<Entry 1.2:x [] ['a', 'b', 'c', '## CONFLICT: 1.3']>]
    '''
    if entries:
        assert reduce(lambda same, e: same and len(e.names) == 1,
                      entries, True), 'Multiple names'
        assert reduce(lambda same, e: same and e.date == entries[0].date,
                      entries, True), 'Dates vary'
        assert len(set(map(lambda e: e.ipv4, entries))) == len(entries), \
            'IPv4 are not all distinct'
    else:
        return entries
    merged = entries[0]
    # if being used silently, fail
    if quiet:
        raise Exception('Conflicting IPv4 addresses (%s) for %s' % \
            (','.join(map(lambda e: e.ipv4, entries)), merged.names[0]))
    known_comments = set(map(strip, merged.comments))
    for other in entries[1:]:
        print >> stderr, 'WARNING: Discarding %s as conflict for %s' % \
            (other.ipv4, merged.names[0])
        combine_comments(merged, other, known_comments)
        merged.comments.append('## CONFLICT: %s' % other.ipv4)
    return [merged]
    

def note_access(source, quiet=True, write=False):
    if not quiet:
        if write:
            action = 'Writing to'
        else:
            action = 'Reading from'
        print >> stderr, '%s %s' % (action, source)


def get_hosts_path(path=None):
    '''
    Try to work out where the hosts file is located.
    '''
    if path is None:
        path = DEFAULT_HOSTS.get(system())
    if path is None:
        raise Exception('Hosts location unknown for %s, please use -p option'
                        % system())
    if not exists(path) or not isfile(path):
        raise Exception('Hosts not at %s, please use -p option' % path)
    return path
        

def open_hosts(path=None, mode='r', quiet=True):
    path = get_hosts_path(path)
    note_access(path, quiet, 'w' in mode)
    return open(path, mode)


def split(open_file):
    '''
    It is important that this reads the entire file eagerly as the file
    is closed after being called.
    '''
    return EOL.split(open_file.read())


def pull_urls(urls, quiet=True):
    for url in urls:
        note_access(url, quiet)
        (path, headers) = urlretrieve(url)
        yield path
        remove(path)


def read_all(options):
    '''
    Provide an iterator over all inputs, according to the options.
    Note that we avoid "finally" to close files (and "with"), for backwards
    compatability, at the risk of leaving files open (not an issue in normal
    use, but libraries may want to re-implement).
    '''
    if not options.exclude:
        hosts = open_hosts(path=options.path, quiet=options.quiet)
        for (ok, entry) in parse(split(hosts), quiet=options.quiet, 
                                 fragile=True):
            if ok:
                yield entry
        hosts.close()
    for path in options.inputs:
        note_access(path, options.quiet)
        source = open(path)
        for (ok, entry) in parse(split(source), quiet=options.quiet):
            if ok:
                yield entry
        source.close()
    for path in pull_urls(options.urls):
        source = open(path)
        for (ok, entry) in parse(split(source), quiet=options.quiet):
            if ok:
                yield entry
        source.close()
    if options.stdin:
        note_access('the command line (stdin)', options.quiet)
        for (ok, entry) in parse(split(stdin), quiet=options.quiet):
            if ok:
                yield entry
        

def write(out, entries):
    print >> out, '### BEGIN GHETTONET'
    print >> out
    for entry in entries:
        print >> out, str(entry)
        print >> out
    print >> out, '### END GHETTONET'


def read_existing(path):
    note_access(path, options.quiet)
    source = open(path)
    for (skip, lines) in parse(split(source), quiet=options.quiet):
        if not skip:
            for line in lines:
                yield line
    source.close()


def update_hosts(options, entries):
    '''
    Store non-GhettoNet data from the existing file, rename it to a 
    backup, then write the new data (non-GhettoNet followed by merged
    entries).
    '''
    path = get_hosts_path(path=options.path)
    existing = list(read_existing(path)) # force read and close
    count = 0
    while (exists('%s.%d' % (path, count))): count = count + 1
    backup = '%s.%d' % (path, count)
    if not options.quiet:
        print >> stderr, 'Copying %s to %s' % (path, backup)
    try:
        rename(path, backup)
    except:
        raise Exception('The existing hosts file could not be renamed.  '
                        'You need to run this program with system rights.  '
                        'If you do not understand this, DO NOT USE.')
    note_access(path, options.quiet, write=True)
    hosts = open(path, 'w')
    for line in existing:
        print >> hosts, line
    print >> hosts
    write(hosts, entries)
    hosts.close()


if __name__ == '__main__':
    parser = build_parser()
    (options, args) = parser.parse_args()
    if options.doctests:
        testmod(verbose=True)
    elif args:
        parser.error('Missing option flag (do you need to include -i?)')
    elif options.write:
        update_hosts(options, merge(read_all(options), options.quiet))
    else:
        write(stdout, merge(read_all(options), options.quiet))
