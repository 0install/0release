# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, subprocess
from zeroinstall import SafeException

class SCM:
	def __init__(self, local_iface, options):
		self.local_iface = local_iface
		self.options = options

class GIT(SCM):
	def _run(self, args, **kwargs):
		return subprocess.Popen(["git"] + args, cwd = os.path.dirname(self.local_iface.uri), **kwargs)
	
	def _run_check(self, args, **kwargs):
		child = self._run(args, **kwargs)
		code = child.wait()
		if code:
			raise SafeException("Git %s failed with exit code %d" % (repr(args), code))

	def reset_hard(self, revision):
		self._run_check(['reset', '--hard', revision])

	def ensure_committed(self):
		child = self._run(["status", "-a"], stdout = subprocess.PIPE)
		stdout, unused = child.communicate()
		if not child.returncode:
			raise SafeException('Uncommitted changes! Use "git-commit -a" to commit them. Changes are:\n' + stdout)
	
	def make_tag(self, version):
		return 'v' + version

	def tag(self, version, revision):
		tag = self.make_tag(version)
		if self.options.key:
			key_opts = ['-u', self.options.key]
		else:
			key_opts = []
		self._run_check(['tag', '-s'] + key_opts + ['-m', 'Release %s' % version, tag, revision])
		print "Tagged as %s" % tag
	
	def ensure_no_tag(self, version):
		tag = self.make_tag(version)
		child = self._run(['tag', '-l', '-q', tag])
		code = child.wait()
		if code == 0:
			raise SafeException(("Release %s is already tagged! If you want to replace it, do\n" + 
						"git-tag -d %s") % (version, tag))
	
	def export(self, prefix, archive_file):
		child = self._run(['archive', '--format=tar', '--prefix=' + prefix + '/', 'HEAD'], stdout = subprocess.PIPE)
		subprocess.check_call(['bzip2', '-'], stdin = child.stdout, stdout = file(archive_file, 'w'))
		status = child.wait()
		if status:
			if os.path.exists(archive_file):
				os.unlink(archive_file)
			raise SafeException("git-archive failed with exit code %d" % status)
	
	def commit(self, message):
		self._run_check(['commit', '-q', '-a', '-m', message])
	
	def get_head_revision(self):
		proc = self._run(['rev-parse', 'HEAD'], stdout = subprocess.PIPE)
		stdout, unused = proc.communicate()
		if proc.returncode:
			raise Exception("git rev-parse failed with exit code %d" % proc.returncode)
		head = stdout.strip()
		assert head
		return head
