# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

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

	master_feed_name = iface.get_name().replace(' ', '-') + '.xml'

	make_release = file('make-release', 'w')
	make_release.write("""#!/bin/sh

# The directory people will download the releases from.
# This will appear in the remote feed file.
#ARCHIVE_DIR_PUBLIC_URL=http://placeholder.org/releases
ARCHIVE_DIR_PUBLIC_URL=

# The path to the main feed.
# The new version is added here when you publish a release.
#MASTER_FEED_FILE="$HOME/public_html/feeds/MyProg.xml"
MASTER_FEED_FILE="%s"

# A shell command to upload the generated archive file to the
# public server (corresponds to $ARCHIVE_DIR_PUBLIC_URL, which is
# used to download it again).
#ARCHIVE_UPLOAD_COMMAND='scp "$@" me@myhost:/var/www/releases/'
ARCHIVE_UPLOAD_COMMAND=

# A shell command to upload the master feed ($MASTER_FEED_FILE)
# to your web server. It will be downloaded using the feed's URL.
#MASTER_FEED_UPLOAD_COMMAND='scp "$@" me@myhost:/var/www/feeds/'
MASTER_FEED_UPLOAD_COMMAND=

cd `dirname "$0"`
exec 0launch %s --release %s \\
 --archive-dir-public-url="$ARCHIVE_DIR_PUBLIC_URL" \\
 --master-feed-file="$MASTER_FEED_FILE" \\
 --archive-upload-command="$ARCHIVE_UPLOAD_COMMAND" \\
 --master-feed-upload-command="$MASTER_FEED_UPLOAD_COMMAND" \\
 "$@"
""" % (master_feed_name, release_uri, iface.uri))
	make_release.close()
	os.chmod('make-release', 0775 & ~umask)
	print "Success - created script:\n %s\nNow edit it with your local settings." % os.path.abspath('make-release')
	print "Then, create new releases by running it."
