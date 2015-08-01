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

	print "Setting up releases directory for %s" % feed.get_name()

	master_feed_name = feed.get_name().replace(' ', '-') + '.xml'

	if os.name == 'nt':
		make_release = file('make-release.bat', 'w')
		make_release.write("""@echo off

:: The directory people will download the releases from.
:: This will appear in the remote feed file.
::set ARCHIVE_DIR_PUBLIC_URL=http://placeholder.org/releases/%%RELEASE_VERSION%%
set ARCHIVE_DIR_PUBLIC_URL=

:: The path to the main feed.
:: The new version is added here when you publish a release.
::set MASTER_FEED_FILE="$HOME/public_html/feeds/MyProg.xml"
set MASTER_FEED_FILE=%s

:: A shell command to upload the generated archive file to the
:: public server (corresponds to %%ARCHIVE_DIR_PUBLIC_URL%%, which is
:: used to download it again).
:: If unset, you'll have to upload it yourself.
::set ARCHIVE_UPLOAD_COMMAND=scp %%* me@myhost:/var/www/releases/%%RELEASE_VERSION%%/
set ARCHIVE_UPLOAD_COMMAND=

:: A shell command to upload the master feed (%%MASTER_FEED_FILE%%) and
:: related files to your web server. It will be downloaded using the
:: feed's URL. If unset, you'll have to upload it yourself.
::set MASTER_FEED_UPLOAD_COMMAND=scp %%* me@myhost:/var/www/feeds/
set MASTER_FEED_UPLOAD_COMMAND=

:: Your public version control repository. When publishing, the new
:: HEAD and the release tag will be pushed to this using a command
:: such as "git-push main master v0.1"
:: If unset, you'll have to update it yourself.
::set PUBLIC_SCM_REPOSITORY=origin
set PUBLIC_SCM_REPOSITORY=

cd /d "%%~dp0"
0launch %s --release %s ^
 --archive-dir-public-url="%%ARCHIVE_DIR_PUBLIC_URL%%" ^
 --master-feed-file="%%MASTER_FEED_FILE%%" ^
 --archive-upload-command="%%ARCHIVE_UPLOAD_COMMAND%%" ^
 --master-feed-upload-command="%%MASTER_FEED_UPLOAD_COMMAND%%" ^
 --public-scm-repository="%%PUBLIC_SCM_REPOSITORY%%" ^
 %%*
""" % (master_feed_name, release_uri, feed.local_path))
		make_release.close()
		print "Success - created script:\n %s" % os.path.abspath('make-release.bat')
	else:
		make_release = file('make-release', 'w')
		make_release.write("""#!/bin/sh

# The directory people will download the releases from.
# This will appear in the remote feed file.
#ARCHIVE_DIR_PUBLIC_URL='http://placeholder.org/releases/$RELEASE_VERSION'
ARCHIVE_DIR_PUBLIC_URL=

# The path to the main feed.
# The new version is added here when you publish a release.
#MASTER_FEED_FILE="$HOME/public_html/feeds/MyProg.xml"
MASTER_FEED_FILE="%s"

# A shell command to upload the generated archive file to the
# public server (corresponds to $ARCHIVE_DIR_PUBLIC_URL, which is
# used to download it again).
# If unset, you'll have to upload it yourself.
#ARCHIVE_UPLOAD_COMMAND='scp "$@" me@myhost:/var/www/releases/$RELEASE_VERSION/'
ARCHIVE_UPLOAD_COMMAND=

# A shell command to upload the master feed ($MASTER_FEED_FILE) and
# related files to your web server. It will be downloaded using the
# feed's URL. If unset, you'll have to upload it yourself.
#MASTER_FEED_UPLOAD_COMMAND='scp "$@" me@myhost:/var/www/feeds/'
MASTER_FEED_UPLOAD_COMMAND=

# Your public version control repository. When publishing, the new
# HEAD and the release tag will be pushed to this using a command
# such as "git-push main master v0.1"
# If unset, you'll have to update it yourself.
#PUBLIC_SCM_REPOSITORY=origin
PUBLIC_SCM_REPOSITORY=

cd `dirname "$0"`
exec 0launch %s --release %s \\
 --archive-dir-public-url="$ARCHIVE_DIR_PUBLIC_URL" \\
 --master-feed-file="$MASTER_FEED_FILE" \\
 --archive-upload-command="$ARCHIVE_UPLOAD_COMMAND" \\
 --master-feed-upload-command="$MASTER_FEED_UPLOAD_COMMAND" \\
 --public-scm-repository="$PUBLIC_SCM_REPOSITORY" \\
 "$@"
""" % (master_feed_name, release_uri, feed.local_path))
		make_release.close()
		os.chmod('make-release', 0775 & ~umask)
		print "Success - created script:\n %s" % os.path.abspath('make-release')
	print "Now edit it with your local settings."
	print "Then, create new releases by running it."
