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

DFLT_CFG="""# file naming scheme
#   <%metadata%>[|<convert>]
#
# available metadata fields: albumartist, artist, album, tracknumber, title
# case convertion: lower, upper, swapcase, capitalize, title

[filenames]
mult_files:     %tracknumber% - %title%|lower
mult_files_va:  %tracknumber% - %artist% - %title%|lower
single_file:    %albumartist% - %album%|lower

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
            help="output resulting cuesheet to the FILE, instead of printing\
 to stdout", metavar="FILE")
        opt_parse.add_option("-c", "--compliant",
            action="store_false", dest="noncompliant", default=True,
            help="output to 'compliant' cuesheet")
        opt_parse.add_option("-0", "--zero-track",
            action="store_false", dest="notrackzero", default=True,
            help="when splitting to 'non-compliant' cue, write contents of the\
 first track pre-gap to a file with tracknumber 00")
        opt_parse.add_option("-w", "--write",
            action="store_false", dest="nowrite", default=True,
            help='additionally write splitted/merged audio files')
        opt_parse.add_option("-e", "--encode",
            help="encode audio files to specified FORMAT(s) (use comma as\
 separator)",
            metavar="FORMAT")
        opt_parse.add_option("-r", "--replay-gain",
            action="store_false", dest="norg", default=True,
            help="apply replay gain to encoded file(s)")
        opt_parse.add_option("-d", "--delete-files",
            action="store_false", dest="nodelete", default=True,
            help="delete source files after encoding")
        opt_parse.add_option("-Y", "--year",
            help="set YEAR metadata field", metavar="YEAR")
        opt_parse.add_option("-N", "--discnumber",
            help="set DISCNUMBER metadata field", metavar="DISCNUMBER")

        opt_parse.set_usage('%prog [options] <in.cue>')

        opt_parse.set_description("This script converts a cuesheet created\
 with EAC to another type. If input cuesheet is 'single-file' (i.e CD image),\
 it will be converted ('splitted') to 'multiple-files' cue. Referenced audio\
 file can be splitted to separate files accordingly. And vice versa,\
 'multiple-files' cue will be converted ('merged') to 'single-file' one,\
 while optionally merging referenced files to single audio file.")

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
        self.cfg_ = os.path.expanduser('~/.cueekrc')
        self.cfg_parse = ConfigParser.ConfigParser()
        io_.fname = self.cfg_
        if not os.path.isfile(self.cfg_): # write config file on first run
            cfg_file = io_.tryfile(1)
            cfg_file.write(DFLT_CFG)
            cfg_file.close()
        cfg_file = io_.tryfile()
        self.cfg_parse.readfp(cfg_file)
        self.section = ''
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
        s = self.read(e)
        spl = s.split('%')
        sch = ''
        for s in spl:
            if s in ('artist', 'title'):
                sch = sch + meta_.put_missing(t, s)
            elif s == 'tracknumber':
                sch = sch + str_.leadzero(t)
            elif s == 'albumartist':
                sch = sch + meta_.data['albumartist']
            elif s == 'album':
                sch = sch + meta_.data['album']
            else:
                sch = sch + s
        spl = sch.split('|')
        if len(spl) == 2:
            if spl[1] == 'capitalize': sch = spl[0].capitalize()
            elif spl[1] == 'lower': sch = spl[0].lower()
            elif spl[1] == 'swapcase': sch = spl[0].swapcase()
            elif spl[1] == 'title': sch = spl[0].title()
            elif spl[1] == 'upper': sch = spl[0].upper()
            else: sch = spl[0]
        return sch

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
    def stripquotes(self, s):
        s = re.sub('^"', '', s)
        s = re.sub('"$', '', s)
        return s
    def getlength(self, n):
        smpl_freq = meta_.data['wavparams'][2]
        fr = divmod(n, smpl_freq)
        ms = divmod(fr[0], 60)
        m = ms[0]
        s = ms[1]
        f = fr[1] / (smpl_freq / 75)
        lngth = self.leadzero(m) + self.enclose(':', self.leadzero(s)) + \
            self.leadzero(f)
        return lngth
    def getidx(self, s):
        smpl_freq = meta_.data['wavparams'][2]
        idx = s.split(':')
        mm = idx[0]; mm = mm[-2:]; ss = idx[1]; ff = idx[2]
        idx_pos = ((int(mm) * 60 + int(ss)) * smpl_freq + int(ff) *
            (smpl_freq / 75))
        return idx_pos
    def linehas(self, n, s):
        result = 0
        if re.search(n+'\s+\d+:\d+:\d+', s):
            result = 1
        return result
    def repl_time(self, n, s):
        return re.sub('\d+:\d+:\d+', self.getlength(n), s)
    def enclose(self, s1, s2):
        return s1 + s2 + s1

class Meta:
    def __init__(self):
        self.data = {'albumartist': 'unknown', 'album': 'untitled'}
    def put(self, p, e, v):
        self.data[str_.leadzero(p) + e] = v
    def get(self, p, e):
        try:
            v = self.data[str_.leadzero(p) + e]
        except KeyError:
            v = 0
        return v
    def put_missing(self, t, e):
        if self.get(t, e):
            result = self.get(t, e)
        elif e == 'artist':
            result = self.data['albumartist']
        else:
            result = 'untitled'
        return result
    def tag(self, n = 0):
        if callable(File):
            f = File(io_.fname.strip('\'"'))
        else:
            f = None
        if hasattr(f, 'info'):
            f.info
            if cue_.is_va:
                f['ALBUMARTIST'] = self.data['albumartist'].lower()
            f['ARTIST'] = self.put_missing(n, 'artist').lower()
            f['ALBUM'] = self.data['album'].lower()
            if cue_.is_singlefile:
                f['TITLE'] = self.put_missing(n, 'title').lower()
                f['TRACKNUMBER'] = str(n)
                if argv_.format == 'mpc':
                    f['TRACK'] = str(n)
            else:
                f['CUESHEET'] = ''.join(cue_.sheet)
            if argv_.options.year:
                f['DATE'] = argv_.options.year
                if argv_.format == 'mpc':
                    f['YEAR'] = argv_.options.year
            if argv_.options.discnumber:
                f['DISCNUMBER'] = argv_.options.discnumber
            f.save()
    def filename(self, t, single=0):
        cfg_.section = 'filenames'
        if single:
            f = cfg_.scheme(t, 'single_file')
        else:
            if cue_.is_va:
                f = cfg_.scheme(t, 'mult_files_va')
            else:
                f = cfg_.scheme(t, 'mult_files')
        f = re.sub('[*":/\\\?]', '_', f)
        f = f + '.' + argv_.format
        return f

class IO:
    def __init__(self):
        self.trknum = 0
        self.fname = ''
    def tryfile(self, write = 0):
        if write == 1:
            mode, mode_str = 'wb', 'writing'
        else:
            mode, mode_str = 'rb', 'reading'
        try:
            f = open(self.fname, mode)
        except IOError, (errno, strerror):
            errstr = 'cannot open "%s" for %s: %s' % \
                (self.fname, mode_str, strerror.decode(encoding))
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
            f = self.tryfile(1)
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
        self.frnum = 0
        self.hdr_frnum = 0
        self.fin = None
        self.fout = None
    def get_params(self):
        return self.fin.getparams()
    def gen_hdr(self):
        params = meta_.data['wavparams']
        datalength = self.hdr_frnum * params[0] * params[1]
        hdr = 'RIFF' + struct.pack('<l4s4slhhllhh4s', 36 + datalength,\
            'WAVE', 'fmt ', 16, wave.WAVE_FORMAT_PCM, params[0], params[2],\
            params[0] * params[2] * params[1], params[0] * params[1],\
            params[1] * 8, 'data')
        hdr = hdr + struct.pack('<l', datalength)
        return hdr
    def wr_chunks(self):
        smpl_freq = meta_.data['wavparams'][2]
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
            self.hdr_frnum = meta_.data['cd_duration']
            start = 0
            if not cue_.trackzero_present:
                start = 1
            for x in xrange(start, len(_fin)):
                io_.fname = _fin[x]
                (self.fin, child_dec) = io_.wav_rd()
                self.frnum = self.get_params()[3]

                abs_pos = meta_.get(x-1, 'apos')
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
                if meta_.get(1, 'idx1') and not argv_.options.notrackzero:
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
        self.pregap = 0
        self.trackzero_present = 0
        self.is_compl = 0
        self.is_noncompl = 0
        self.is_singlefile = 0
        self.is_va = 0
        self.encoding = encoding
        self.sheet = []
    def parse(self, src):
        trknum = 1
        for line in src:
            line = line.decode(self.encoding).rstrip('\r\n')
            if line.find('PERFORMER') != -1:
                metadata = re.sub('\s*PERFORMER\s+', '', line)#.strip('"')
                metadata = str_.stripquotes(metadata)
                if not meta_.get(1, 'trck'):
                    meta_.data['albumartist'] = metadata
                else:
                    meta_.put(trknum, 'artist', metadata)
                self.sheet.append(line)
            elif line.find('TITLE') != -1:
                metadata = re.sub('\s*TITLE\s+', '', line)#.strip('"')
                metadata = str_.stripquotes(metadata)
                if not meta_.get(1, 'trck'):
                    meta_.data['album'] = metadata
                else:
                    meta_.put(trknum, 'title', metadata)
                self.sheet.append(line)
            elif line.find('FILE') != -1:
                spl_lines = line.split('"')
                ref_file = spl_lines[1]

                io_.fname = ref_file
                aud_.fin = io_.wav_rd()[0]
                params = aud_.get_params()
                meta_.data['wavparams'] = params
                aud_.fin.close()

                framenum = params[3]
                if not meta_.get(1, 'trck'):
                    self.sheet.append(line)
                    meta_.put(0, 'name', ref_file)
                    meta_.put(0, 'lgth', framenum)
                    meta_.put(1, 'name', ref_file)
                    meta_.put(1, 'lgth', framenum)
                else:
                    meta_.put(trknum, 'name', ref_file)
                    meta_.put(trknum, 'lgth', framenum)
                if meta_.get(0, 'lgth') != meta_.get(1, 'lgth') \
                and trknum == 1: # track zero
                    self.trackzero_present = 1
                    meta_.put(0, 'apos', meta_.get(0, 'lgth'))
                abs_pos = meta_.get(trknum-1, 'apos') + framenum
                meta_.put(trknum, 'apos', abs_pos)
            elif line.find('TRACK') != -1:
                meta_.put(trknum, 'trck', 1)
                self.sheet.append(line)
            elif str_.linehas('PREGAP', line):
                self.pregap = str_.getidx(line)
                self.sheet.append(line)
            elif str_.linehas('INDEX\s+00', line):
                idx_pos = str_.getidx(line)
                meta_.put(trknum, 'idx0', idx_pos)
                self.sheet.append(line)
            elif str_.linehas('INDEX\s+01', line):
                idx_pos = str_.getidx(line)
                meta_.put(trknum, 'idx1', idx_pos)
                self.sheet.append(line)
                trknum = trknum + 1
            else:
                self.sheet.append(line)
        if not self.trackzero_present:
            del meta_.data['00lgth']
        meta_.data['numoftracks'] = trknum
        meta_.data['cd_duration'] = abs_pos
        src.close()
    def type(self):
        gaps_present = 0
        self.is_va = 0
        if not meta_.get(2, 'name'):
            self.is_singlefile = 1
            cue_type = 'single-file'
        else:
            for x in xrange(2, meta_.data['numoftracks']):
                if meta_.get(x, 'idx0'):
                    cue_type = 'non-compliant'
                    gaps_present = 1
                    self.is_noncompl = 1
                    break
                elif meta_.get(x, 'idx1'):
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
        for x in xrange(meta_.data['numoftracks']):
            if meta_.get(x, 'artist') and not \
            meta_.get(x, 'artist') == meta_.data['albumartist']:
                self.is_va = 1
                break
    def modify(self):
        trknum = 1
        gap = 0
        abs_pos = meta_.data['cd_duration']
        for x in xrange(len(cue_.sheet)):
            line = cue_.sheet.pop(x) + '\n'
            if line.find('FILE') != -1:
                if cue_.is_singlefile:
                    if meta_.get(trknum, 'idx1') and \
                    argv_.options.noncompliant and \
                    not argv_.options.notrackzero:
                        wav_file = meta_.filename(trknum-1)
                    else:
                        wav_file = meta_.filename(trknum)
                else:
                    wav_file = meta_.filename(trknum, single=1)
                wav_file = str_.enclose('"', wav_file)
                line = re.sub('".+"', wav_file, line)
                cue_.sheet.insert(x, line)
            elif str_.linehas('INDEX\s+00', line):
                if cue_.is_noncompl:
                    gap = meta_.get(trknum-1, 'lgth') - \
                        meta_.get(trknum, 'idx0')
                    idx00 = meta_.get(trknum-1, 'apos') - gap
                    line = str_.repl_time(idx00, line)
                elif cue_.is_compl:
                    gap = meta_.get(trknum, 'idx1')
                    idx00 = meta_.get(trknum-1, 'apos')
                    line = str_.repl_time(idx00, line)
                elif cue_.is_singlefile:
                    if meta_.get(trknum, 'idx0') or \
                    (trknum == 1 and meta_.get(trknum, 'idx1')):
                        gap = meta_.get(trknum, 'idx1') - \
                            meta_.get(trknum, 'idx0')
                    if not argv_.options.noncompliant:
                        line = str_.repl_time(0, line)
                    elif trknum > 1 or not argv_.options.notrackzero:
                        trk_length = meta_.get(trknum, 'idx1') - \
                            meta_.get(trknum-1, 'idx1')
                        idx00 = trk_length - gap
                        if not (trknum == 2 and argv_.options.notrackzero):
                            line = str_.repl_time(idx00, line)
                        line = line + '\r\nFILE "' + \
                            meta_.filename(trknum) + '" WAVE'
                meta_.put(trknum, 'gap', gap)
                cue_.sheet.insert(x, line)

            elif str_.linehas('INDEX\s+01', line):
                if cue_.is_singlefile:
                    idx01 = 0
                    if trknum == 1:
                        if not argv_.options.noncompliant or \
                        (meta_.get(trknum, 'idx1') and \
                        argv_.options.notrackzero):
                            idx01 = meta_.get(trknum, 'idx1')
                    elif not argv_.options.noncompliant and \
                    meta_.get(trknum, 'idx0'):
                        idx01 = gap
                    if meta_.get(trknum+1, 'idx1'):
                        if not argv_.options.noncompliant or \
                        (argv_.options.noncompliant and \
                        not meta_.get(trknum+1, 'idx0')):
                            line = line + '\r\nFILE "' + \
                                meta_.filename(trknum+1) + '" WAVE'
                    line = str_.repl_time(idx01, line)
                elif cue_.is_noncompl and trknum > 1:
                    idx01 = meta_.get(trknum-1, 'apos')
                    line = str_.repl_time(idx01, line)
                else:
                    idx01 = meta_.get(trknum-1, 'apos') + \
                        meta_.get(trknum, 'idx1')
                    line = str_.repl_time(idx01, line)
                cue_.sheet.insert(x, line)
                trknum = trknum + 1
                gap = 0
            else:
                cue_.sheet.insert(x, line)
    def lengths(self):
        abs_pos = meta_.data['cd_duration']
        start = 1
        if self.trackzero_present: start = 0
        for trknum in xrange(start, meta_.data['numoftracks']):
            if not argv_.options.noncompliant:
                if trknum > 1 and not meta_.get(trknum, 'idx0'):
                    start_pos = meta_.get(trknum, 'idx1')
                else:
                    start_pos = meta_.get(trknum, 'idx0')
                if not meta_.get(trknum+1, 'idx1'):
                    end_pos = abs_pos
                elif not meta_.get(trknum+1, 'idx0'):
                    end_pos = meta_.get(trknum+1, 'idx1')
                else:
                    end_pos = meta_.get(trknum+1, 'idx0')
            else:
                start_pos = meta_.get(trknum, 'idx1')
                if meta_.get(trknum+1, 'idx1'):
                    end_pos = meta_.get(trknum+1, 'idx1')
                else:
                    end_pos = abs_pos
                if trknum == 1 and meta_.get(1, 'idx1'):
                    if argv_.options.notrackzero:
                        start_pos = 0
                    else:
                        meta_.put(0, 'lgth', meta_.get(1, 'idx1'))
            trk_length = end_pos - start_pos
            meta_.put(trknum, 'spos', start_pos)
            meta_.put(trknum, 'lgth', trk_length)
    def print_(self):
        statstr = "This cuesheet appears to be of '" + self.type + "' type"
        if self.is_va:
            statstr = statstr + ", 'various artists'"
        statstr = statstr + "...\n\nCD Layout:\n\n"
        # check if we display layout for compliant cue
        # i.e. source is (or output requested as) compliant
        want_compliant = 0
        if (cue_.is_compl or
        (cue_.is_singlefile and not argv_.options.noncompliant)):
            want_compliant = 1
        for trknum in xrange(meta_.data['numoftracks']):
            gap_str = ''
            trk_str = ''
            lgth_str = ''
            if want_compliant:
                gap = meta_.get(trknum, 'gap')
            else:
                gap = meta_.get(trknum+1, 'gap')
            if meta_.get(trknum, 'lgth'):
                real_length = meta_.get(trknum, 'lgth')
                length = real_length - gap
                trk_str = 'Track %s (%s)\n' % \
                    (str_.leadzero(trknum), str_.getlength(real_length))
                lgth_str = ' content: %s\n' % (str_.getlength(length))
            if cue_.pregap > 0 and trknum == 1:
                statstr += 'Pregap   (%s)\n' % (str_.getlength(cue_.pregap))
            statstr += trk_str
            if gap:
                gap_str = '     gap: %s\n' % (str_.getlength(gap))
                if want_compliant:
                    statstr += gap_str + lgth_str
                else:
                    statstr += lgth_str + gap_str
        statstr += '\nLength   (%s)\n' % \
            (str_.getlength(meta_.data['cd_duration']))
        str_.pollute(statstr)
    def save(self):
        cue = ''.join(cue_.sheet).encode(encoding)
        if argv_.options.output:
            io_.fname = argv_.options.output; result = io_.tryfile(1)
            result.write(cue)
            result.close()
        else:
            str_.pollute('\n- - - - - - - - 8< - - - - - - - -\n')
            print cue
            str_.pollute('- - - - - - - - 8< - - - - - - - -\n')
class Files:
    def write(self):
        n = meta_.data['numoftracks']
        for argv_.format in argv_.formats:
            str_.pollute('\nWriting %s files...\n\n' % (argv_.format))
            files=[]
            lengths=[]
            if cue_.is_singlefile:
                for x in xrange(n):
                    if meta_.get(x, 'lgth'):
                        out_file = meta_.filename(x)
                        files.append(out_file)
                        lengths.append(meta_.get(x, 'lgth'))
                aud_.write(meta_.get(1, 'name'), files, lengths)
                self.apply_rg(files)
            else:
                for x in xrange(n):
                    if meta_.get(x, 'name'):
                        files.append(meta_.get(x, 'name'))
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
        n = meta_.data['numoftracks']
        for x in xrange(1, n):
            if meta_.get(x, 'name'):
                f = meta_.get(x, 'name')
                str_.pollute('<<< %s\n' % f, override=1)
                os.remove(f)


if __name__ == '__main__':
    locale.setlocale(locale.LC_ALL, '')
    encoding = locale.getlocale()[1]

    argv_ = Argv()
    str_ = Strings()
    io_ = IO()
    meta_ = Meta()
    aud_ = Audio()
    cfg_ = Config()
    cue_ = Cue()
    files_ = Files()

    cuename = os.path.abspath(argv_.args[0])
    io_.fname = cuename
    cuedir = os.path.split(cuename)[0]
    os.chdir(cuedir)

    if argv_.options.charmap:
        cue_.encoding = argv_.options.charmap
    else:
        try:
            import chardet
            orig_cue = io_.tryfile()
            data = orig_cue.read()
            cue_.encoding = chardet.detect(data)['encoding']
            orig_cue.close()
        except ImportError:
            pass
    orig_cue = io_.tryfile()
    cue_.parse(orig_cue)
    cue_.type()

    cue_.modify()
    if cue_.is_singlefile:
        cue_.lengths()
    if not argv_.options.quiet:
        cue_.print_()
    cue_.save()

    if not argv_.options.nowrite:
        try:
            from mutagen import File
        except ImportError:
            File = None
        files_.write()
        if not argv_.options.nodelete:
            files_.rm()

    str_.pollute('\nFinished succesfully\n')

