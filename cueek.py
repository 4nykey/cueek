#!/usr/bin/python
import sys
import os
import re

DFLT_CFG="""
# these below are available for filename generation and tagging:
#   metadata fields: albumartist, artist, album, title, tracknumber
#   translation modes: lower, upper, swapcase, capitalize, title

[filenames]
mult_files:     %tracknumber% - %title%
mult_files_va:  %tracknumber% - %artist% - %title%
single_file:    %albumartist% - %album%
translate:      lower

[tags]
fields_skip:    replaygain_album_gain, replaygain_album_peak, replaygain_track_gain, replaygain_track_peak
fields_notran:  discid, cuesheet
translate:      title

# encoders and decoders
# decoders must be able to write to stdout, encoders - read from stdin
#   [extension]
#   decode: <commandline>   where '%f' is input file
#   encode: <commandline>   where '%f' is output file
#   rg: <commandline>       format-specific replay-gain scanner

[flac]
decode: flac -dc %f
encode: flac -f -o %f -
rg:     metaflac --add-replay-gain %f

[wv]
decode: wvunpack -o - %f
encode: wavpack -myi -o %f -
rg:     wvgain -a %f

[ape]
decode: mac %f - -d

[play]
encode: aplay -
"""
exit_str = '\nFinished succesfully\n'

class Argv:
    def __init__(self):
        from optparse import OptionParser
        opt_parse = OptionParser()

        opt_parse.add_option("-v", "--verbose",
            action="store_false", dest="quiet", default=True,
            help="print status messages to stderr")
        opt_parse.add_option("-m", "--charmap",
            help="decode cuesheet from specified CHARMAP", metavar="CHARMAP")
        opt_parse.add_option("-o", "--output",
            help="output resulting cuesheet to the FILE, instead of printing "
            "to stdout", metavar="FILE")
        opt_parse.add_option("-c", "--compliant",
            action="store_false", dest="noncompliant", default=True,
            help="output to 'compliant' cuesheet")
        opt_parse.add_option("-0", "--zero-track",
            action="store_false", dest="notrackzero", default=True,
            help="when splitting to 'non-compliant' cue, write contents of "
            "the first track pre-gap to a file with tracknumber 00")
        opt_parse.add_option("-w", "--write",
            action="store_false", dest="nowrite", default=True,
            help='additionally write splitted/merged audio files')
        opt_parse.add_option("-e", "--encode",
            help="encode audio files to specified FORMAT(s) (use comma as "
            "separator)", metavar="FORMAT")
        opt_parse.add_option("-t", "--tracks",
            help="write only tracks with specified NUMBER(s) (use comma as "
            "separator, dash for setting ranges)", metavar="NUMBER")
        opt_parse.add_option("-r", "--replay-gain",
            action="store_false", dest="norg", default=True,
            help="apply replay gain to encoded file(s)")
        opt_parse.add_option("-d", "--delete-files",
            action="store_false", dest="nodelete", default=True,
            help="delete source files after encoding")

        opt_parse.set_usage('%prog [options] <in.cue>')

        opt_parse.set_description(
            "This script converts a cuesheet to another type. If input cue is "
            "of 'single-file' type (i.e CD image), it will be converted "
            "('splitted') to a 'multiple-files' one. Referenced audio file can "
            "be splitted accordingly. "
            "Vice versa, a 'multiple-files' cue will be converted ('merged') to"
            " a 'single-file' one, while optionaly merging referenced files. "
            "Configuration is read from ~/.cueekrc file, it will be created on "
            "the first run and is needed for running this script.")

        (self.options, self.args) = opt_parse.parse_args()

        if len(self.args) != 1:
            opt_parse.error('Please specify the cuesheet to process')

        if not self.options.noncompliant:
            self.options.notrackzero = True

        if self.options.encode:
            self.formats=self.options.encode.split(',')
        else:
            self.formats=['wav']
        self.format = self.formats[0]

        self.tracks = []
        if self.options.tracks:
            for x in self.options.tracks.split(','):
                t = [int(y) for y in x.split('-')]
                for z in xrange(t[0], t[-1]+1):
                    self.tracks.append(z)
        self.tracks.sort()

class Config:
    def __init__(self):
        from ConfigParser import ConfigParser, NoSectionError, NoOptionError
        self.cfg_parse = ConfigParser()
        (self.nosect, self.noopt) = (NoSectionError, NoOptionError)
        io_.fname = os.path.expanduser('~/.cueekrc')
        if not os.path.isfile(io_.fname): # write config file on first run
            cfg_file = io_.tryfile('w')
            cfg_file.write(DFLT_CFG)
            cfg_file.close()
        cfg_file = io_.tryfile()
        self.cfg_parse.readfp(cfg_file)
        self.section = ''
        self.case_conv = ['capitalize', 'lower', 'swapcase', 'title', 'upper']
    def read(self, e, supress=0):
        result = ''
        try:
            result = self.cfg_parse.get(self.section, e)
        except (self.nosect, self.noopt), err:
            if not supress:
                exit('Config file: "%s": %s\n' % (io_.fname, err), 1)
        return result
    def get_cmdline(self, action, fname):
        cmd = self.read(action).split()
        try:
            pos = cmd.index('%f')
            cmd = cmd[:pos] + fname + cmd[pos+1:]
        except ValueError:
            pass
        return cmd
    def scheme(self, t, e):
        self.section = 'filenames'
        sch = ''
        for s in self.read(e).split('%'):
            if s in ('artist', 'title'):
                sch += meta_.add_missing(s, t)
            elif s == 'tracknumber':
                sch += str(t).zfill(2)
            elif s == 'albumartist':
                sch += meta_.get('artist')
            elif s == 'album':
                sch += meta_.get('title')
            else:
                sch += s
        if self.read('translate', 1) in self.case_conv:
            sch = repr(sch) + '.' + self.read('translate') + '()'
            sch = eval(sch)
        return sch
    def str2list(self, s):
        list = []
        if self.read(s, 1):
            list = [x.strip() for x in self.read(s).upper().split(',')]
        return list

class Strings:
    def __init__(self):
        self.msfstr = '\d{1,2}:\d\d:\d\d'
    def pollute(self, s, override=0):
        if not argv_.options.quiet or override:
            if isinstance(s, unicode): s = s.encode(encoding)
            sys.stderr.write(s)
            sys.stderr.flush()
    def getlength(self, n):
        ms, fr = divmod(n, aud_.smpl_freq)
        m, s = divmod(ms, 60)
        f = fr / (aud_.smpl_freq / 75)
        s = ':'.join([str(x).zfill(2) for x in m,s,f])
        return s
    def getidx(self, s):
        mm, ss, ff = [int(x[-2:]) for x in s.strip().split(':')]
        idx = ((mm * 60 + ss) * aud_.smpl_freq + ff * (aud_.smpl_freq / 75))
        return idx
    def linehas(self, n, s):
        result = 0
        if re.search(n+'\s+'+self.msfstr, s, re.I): result = 1
        return result
    def repl_time(self, n, s):
        return re.sub(self.msfstr, self.getlength(n), s)

class Meta:
    def __init__(self):
        from mutagen import File, musepack, mp3, id3
        (self.mutagen, self.mpc, self.mp3, self.id3) = (File,
            musepack.Musepack, mp3.MP3, id3)
        self.id3tr = {'ARTIST': 'TPE1', 'ALBUM': 'TALB', 'TITLE': 'TIT2',
            'TRACKNUMBER': 'TRCK', 'DATE': 'TDRC', 'DISCNUMBER': 'TPOS',
            'GENRE': 'TCON', 'COMMENT': 'COMM'}
        self.id3fr = []
        for (name, frame) in self.id3.Frames.items(): self.id3fr.append(name)
        self.data = {'albumartist': 'unknown', 'albumtitle': 'untitled'}
        cfg_.section = 'tags'
        self.tags_omit = cfg_.str2list('fields_skip')
        self.tags_dontranslate = cfg_.str2list('fields_notran')
        self.translate = ''
        if cfg_.read('translate', 1) in cfg_.case_conv:
            self.translate = '.' + cfg_.read('translate') + '()'
    def put(self, entry, val, tn='album'):
        if isinstance(tn, int): tn = str(tn).zfill(2)
        entry = tn + entry
        self.data[entry] = val
    def get(self, entry, tn='album'):
        if isinstance(tn, int): tn = str(tn).zfill(2)
        entry = tn + entry
        val = self.data.get(entry)
        if not val: val = 0
        return val
    def add_missing(self, entry, tn):
        result = 'untitled'
        if not self.get(entry, tn):
            if entry == 'artist': result = self.get(entry)
        else:
            result = self.get(entry, tn)
        return result
    def tag(self, n = 0):
        cfg_.section = 'tags'
        (f, ismpc, ismp3) = 3 * (None,)
        if os.path.isfile(io_.fname): f = self.mutagen(io_.fname)
        if hasattr(f, 'info'):
            tags = {}
            if isinstance(f, self.mpc): ismpc = 1
            elif isinstance(f, self.mp3): ismp3 = 1
            # collect tags
            if cue_.is_va:
                tags['ALBUMARTIST'] = self.get('artist')
            tags['ARTIST'] =  self.add_missing('artist', n)
            tags['ALBUM'] =  self.get('title')
            if meta_.get('comment'):
                for x in meta_.get('comment'): tags[x[0]] = x[1]
            if cue_.is_singlefile:
                tags['TITLE'] =  self.add_missing('title', n)
                tags['TRACKNUMBER'] =  str(n)
                if meta_.get('comment', n):
                    for x in meta_.get('comment', n): tags[x[0]] = x[1]
            else:
                if not argv_.options.tracks:
                    tags['CUESHEET'] =  ''.join(cue_.sheet)
            if ismpc:
                tags['TRACK'] = tags['TRACKNUMBER']
                if tags.has_key('DATE'): tags['YEAR'] = tags['DATE']
            if ismp3:
                fn = f.filename
                try: f = self.id3.ID3(fn)
                except self.id3.ID3NoHeaderError: f = self.id3.ID3()
            # convert case if requested and write to file
            for (key, val) in tags.iteritems():
                if key not in self.tags_omit:
                    if self.translate and key not in self.tags_dontranslate:
                        val = eval(repr(val) + self.translate)
                    if ismp3: # taken from mid3v2
                        if self.id3tr.has_key(key): key = self.id3tr[key]
                        if key in self.id3fr:
                            if key == 'COMM':
                                fr = self.id3.COMM(encoding=3, text=val,
                                    lang='eng', desc='')
                            else:
                                fr = self.id3.Frames[key](encoding=3, text=val)
                        else:
                            fr = self.id3.TXXX(encoding=3, text=val, desc=key)
                        f.add(fr)
                    else:
                        if ismpc: key = key.title()
                        f[key] = val
            if ismp3: f.save(fn)
            else: f.save()
    def filename(self, t):
        if not cue_.is_singlefile:
            s = 'single_file'
        elif cue_.is_va:
            s = 'mult_files_va'
        else:
            s = 'mult_files'
        f = re.sub('[*":/\\\?]', '_', cfg_.scheme(t, s)) + '.' + argv_.format
        return f

class IO:
    def __init__(self):
        from wave import Wave_read
        self.wavrd = Wave_read
        (self.fname, self.rdcmd, self.wrcmd) = 3 * ('', )
    def tryfile(self, mode='r'):
        try:
            f = open(self.fname, mode)
        except IOError, err:
            errstr = 'Failed to open "%s": %s\n' % (err.filename, err.strerror)
            exit(errstr, 1)
        return f
    def wav_rd(self):
        fn = self.fname
        ext = fn.split('.')[-1].lower()
        cfg_.section = ext.encode(encoding)
        if ext == 'wav':
            r = self.tryfile('rb')
        elif cfg_.read('decode'):
            self.rdcmd = cfg_.get_cmdline('decode', [fn])
            subp_.exec_child()
            r = subp_.rdproc.stdout
        try:
            r = self.wavrd(r)
        except EOFError:
            subp_.wait_for_child()
            exit(errstr, 1)
        return r
    def wav_wr(self):
        cfg_.section = argv_.format
        tag_str = ''
        if argv_.format == 'wav':
            w = self.tryfile('wb')
        elif cfg_.read('encode'):
            self.wrcmd = cfg_.get_cmdline('encode', [self.fname])
            subp_.exec_child('wr')
            w = subp_.wrproc.stdin
        return w

class Audio:
    def __init__(self):
        from struct import pack
        self.pack = pack
        from wave import WAVE_FORMAT_PCM
        self.fmtpcm = WAVE_FORMAT_PCM
        (self.frnum, self.hdr_frnum) = 2 * (0,)
        (self.fin, self.fout) = 2 * (None,)
    def get_params(self):
        self.params = self.fin.getparams()
        self.smpl_freq = self.params[2]
    def gen_hdr(self): # taken from `wave' module
        par = self.params
        len = self.hdr_frnum * par[0] * par[1]
        hdr = 'RIFF' + self.pack('<l4s4slhhllhh4sl', 36 + len, 'WAVE', 'fmt ',
            16, self.fmtpcm, par[0], par[2], par[0] * par[2] * par[1],
            par[0] * par[1], par[1] * 8, 'data', len)
        return hdr
    def wr_chunks(self):
        step = self.smpl_freq * 10 # 10s chunks
        if self.hdr_frnum:
            hdr = self.gen_hdr()
            self.fout.write(hdr)
        for x in xrange(self.frnum/step):
            frames = self.fin.readframes(step)
            self.fout.write(frames)
        frames = self.fin.readframes(self.frnum%step) # leftovers
        self.fout.write(frames)
    def write(self, _if='', _of=''):
        if _of: # merging to one file
            io_.fname = _of
            self.fout = io_.wav_wr()
            # wave header with number of samples equal to sum of input files
            self.hdr_frnum = reduce(lambda x, y: x+y, files_.lgth)
            for x in xrange(len(files_.list)):
                io_.fname = files_.list[x]
                self.fin = io_.wav_rd()
                self.frnum = files_.lgth[x]

                abs_pos = 0
                if x: abs_pos = reduce(lambda x, y: x+y, files_.lgth[:x])
                statstr = '%s >> %s @ %s\n' % \
                    (io_.fname, _of, str_.getlength(abs_pos))
                str_.pollute(statstr, 1)

                self.wr_chunks()
                if self.hdr_frnum: self.hdr_frnum = 0 # write header only once
                subp_.wait_for_child()
                self.fin.close()
            self.fout.close()
            subp_.wait_for_child('wr')
            io_.fname = _of
            meta_.tag()
        elif _if: # splitting to multiple files
            io_.fname = _if
            self.fin = io_.wav_rd()
            for x in xrange(len(files_.list)):
                if x >= argv_.tracks[-1]:
                    self.fin.close()
                    exit(exit_str)
                if meta_.get('idx1', 1) and not argv_.options.notrackzero: t = x
                else: t = x + 1
                io_.fname = files_.list[x]
                if not io_.fname:
                    io_.fname = os.devnull
                    self.fout = io_.tryfile('wb')
                else:
                    self.fout = io_.wav_wr()
                self.hdr_frnum = self.frnum = files_.lgth[x]

                statstr = '%s > %s # %s\n' % \
                    (_if, io_.fname, str_.getlength(self.frnum))
                str_.pollute(statstr, 1)

                self.wr_chunks()
                self.fout.close()
                subp_.wait_for_child('wr')
                meta_.tag(t)
            self.fin.close()
            subp_.wait_for_child()

class Cue:
    def __init__(self):
        (self.pregap, self.trackzero_present, self.is_compl, self.is_noncompl, 
            self.is_singlefile, self.is_va) = 6 * (0,)
        (self.charmap, self.sheet, self.ref_file) = (encoding, [], '')
    def probe(self, fn):
        io_.fname = fn
        f = io_.tryfile()
        size = os.path.getsize(fn)
        if size >= long(16384):
            _f = meta_.mutagen(io_.fname)
            try:
                self.sheet = _f['CUESHEET'][0].splitlines(1)
                self.ref_file = io_.fname
            except (KeyError, TypeError):
                exit('Failed to probe the cuesheet', 1)
        else:
            if argv_.options.charmap:
                self.charmap = argv_.options.charmap
            else:
                try:
                    import chardet
                    _f = io_.tryfile()
                    self.charmap = chardet.detect(_f.read())['encoding']
                    _f.close()
                except ImportError:
                    pass
            self.sheet = [line.decode(self.charmap) for line in f]
        f.close()
    def dblquotes(self, s):
        """This is to allow double quotes inside PERFORMER and TITLE fields,
        so they could be used for tagging, while replacing them with single
        quotes in output"""
        list=re.split('([^"]*")(.*)("[^"]*)', s)
        m = list[2]
        list[2] = m.replace('"', "''")
        return (m, ''.join(list))
    def parse(self):
        trknum = 1
        for line in [s.lstrip() for s in self.sheet]:
            tn = 'album'
            if re.search('^PERFORMER\s+"', line, re.I):
                metadata = self.dblquotes(line)[0]
                if meta_.get('trck', 1): tn = trknum
                meta_.put('artist', metadata, tn)
            elif re.search('^TITLE\s+"', line, re.I):
                metadata = self.dblquotes(line)[0]
                if meta_.get('trck', 1): tn = trknum
                meta_.put('title', metadata, tn)
            elif re.search('^REM\s+', line, re.I):
                if meta_.get('trck', 1): tn = trknum
                metadata = []
                if meta_.get('comment', tn):
                    metadata = meta_.get('comment', tn)
                spl = line.split()
                key, val = spl[1].upper(), ' '.join(spl[2:]).strip('"')
                metadata.append([str(key), val])
                meta_.put('comment', metadata, tn)
            elif re.search('^FILE\s+"', line, re.I):
                ref_file = line.split('"')[1]

                if self.ref_file:
                    ref_file = self.ref_file
                io_.fname = ref_file
                aud_.fin = io_.wav_rd()
                aud_.get_params()
                meta_.put('wpar', aud_.params, trknum)
                aud_.fin.close()
                try:
                    subp_.rdproc.stdout.close()
                    os.remove(subp_.rdlog)
                except (AttributeError, TypeError):
                    pass

                framenum = aud_.params[3]
                if not meta_.get('trck', 1):
                    for x in 0, 1:
                        meta_.put('name', ref_file, x)
                        meta_.put('lgth', framenum, x)
                else:
                    meta_.put('name', ref_file, trknum)
                    meta_.put('lgth', framenum, trknum)
                if meta_.get('lgth', 0) != meta_.get('lgth', 1) \
                and trknum == 1: # track zero
                    self.trackzero_present = 1
                    abs_pos = meta_.get('lgth', 0)
                    meta_.put('apos', abs_pos, 0)
                abs_pos = meta_.get('apos', trknum-1) + framenum
                meta_.put('apos', abs_pos, trknum)
            elif re.search('^TRACK\s+', line, re.I):
                meta_.put('trck', 1, trknum)
            elif str_.linehas('^PREGAP\s+', line):
                self.pregap = str_.getidx(line)
            elif str_.linehas('^INDEX\s+00', line):
                idx_pos = str_.getidx(line)
                meta_.put('idx0', idx_pos, trknum)
            elif str_.linehas('^INDEX\s+01', line):
                idx_pos = str_.getidx(line)
                meta_.put('idx1', idx_pos, trknum)
                trknum += 1
        if not meta_.get('lgth', 1):
            exit('Failed to get the length of referenced file', 1)
        if not self.trackzero_present:
            del meta_.data['00lgth']
        meta_.put('numoftracks', trknum)
        meta_.put('duration', abs_pos)
    def type(self):
        (gaps_present, self.is_va) = 2 * (0,)
        if not meta_.get('name', 2):
            self.is_singlefile = 1
            cue_type = 'single-file'
        else:
            for x in xrange(2, meta_.get('numoftracks')):
                if meta_.get('idx0', x):
                    cue_type = 'non-compliant'
                    gaps_present = 1
                    self.is_noncompl = 1
                    break
                elif meta_.get('idx1', x):
                    cue_type = 'compliant'
                    self.is_compl = 1
                    break
            if self.is_compl ==  self.is_noncompl:
                if not gaps_present:
                    cue_type = 'gapless'
                else:
                    errstr = 'Failed to parse the cuesheet'
                    exit(errstr, 1)
        self.type = cue_type
        for x in xrange(meta_.get('numoftracks')):
            if meta_.get('artist', x) and not \
            meta_.get('artist', x) == meta_.get('artist'):
                self.is_va = 1
                break
    def modify(self):
        (trknum, gap, cue, wav_file) = (1, 0, [], '')
        abs_pos = meta_.get('duration')
        for x in xrange(len(self.sheet)):
            line = self.sheet[x].rstrip() + os.linesep
            lstr = line.lstrip()
            if re.search('^PERFORMER|TITLE', lstr, re.I):
                line = self.dblquotes(line)[1]
                cue.append(line)
            elif re.search('^FILE\s+', lstr, re.I):
                if not wav_file or self.is_singlefile:
                    if self.is_singlefile:
                        if meta_.get('idx1', trknum) and \
                        argv_.options.noncompliant and \
                        not argv_.options.notrackzero:
                            wav_file = meta_.filename(trknum-1)
                        else:
                            wav_file = meta_.filename(trknum)
                    else:
                        wav_file = meta_.filename(trknum)
                    wav_file = '"' + wav_file + '"'
                    line = re.sub('".+"', wav_file, line)
                    cue.append(line)
            elif str_.linehas('^INDEX\s+00', lstr):
                if self.is_noncompl:
                    gap = meta_.get('lgth', trknum-1) - \
                        meta_.get('idx0', trknum)
                    idx00 = meta_.get('apos', trknum-1) - gap
                    line = str_.repl_time(idx00, line)
                elif self.is_compl:
                    gap = meta_.get('idx1', trknum)
                    idx00 = meta_.get('apos', trknum-1)
                    line = str_.repl_time(idx00, line)
                elif self.is_singlefile:
                    if meta_.get('idx0', trknum) or \
                    (trknum == 1 and meta_.get('idx1', trknum)):
                        gap = meta_.get('idx1', trknum) - \
                            meta_.get('idx0', trknum)
                    if not argv_.options.noncompliant:
                        line = str_.repl_time(0, line)
                    elif trknum > 1 or not argv_.options.notrackzero:
                        trk_length = meta_.get('idx1', trknum) - \
                            meta_.get('idx1', trknum-1)
                        idx00 = trk_length - gap
                        if not (trknum == 2 and argv_.options.notrackzero):
                            line = str_.repl_time(idx00, line)
                        line += 'FILE "' + \
                            meta_.filename(trknum) + '" WAVE\n'
                meta_.put('gap', gap, trknum)
                cue.append(line)
            elif str_.linehas('^INDEX\s+01', lstr):
                if self.is_singlefile:
                    idx01 = 0
                    if trknum == 1:
                        if not argv_.options.noncompliant or \
                        (meta_.get('idx1', trknum) and \
                        argv_.options.notrackzero):
                            idx01 = meta_.get('idx1', trknum)
                    elif not argv_.options.noncompliant and \
                    meta_.get('idx0', trknum):
                        idx01 = gap
                    if meta_.get('idx1', trknum+1):
                        if not argv_.options.noncompliant or \
                        (argv_.options.noncompliant and \
                        not meta_.get('idx0', trknum+1)):
                            line += 'FILE "' + \
                                meta_.filename(trknum+1) + '" WAVE\n'
                    line = str_.repl_time(idx01, line)
                elif self.is_noncompl and trknum > 1:
                    idx01 = meta_.get('apos', trknum-1)
                    line = str_.repl_time(idx01, line)
                else:
                    idx01 = meta_.get('apos', trknum-1) + \
                        meta_.get('idx1', trknum)
                    line = str_.repl_time(idx01, line)
                cue.append(line)
                trknum += 1
                gap = 0
            else:
                cue.append(line)
        self.sheet = cue
    def lengths(self):
        abs_pos = meta_.get('duration')
        start = 1
        if self.trackzero_present: start = 0
        for trknum in xrange(start, meta_.get('numoftracks')):
            if not argv_.options.noncompliant:
                if trknum > 1 and not meta_.get('idx0', trknum):
                    start_pos = meta_.get('idx1', trknum)
                else:
                    start_pos = meta_.get('idx0', trknum)
                if not meta_.get('idx1', trknum+1):
                    end_pos = abs_pos
                elif not meta_.get('idx0', trknum+1):
                    end_pos = meta_.get('idx1', trknum+1)
                else:
                    end_pos = meta_.get('idx0', trknum+1)
            else:
                start_pos = meta_.get('idx1', trknum)
                if meta_.get('idx1', trknum+1):
                    end_pos = meta_.get('idx1', trknum+1)
                else:
                    end_pos = abs_pos
                if trknum == 1 and meta_.get('idx1', 1):
                    if argv_.options.notrackzero:
                        start_pos = 0
                    else:
                        length = meta_.get('idx1', 1)
                        meta_.put('lgth', length, 0)
            trk_length = end_pos - start_pos
            meta_.put('spos', start_pos, trknum)
            meta_.put('lgth', trk_length, trknum)
    def print_(self):
        statstr = "This cuesheet appears to be of '" + self.type
        if self.is_va:
            statstr += "', 'various artists"
        statstr += "' type" + "...\n\nCD Layout:\n\n"
        # check if we display layout for compliant cue
        # i.e. source is (or output requested as) compliant
        want_compliant = 0
        if (self.is_compl or
        (self.is_singlefile and not argv_.options.noncompliant)):
            want_compliant = 1
        for trknum in xrange(meta_.get('numoftracks')):
            (gap_str, trk_str, lgth_str) = 3 * ('',)
            if want_compliant:
                gap = meta_.get('gap', trknum)
            else:
                gap = meta_.get('gap', trknum+1)
            if meta_.get('lgth', trknum):
                real_length = meta_.get('lgth', trknum)
                length = real_length - gap
                trk_str = 'Track %s (%s)\n' % \
                    (str(trknum).zfill(2), str_.getlength(real_length))
                lgth_str = ' content: %s\n' % (str_.getlength(length))
            if self.pregap > 0 and trknum == 1:
                statstr += 'Pregap   (%s)\n' % (str_.getlength(self.pregap))
            statstr += trk_str
            if gap:
                gap_str = '     gap: %s\n' % (str_.getlength(gap))
                if want_compliant:
                    statstr += gap_str + lgth_str
                else:
                    statstr += lgth_str + gap_str
        statstr += 19 * '-' + '\n         (%s)\n' % \
            (str_.getlength(meta_.get('duration')))
        str_.pollute(statstr)
    def save(self):
        cue = ''.join(self.sheet).encode(encoding)
        cutstr = 10 * '- ' + '8< ' + 10 * '- ' + '\n'
        if argv_.options.output:
            io_.fname = argv_.options.output; result = io_.tryfile('w')
            result.write(cue)
            result.close()
        else:
            str_.pollute('\nCuesheet:\n\n' + cutstr)
            print cue
            str_.pollute(cutstr)
class Files:
    def write(self):
        n = meta_.get('numoftracks')
        if not argv_.tracks: argv_.tracks = range(n+1)
        for argv_.format in argv_.formats:
            str_.pollute('\nWriting %s files...\n\n' % (argv_.format))
            self.list, self.lgth = [], []
            if cue_.is_singlefile:
                for x in xrange(n):
                    if meta_.get('lgth', x):
                        out_file = ''
                        if x in argv_.tracks: out_file = meta_.filename(x)
                        self.list.append(out_file)
                        self.lgth.append(meta_.get('lgth', x))
                aud_.write(_if=meta_.get('name', 1))
                self.apply_rg()
            else:
                for x in xrange(n):
                    if meta_.get('lgth', x) and x in argv_.tracks:
                        self.list.append(meta_.get('name', x))
                        self.lgth.append(meta_.get('lgth', x))
                out_file = meta_.filename(1)
                aud_.write(_of=out_file)
                self.list = [out_file]
                self.apply_rg()
    def apply_rg(self):
        if not argv_.options.norg and not argv_.format == 'wav':
            cfg_.section = argv_.format
            str_.pollute('\nApplying replay gain...\n\n')
            while self.list.count(''): self.list.remove('')
            if cfg_.read('rg'):
                statstr = 'RG* (%s)\n' % (', '.join(self.list))
                str_.pollute(statstr, 1)

                io_.rdcmd = cfg_.get_cmdline('rg', self.list)
                subp_.exec_child()
                subp_.wait_for_child()
    def rm(self):
        str_.pollute('\nDeleting files...\n\n')
        n = meta_.get('numoftracks')
        for x in xrange(1, n):
            if meta_.get('name', x):
                f = meta_.get('name', x)
                str_.pollute('<<< %s\n' % f, 1)
                os.remove(f)

class SubProc:
    def __init__(self):
        from subprocess import Popen, PIPE
        from tempfile import mkstemp
        (self.run, self.pipe, self.mktmp) = (Popen, PIPE, mkstemp)
        (self.rdproc, self.rdlog, self.wrproc, self.wrlog) = 4 * (None,)
        self.cmd = ''
    def bailout(self, str):
        s = 'While running "%s": %s\n' % \
            (' '.join(self.cmd), str.decode(encoding))
        exit(s, 1)
    def exec_child(self, mode='rd'):
        if mode == 'rd':
            (pipe, self.cmd) = ('out', io_.rdcmd)
            (self.rddump, self.rdlog) = self.mktmp('rdlog', 'cueek')
        else:
            (pipe, self.cmd) = ('in', io_.wrcmd)
            (self.wrdump, self.wrlog) = self.mktmp('wrlog', 'cueek')
        p = 'self.run(self.cmd, std%s=self.pipe, stderr=self.%sdump)' % \
            (pipe, mode)
        try:
            proc = eval(p)
        except OSError, err:
            self.bailout('Cannot execute the program: %s' % err.strerror)
        if mode == 'rd': self.rdproc = proc
        else: self.wrproc = proc
    def wait_for_child(self, mode='rd'):
        retcode = 0
        if mode == 'rd':
            (proc, f) = (self.rdproc, self.rdlog)
        else:
            (proc, f) = (self.wrproc, self.wrlog)
        try:
            retcode = proc.wait()
            log = open(f)
            msgs = log.read().strip()
            log.close()
            os.remove(f)
            proc.stdin.close()
            proc.stdout.close()
        except AttributeError:
            pass
        if retcode:
            errstr = 'Child returned %i: %s' % (retcode, msgs)
            self.bailout(errstr)

def exit(s, die=0):
    if die:
        s = 'ERROR: ' + s
        str_.pollute(s, 1)
        sys.exit(1)
    else:
        str_.pollute(s)
        sys.exit(0)

if __name__ == '__main__':
    from locale import getdefaultlocale
    encoding = getdefaultlocale()[1]

    argv_ = Argv()
    str_ = Strings()
    subp_ = SubProc()
    io_ = IO()
    cfg_ = Config()
    meta_ = Meta()
    aud_ = Audio()
    cue_ = Cue()
    files_ = Files()

    cuename = os.path.abspath(argv_.args[0])
    cuedir = os.path.split(cuename)[0]
    os.chdir(cuedir)

    cue_.probe(cuename)
    cue_.parse()
    cue_.type()

    cue_.modify()
    if cue_.is_singlefile:
        cue_.lengths()
    if not argv_.options.quiet:
        cue_.print_()
    cue_.save()

    if not argv_.options.nowrite:
        files_.write()
        if not argv_.options.nodelete:
            files_.rm()

    exit(exit_str)

