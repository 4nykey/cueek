#!/usr/bin/python
import sys
import os
import re
from locale import getdefaultlocale

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
encoding = getdefaultlocale()[1]
exit_str = '\nFinished succesfully\n'
config_file = os.path.expanduser('~/.cueekrc')

class Argv:
    def __init__(self):
        from optparse import OptionParser
        opt_parse = OptionParser()

        opt_parse.add_option("-g", "--config",
            action="callback", callback=config,
            help="dump default settings to config file")
        opt_parse.add_option("-v", "--verbose",
            action="store_false", dest="quiet", default=True,
            help="print status messages to stderr")
        opt_parse.add_option("-m", "--charmap",
            help="decode cuesheet from specified CHARMAP", metavar="CHARMAP")
        opt_parse.add_option("-o", "--output",
            help="output resulting cuesheet to the FILE, instead of printing "
            "to stdout", metavar="FILE")
        opt_parse.add_option("-c", "--compliant",
            action="store_false", dest="noncompl", default=True,
            help="output to 'compliant' cuesheet")
        opt_parse.add_option("-0", "--zero-track",
            action="store_false", dest="notrk0", default=True,
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
            "This script converts a cuesheet to another type: `single-file' "
            "cue, will be converted to a `multiple-files' one, and vice versa. "
            "Referenced files can be processed accordingly. "
            "Configuration is read from `%s' file, which is created "
            "on first run or manually with `--config'." % config_file)

        (self.opts, self.args) = opt_parse.parse_args()

        if len(self.args) != 1:
            opt_parse.error('Please specify the cuesheet to process')

        if not self.opts.noncompl: self.opts.notrk0 = True

        if self.opts.encode : self.formats=self.opts.encode.split(',')
        else                : self.formats=['wav']
        self.format = self.formats[0]

        self.tracks = []
        if self.opts.tracks:
            for x in self.opts.tracks.split(','):
                t = [int(y) for y in x.split('-')]
                for z in xrange(t[0], t[-1]+1):
                    self.tracks.append(z)
        self.tracks.sort()

class Config:
    def __init__(self):
        # write config file on first run
        if not os.path.isfile(config_file): config(None, None, None)
        cfg_file = tryfile(config_file)
        from ConfigParser import ConfigParser, NoSectionError, NoOptionError
        self.cfg_parse = ConfigParser()
        self.nosect, self.noopt = NoSectionError, NoOptionError
        self.cfg_parse.readfp(cfg_file)
        self.section = ''
        self.case_conv = ['capitalize', 'lower', 'swapcase', 'title', 'upper']
    def read(self, e, supress=0):
        result = ''
        try:
            result = self.cfg_parse.get(self.section, e)
        except (self.nosect, self.noopt), err:
            if not supress:
                exit('Config file: %s\n' % err, 1)
        return result
    def get_cmdline(self, action, fname):
        cmd = self.read(action).split()
        try:
            pos = cmd.index('%f')
            cmd = cmd[:pos] + fname + cmd[pos+1:]
        except ValueError:
            pass
        return cmd
    def str2list(self, s):
        list = []
        if self.read(s, 1):
            list = [x.strip() for x in self.read(s).upper().split(',')]
        return list

class Meta:
    def __init__(self):
        from mutagen import File, musepack, mp3, id3
        self.mutagen, self.mpc, self.mp3, self.id3 = (File, musepack.Musepack,
            mp3.MP3, id3)
        self.id3trans = {'ARTIST': 'TPE1', 'ALBUM': 'TALB', 'TITLE': 'TIT2',
            'TRACKNUMBER': 'TRCK', 'DATE': 'TDRC', 'DISCNUMBER': 'TPOS',
            'GENRE': 'TCON', 'COMMENT': 'COMM'}
        self.id3frames = []
        for name, frame in self.id3.Frames.items(): self.id3frames.append(name)
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
    def tag(self, fn, n=0):
        cfg_.section = 'tags'
        f, ismpc, ismp3 = 3 * [None]
        if os.path.isfile(fn): f = self.mutagen(fn)
        if hasattr(f, 'info'):
            tags = {}
            if isinstance(f, self.mpc)    : ismpc = 1
            elif isinstance(f, self.mp3)  : ismp3 = 1
            # collect tags
            if self.get('is_va'):
                tags['ALBUMARTIST'] = self.get('artist')
            tags['ARTIST'] =  self.add_missing('artist', n)
            tags['ALBUM'] =  self.get('title')
            if self.get('comment'):
                for x in self.get('comment'): tags[x[0]] = x[1]
            if self.get('is_singlefile'):
                tags['TITLE'] =  self.add_missing('title', n)
                tags['TRACKNUMBER'] =  str(n)
                if self.get('comment', n):
                    for x in self.get('comment', n): tags[x[0]] = x[1]
            else:
                if not option_.tracks:
                    tags['CUESHEET'] = self.get('cuesheet')
            if ismpc:
                tags['TRACK'] = tags['TRACKNUMBER']
                if tags.has_key('DATE'): tags['YEAR'] = tags['DATE']
            if ismp3:
                try: f = self.id3.ID3(fn)
                except self.id3.ID3NoHeaderError: f = self.id3.ID3()
            # convert case if requested and write to file
            for (key, val) in tags.iteritems():
                if key not in self.tags_omit:
                    if self.translate and key not in self.tags_dontranslate:
                        val = eval(repr(val) + self.translate)
                    if ismp3: # taken from mid3v2
                        if self.id3trans.has_key(key): key = self.id3trans[key]
                        if key in self.id3frames:
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
            if ismp3  : f.save(fn)
            else      : f.save()
    def filename(self, t):
        cfg_.section = 'filenames'
        sch = ''
        if not self.get('is_singlefile')  : e = 'single_file'
        elif self.get('is_va')            : e = 'mult_files_va'
        else                              : e = 'mult_files'
        for s in cfg_.read(e).split('%'):
            if s in ('artist', 'title')   : sch += self.add_missing(s, t)
            elif s == 'tracknumber'       : sch += str(t).zfill(2)
            elif s == 'albumartist'       : sch += self.get('artist')
            elif s == 'album'             : sch += self.get('title')
            else:                           sch += s
        if cfg_.read('translate', 1) in cfg_.case_conv:
            sch = repr(sch) + '.' + cfg_.read('translate') + '()'
            sch = eval(sch)
        f = re.sub('[*":/\\\?]', '_', sch) + '.' + argv_.format
        return f

class Audio:
    def __init__(self):
        from mutagen import version as v
        self.use_mutagen = False
        if v >= (1,11): self.use_mutagen = True
        from struct import pack
        self.pack = pack
        from wave import Wave_read, WAVE_FORMAT_PCM
        self.wavread, self.fmtpcm = Wave_read, WAVE_FORMAT_PCM
        self.fname, self.rdcmd, self.wrcmd = 3 * ['']
        self.frnum, self.hdr_frnum = 2 * [0]
        self.params, self.fin, self.fout = 3 * [None]
        self.msfstr = '\d{1,2}:\d\d:\d\d'
        self.smpl_freq = 0
    def get_params(self):
        f = meta_.mutagen(self.fname)
        if hasattr(f, 'info') and hasattr(f.info, 'sample_rate') and \
        self.use_mutagen:
            f = f.info
            ch, sr = f.channels, f.sample_rate
            if hasattr(f,'bits_per_sample') : sw = f.bits_per_sample / 8
            else                            : sw = 2 # assume cdda
            if hasattr(f,'total_samples')   : sn = f.total_samples
            else                            : sn = f.length * sr
            self.params = (ch, sw, sr, long(sn), None, None)
        else:
            self.wav_rd()
            self.params = self.fin.getparams()
            self.fin.close()
            if subp_.rdproc: subp_.rdproc.stdout.close()
            subp_.wait_for_child(kill=1)
        if not self.smpl_freq: self.smpl_freq = self.params[2]
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
    def wav_rd(self):
        ext = self.fname.split('.')[-1].lower()
        cfg_.section = ext.encode(encoding)
        r = tryfile(self.fname, 'rb')
        if ext != 'wav' and cfg_.read('decode'):
            r.close()
            self.rdcmd = cfg_.get_cmdline('decode', [self.fname])
            subp_.exec_child()
            r = subp_.rdproc.stdout
        try:
            r = self.wavread(r)
        except EOFError:
            subp_.wait_for_child()
            exit(errstr, 1)
        self.fin = r
    def wav_wr(self):
        cfg_.section = argv_.format
        if argv_.format == 'wav':
            w = tryfile(self.fname, 'wb')
        elif cfg_.read('encode'):
            self.wrcmd = cfg_.get_cmdline('encode', [self.fname])
            subp_.exec_child('wr')
            w = subp_.wrproc.stdin
        self.fout = w
    def getlength(self, n, sep=':'):
        ms, fr = divmod(n, self.smpl_freq)
        m, s = divmod(ms, 60)
        f = fr / (self.smpl_freq / 75)
        return sep.join([str(x).zfill(2) for x in m,s,f])
    def getidx(self, s):
        mm, ss, ff = [int(x[-2:]) for x in s.strip().split(':')]
        return ((mm * 60 + ss) * self.smpl_freq + ff * (self.smpl_freq / 75))
    def linehas(self, n, s):
        result = 0
        if re.search(n+'\s+'+self.msfstr, s, re.I): result = 1
        return result
    def repl_time(self, n, s):
        return re.sub(self.msfstr, self.getlength(n), s)

class Cue:
    def __init__(self):
        (self.pregap, self.trackzero_present, self.is_compl, self.is_noncompl,
            self.is_singlefile, self.is_va) = 6 * [0]
        self.charmap, self.sheet, self.ref_file = encoding, [], ''
    def probe(self, fn):
        f = tryfile(fn)
        size = os.path.getsize(fn)
        if size >= long(16384):
            _f = meta_.mutagen(fn)
            try:
                self.sheet = _f['CUESHEET'][0].splitlines(1)
                self.ref_file = fn
            except (KeyError, TypeError):
                exit('Failed to probe the cuesheet', 1)
        else:
            if option_.charmap: self.charmap = option_.charmap
            else:
                try:
                    import chardet
                    _f = tryfile(fn)
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
        lst = re.split('([^"]*")(.*)("[^"]*)', s)
        m = lst[2]
        lst[2] = m.replace('"', "''")
        return (m, ''.join(lst))
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

                if self.ref_file: ref_file = self.ref_file
                aud_.fname = ref_file
                aud_.get_params()

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
            elif re.search('^TRACK\s+\d+\s+AUDIO', line, re.I):
                meta_.put('trck', 1, trknum)
            elif aud_.linehas('^PREGAP\s+', line):
                self.pregap = aud_.getidx(line)
            elif aud_.linehas('^INDEX\s+00', line):
                idx_pos = aud_.getidx(line)
                meta_.put('idx0', idx_pos, trknum)
            elif aud_.linehas('^INDEX\s+01', line):
                idx_pos = aud_.getidx(line)
                meta_.put('idx1', idx_pos, trknum)
                trknum += 1
        if not meta_.get('lgth', 1):
            exit('Failed to get the length of referenced file', 1)
        if not self.trackzero_present:
            del meta_.data['00lgth']
        meta_.put('numoftracks', trknum)
        meta_.put('duration', abs_pos)
        meta_.put('apos', abs_pos, trknum-1)
        self.type()
    def type(self):
        gaps_present, self.is_va = 2 * [0]
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
        meta_.put('is_singlefile', self.is_singlefile)
        meta_.put('is_va', self.is_va)
    def modify(self):
        trknum, gap, cue, wav_file = (1, 0, [], '')
        abs_pos = meta_.get('duration')
        for line in self.sheet:
            line = line.rstrip() + os.linesep
            lstr = line.lstrip()
            if re.search('^(PERFORMER|TITLE)\s+', lstr, re.I):
                line = self.dblquotes(line)[1]
                cue.append(line)
            elif re.search('^FILE\s+', lstr, re.I):
                if not wav_file or self.is_singlefile:
                    if self.is_singlefile:
                        if meta_.get('idx1', trknum) and option_.noncompl and \
                        not option_.notrk0:
                            wav_file = meta_.filename(trknum-1)
                        else:
                            wav_file = meta_.filename(trknum)
                    else:
                        wav_file = meta_.filename(trknum)
                    wav_file = '"' + wav_file + '"'
                    line = re.sub('".+"', wav_file, line)
                    cue.append(line)
            elif aud_.linehas('^INDEX\s+00', lstr):
                if self.is_noncompl:
                    gap = meta_.get('lgth', trknum-1) - \
                        meta_.get('idx0', trknum)
                    idx00 = meta_.get('apos', trknum-1) - gap
                    line = aud_.repl_time(idx00, line)
                elif self.is_compl:
                    gap = meta_.get('idx1', trknum)
                    idx00 = meta_.get('apos', trknum-1)
                    line = aud_.repl_time(idx00, line)
                elif self.is_singlefile:
                    if meta_.get('idx0', trknum) or \
                    (trknum == 1 and meta_.get('idx1', trknum)):
                        gap = meta_.get('idx1', trknum) - \
                            meta_.get('idx0', trknum)
                    if not option_.noncompl:
                        line = aud_.repl_time(0, line)
                    elif trknum > 1 or not option_.notrk0:
                        trk_length = meta_.get('idx1', trknum) - \
                            meta_.get('idx1', trknum-1)
                        idx00 = trk_length - gap
                        if not (trknum == 2 and option_.notrk0):
                            line = aud_.repl_time(idx00, line)
                        line += 'FILE "' + \
                            meta_.filename(trknum) + '" WAVE' + os.linesep
                meta_.put('gap', gap, trknum)
                cue.append(line)
            elif aud_.linehas('^INDEX\s+01', lstr):
                if self.is_singlefile:
                    idx01 = 0
                    if trknum == 1:
                        if not option_.noncompl or \
                        (meta_.get('idx1', trknum) and option_.notrk0):
                            idx01 = meta_.get('idx1', trknum)
                    elif not option_.noncompl and meta_.get('idx0', trknum):
                        idx01 = gap
                    if meta_.get('idx1', trknum+1):
                        if not option_.noncompl or \
                        (option_.noncompl and not meta_.get('idx0', trknum+1)):
                            line += 'FILE "' + \
                                meta_.filename(trknum+1) + '" WAVE' + os.linesep
                    line = aud_.repl_time(idx01, line)
                elif self.is_noncompl and trknum > 1:
                    idx01 = meta_.get('apos', trknum-1)
                    line = aud_.repl_time(idx01, line)
                else:
                    idx01 = meta_.get('apos', trknum-1) + \
                        meta_.get('idx1', trknum)
                    line = aud_.repl_time(idx01, line)
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
            if not option_.noncompl:
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
                    if option_.notrk0:
                        start_pos = 0
                    else:
                        length = meta_.get('idx1', 1)
                        meta_.put('lgth', length, 0)
            trk_length = end_pos - start_pos
            meta_.put('apos', start_pos, trknum-1)
            meta_.put('lgth', trk_length, trknum)
    def print_(self):
        statstr = "This cuesheet appears to be of '" + self.type
        if self.is_va:
            statstr += "', 'various artists"
        statstr += "' type" + "...\n\nCD Layout:\n\n"
        # check if we display layout for compliant cue
        # i.e. source is (or output requested as) compliant
        want_compliant = 0
        if self.is_compl or (self.is_singlefile and not option_.noncompl):
            want_compliant = 1
        for trknum in xrange(meta_.get('numoftracks')):
            gap_str, trk_str, lgth_str = 3 * ['']
            if want_compliant:
                gap = meta_.get('gap', trknum)
            else:
                gap = meta_.get('gap', trknum+1)
            if meta_.get('lgth', trknum):
                real_length = meta_.get('lgth', trknum)
                length = real_length - gap
                trk_str = 'Track %s (%s)\n' % \
                    (str(trknum).zfill(2), aud_.getlength(real_length))
                lgth_str = ' content: %s\n' % (aud_.getlength(length))
            if self.pregap > 0 and trknum == 1:
                statstr += 'Pregap   (%s)\n' % (aud_.getlength(self.pregap))
            statstr += trk_str
            if gap:
                gap_str = '     gap: %s\n' % (aud_.getlength(gap))
                if want_compliant:
                    statstr += gap_str + lgth_str
                else:
                    statstr += lgth_str + gap_str
        statstr += 19 * '-' + '\n         (%s)\n' % \
            (aud_.getlength(meta_.get('duration')))
        pollute(statstr)
    def save(self):
        cue = ''.join(self.sheet)
        meta_.put('cuesheet', cue)
        cue = cue.encode(encoding)
        cutstr = 10 * '- ' + '8< ' + 10 * '- ' + '\n'
        if option_.output:
            result = tryfile(option_.output, 'w')
            result.write(cue)
            result.close()
        else:
            pollute('\nCuesheet:\n\n' + cutstr)
            print cue
            pollute(cutstr)
class Files:
    def write(self):
        n = meta_.get('numoftracks')
        if not argv_.tracks: argv_.tracks = range(n+1)
        for argv_.format in argv_.formats:
            pollute('\nWriting %s files...\n\n' % (argv_.format))
            self.list, self.lgth = [], []
            if meta_.get('is_singlefile'):
                _if = meta_.get('name', 1)
                aud_.fname = _if
                aud_.wav_rd()
                for x in xrange(n):
                    if meta_.get('lgth', x):
                        if meta_.get('idx1', 1) and not option_.notrk0: t = x
                        else                                          : t = x+1
                        if x > argv_.tracks[-1]:
                            aud_.fin.close()
                            exit(exit_str)
                        elif x in argv_.tracks:
                            aud_.fname = meta_.filename(x)
                            aud_.wav_wr()
                            self.list.append(aud_.fname)
                        else:
                            aud_.fname = os.devnull
                            aud_.fout = tryfile(aud_.fname, 'wb')
                        scurr = meta_.get('apos', x-1)
                        snext = meta_.get('apos', x)
                        aud_.hdr_frnum = aud_.frnum = snext - scurr
                        statstr = '%s[%s:%s] > %s\n' % \
                            (_if, aud_.getlength(scurr,'.'),
                            aud_.getlength(snext,'.'), aud_.fname)
                        pollute(statstr, 1)

                        aud_.wr_chunks()
                        aud_.fout.close()
                        subp_.wait_for_child('wr')
                        meta_.tag(aud_.fname, x)
                aud_.fin.close()
                subp_.wait_for_child()
            else:
                _of = meta_.filename(1)
                aud_.fname = _of
                aud_.wav_wr()
                # first getting the aggregate length of requested tracks
                # to write it to wav header
                for x in xrange(n):
                    if meta_.get('lgth', x) and x in argv_.tracks:
                        self.list.append(meta_.get('name', x))
                        self.lgth.append(meta_.get('lgth', x))
                aud_.hdr_frnum = reduce(lambda x, y: x+y, self.lgth)
                for x in xrange(len(self.list)):
                    aud_.frnum = self.lgth[x]
                    aud_.fname = self.list[x]
                    aud_.wav_rd()

                    abs_pos = 0
                    if x: abs_pos = reduce(lambda x, y: x+y, self.lgth[:x])
                    statstr = '%s >> %s @ %s\n' % \
                        (aud_.fname, _of, aud_.getlength(abs_pos))
                    pollute(statstr, 1)

                    aud_.wr_chunks()
                    if aud_.hdr_frnum: aud_.hdr_frnum = 0 # write header only once
                    subp_.wait_for_child()
                    aud_.fin.close()

                aud_.fout.close()
                subp_.wait_for_child('wr')
                meta_.tag(_of)
                self.list = [_of]
            self.apply_rg()
    def apply_rg(self):
        cfg_.section = argv_.format
        if not option_.norg and cfg_.read('rg'):
            pollute('\nApplying replay gain...\n\n')
            statstr = 'RG* (%s)\n' % (', '.join(self.list))
            pollute(statstr, 1)

            aud_.rdcmd = cfg_.get_cmdline('rg', self.list)
            subp_.exec_child()
            subp_.wait_for_child()
    def rm(self):
        pollute('\nDeleting files...\n\n')
        n = meta_.get('numoftracks')
        for x in xrange(1, n):
            if meta_.get('name', x):
                f = meta_.get('name', x)
                pollute('<<< %s\n' % f, 1)
                os.remove(f)

class SubProc:
    def __init__(self):
        from subprocess import Popen, PIPE
        from tempfile import mkstemp
        self.run, self.pipe, self.mktmp = Popen, PIPE, mkstemp
        self.rdproc, self.rdlog, self.wrproc, self.wrlog = 4 * [None]
        self.rddump, self.wrdump = 2 * [-1]
        self.cmd = ''
    def bailout(self, str):
        s = 'While running "%s": %s\n' % \
            (' '.join(self.cmd), str.decode(encoding))
        exit(s, 1)
    def exec_child(self, mode='rd'):
        if mode == 'rd':
            pipe, self.cmd = 'out', aud_.rdcmd
            self.rddump, self.rdlog = self.mktmp('rdlog', 'cueek')
        else:
            pipe, self.cmd = 'in', aud_.wrcmd
            self.wrdump, self.wrlog = self.mktmp('wrlog', 'cueek')
        p = 'self.run(self.cmd, std%s=self.pipe, stderr=self.%sdump)' % \
            (pipe, mode)
        try:
            proc = eval(p)
        except OSError, err:
            self.bailout('Cannot execute the program: %s' % err.strerror)
        if mode == 'rd' : self.rdproc = proc
        else            : self.wrproc = proc
    def wait_for_child(self, mode='rd', kill=0):
        retcode = 0
        if mode == 'rd' : (p, fd, fn) = (self.rdproc, self.rddump, self.rdlog)
        else            : (p, fd, fn) = (self.wrproc, self.wrdump, self.wrlog)
        if p:
            retcode = p.wait()
            if p.stdin : p.stdin.close()
            if p.stdout: p.stdout.close()
        if retcode and not kill:
            log = open(fn)
            errstr = 'Child returned %i: %s\n' % (retcode, log.read().strip())
            log.close()
        try:
            os.close(fd)
            os.remove(fn)
        except OSError:
            pass
        if retcode and not kill: self.bailout(errstr)

def config(option, opt, value, parser=None):
    cfg_file = open(config_file, 'w')
    cfg_file.write(DFLT_CFG)
    cfg_file.close()
    if parser: exit('Configuration written to %s' % config_file)

def tryfile(fn, mode='r'):
    try:
        f = open(fn, mode)
    except IOError, err:
        errstr = 'Failed to open "%s": %s\n' % (err.filename, err.strerror)
        exit(errstr, 1)
    return f

argv_ = Argv()
option_ = argv_.opts
subp_ = SubProc()
cfg_ = Config()
meta_ = Meta()
aud_ = Audio()
cue_ = Cue()

def pollute(s, override=0):
    if not option_.quiet or override:
        if isinstance(s, unicode): s = s.encode(encoding)
        sys.stderr.write(s)
        sys.stderr.flush()

def exit(s, die=0):
    if die:
        s = 'ERROR: ' + s
        pollute(s, 1)
        sys.exit(1)
    else:
        pollute(s)
        sys.exit(0)

def main(fn):
    os.chdir(os.path.split(fn)[0])

    cue_.probe(fn)
    cue_.parse()
    cue_.modify()
    if cue_.is_singlefile:
        cue_.lengths()
    if not option_.quiet: cue_.print_()
    cue_.save()

    if not option_.nowrite:
        files_ = Files()
        files_.write()
        if not option_.nodelete: files_.rm()

    exit(exit_str)

if __name__ == '__main__':
    cuename = os.path.abspath(argv_.args[0])
    main(cuename)
