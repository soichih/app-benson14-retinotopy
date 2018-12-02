####################################################################################################
# neuropythy/util/filemap.py
# Utility for presenting a directory with a particular format as a data structure.
# By Noah C. Benson

import os, warnings, six, tarfile, atexit, shutil, pimms
import numpy          as np
import pyrsistent     as pyr
from   posixpath  import join as urljoin
from   six.moves  import urllib
from   .core      import (library_path, curry, ObjectWithMetaData, AutoDict, data_struct, tmpdir)

@pimms.immutable
class PseudoDir(ObjectWithMetaData):
    '''
    The PseudoDir class represents either directories themselves, tarballs, or URLs as if they were
    directories.
    '''
    _tarball_endings = tuple([('.tar' + s) for s in ('','.gz','.bz2','.lzma')])
    def __init__(self, source_path, cache_path=None, delete=Ellipsis, meta_data=None):
        ObjectWithMetaData.__init__(self, meta_data=meta_data)
        self.source_path = source_path
        self.cache_path = cache_path
        self.delete = delete
    @pimms.param
    def source_path(sp):
        '''
        pseudo_dir.source_path is the source path of the the given pseudo-dir object.
        '''
        if sp is None: return os.path.join('/')
        if not pimms.is_str(sp): raise ValueError('source_path must be a string/path')
        try:
            with urllib.request.urlopen(sp, 'r'): return sp
        except:
            return os.path.expanduser(os.path.expandvars(sp))
    @pimms.param
    def cache_path(cp):
        '''
        pseudo_dir.cache_path is the optionally provided cache path; this is the same as the
        storage path unless this is None.
        '''
        if cp is None: return None
        if not pimms.is_str(cp): raise ValueError('cache_path must be a string')
        return os.path.expanduser(os.path.expandvars(cp))
    @pimms.param
    def delete(d):
        '''
        pseudo_dir.delete is True if the pseudo_dir self-deletes on Python exit and False otherwise;
        if this is Ellipsis, then self-deletes only when the cache-directory is created by the
        PseudoDir class and is a temporary directory (i.e., not explicitly provided).
        '''
        if d in (True, False, Ellipsis): return d
        raise ValueError('delete must be True, False, or Ellipsis')
    @staticmethod
    def _is_url(url):
        try: return bool(urllib.request.urlopen(url))
        except: return False
    @staticmethod
    def _url_get(url, topath):
        # ensure directory exists
        os.makedirs(os.path.dirname(topath))
        if six.PY2:
            response = urllib.request.urlopen(url)
            with open(topath, 'wb') as fl:
                shutil.copyfileobj(response, fl)
        else:
            with urllib.request.urlopen(url) as response:
                with open(topath, 'wb') as fl:
                    shutil.copyfileobj(response, fl)
        return topath
    @staticmethod
    def _url_exists(urlbase, cache_path, path):
        cpath = urljoin(cache_path, path)
        if os.path.exists(cpath): return True
        else: return PseudoDir._is_url(os.path.hoin(urlbase, path))
    @staticmethod
    def _url_getpath(urlbase, cache_path, path):
        cpath = urljoin(cache_path, path)
        if os.path.exists(cpath): return cpath
        url = os.path.join(urlbase, path)
        return PsudoDir._url_get(url, cpath)
    @staticmethod
    def _tar_exists(tarpath, cache_path, path):
        cpath = os.path.join(cache_path, path)
        if os.path.exists(cpath): return True
        with tarfile.open(tarpath, 'r') as tfl:
            try: return bool(tfl.getmember(path))
            except: return False
    @staticmethod
    def _tar_getpath(tarpath, cache_path, path):
        cpath = os.path.join(cache_path, path)
        if os.path.exists(cpath): return cpath
        with tarfile.open(tarpath, 'r') as tfl: tfl.extract(path, cache_path)
        return cpath
    @pimms.value
    def _path_data(source_path, cache_path, delete):
        if os.path.isdir(source_path):
            # just a normal directory... cache path is ignored, delete is ignored
            return pyr.pmap({'repr':    source_path,
                             'exists':  lambda pth: os.path.exists(os.path.join(source_path, pth)),
                             'getpath': lambda pth: os.path.join(source_path, pth),
                             'cache':   None,
                             'join':    os.path.join})
        # Since it's not a directory, we'll need a cache:
        if cache_path is None: cache_path = tmpdir(delete=(True if delete is Ellipsis else delete))
        # S3 not yet supported... #TODO
        if source_path.lower().startswith('s3:'): raise ValueError('S3 URLs are not yet supported')
        # Okay, it might be an Amazon S3 URL; it might be a different URL; it might be a tarball
        if PseudoDir._is_url(source_path):
            def exists_fn(pth):  return PseudoDir._url_exists(source_path,  cache_path, pth)
            def getpath_fn(pth): return PseudoDir._url_getpath(source_path, cache_path, pth)
            return pyr.pmap({'repr':    source_path,
                             'exists':  exists_fn,
                             'getpath': getpath_fn,
                             'cache':   cache_path,
                             'join':    urljoin})
        # Check if it's a "<tarball>:path", like subject10.tar.gz:subject10/"
        ss = next((q for s in PseudoDir._tarball_endings for q in [s+':'] if q in source_path),None)
        if ss is not None:
            spl = source_path.split(ss)
            tb = spl[0] + ss[:-1]
            ip = ss.join(spl[1:])
            def exists_fn(p):  return PseudoDir._tar_exists(tb,  cache_path, os.path.join(ip, p))
            def getpath_fn(p): return PseudoDir._tar_getpath(tb, cache_path, os.path.join(ip, p))
            return pyr.pmap({'repr':source_path, 'exists': exists_fn,
                             'getpath': getpath_fn, 'cache':cache_path, 'join': os.path.join})
        # okay, maybe it's just a tarball by itself...
        ss = next((q for q in PseudoDir._tarball_endings if source_path.endswith(q)), None)
        if ss is not None:
            def exists_fn(p):  return PseudoDir._tar_exists(source_path,  cache_path, p)
            def getpath_fn(p): return PseudoDir._tar_getpath(source_path, cache_path, p)
            return pyr.pmap({'repr':source_path, 'exists': exists_fn,
                             'getpath': getpath_fn, 'cache':cache_path, 'join': os.path.join})
        # ok, don't know what it is...
        raise ValueError('Could not interpret source path: %s' % source_path)
    @pimms.value
    def actual_cache_path(_path_data):
        '''
        pdir.actual_cache_path is the cache path being used by the pseudo-dir pdir; this may differ
          from the pdir.cache_path if the cache_path provided was None yet a temporary cache path
          was needed.
        '''
        return _path_data['cache']
    def __repr__(self):
        p = self._path_data['repr']
        return 'pseudo_dir(%s)' % p
    def join(self, *args):
        '''
        pdir.join(args...) is equivalent to os.path.join(args...) but always appropriate for the
          kind of path represented by the pseudo-dir pdir.
        '''
        join = self._path_data['join']
        return join(*args)
    def find(self, *args):
        '''
        pdir.find(paths...) is similar to to os.path.join(paths...) but it only yields the joined
          relative path if it can be found inside pdir; otherwise None is yielded. Note that this
          does not extract or download the path--it merely ensures that it exists.
        '''
        data = self._path_data
        exfn = data['exists']
        join = data['join']
        path = join(*args)
        return path if exfn(path) else None
    def local_path(self, *args):
        '''
        pdir.local_path(paths...) is similar to os.path.join(pdir, paths...) except that it
          additionally ensures that the path being requested is found in the pseudo-dir pdir then
          ensures that this path can be found in a local directory by downloading or extracting it
          if necessary. The local path is yielded.
        '''
        data = self._path_data
        gtfn = data['getpath']
        join = data['join']
        path = join(*args)
        return gtfn(path)

@pimms.immutable
class FileMap(ObjectWithMetaData):
    '''
    The FileMap class is a pimms immutable class that tracks a set of FileMap format instructions
    with a valid path containing data of that format.
    '''
    def __init__(self, path, instructions, path_parameters=None, data_hierarchy=None,
                 load_function=None, meta_data=None, **kw):
        ObjectWithMetaData.__init__(self, meta_data=meta_data)
        self.path = path
        self.instructions = instructions
        self.data_hierarchy = data_hierarchy
        self.supplemental_paths = kw
        self.path_parameters = path_parameters
        self.load_function = load_function
    _tarball_endings = tuple([('.tar' + s) for s in ('','.gz','.bz2','.lzma')])
    @staticmethod
    def valid_path(p):
        '''
        FileMap.valid_path(path) yields os.path.abspath(path) if path is either a directory or a
          tarball file; otherwise yields None.
        '''
        if os.path.isdir(p): return os.path.abspath(p)
        elif any(p.endswith('.tar' + s) for s in _tarball_endings): return os.path.abspath(p)
        else: return None
    @pimms.param
    def load_function(lf):
        '''
        filemap.load_function is the function used to load data by the filemap. It must accept
        exactly two arguments: filename and filedata. The file-data object is a merged map of both
        the path_parameters, meta_data, and file instruction, left-to-right in that order.
        '''
        if lf is None:
            from ..io import load
            return lambda fl,ii: load(fl)
        else: return lf
    @pimms.param
    def path(p):
        '''
        filemap.path is the root path of the filemap object. 
        '''
        p = FileMap.valid_path(p)
        if p is None: raise ValueError('Path must be a directory or a tarball')
        else: return p
    @pimms.param
    def instructions(inst):
        '''
        filemap.instructions is the map of load/save instructions for the given filemap.
        '''
        if not pimms.is_map(inst) and not isinstance(inst, list):
            raise ValueError('instructions must be a map or a list')
        return pimms.persist(inst)
    @pimms.param
    def data_hierarchy(h):
        '''
        filemap.data_hierarchy is the initial data hierarchy provided to the filemap object.
        '''
        return pimms.persist(h)
    @pimms.param
    def supplemental_paths(sp):
        '''
        filemap.supplemental_paths is a map of additional paths provided to the filemap object.
        '''
        if not pimms.is_map(sp): raise ValueError('supplemental_paths must be a map')
        rr = {}
        for (nm,pth) in six.iteritems(sp):
            pth = FileMap.valid_path(pth)
            if pth is None: raise ValueError('supplemental paths must be directories or tarballs')
            rr[nm] = pth
        return pimms.persist(rr)
    @pimms.param
    def path_parameters(pp):
        '''
        filemap.path_parameters is a map of parameters for the filemap's path.
        '''
        if pp is None: return pyr.m()
        elif not pimms.is_map(pp): raise ValueError('path perameters must be a mapping')
        else: return pimms.persist(pp)
    @staticmethod
    def parse_instructions(inst, hierarchy=None):
        '''
        FileMap.parse_instructions(inst) yields the tuple (data_files, data_tree); data_files is a
          map whose keys are relative filenames and whose values are the instruction data for the
          given file; data_tree is a lazy/nested map structure of the instruction data using 'type'
          as the first-level keys.

        The optional argument hierarchy specifies the hierarchy of the data to return in the
        data_tree. For example, if hierarchy is ['hemi', 'surface', 'roi'] then a file with the
        instructions {'type':'property', 'hemi':'lh', 'surface':'white', 'roi':'V1', 'name':'x'}
        would appear at data_tree['hemi']['lh']['surface']['white']['roi']['V1']['property']['x']
        whereas if hierarchy were ['roi', 'hemi', 'surface'] it would appear at
        data_tree['roi']['V1']['surface']['white']['hemi']['lh']['property']['x']. By default the
        ordering is undefined.
        '''
        dirstack = []
        data_tree = {}
        data_files = {}
        hierarchies = hierarchy if hierarchy else []
        if len(hierarchies) > 0 and pimms.is_str(hierarchies[0]): hierarchies = [hierarchies]
        known_filekeys = ('load','filt','when','then','miss')
        hierarchies = list(hierarchies)
        def handle_file(inst):
            # If it's a tuple, we just do each of them
            if isinstance(inst, tuple):
                for ii in inst: handle_file(ii)
                return None
            # first, walk the hierarchies; if we find one that matches, we use it; otherwise we make
            # one up
            dat = None
            for hrow in hierarchies:
                if not all(h in inst for h in hrow): continue
                dat = data_tree
                for h in hrow:
                    v = inst[h]
                    if h not in dat: dat[h] = {}
                    dat = dat[h]
                    if v not in dat: dat[v] = {}
                    dat = dat[v]
                break
            if dat is None:
                # we're gonna make up a hierarchy
                hh = []
                dat = data_tree
                for (k,v) in six.iteritems(inst):
                    if k in known_filekeys: continue
                    hh.append(k)
                    if k not in dat: dat[k] = {}
                    dat = dat[k]
                    if v not in dat: dat[v] = {}
                    dat = dat[v]
                # append this new hierarchy to the hierarchies
                hierarchies.append(hh)
            # Okay, we have the data, get the filename
            flnm = os.path.join(*dirstack)
            # add this data ot the data tree
            dat[flnm] = pyr.pmap(inst).set('_relpath', flnm)
            data_files[flnm] = inst
            return None
        def handle_dir(inst):
            # iterate over members
            dnm = None
            for k in inst:
                if dnm: dnm = handle_inst(k, dnm)
                elif pimms.is_str(k): dnm = k
                elif not isinstance(k, tuple) or len(k) != 2: raise ValueError('Bad dir content')
                else: dnm = handle_inst(k, dnm)
            return None
        def handle_inst(inst, k=None):
            if k: dirstack.append(k)
            if pimms.is_map(inst): handle_file(inst)
            elif isinstance(inst, (list, tuple)):
                if len(inst) == 0 or not pimms.is_map(inst[0]): handle_dir(inst)
                else: handle_file(inst)
            else: raise ValueError('Illegal instruction type: %s' % (inst,))
            if k: dirstack.pop()
            return None
        handle_inst(inst)
        return (data_files, data_tree)
    @pimms.value
    def _parsed_instructions(instructions, data_hierarchy):
        return pimms.persist(FileMap.parse_instructions(instructions, data_hierarchy))
    @staticmethod
    def _load(pathgen, flnm, loadfn, *argmaps, **kwargs):
        try:
            fnm = pathgen(flnm)
            args = pimms.merge(*argmaps, **kwargs)
            loadfn = inst['load'] if 'load' in args else loadfn
            filtfn = inst['filt'] if 'filt' in args else lambda x,y:x
            dat = loadfn(fnm, args)
            dat = filtfn(dat, args)
        except: dat = None
        # check for miss instructions if needed
        if dat is None and 'miss' in args:
            miss = args['miss']
        elif pimms.is_str(miss) and miss.lower() in ('error','raise','exception'):
            raise ValueError('File %s failed to load' % flnm)
        elif miss is not None:
            dat = miss(flnm, args)
        return dat
    @staticmethod
    def _path_to_pathgen(path):
        path = os.path.expanduser(os.path.expandvars(path))
        if any(path.endswith(s) for s in FileMap._tarball_endings):
            tbnm = path
            tbpx = []
        else:
            s = next((s for s in FileMap._tarball_endings if (s + ':') in path), None)
            if s is None: return (path, lambda fnm: os.path.join(path, fnm))
            ss = path.split(s)
            tbnm = ss[0]
            tbpx = [':'.join(ss[1:])]
        tdir = tmpdir()
        def _into_tdir(flnm):
            tdir_flnm = os.path.join(*([tdir] + tbpx + [flnm]))
            if not os.path.exist(tdir_flnm):
                trbl_flnm = os.path.join(*(tbpx + [flnm]))
                with tarfile.open(tbnm, 'r') as tfl: tfl.extract(trbl_flnm, tdir_flnm)
            return tdir_flnm
        return (tdir, _into_tdir)
    @staticmethod
    def _parse_path(flnm, path, spaths, path_parameters, inst):
        flnm = flnm.format(**pimms.merge(path_parameters, inst))
        p0 = None
        for k in six.iterkeys(spaths):
            if flnm.startswith(k + ':'):
                (flnm, p0) = (flnm[(len(k)+1):], k)
                break
        return (p0, flnm)
    @pimms.value
    def data_files(path, supplemental_paths, path_parameters, load_function, meta_data,
                   _parsed_instructions):
        '''
        filemap.data_files is a lazy map whose keys are filenames and whose values are the loaded
        files.
        '''
        spaths = {s:_path_to_pathgen(p) for (s,p) in six.iteritems(supplemental_paths)}
        spaths[None] = _path_to_pathgen(path)
        (data_files, data_tree) = _parsed_instructions
        def load_via_pathgen(pathnm, flnm, inst):
            (p, pg) = spaths[pathnm]
            try:
                return FileMap._load(pg, flnm, load_function, path_parameters, meta_data, inst)
            except:
                return None
        res = {}
        for (flnm, inst) in six.iteritems(data_files):
            (pathnm, flnm) = FileMap._parse_path(flnm, path,
                                                 supplemental_paths, path_parameters, inst)
            res[fn] = curry(FileMap._load,
                            spaths[pathnm], flnm, load_function,
                            path_parameters, meta_data, inst)
        return pimms.lazy_map(res)
    @pimms.value
    def data_tree(_parsed_instructions, path, supplemental_paths, path_parameters, data_files):
        '''
        filemap.data_tree is a lazy data-structure of the data loaded by the filemap's instructions.
        '''
        data_tree = _parsed_instructions[1]
        class _tmp:
            ident = 0
        def visit_data(d):
            d = {k:visit_maps(v) for (k,v) in six.iteritems(d)}
            return data_struct(d)
        def visit_maps(m):
            r = {}
            anylazy = False
            for (k,v) in six.iteritems(m):
                kk = k if isinstance(k, tuple) else [k]
                for k in kk:
                    if len(v) > 0 and '_relpath' in next(six.itervalues(v)):
                        (flnm,inst) = next(six.iteritems(v))
                        flnm = FileMap._deduce_filename(flnm, path, supplemental_paths,
                                                        path_parameters, inst)
                        r[k] = curry(lambda flnm:data_files[flnm], flnm)
                        anylazy = True
                    else: r[k] = visit_data(v)
            return pimms.lazy_map(r) if anylazy else pyr.pmap(r)
        return visit_data(data_tree)
def file_map(path, instructions, **kw):
    '''
    file_map(path, instructions) yields a file-map object for the given path and instruction-set.
    file_map(None, instructions) yields a lambda of exactly one argument that is equivalent to the
      following:  lambda p: file_map(p, instructions)
    
    File-map objects are pimms immutable objects that combine a format-spec for a directory 
    (instructions) with a directory to yield a lazily-loaded data object. The format-spec is not
    currently documented, but interested users should see the variable
    neuropythy.hcp.files.hcp_filemap_instructions.
    
    The following options can be given:
     * path_parameters (default: None) may be set to a map of parameters that are used to format the
       filenames in the instructions.
     * data_hierarchy (default: None) may specify how the data should be nested; see the variable
       neuropythy.hcp.files.hcp_filemap_data_hierarchy.
     * load_function (default: None) may specify the function that is used to load filenames; if
       None then neuropythy.io.load is used.
     * meta_data (default: None) may be passed on to the FileMap object.

    Any additional keyword arguments given to the file_map function will be used as supplemental
    paths.
    '''
    if path: return FileMap(path, instructions, **kw)
    else:    return lambda path:file_map(path, instructions, **kw)