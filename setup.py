import os, sys
from zeroinstall import SafeException
from zeroinstall.injector import reader, model

release_uri = '/home/talex/Projects/zero-install/0release/0release.xml'

umask = os.umask(0)
os.umask(umask)

def init_releases_directory(iface):
	files = os.listdir('.')
	if files:
		raise SafeException("This command must be run from an empty directory!\n(this one contains %s)" % (', '.join(files[:5])))

	print "Setting up releases directory for %s" % iface.get_name()

	make_release = file('make-release', 'w')
	make_release.write("""#!/bin/sh
cd `dirname "$0"`
0launch %s --release %s "$@"
""" % (release_uri, iface.uri))
	make_release.close()
	os.chmod('make-release', 0775 & ~umask)
	print "Success! To create new releases, run %s" % os.path.abspath('make-release')
