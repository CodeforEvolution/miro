#!/usr/bin/env python

# Miro - an RSS based video player application
# Copyright (C) 2005, 2006, 2007, 2008, 2009, 2010, 2011
# Participatory Culture Foundation
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301 USA
#
# In addition, as a special exception, the copyright holders give
# permission to link the code of portions of this program with the OpenSSL
# library.
#
# You must obey the GNU General Public License in all respects for all of
# the code used other than OpenSSL. If you modify file(s) with this
# exception, you may extend this exception to your version of the file(s),
# but you are not obligated to do so. If you do not wish to do so, delete
# this exception statement from your version. If you delete this exception
# statement from all source files in the program, then also delete it here.

################################################################
## No user-serviceable parts inside                           ##
################################################################

import sys

# verify we have required bits for compiling Miro

from distutils import ccompiler
from distutils.cmd import Command
from distutils.core import setup
from distutils.extension import Extension
from distutils.errors import DistutilsOptionError
from distutils.util import change_root
from glob import glob
from string import Template
from distutils.command.build import build
from distutils.command.install_data import install_data
import os
import platform
import pwd
import subprocess
import time
import shutil



#### useful paths to have around ####
def is_root_dir(d):
    return os.path.exists(os.path.join(d, "MIRO_ROOT"))


def get_root_dir():
    root_try = os.path.abspath(os.path.dirname(__file__))
    while True:
        if is_root_dir(root_try):
            root_dir = root_try
            break
        if root_try == '/':
            raise RuntimeError("Couldn't find Miro root directory")
        root_try = os.path.abspath(os.path.join(root_try, '..'))
    return root_dir

root_dir = get_root_dir()
git_root_dir = os.path.dirname(root_dir)
portable_dir = os.path.join(root_dir, 'lib')
portable_frontend_dir = os.path.join(portable_dir, 'frontends')
portable_xpcom_dir = os.path.join(portable_frontend_dir, 'widgets', 'gtk',
                                  'xpcom')
dl_daemon_dir = os.path.join(portable_dir, 'dl_daemon')
test_dir = os.path.join(portable_dir, 'test')
resource_dir = os.path.join(root_dir, 'resources')
extensions_dir = os.path.join(root_dir, 'extensions')
platform_dir = os.path.join(root_dir, 'haiku')
platform_package_dir = os.path.join(platform_dir, 'plat')
platform_widgets_dir = os.path.join(platform_package_dir, 'frontends',
                                    'widgets')
platform_extensions_dir = os.path.join(platform_dir, 'extensions')

# insert the root_dir to the beginning of sys.path so that we can
# pick up portable and other packages
sys.path.insert(0, root_dir)

# little hack to get the version from the current app.config.template

app_config = os.path.join(resource_dir, 'app.config.template')
appVersion = 6.0


def getlogin():
    """Does a best-effort attempt to return the login of the user running the
    script.
    """
    try:
        return os.environ['LOGNAME']
    except KeyError:
        pass
    try:
        return os.environ['USER']
    except KeyError:
        pass
    pwd.getpwuid(os.getuid())[0]


def read_file(path):
    f = open(path)
    try:
        return f.read()
    finally:
        f.close()


def write_file(path, contents):
    f = open(path, 'w')
    try:
        f.write(contents)
    finally:
        f.close()


def expand_file_contents(path, **values):
    """Do a string expansion on the contents of a file using the same
    rules as string.Template from the standard library.
    """
    template = Template(read_file(path))
    expanded = template.substitute(**values)
    write_file(path, expanded)


def get_command_output(cmd, warnOnStderr=True, warnOnReturnCode=True):
    """Wait for a command and return its output.  Check for common
    errors and raise an exception if one of these occurs.
    """
    p = subprocess.Popen(cmd, shell=True, close_fds=True,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = p.communicate()
    if warnOnStderr and stderr != '':
        raise RuntimeError("%s outputted the following error:\n%s" %
                           (cmd, stderr))
    if warnOnReturnCode and p.returncode != 0:
        raise RuntimeError("%s had non-zero return code %d" %
                           (cmd, p.returncode))
    return stdout


def parse_pkg_config(command, components, options_dict=None):
    """Helper function to parse compiler/linker arguments from
    pkg-config and update include_dirs, library_dirs, etc.

    We return a dict with the following keys, which match up with
    keyword arguments to the setup function: include_dirs,
    library_dirs, libraries, extra_compile_args.

    Command is the command to run (pkg-config, etc).  Components is a
    string that lists the components to get options for.

    If options_dict is passed in, we add options to it, instead of
    starting from scratch.
    """
    if options_dict is None:
        options_dict = {
            'include_dirs': [],
            'library_dirs': [],
            'libraries': [],
            'extra_compile_args': []
        }
    
    commandLine = "%s --cflags --libs %s" % (command, components)
    output = get_command_output(commandLine).strip()
    
    for comp in output.split():
        prefix, rest = comp[:2], comp[2:]
        if prefix == '-I':
            options_dict['include_dirs'].append(rest)
        elif prefix == '-L':
            options_dict['library_dirs'].append(rest)
        elif prefix == '-l':
            options_dict['libraries'].append(rest)
            

    commandLine = "%s --variable=libdir %s" % (command, components)
    output = get_command_output(commandLine).strip()

    return options_dict


def package_exists(package_name):
    """
    Return True if the package is present in the system.  False
    otherwise.  The check is made with pkg-config.
    """
    # pkg-config returns 0 if the package is present
    return subprocess.call(['pkg-config', '--exists', package_name]) == 0

namecollation_ext = \
    Extension("miro.data.namecollation",
        [os.path.join(portable_dir, 'data', 'namecollation.cpp')],
        libraries=['sqlite3'],
    )

fixedliststore_dir = os.path.join(portable_frontend_dir, 'widgets', 'gtk',
                                  'fixedliststore')

#### Build the data_files list ####
def listfiles(path):
    all_files = [f for f in glob(os.path.join(path, '*')) if os.path.isfile(f)
                 if not f.endswith("~")]
    return all_files

script_files = []
data_files = []
# append the root resource directory.
# filter out app.config.template (which is handled specially)
files = [f for f in listfiles(resource_dir) \
        if os.path.basename(f) != 'app.config.template']
data_files.append(('/boot/system/non-packaged/data/miro/resources/', files))

# handle the sub directories.
for dir in ('searchengines', 'images', 'conversions', 'devices'):
    source_dir = os.path.join(resource_dir, dir)
    dest_dir = os.path.join('/boot/system/non-packaged/data/miro/resources/', dir)
    data_files.append((dest_dir, listfiles(source_dir)))
for path, dirs, files in os.walk(os.path.join(resource_dir, 'testdata')):
    relpath = os.path.relpath(path, resource_dir)
    dest_dir = os.path.join('/boot/system/non-packaged/data/miro/resources/', relpath)
    files = [os.path.join(resource_dir, relpath, f) for f in files]
    data_files.append((dest_dir, files))

data_files.append((dest_dir, [os.path.join(resource_dir, 'donate.html')]))

# add core extension files
for root, dirs, files in os.walk(extensions_dir):
    extroot = root[len(extensions_dir) + 1:]
    files = [os.path.join(root, f) for f in files
             if (not f.endswith("~") and not "#" in f)]
    data_files.append((
        os.path.join('/boot/system/non-packaged/data/miro/resources/extensions/', extroot),
        files))

# add core platform extension files
for root, dirs, files in os.walk(platform_extensions_dir):
    extroot = root[len(platform_extensions_dir) + 1:]
    files = [os.path.join(root, f) for f in files
             if (not f.endswith("~") and not "#" in f)]
    data_files.append((
        os.path.join('/boot/system/non-packaged/data/miro/resources/extensions/', extroot),
        files))

# add the desktop file, mime data, and man page
data_files += [
    ('/boot/system/non-packaged/data/miro/resources',
     [os.path.join(root_dir, 'CREDITS')]),
    ('/boot/system/non-packaged/documentation/man/man1',
     [os.path.join(platform_dir, 'Miro.1')]),
]

#### Our specialized install_data command ####
class miro_install_data(install_data):
    """miro_install_data extends to default implementation so that it
    automatically installs app.config from app.config.template.
    """

    def install_app_config(self):
        source = os.path.join(resource_dir, 'app.config.template')
        dest = '/boot/system/non-packaged/data/miro/resources/app.config'

        from miro import buildutils

        config_file = buildutils.read_simple_config_file(source)
        print "Trying to figure out the git revision...."
        if config_file["appVersion"].endswith("git"):
            revision = buildutils.query_revision()
            if revision is None:
                revision = "unknown"
                revisionurl = "unknown"
                revisionnum = "unknown"
            else:
                revisionurl = revision[0]
                revisionnum = revision[1]
                revision = "%s - %s" % (revisionurl, revisionnum)
        else:
            revisionurl = ""
            revisionnum = ""
            revision = ""
        print "Using %s" % revisionnum

        if self.root:
            dest = change_root(self.root, dest)
        self.mkpath(os.path.dirname(dest))
        # We don't use the dist utils copy_file() because it only copies
        # the file if the timestamp is newer
        shutil.copyfile(source, dest)
        expand_file_contents(dest, APP_REVISION=revision,
                             APP_REVISION_NUM=revisionnum,
                             APP_REVISION_URL=revisionurl,
                             APP_PLATFORM='haiku',
                             BUILD_MACHINE="%s@%s" % (getlogin(),
                                                      os.uname()[1]),
                             BUILD_TIME=str(time.time()),
                             MOZILLA_LIB_PATH="")
        self.outfiles.append(dest)

        locale_dir = os.path.join(resource_dir, "locale")

        for source in glob(os.path.join(locale_dir, "*.mo")):
            lang = os.path.basename(source)[:-3]
            if 'LINGUAS' in os.environ and lang not in os.environ['LINGUAS']:
                continue
            dest = '/boot/system/non-packaged/data/locale/%s/LC_MESSAGES/miro.mo' % lang
            if self.root:
                dest = change_root(self.root, dest)
            self.mkpath(os.path.dirname(dest))
            self.copy_file(source, dest)
            self.outfiles.append(dest)

    def run(self):
        install_data.run(self)
        self.install_app_config()

class miro_build(build):
    def build_segmenter(self):
        segmenter_src = os.path.join(platform_dir, 'miro-segmenter.c')
        cc = ccompiler.new_compiler()
        cc.add_library('avutil')
        cc.add_library('avformat')
        cc.add_library('avcodec')
        cc.add_library('network')
        cc.add_include_dir('/boot/system/develop/headers/ffmpeg')
        output_dir = os.path.join(self.build_base, 'miro-segmenter')
        segmenter_objs = cc.compile([segmenter_src],
                                    output_dir=output_dir,
                                    extra_preargs=(os.environ.get("CFLAGS") or "").split())
        cc.link_executable(segmenter_objs, 'miro-segmenter',
                           output_dir=output_dir)
        segmenter_exe = os.path.join(output_dir, 'miro-segmenter')
        self.distribution.scripts.append(segmenter_exe)

    def run(self):
        self.build_segmenter()
        build.run(self)

class test_system(Command):
    description = ("Allows you to test configurations without compiling "
                   "or running.")
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        # FIXME - try importing and all that other stuff to make sure
        # we have most of the pieces here?
        pass


#### install_theme installs a specified theme .zip
class install_theme(Command):
    description = 'Install a provided theme to /boot/system/data/miro/themes'
    user_options = [("theme=", None, 'ZIP file containing the theme')]

    def initialize_options(self):
        self.theme = None

    def finalize_options(self):
        if self.theme is None:
            raise DistutilsOptionError("must supply a theme ZIP file")
        if not os.path.exists(self.theme):
            raise DistutilsOptionError("theme file does not exist")
        import zipfile
        if not zipfile.is_zipfile(self.theme):
            raise DistutilsOptionError("theme file is not a ZIP file")
        zf = zipfile.ZipFile(self.theme)
        appConfig = zf.read('app.config')
        themeName = None
        for line in appConfig.split('\n'):
            if '=' in line:
                name, value = line.split('=', 1)
                name = name.strip()
                value = value.lstrip()
                if name == 'themeName':
                    themeName = value
        if themeName is None:
            raise DistutilsOptionError("invalid theme file")
        self.zipfile = zf
        self.theme_name = themeName
        self.theme_dir = '/boot/system/non-packaged/data/miro/themes/%s' % themeName

    def run(self):
        if os.path.exists(self.theme_dir):
            shutil.rmtree(self.theme_dir)
        os.makedirs(self.theme_dir)
        for name in self.zipfile.namelist():
            if name.startswith('xul/'):
                # ignore XUL stuff, we don't need it on Haiku
                continue
            print 'installing', os.path.join(self.theme_dir, name)
            if name[-1] == '/':
                os.makedirs(os.path.join(self.theme_dir, name))
            else:
                f = file(os.path.join(self.theme_dir, name), 'wb')
                f.write(self.zipfile.read(name))
                f.close()
        print """%s theme installed.

To use this theme, run:

    miro --theme="%s"
""" % (self.theme_name, self.theme_name)


class clean(Command):
    description = 'Cleans the build and dist directories'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        if os.path.exists('./build/'):
            print "removing build directory"
            shutil.rmtree('./build/')

        if os.path.exists('./dist/'):
            print "removing dist directory"
            shutil.rmtree('./dist/')


ext_modules = []

script_files += [os.path.join(platform_dir, 'Miro'),
                ]

#### Run setup ####
setup(name='miro',
    version=appVersion,
    author='Participatory Culture Foundation',
    author_email='feedback@pculture.org',
    url='http://www.getmiro.com/',
    download_url='http://www.getmiro.com/downloads/',
    scripts=script_files,
    data_files=data_files,
    ext_modules=ext_modules,
    packages=[
        'miro',
        'miro.libdaap',
        'miro.data',
        'miro.dl_daemon',
        'miro.test',
        'miro.dl_daemon.private',
        'miro.frontends',
        'miro.frontends.cli',
        'miro.frontends.profilewidgets',
        'miro.frontends.shell',
        'miro.frontends.widgets',
        'miro.frontends.widgets.gst',
        'miro.frontends.widgets.gtk',
        'miro.plat',
        'miro.plat.frontends',
        'miro.plat.frontends.widgets',
    ],
    package_dir={
        'miro': portable_dir,
        'miro.test': test_dir,
        'miro.plat': platform_package_dir,
    },
    cmdclass={
        'test_system': test_system,
        'build': miro_build,
        'install_data': miro_install_data,
        'install_theme': install_theme,
        'clean': clean,
    }
)
