# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os
from zeroinstall import SafeException

release_uri = 'http://0install.net/2007/interfaces/0release.xml'

umask = os.umask(0)
os.umask(umask)

def init_releases_directory(feed):
	files = os.listdir('.')
	if files:
		raise SafeException("This command must be run from an empty directory!\n(this one contains %s)" % (', '.join(files[:5])))

	print("Setting up releases directory for %s" % feed.get_name())

	master_feed_name = feed.get_name().replace(' ', '-') + '.xml'

	if os.name == 'nt':
		make_release = file('make-release.bat', 'w')
		make_release.write("""@echo off

:: Your public version control repository. When publishing, the new
:: HEAD and the release tag will be pushed to this using a command
:: such as "git push origin master v0.1"
:: If unset, you'll have to update it yourself.
::set PUBLIC_SCM_REPOSITORY=origin
set PUBLIC_SCM_REPOSITORY=

cd /d "%%~dp0"
0launch %s --release %s ^
 --public-scm-repository="%%PUBLIC_SCM_REPOSITORY%%" ^
 %%*
""" % (master_feed_name, release_uri, feed.local_path))
		make_release.close()
		print("Success - created script:\n %s" % os.path.abspath('make-release.bat'))
	else:
		make_release = file('make-release', 'w')
		make_release.write("""#!/bin/sh

# Your public version control repository. When publishing, the new
# HEAD and the release tag will be pushed to this using a command
# such as "git push origin master v0.1"
# If unset, you'll have to update it yourself.
#PUBLIC_SCM_REPOSITORY=origin
PUBLIC_SCM_REPOSITORY=

cd `dirname "$0"`
exec 0launch %s \\
 --release %s \\
 --public-scm-repository="$PUBLIC_SCM_REPOSITORY" \\
 "$@"
""" % (release_uri, feed.local_path))
		make_release.close()
		os.chmod('make-release', 0o775 & ~umask)
		print("Success - created script:\n %s" % os.path.abspath('make-release'))
	print("Now edit it with your local settings.")
	print("Then, create new releases by running it.")
