#!/usr/bin/python
import sys
import os
import locale
import re
import wave
import struct
import ConfigParser
from optparse import OptionParser
from subprocess import *
from mutagen import File

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
#translate:      lower

# encoders and decoders
# decoders must be able to write to stdout, encoders - read from stdin
#   [extension]
#   decode: <commandline>   where '%f' is input file
#   encode: <commandline>   where '%f' is output file
#   rg: <commandline>       format-specific replay-gain scanner

[flac]
decode: flac -dcs %f
encode: flac -fs -o %f -
rg:     metaflac --add-replay-gain %f

[wv]
decode: wvunpack -q -o - %f
encode: wavpack -myiq -o %f -
rg:     wvgain -aq %f

[ape]
decode: mac %f - -d
"""

class Argv:
    def __init__(self):
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
        opt_parse.add_option("-r", "--replay-gain",
            action="store_false", dest="norg", default=True,
            help="apply replay gain to encoded file(s)")
        opt_parse.add_option("-d", "--delete-files",
            action="store_false", dest="nodelete", default=True,
            help="delete source files after encoding")

        opt_parse.set_usage('%prog [options] <in.cue>')

        opt_parse.set_description("This script converts a cuesheet to another "
            "type. If input cuesheet is 'single-file' (i.e CD image), it will "
            "be converted ('splitted') to 'multiple-files' one. "
            "Referenced audio file can be splitted accordingly. "
            "Vice versa, 'multiple-files' cue will be converted ('merged') to "
            "'single-file' one, while optionally merging referenced files.")

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

class Config:
    def __init__(self):
        self.cfg_parse = ConfigParser.ConfigParser()
        io_.fname = os.path.expanduser('~/.cueekrc')
        if not os.path.isfile(io_.fname): # write config file on first run
            cfg_file = io_.tryfile(mode='w')
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
        except (ConfigParser.NoSectionError, ConfigParser.NoOptionError), \
        (strerror):
            if not supress:
                errstr = 'ERROR: config file: %s\n' % strerror
                str_.pollute(errstr)
        return result
    def get_cmdline(self, action, fname):
        cmd = cfg_.read(action).split()
        pos = cmd.index('%f')
        cmd = cmd[:pos] + fname + cmd[pos+1:]
        return cmd
    def scheme(self, t, e):
        self.section = 'filenames'
        spl = self.read(e).split('%')
        sch = ''
        for s in spl:
            if s in ('artist', 'title'):
                sch += meta_.add_missing(s, t)
            elif s == 'tracknumber':
                sch += str_.leadzero(t)
            elif s == 'albumartist':
                sch += meta_.get('artist')
            elif s == 'album':
                sch += meta_.get('title')
            else:
                sch += s
        if self.read('translate') in self.case_conv:
            sch = repr(sch) + '.' + self.read('translate') + '()'
            sch = eval(sch)
        return sch
    def str2list(self, s):
        s = [x.strip() for x in self.read(s).upper().split(',')]
        return s

class Strings:
    def __init__(self):
        self.pad = 2
    def pollute(self, s, override=0, die=0):
        if not argv_.options.quiet or override or die:
            if isinstance(s, unicode): s = s.encode(encoding)
            if die: s = 'ERROR: ' + s
            sys.stderr.write(s)
            sys.stderr.flush()
            if die: sys.exit(1)
    def leadzero(self, n):
        nn = str(n).zfill(self.pad)
        return nn
    def getlength(self, n):
        fr = divmod(n, smpl_freq)
        ms = divmod(fr[0], 60)
        m = ms[0]
        s = ms[1]
        f = fr[1] / (smpl_freq / 75)
        lngth = self.leadzero(m) + ':' + self.leadzero(s) + ':' + \
            self.leadzero(f)
        return lngth
    def getidx(self, s):
        idx = s.split(':')
        mm = idx[0]; mm = mm[-2:]; ss = idx[1]; ff = idx[2]
        idx_pos = ((int(mm) * 60 + int(ss)) * smpl_freq + int(ff) *
            (smpl_freq / 75))
        return idx_pos
    def linehas(self, n, s):
        result = 0
        if re.search(n+'\s+\d+:\d+:\d+', s, re.I): result = 1
        return result
    def repl_time(self, n, s):
        return re.sub('\d+:\d+:\d+', self.getlength(n), s)

class Meta:
    def __init__(self):
        self.data = {'albumartist': 'unknown', 'albumtitle': 'untitled'}
        cfg_.section = 'tags'
        self.tags_omit = cfg_.str2list('fields_skip')
        self.tags_dontranslate = cfg_.str2list('fields_notran')
        if cfg_.read('translate') in cfg_.case_conv:
            self.translate = '.' + cfg_.read('translate') + '()'
    def put(self, entry, val, tn='album'):
        if isinstance(tn, int): tn = str_.leadzero(tn)
        entry = tn + entry
        self.data[entry] = val
    def get(self, entry, tn='album'):
        if isinstance(tn, int): tn = str_.leadzero(tn)
        entry = tn + entry
        try:
            val = self.data[entry]
        except KeyError:
            val = 0
        return val
    def add_missing(self, entry, tn):
        result = 'untitled'
        if not self.get(entry, tn=tn):
            if entry == 'artist': result = self.get(entry)
        else:
            result = self.get(entry, tn)
        return result
    def tag(self, n = 0):
        cfg_.section = 'tags'
        f = File(io_.fname.strip('\'"'))
        if hasattr(f, 'info'):
            tags = []
            # collect tags
            if cue_.is_va:
                tags.append(['ALBUMARTIST', self.get('artist')])
            tags.append(['ARTIST', self.add_missing('artist', n)])
            tags.append(['ALBUM', self.get('title')])
            if meta_.get('comment'):
                for x in meta_.get('comment'): tags.append(x)
            if cue_.is_singlefile:
                tags.append(['TITLE', self.add_missing('title', n)])
                tags.append(['TRACKNUMBER', str(n)])
                if meta_.get('comment', n):
                    for x in meta_.get('comment', n): tags.append(x)
            else:
                tags.append(['CUESHEET', ''.join(cue_.sheet)])
            # convert case if requested and write to file
            for (key, val) in tags:
                if key not in self.tags_omit:
                    if self.translate and key not in self.tags_dontranslate:
                        val = eval(repr(val) + self.translate)
                    f[key] = val
            f.save()
    def filename(self, t, single=0):
        if single:
            f = cfg_.scheme(t, 'single_file')
        else:
            if cue_.is_va:
                f = cfg_.scheme(t, 'mult_files_va')
            else:
                f = cfg_.scheme(t, 'mult_files')
        f = re.sub('[*":/\\\?]', '_', f) + '.' + argv_.format
        return f

class IO:
    def __init__(self):
        (self.trknum, self.fname) = (0, '')
    def tryfile(self, mode='r'):
        try:
            f = open(self.fname, mode)
        except IOError, (errno, strerror):
            errstr = 'cannot open "%s": %s' % \
                (self.fname, strerror.decode(encoding))
            str_.pollute(errstr, die=1)
        return f
    def wav_rd(self):
        fn = self.fname
        ext = fn.split('.')[-1].lower()
        cfg_.section = ext
        if ext == 'wav':
            r = fn
            p = None
        elif cfg_.read('decode', 1):
            s = cfg_.get_cmdline('decode', [fn])
            p = Popen(s, stdout=PIPE, stderr=PIPE)
            (r, e) = (p.stdout, p.stderr)
        else:
            errstr = 'don\'t know how to decode "%s", ' % (fn)
            errstr += 'please set decoder in config file'
            str_.pollute(errstr, die=1)
        try:
            r = wave.open(r, 'rb')
        except IOError, (errno, strerror):
            errstr = 'cannot open "%s" for reading: %s' % \
                (fn, strerror.decode(encoding))
            str_.pollute(errstr, die=1)
        except wave.Error, (strerror):
            errstr = 'cannot open wave file "%s": %s' % \
                (fn, str(strerror).decode(encoding))
            str_.pollute(errstr, die=1)
        except EOFError:
            errstr = 'cannot decode %s: %s' % \
                (fn, e.read().strip().decode(encoding))
            e.close
            str_.pollute(errstr, die=1)
        return (r, p)
    def wav_wr(self):
        cfg_.section = argv_.format
        tag_str = ''
        if argv_.format == 'wav':
            f = self.tryfile(mode='wb')
            w = (f, None)
        elif cfg_.read('encode', 1):
            s = cfg_.get_cmdline('encode', [self.fname])
            p = Popen(s, stdin=PIPE, stderr=PIPE)
            p.stderr.close()
            w = (p.stdin, p)
        else:
            errstr = 'don\'t how to encode "%s" files, ' % (argv_.format)
            errstr += 'please set appropriate encoder in config file'
            str_.pollute(errstr, die=1)
        return w

class Audio:
    #smpl_freq = 44100
    #frm_length = smpl_freq / 75
    def __init__(self):
        (self.frnum, self.hdr_frnum) = 2 * (0,)
        (self.fin, self.fout) = 2 * (None,)
    def get_params(self):
        return self.fin.getparams()
    def gen_hdr(self):
        params = meta_.get('wavparams')
        length = self.hdr_frnum * params[0] * params[1]
        hdr = 'RIFF' + struct.pack('<l4s4slhhllhh4sl', 36 + length,
            'WAVE', 'fmt ', 16, wave.WAVE_FORMAT_PCM, params[0], params[2],
            params[0] * params[2] * params[1], params[0] * params[1],
            params[1] * 8, 'data', length)
        return hdr
    def wr_chunks(self):
        step = smpl_freq * 10 # 10s chunks
        if self.hdr_frnum:
            hdr = self.gen_hdr()
            self.fout.write(hdr)
        for x in xrange(self.frnum/step):
            frames = self.fin.readframes(step)
            self.fout.write(frames)
        frames = self.fin.readframes(self.frnum%step) # leftovers
        self.fout.write(frames)
    def wait_for_child(self, proc):
        retcode = 0
        try:
            retcode = proc.wait()
        except AttributeError:
            pass
        if retcode:
            errstr = 'error while running child process: %s' % \
                proc.stderr.read().strip().decode(encoding)
            str_.pollute(errstr, die=1)
    def write(self, _fin, _fout, lgth=0):
        if isinstance(_fin, list): # merging input files to 1 out file
            io_.fname = _fout
            (self.fout, child_enc) = io_.wav_wr()
            # when piping, write wav header with number of samples
            # equal to sum of lengths of input files
            self.hdr_frnum = meta_.get('duration')
            start = 0
            if not cue_.trackzero_present:
                start = 1
            for x in xrange(start, len(_fin)):
                io_.fname = _fin[x]
                (self.fin, child_dec) = io_.wav_rd()
                self.frnum = self.get_params()[3]

                abs_pos = meta_.get('apos', x-1)
                statstr = '%s >> %s @ %s\n' % \
                    (_fin[x], _fout, str_.getlength(abs_pos))
                str_.pollute(statstr, override=1)

                self.wr_chunks()
                if self.hdr_frnum: self.hdr_frnum = 0 # write header only once
                self.wait_for_child(child_dec)
                self.fin.close()
            self.fout.close()
            self.wait_for_child(child_enc)
            io_.fname = _fout
            meta_.tag()
        elif isinstance(_fout, list): # splitting to multiple files
            io_.fname = _fin
            (self.fin, child_dec) = io_.wav_rd()
            self.get_params()
            for x in xrange(len(_fout)):
                if meta_.get('idx1', 1) and not argv_.options.notrackzero:
                    io_.trknum = x
                else:
                    io_.trknum = x + 1
                io_.fname = _fout[x]
                (self.fout, child_enc) = io_.wav_wr()
                self.hdr_frnum = self.frnum = lgth[x]

                statstr = '%s > %s # %s\n' % \
                    (_fin, _fout[x], str_.getlength(lgth[x]))
                str_.pollute(statstr, override=1)

                self.wr_chunks()
                self.fout.close()
                self.wait_for_child(child_enc)
                meta_.tag(x+1)
            self.wait_for_child(child_dec)
            self.fin.close()

class Cue:
    def __init__(self):
        (self.pregap, self.trackzero_present, self.is_compl, self.is_noncompl, 
            self.is_singlefile, self.is_va) = 6 * (0,)
        (self.encoding, self.sheet, self.ref_file) = (encoding, [], '')
    def probe(self, fn):
        size = os.path.getsize(fn)
        io_.fname = fn
        f = io_.tryfile(mode='Ur')
        if size >= long(16384):
            _f = File(io_.fname)
            try:
                self.sheet = _f['CUESHEET'][0].splitlines(1)
                self.ref_file = io_.fname
            except (KeyError, TypeError):
                str_.pollute('failed to probe this cuesheet', die=1)
        else:
            if argv_.options.charmap:
                self.encoding = argv_.options.charmap
            else:
                try:
                    import chardet
                    _f = io_.tryfile()
                    self.encoding = chardet.detect(_f.read())['encoding']
                    _f.close()
                except ImportError:
                    pass
            self.sheet = [line.decode(self.encoding) for line in f]
        f.close()
    def dblquotes(self, s):
        """This is to allow double quotes inside PERFORMER and TITLE fields,
        so they could be used for tagging, while replacing them with single
        quotes in output"""
        p1 = s.partition('"')
        p2 = p1[2].rpartition('"')
        m = p2[0]
        s = p1[0] + '"' + p2[0].replace('"', "'") + '"' + p2[2]
        return (m, s)
    def parse(self):
        trknum = 1
        for line in self.sheet:
            tn = 'album'
            if re.search('PERFORMER', line, re.I):
                metadata = self.dblquotes(line)[0]
                if meta_.get('trck', 1): tn = trknum
                meta_.put('artist', metadata, tn)
            elif re.search('TITLE', line, re.I):
                metadata = self.dblquotes(line)[0]
                if meta_.get('trck', 1): tn = trknum
                meta_.put('title', metadata, tn)
            elif re.search('REM', line, re.I):
                if meta_.get('trck', 1): tn = trknum
                metadata = []
                if meta_.get('comment', tn):
                    metadata = meta_.get('comment', tn)
                key, val = line.split()[1].upper(), ' '.join(line.split()[2:])
                metadata.append([str(key), val])
                meta_.put('comment', metadata, tn)
            elif re.search('FILE', line, re.I):
                ref_file = line.split('"')[1]

                if self.ref_file:
                    ref_file = self.ref_file
                io_.fname = ref_file
                aud_.fin = io_.wav_rd()[0]
                params = aud_.get_params()
                meta_.put('wavparams', params)
                global smpl_freq
                smpl_freq = params[2]
                aud_.fin.close()

                framenum = params[3]
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
            elif re.search('TRACK', line, re.I):
                meta_.put('trck', 1, trknum)
            elif str_.linehas('PREGAP', line):
                self.pregap = str_.getidx(line)
            elif str_.linehas('INDEX\s+00', line):
                idx_pos = str_.getidx(line)
                meta_.put('idx0', idx_pos, trknum)
            elif str_.linehas('INDEX\s+01', line):
                idx_pos = str_.getidx(line)
                meta_.put('idx1', idx_pos, trknum)
                trknum += 1
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
                    errstr = 'failed to recognise cuesheet type'
                    str_.pollute(errstr, die=1)
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
            line = self.sheet[x]
            if re.search('PERFORMER|TITLE', line, re.I):
                line = self.dblquotes(line)[1]
                cue.append(line)
            elif re.search('FILE', line, re.I):
                if not wav_file or self.is_singlefile:
                    if self.is_singlefile:
                        if meta_.get('idx1', trknum) and \
                        argv_.options.noncompliant and \
                        not argv_.options.notrackzero:
                            wav_file = meta_.filename(trknum-1)
                        else:
                            wav_file = meta_.filename(trknum)
                    else:
                        wav_file = meta_.filename(trknum, single=1)
                    wav_file = '"' + wav_file + '"'
                    line = re.sub('".+"', wav_file, line)
                    cue.append(line)
            elif str_.linehas('INDEX\s+00', line):
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
            elif str_.linehas('INDEX\s+01', line):
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
                    (str_.leadzero(trknum), str_.getlength(real_length))
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
        statstr += '\nLength   (%s)\n' % \
            (str_.getlength(meta_.get('duration')))
        str_.pollute(statstr)
    def save(self):
        cue = ''.join(self.sheet).encode(encoding)
        if argv_.options.output:
            io_.fname = argv_.options.output; result = io_.tryfile(mode='w')
            result.write(cue)
            result.close()
        else:
            str_.pollute('\n- - - - - - - - 8< - - - - - - - -\n')
            print cue
            str_.pollute('- - - - - - - - 8< - - - - - - - -\n')
class Files:
    def write(self):
        n = meta_.get('numoftracks')
        for argv_.format in argv_.formats:
            str_.pollute('\nWriting %s files...\n\n' % (argv_.format))
            files=[]
            lengths=[]
            if cue_.is_singlefile:
                for x in xrange(n):
                    if meta_.get('lgth', x):
                        out_file = meta_.filename(x)
                        files.append(out_file)
                        lengths.append(meta_.get('lgth', x))
                aud_.write(meta_.get('name', 1), files, lengths)
                self.apply_rg(files)
            else:
                for x in xrange(n):
                    if meta_.get('name', x):
                        files.append(meta_.get('name', x))
                out_file = meta_.filename(x, single=1)
                aud_.write(files, out_file)
                self.apply_rg([out_file])
    def apply_rg(self, files):
            if not argv_.options.norg and not argv_.format == 'wav':
                cfg_.section = argv_.format
                str_.pollute('\nApplying replay gain...\n\n')
                f = []
                for file in files: # get list of encoded files
                    f.append(file)
                if cfg_.read('rg', 1):
                    s = cfg_.get_cmdline('rg', f)
                    if call(s):
                        str_.pollute('WARNING: failed to apply replay gain',
                        override=1)
    def rm(self):
        str_.pollute('\nDeleting files...\n\n')
        n = meta_.get('numoftracks')
        for x in xrange(1, n):
            if meta_.get('name', x):
                f = meta_.get('name', x)
                str_.pollute('<<< %s\n' % f, override=1)
                os.remove(f)


if __name__ == '__main__':
    locale.setlocale(locale.LC_ALL, '')
    encoding = locale.getlocale()[1]

    argv_ = Argv()
    str_ = Strings()
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

    str_.pollute('\nFinished succesfully\n')

