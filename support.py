# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, subprocess, shutil, tarfile
import urlparse, ftplib, httplib
from zeroinstall import SafeException
from zeroinstall.injector import model
from logging import info

release_status_file = 'release-status'

def check_call(*args, **kwargs):
	exitstatus = subprocess.call(*args, **kwargs)
	if exitstatus != 0:
		if type(args[0]) in (str, unicode):
			cmd = args[0]
		else:
			cmd = ' '.join(args[0])
		raise SafeException("Command failed with exit code %d:\n%s" % (exitstatus, cmd))

def show_and_run(cmd, args):
	print "Executing: %s %s" % (cmd, ' '.join("[%s]" % x for x in args))
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

def publish(iface, **kwargs):
	args = [os.environ['0PUBLISH']]
	for k in kwargs:
		value = kwargs[k] 
		if value is True:
			args += ['--' + k.replace('_', '-')]
		elif value is not None:
			args += ['--' + k.replace('_', '-'), value]
	args.append(iface)
	info("Executing %s", args)
	check_call(args)

def get_singleton_impl(iface):
	impls = iface.implementations
	if len(impls) != 1:
		raise SafeException("Local feed '%s' contains %d versions! I need exactly one!" % (iface.uri, len(impls)))
	return impls.values()[0]

def backup_if_exists(name):
	if not os.path.exists(name):
		return
	backup = name + '~'
	if os.path.exists(backup):
		print "(deleting old backup %s)" % backup
		if os.path.isdir(backup):
			shutil.rmtree(backup)
		else:
			os.unlink(backup)
	os.rename(name, backup)
	print "(renamed old %s as %s; will delete on next run)" % (name, backup)

def get_choice(options):
	while True:
		choice = raw_input('/'.join(options) + ': ').lower()
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
				print "WARNING: command %s failed with exit code %d" % (cmd, code)
			return

class Status(object):
	__slots__ = ['old_snapshot_version', 'release_version', 'head_before_release', 'new_snapshot_version',
		     'head_at_release', 'created_archive', 'tagged', 'uploaded_archive', 'updated_master_feed']
	def __init__(self):
		for name in self.__slots__:
			setattr(self, name, None)

		if os.path.isfile(release_status_file):
			for line in file(release_status_file):
				assert line.endswith('\n')
				line = line[:-1]
				name, value = line.split('=')
				setattr(self, name, value)
				info("Loaded status %s=%s", name, value)

	def save(self):
		tmp_name = release_status_file + '.new'
		tmp = file(tmp_name, 'w')
		try:
			lines = ["%s=%s\n" % (name, getattr(self, name)) for name in self.__slots__ if getattr(self, name)]
			tmp.write(''.join(lines))
			tmp.close()
			os.rename(tmp_name, release_status_file)
			info("Wrote status to %s", release_status_file)
		except:
			os.unlink(tmp_name)
			raise

def host(address):
	if hasattr(address, 'hostname'):
		return address.hostname
	else:
		return address[1].split(':', 1)[0]

def port(address):
	if hasattr(address, 'port'):
		return address.port
	else:
		port = address[1].split(':', 1)[1:]
		if port:
			return int(port[0])
		else:
			return None

def get_http_size(url, ttl = 1):
	assert url.lower().startswith('http://')

	address = urlparse.urlparse(url)
	http = httplib.HTTPConnection(host(address), port(address) or 80)

	parts = url.split('/', 3)
	if len(parts) == 4:
		path = parts[3]
	else:
		path = ''

	http.request('HEAD', '/' + path, headers = {'Host': host(address)})
	response = http.getresponse()
	try:
		if response.status == 200:
			return response.getheader('Content-Length')
		elif response.status in (301, 302):
			new_url_rel = response.getheader('Location') or response.getheader('URI')
			new_url = urlparse.urljoin(url, new_url_rel)
		else:
			raise SafeException("HTTP error: got status code %s" % response.status)
	finally:
		response.close()

	if ttl:
		info("Resource moved! Checking new URL %s" % new_url)
		assert new_url
		return get_http_size(new_url, ttl - 1)
	else:
		raise SafeException('Too many redirections.')

def get_ftp_size(url):
	address = urlparse.urlparse(url)
	ftp = ftplib.FTP(host(address))
	try:
		ftp.login()
		return ftp.size(url.split('/', 3)[3])
	finally:
		ftp.close()

def get_size(url):
	scheme = urlparse.urlparse(url)[0].lower()
	if scheme.startswith('http'):
		return get_http_size(url)
	elif scheme.startswith('ftp'):
		return get_ftp_size(url)
	else:
		raise SafeException("Unknown scheme '%s' in '%s'" % (scheme, url))

def unpack_tarball(archive_file):
	tar = tarfile.open(archive_file, 'r:bz2')
	members = [m for m in tar.getmembers() if m.name != 'pax_global_header']
	tar.extractall('.', members = members)

