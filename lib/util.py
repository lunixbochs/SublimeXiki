import os
import shutil
import tempfile
import subprocess

from threading import Timer

def memoize(f):
	rets = {}

	def wrap(*args):
		if not args in rets:
			rets[args] = f(*args)

		return rets[args]

	wrap.__name__ = f.__name__
	return wrap

def extract_path(cmd, delim=':'):
	path = popen(cmd, os.environ).communicate()[0]
	path = path.split('__SUBL__', 1)[1].strip('\r\n')
	return ':'.join(path.split(delim))

def find_path(env):
	# find PATH using shell --login
	if 'SHELL' in env:
		shell_path = env['SHELL']
		shell = os.path.basename(shell_path)

		if shell in ('bash', 'zsh'):
			return extract_path(
				(shell_path, '--login', '-c', 'echo __SUBL__$PATH')
			)
		elif shell == 'fish':
			return extract_path(
				(shell_path, '--login', '-c', 'echo __SUBL__; for p in $PATH; echo $p; end'),
				'\n'
			)

	# guess PATH if we haven't returned yet
	split = env['PATH'].split(':')
	p = env['PATH']
	for path in (
		'/usr/bin', '/usr/local/bin',
		'/usr/local/php/bin', '/usr/local/php5/bin'
				):
		if not path in split:
			p += (':' + path)

	return p

@memoize
def create_environment():
	if os.name == 'posix':
		os.environ['PATH'] = find_path(os.environ)

	return os.environ

def which(cmd, env=None):
	if env is None:
		env = create_environment()

	for path in env['PATH'].split(':'):
		full = os.path.join(path, cmd)
		if os.path.isfile(full) and os.access(full, os.X_OK):
			return full

# popen methods
def communicate(cmd, stdin=None, timeout=None, **popen_args):
	p = popen(cmd, **popen_args)
	if isinstance(p, subprocess.Popen):
		timer = None
		if timeout is not None:
			kill = lambda: p.kill()
			timer = Timer(timeout, kill)
			timer.start()

		out = p.communicate(stdin)
		if timer is not None:
			timer.cancel()

		return (out[0] or '') + (out[1] or '')
	elif isinstance(p, basestring):
		return p
	else:
		return ''

def tmpfile(cmd, code, suffix=''):
	if isinstance(cmd, basestring):
		cmd = cmd,

	f = tempfile.NamedTemporaryFile(suffix=suffix)
	f.write(code)
	f.flush()

	cmd = tuple(cmd) + (f.name,)
	out = popen(cmd)
	if out:
		out = out.communicate()
		return (out[0] or '') + (out[1] or '')
	else:
		return ''

def tmpdir(cmd, files, filename, code):
	filename = os.path.split(filename)[1]
	d = tempfile.mkdtemp()

	for f in files:
		try: os.makedirs(os.path.split(f)[0])
		except: pass

		target = os.path.join(d, f)
		if os.path.split(target)[1] == filename:
			# source file hasn't been saved since change, so update it from our live buffer
			f = open(target, 'wb')
			f.write(code)
			f.close()
		else:
			shutil.copyfile(f, target)

	os.chdir(d)
	out = popen(cmd)
	if out:
		out = out.communicate()
		out = (out[0] or '') + '\n' + (out[1] or '')
		
		# filter results from build to just this filename
		# no guarantee all languages are as nice about this as Go
		# may need to improve later or just defer to communicate()
		out = '\n'.join([
			line for line in out.split('\n') if filename in line.split(':', 1)[0]
		])
	else:
		out = ''

	shutil.rmtree(d, True)
	return out

def popen(cmd, env=None, return_error=False):
	if isinstance(cmd, basestring):
		cmd = cmd,

	info = None
	if os.name == 'nt':
		info = subprocess.STARTUPINFO()
		info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
		info.wShowWindow = subprocess.SW_HIDE

	if env is None:
		env = create_environment()

	try:
		return subprocess.Popen(cmd, stdin=subprocess.PIPE,
			stdout=subprocess.PIPE, stderr=subprocess.PIPE,
			startupinfo=info, env=env)
	except OSError, err:
		print 'Error launching', repr(cmd)
		print 'Error was:', err.strerror

		if return_error:
			return err.strerror

