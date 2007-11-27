# Copyright (C) 2007, Thomas Leonard
# See the README file for details, or visit http://0install.net.

import os, subprocess, shutil
from zeroinstall import SafeException
from zeroinstall.injector import model
from logging import info

def check_call(*args, **kwargs):
	exitstatus = subprocess.call(*args, **kwargs)
	if exitstatus != 0:
		raise SafeException("Command %s failed with exit code %d" % (' '.join(args), exitstatus))

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

def get_choice(*options):
	while True:
		choice = raw_input('/'.join(options) + ': ').lower()
		if not choice: continue
		for o in options:
			if o.lower().startswith(choice):
				return o

