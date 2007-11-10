import os, sys, subprocess, shutil, tarfile
from zeroinstall import SafeException
from zeroinstall.injector import reader, model
from logging import info

class SCM:
	def __init__(self, local_iface):
		self.local_iface = local_iface

class GIT(SCM):
	def _run(self, args, **kwargs):
		return subprocess.Popen(["git"] + args, cwd = os.path.dirname(self.local_iface.uri), **kwargs)
	
	def _run_check(self, args, **kwargs):
		child = self._run(args, **kwargs)
		code = child.wait()
		if code:
			raise SafeException("Git %s failed with exit code %d" % (repr(args), code))

	def ensure_committed(self):
		child = self._run(["status", "-a"], stdout = subprocess.PIPE)
		stdout, unused = child.communicate()
		if not child.returncode:
			raise SafeException('Uncommitted changes! Use "git-commit -a" to commit them. Changes are:\n' + stdout)
	
	def tag(self, version):
		tag = 'v' + version
		self.commit('Release %s' % version)
		self._run_check(['tag', tag])
		print "Tagged as %s" % tag
	
	def export(self, prefix, archive_file):
		child = self._run(['archive', '--format=tar', '--prefix=' + prefix + '/', 'HEAD'], stdout = subprocess.PIPE)
		subprocess.check_call(['bzip2', '-'], stdin = child.stdout, stdout = file(archive_file, 'w'))
		status = child.wait()
		if status:
			if os.path.exists(archive_file):
				os.unlink(archive_file)
			raise SafeException("git-archive failed with exit code %d" % status)
	
	def commit(self, message):
		self._run_check(['commit', '-a', '-m', message])

def run_unit_tests(impl):
	print "SKIPPING unit tests for %s" % impl

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
		args += ['--' + k.replace('_', '-'), kwargs[k]]
	args.append(iface)
	info("Executing %s", args)
	subprocess.check_call(args)

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
		print "DELETING old backup", backup
		shutil.rmtree(backup)
	os.rename(name, backup)
	print "Renamed old %s as %s. Will delete on next run." % (name, backup)

def make_new_release(local_iface):
	local_impl = get_singleton_impl(local_iface)

	local_impl_dir = local_impl.id
	assert local_impl_dir.startswith('/')
	local_impl_dir = os.path.realpath(local_impl_dir)
	assert os.path.isdir(local_impl_dir)
	assert local_iface.uri.startswith(local_impl_dir + '/')
	local_iface_rel_path = local_iface.uri[len(local_impl_dir) + 1:]
	assert not local_iface_rel_path.startswith('/')
	assert os.path.isfile(os.path.join(local_impl_dir, local_iface_rel_path))

	downloads_base = 'http://placeholder.org/releases'

	scm = GIT(local_iface)

	def tag_release():
		print "Snapshot version is " + local_impl.get_version()
		suggested = suggest_release_version(local_impl.get_version())
		release_version = raw_input("Version number for new release [%s]: " % suggested)
		if not release_version:
			release_version = suggested
		print "Releasing version", release_version
		publish(local_iface.uri, set_released = 'today', set_version = release_version)
		scm.tag(release_version)
		return release_version
	
	def set_to_snapshot(snapshot_version):
		assert snapshot_version.endswith('-post')
		publish(local_iface.uri, set_released = '', set_version = snapshot_version)
		scm.commit('Start development series %s' % snapshot_version)
		
	def ensure_ready_to_release():
		scm.ensure_committed()
		info("No uncommitted changes. Good.")
		# Not needed for GIT. For SCMs where tagging is expensive (e.g. svn) this might be useful.
		#run_unit_tests(local_impl)
	
	def create_feed(archive_file, archive_name, version):
		remote_dl_iface = os.path.abspath(local_iface.name + '-' + version + '.xml')
		shutil.copyfile(local_iface.uri, remote_dl_iface)

		publish(remote_dl_iface,
			archive_url = downloads_base + '/' + os.path.basename(archive_file),
			archive_file = archive_file,
			archive_extract = archive_name)
	
	def unpack_tarball(archive_file):
		tar = tarfile.open(archive_file, 'r:bz2')
		tar.extractall('.')

	print "Releasing", local_iface.get_name()

	ensure_ready_to_release()

	version = tag_release()
	#version = '0.1'

	archive_name = local_iface.get_name().lower().replace(' ', '-') + '-' + version
	archive_file = archive_name + '.tar.bz2'
	scm.export(archive_name, archive_file)

	create_feed(archive_file, archive_name, version)

	backup_if_exists(archive_name)
	unpack_tarball(archive_file)
	if local_impl.main:
		main = os.path.join(archive_name, local_impl.main)
		if not os.path.exists(main):
			raise SafeException("Main executable '%s' not found after unpacking archive!" % main)

	extracted_iface_path = os.path.abspath(os.path.join(archive_name, local_iface_rel_path))
	extracted_iface = model.Interface(extracted_iface_path)
	reader.update(extracted_iface, extracted_iface_path, local = True)
	extracted_impl = get_singleton_impl(extracted_iface)
	run_unit_tests(extracted_impl)

	set_to_snapshot(version + '-post')

if __name__ == "__main__":
    import doctest
    doctest.testmod()
