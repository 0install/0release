# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import copy
import os, subprocess, tarfile, platform
import urllib.parse, ftplib, http.client
from xml.dom import minidom

from zeroinstall import SafeException
from zeroinstall.injector import model, qdom, namespaces
from zeroinstall.support import ro_rmtree, portable_rename
from logging import info

release_status_file = os.path.abspath('release-status')

def check_call(*args, **kwargs):
	exitstatus = subprocess.call(*args, **kwargs)
	if exitstatus != 0:
		if type(args[0]) == str:
			cmd = args[0]
		else:
			cmd = ' '.join(args[0])
		raise SafeException("Command failed with exit code %d:\n%s" % (exitstatus, cmd))

def show_and_run(cmd, args):
	print("Executing: %s %s" % (cmd, ' '.join("[%s]" % x for x in args)))
	check_call(['sh', '-c', cmd, '-'] + args)

def suggest_release_version(snapshot_version):
	"""Given a snapshot version, suggest a suitable release version.
	>>> suggest_release_version('1.0-pre')
	'1.0'
	>>> suggest_release_version('0.9-post')
	'0.10'
	>>> suggest_release_version('3')
	Traceback (most recent call last):
		...
	SafeException: Version '3' is not a snapshot version (should end in -pre or -post)
	"""
	version = model.parse_version(snapshot_version)
	mod = version[-1]
	if mod == 0:
		raise SafeException("Version '%s' is not a snapshot version (should end in -pre or -post)" % snapshot_version)
	if mod > 0:
		# -post, so increment the number
		version[-2][-1] += 1
	version[-1] = 0	# Remove the modifier
	return model.format_version(version)

def publish(feed_path, **kwargs):
	args = [os.environ['ZI_PUBLISH']]
	for k in kwargs:
		value = kwargs[k] 
		if value is True:
			args += ['--' + k.replace('_', '-')]
		elif value is not None:
			if platform.system() == 'Windows':
				args += ['--' + k.replace('_', '-') + "='" + value + "'"]
			else:
				args += ['--' + k.replace('_', '-'), value]
	args.append(feed_path)
	info("Executing %s", args)
	check_call(args)

def get_singleton_impl(feed):
	impls = feed.implementations
	if len(impls) != 1:
		raise SafeException("Local feed '%s' contains %d versions! I need exactly one!" % (feed.url, len(impls)))
	return list(impls.values())[0]

def backup_if_exists(name):
	if not os.path.exists(name):
		return
	backup = name + '~'
	if os.path.exists(backup):
		print("(deleting old backup %s)" % backup)
		if os.path.isdir(backup):
			ro_rmtree(backup)
		else:
			os.unlink(backup)
	portable_rename(name, backup)
	print("(renamed old %s as %s; will delete on next run)" % (name, backup))

def get_choice(options):
	while True:
		choice = input('/'.join(options) + ': ').lower()
		if not choice: continue
		for o in options:
			if o.lower().startswith(choice):
				return o

def make_archive_name(feed_name, version):
	return feed_name.lower().replace(' ', '-') + '-' + version

def in_PATH(prog):
	for x in os.environ['PATH'].split(':'):
		if os.path.isfile(os.path.join(x, prog)):
			return True
	return False

def show_diff(from_dir, to_dir):
	for cmd in [['meld'], ['xxdiff'], ['diff', '-ur']]:
		if in_PATH(cmd[0]):
			code = os.spawnvp(os.P_WAIT, cmd[0], cmd + [from_dir, to_dir])
			if code:
				print("WARNING: command %s failed with exit code %d" % (cmd, code))
			return

class Status(object):
	__slots__ = ['old_snapshot_version', 'release_version', 'head_before_release', 'new_snapshot_version',
		     'head_at_release', 'created_archive', 'src_tests_passed', 'tagged']
	def __init__(self):
		for name in self.__slots__:
			setattr(self, name, None)

		if os.path.isfile(release_status_file):
			with open(release_status_file, 'r') as stream:
				for line in stream.readlines():
					assert line.endswith('\n')
					line = line[:-1]
					name, value = line.split('=')
					setattr(self, name, value)
					info("Loaded status %s=%s", name, value)

	def save(self):
		tmp_name = release_status_file + '.new'
		try:
			with open(tmp_name, 'w') as tmp:
				lines = ["%s=%s\n" % (name, getattr(self, name)) for name in self.__slots__ if getattr(self, name)]
				tmp.write(''.join(lines))
			portable_rename(tmp_name, release_status_file)
			info("Wrote status to %s", release_status_file)
		except:
			os.unlink(tmp_name)
			raise

def unpack_tarball(archive_file):
	tar = tarfile.open(archive_file, 'r:bz2')
	members = [m for m in tar.getmembers() if m.name != 'pax_global_header']
	#tar.extractall('.', members = members) # Python >= 2.5 only
	for tarinfo in members:
		tarinfo = copy.copy(tarinfo)
		tarinfo.mode |= 0o600
		tarinfo.mode &= 0o755
		tar.extract(tarinfo, '.')

def load_feed(path):
	with open(path, 'rb') as stream:
		return model.ZeroInstallFeed(qdom.parse(stream), local_path = path)

def get_archive_basename(impl):
	# "2" means "path" (for Python 2.4)
	return os.path.basename(urllib.parse.urlparse(impl.download_sources[0].url)[2])

def make_readonly_recursive(path):
	for root, dirs, files in os.walk(path):
		for d in dirs + files:
			full = os.path.join(root, d)
			mode = os.stat(full).st_mode
			os.chmod(full, mode & 0o555)

def make_archives_relative(feed):
	with open(feed, 'rb') as stream:
		doc = minidom.parse(stream)
	for elem in doc.getElementsByTagNameNS(namespaces.XMLNS_IFACE, 'archive') + doc.getElementsByTagNameNS(namespaces.XMLNS_IFACE, 'file'):
		href = elem.getAttribute('href')
		assert href, 'Missing href on %r' % elem
		if '/' in href:
			elem.setAttribute('href', href.rsplit('/', 1)[1])
	with open(feed, 'w') as stream:
		doc.writexml(stream)
		stream.write('\n')
